import asyncio
import os
import time
import schedule
import signal
import logging
from datetime import datetime, timedelta
from .article import Article
from .config import load_config
from .utils import setup_logger
from .fetcher import FeedFetcher
from .database import DatabaseManager
from .analyzer_llm import NewsAnalyzer
from .publisher import TelegramPublisher
from .bot_manager import TelegramBotManager

logger = setup_logger("Main")

class NewsFeedApp:
    def __init__(self, config_path: str = "config/config.yaml"):
        from . import analyzer_llm, article, fetcher, publisher, config as config_mod, cross_promoter, database
        self._is_running_cycle = False
        self.config = load_config(config_path)

        if self.config.debug:
            level = logging.DEBUG
            logger.setLevel(level)
            analyzer_llm.logger.setLevel(level)
            article.logger.setLevel(level)
            fetcher.logger.setLevel(level)
            publisher.logger.setLevel(level)
            config_mod.logger.setLevel(level)
            cross_promoter.logger.setLevel(level)
            database.logger.setLevel(level)

        self.db = DatabaseManager(self.config.database_path)
        self.fetcher = FeedFetcher(self.db)
        self.analyzer = NewsAnalyzer(self.config.llm, self.config.embeddings)
        self.bot_manager = TelegramBotManager(self.config.telegram_bot_token)
        self.publisher = TelegramPublisher()
        self.cross_promoter = cross_promoter.CrossPromoter(self.config, self.bot_manager)

    async def run_cycle(self):
        """
        Runs one cycle of fetching, analyzing, and publishing.
        """
        if self._is_running_cycle:
            logger.warning("[Update Cycle] Previous cycle still running, skipping this run.")
            return

        self._is_running_cycle = True

        bot = self.bot_manager.create_bot()

        try:
            logger.info("[Update Cycle] Starting cycle")
            cycle_start_time = time.time()

            for theme in self.config.themes:
                logger.info(f"[{theme.name}] Processing theme start")

                await self._handle_pending_articles(bot, theme)

                # 1. Fetch
                new_articles: list[Article] = self.fetcher.fetch_feeds(
                    theme.feeds,
                    theme.name,
                    max_age_hours=self.config.max_article_age_hours
                )

                if not new_articles:
                    logger.info(f"[{theme.name}] No new articles found.")
                    continue

                for article in new_articles:
                    # Add a small delay to respect rate limits (especially for Gemini free tier)
                    if self.config.llm.primary_base_url and "google" in self.config.llm.primary_base_url.lower():
                        await asyncio.sleep(2) # 30 RPM limit = 2s per request.

                    logger.info(f"[{theme.name}] Processing article: {article.title[:50]}... | Source: {article.source_name[:30]}...")

                    # 2. Analyze Scores
                    await asyncio.to_thread(article.analyze_scores, self.analyzer, self.fetcher, theme.prompt_focus)

                    is_selected = (
                        article.relevance_score >= theme.min_relevance_score and
                        article.importance_score >= theme.min_importance_score and
                        article.urgency_score >= theme.min_urgency_score
                    )

                    if not is_selected:
                        # also select if importance and urgency are 1 point below the threshold but their sum is above the threshold
                        # allows for stricter definition of the threshold, but still let's articles be selected if one score is 1 point below but the other score is at least 1 point above
                        is_selected = (
                            article.relevance_score >= theme.min_relevance_score and
                            (article.importance_score >= theme.min_importance_score - 1 and
                            article.urgency_score >= theme.min_urgency_score - 1)
                            and (article.importance_score + article.urgency_score) >= theme.min_importance_score + theme.min_urgency_score
                        )
                        if is_selected:
                            logger.debug(f"[{theme.name}] [ANALYSIS] {article.title} is selected due to fuzzy score matching")

                    status = "SELECTED" if is_selected else "SKIPPED"

                    logger.info(
                        f"[{theme.name}] [ANALYSIS] {status}: Scores: R:{article.relevance_score}, I:{article.importance_score}, U:{article.urgency_score} | "
                        f"{article.title} | Reasoning: {article.reasoning}"
                    )

                    if is_selected:
                        # 3. Similarity Check, before calling the LLM to generate summaries
                        recent_articles = self.db.get_recent_published(theme.name, days=2)
                        similar_title = self.analyzer.check_for_duplicate(article, recent_articles)

                        if similar_title:
                            logger.info(f"[{theme.name}] [SKIP] Similar article already published: '{similar_title}'")
                            article.short_summary = f"DUPLICATE of {similar_title}"
                            article.embedding = None # no need to store the embedding for duplicate articles
                        else:
                            # 4. Analyze Summaries
                            await asyncio.to_thread(article.generate_summaries, self.analyzer, self.fetcher, theme.language)

                            if not article.is_valid_news:
                                logger.info(f"[{theme.name}] [REJECTED] Article rejected: {article.reasoning}")
                                article.embedding = None # no need to store the embedding for rejected articles

                            else:
                                # 4.5 Generate Hashtags
                                await asyncio.to_thread(article.generate_hashtags, self.analyzer, self.fetcher, theme.language, theme.default_hashtags)

                                # 5. Publish
                                logger.info(f"[{theme.name}] [PUBLISH] {article.title}")
                                try:
                                    if not article.short_summary:
                                        logger.warning(f"[{theme.name}] Summary generation failed for '{article.title}'. Defaulting to RSS summary.")
                                        article.short_summary = article.rss_summary

                                    await self.publisher.publish(bot, article, theme.channel_id, include_image=theme.include_image, dev_mode=self.config.dev_mode)
                                    article.mark_published(self.db.get_current_timestamp())
                                except Exception as e:
                                    logger.error(f"[{theme.name}] Failed to publish '{article.title}': {e}")

                    self.db.save_article(article)

                logger.info(f"[{theme.name}] Processing theme end")

        finally:
            self._is_running_cycle = False
            logger.info(f"[Update Cycle] Completed in {(time.time() - cycle_start_time) / 60:.1f} minutes")

    async def _handle_pending_articles(self, bot, theme):
        """
        Checks for articles that were selected for publication but failed to publish,
        and attempts to re-publish them if they pass age and duplicate checks.
        """
        pending_data = self.db.get_pending_articles(theme.name)
        if not pending_data:
            return

        logger.info(f"[{theme.name}] Found {len(pending_data)} pending articles from previous attempts.")
        for p_data in pending_data:
            p_article = Article(
                title=p_data['title'],
                link=p_data['url'],
                rss_summary=p_data['rss_summary'],
                rss_date=p_data['rss_date'],
                source_feed=p_data['source_feed'],
                source_name=p_data['source_name'],
                theme=p_data['theme'],
                short_summary=p_data['short_summary'],
                long_summary=p_data['long_summary'],
                hashtags=p_data['hashtags'],
                full_content=p_data['full_content'],
                relevance_score=p_data['relevance_score'],
                importance_score=p_data['importance_score'],
                urgency_score=p_data['urgency_score'],
                reasoning=p_data['reasoning'],
                embedding=p_data['embedding'],
                post_id=p_data['post_id'],
                discussion_post_id=p_data['discussion_post_id'],
                feed_id=p_data['feed_id']
            )

            # 1. Age check
            try:
                date_seen = datetime.strptime(p_data['date_seen'], self.db.timestamp_format)
                age_hours = (datetime.now() - date_seen).total_seconds() / 3600

                if age_hours > self.config.max_article_age_hours:
                    logger.info(f"[{theme.name}] [PENDING] Skipping old article: '{p_article.title}' ({int(age_hours)}h old)")
                    p_article.short_summary = f"SKIPPED: Too old when trying to publish"
                    p_article.long_summary = None # remove long summary so the article is not processed again
                    self.db.save_article(p_article)
                    continue
            except Exception as e:
                logger.error(f"[{theme.name}] [PENDING] Error checking age for pending article '{p_article.title}': {e}")

            # 2. Duplicate check
            recent_articles = self.db.get_recent_published(theme.name, days=2)
            similar_title = self.analyzer.check_for_duplicate(p_article, recent_articles)

            if similar_title:
                logger.info(f"[{theme.name}] [PENDING] Similar article already published: '{similar_title}'")
                p_article.short_summary = f"DUPLICATE of {similar_title}"
                self.db.save_article(p_article)
                continue

            # 3. Publish
            logger.info(f"[{theme.name}] [PENDING-PUBLISH] {p_article.title}")
            try:
                # on the main loop, we check if the small summary exists and set it to the rss summary if it doesn't
                # that's already been done on the first publication attempt

                await self.publisher.publish(bot, p_article, theme.channel_id, include_image=theme.include_image, dev_mode=self.config.dev_mode)
                p_article.mark_published(self.db.get_current_timestamp())
                self.db.save_article(p_article)
            except Exception as e:
                logger.error(f"[{theme.name}] [PENDING] Failed to publish '{p_article.title}': {e}")

    def _perform_daily_maintenance(self):
        logger.debug("[Maintenance] Performing daily maintenance tasks...")
        self.db.purge_old_entries(days_delete_unpublished=30, days_delete_published=90)
        self.db.cleanup_embeddings(days=3)
        logger.debug("[Maintenance] Daily maintenance tasks completed.")


    def run(self):
        """
        Starts the scheduler loop.
        """
        startup_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logger.info(f"\n\n")
        logger.info(f"{"=" * 60}")
        logger.info(f"{"=" * 15} 🚀 NEWS FEED APP STARTUP 🚀 {"=" * 15}")
        logger.info(f"{"=" * 12} Startup Time: {startup_time} {"=" * 13}")
        logger.info(f"{"=" * 60}\n")

        if self.config.dev_mode:
            logger.info("Development mode enabled")

        # Initial run
        asyncio.run(self.run_cycle())

        # Schedule
        schedule.every(self.config.fetch_interval_minutes).minutes.do(
            lambda: asyncio.run(self.run_cycle())
        )

        # Maintenance tasks (Every day at 03:00 AM)
        schedule.every().day.at("03:00").do(self._perform_daily_maintenance)

        # Statistics export
        os.makedirs("logs", exist_ok=True)
        def export_yesterday_stats():
            yesterday_str = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
            self.db.export_statistics(f"logs/statistics_{yesterday_str}.txt", target_date_str=yesterday_str)

        schedule.every().day.at("03:05").do(export_yesterday_stats)

        # Cross-promotion schedule
        #schedule.every().day.at("09:00").do(
        #    lambda: asyncio.run(self.cross_promoter.promote_channels())
        #)

        running = True
        def signal_handler(sig, frame):
            nonlocal running
            logger.info("Stopping application...")
            running = False

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        while running:
            schedule.run_pending()
            time.sleep(1)

if __name__ == "__main__":
    app = NewsFeedApp()
    app.run()
