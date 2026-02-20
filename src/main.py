import asyncio
import os
import time
import schedule
import signal
import logging
from datetime import datetime
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
        from . import analyzer_llm, fetcher, publisher, config as config_mod, cross_promoter, database
        self._is_running_cycle = False
        self.config = load_config(config_path)

        if self.config.debug:
            level = logging.DEBUG
            logger.setLevel(level)
            analyzer_llm.logger.setLevel(level)
            fetcher.logger.setLevel(level)
            publisher.logger.setLevel(level)
            config_mod.logger.setLevel(level)
            cross_promoter.logger.setLevel(level)
            database.logger.setLevel(level)
            logger.debug("Debug mode enabled")

        self.db = DatabaseManager(self.config.database_path)
        self.fetcher = FeedFetcher(self.db)
        self.analyzer = NewsAnalyzer(self.config.llm)
        self.bot_manager = TelegramBotManager(self.config.telegram_bot_token)
        self.publisher = TelegramPublisher(self.bot_manager)
        self.cross_promoter = cross_promoter.CrossPromoter(self.config, self.analyzer, self.bot_manager)

    async def run_cycle(self):
        """
        Runs one cycle of fetching, analyzing, and publishing.
        """
        if self._is_running_cycle:
            logger.warning("Previous update cycle still running, skipping this run.")
            return

        self._is_running_cycle = True
        try:
            logger.info("Starting update cycle")
            cycle_start_time = time.time()

            for theme in self.config.themes:
                logger.info(f"Processing theme: {theme.name}")

                # 1. Fetch
                new_articles = self.fetcher.fetch_feeds(
                    theme.feeds,
                    theme.name,
                    max_age_hours=self.config.max_article_age_hours
                )

                for article in new_articles:
                    # Add a small delay to respect rate limits (especially for Gemini free tier)
                    if self.config.llm.base_url and "google" in self.config.llm.base_url.lower():
                        await asyncio.sleep(2) # 30 RPM limit = 2s per request. We do 2 calls per article usually.

                    logger.info(f"Analyzing article: {article.title[:50]}... | Source: {article.source_name[:30]}...")

                    # 2. Analyze Scores first
                    scores = self.analyzer.analyze_scores(article, theme.prompt_focus)

                    if not scores:
                        logger.warning(f"Score analysis failed for '{article.title}'. Skipping marking as seen to retry later.")
                        continue

                    # Use theme-level minimum scores if defined, otherwise fall back to global defaults
                    min_relevance = theme.min_relevance_score if theme.min_relevance_score is not None else self.config.min_relevance_score
                    min_importance = theme.min_importance_score if theme.min_importance_score is not None else self.config.min_importance_score
                    min_urgency = theme.min_urgency_score if theme.min_urgency_score is not None else self.config.min_urgency_score

                    # Check criteria (Relevance AND (Importance OR Urgency))
                    is_relevant_enough = scores.relevance_score >= min_relevance
                    is_important_enough = scores.importance_score >= min_importance
                    is_urgent_enough = scores.urgency_score >= min_urgency

                    # 3. Decision and Logging
                    is_selected = is_relevant_enough and (is_important_enough or is_urgent_enough)
                    status = "SELECTED" if is_selected else "SKIPPED"

                    logger.info(
                        f"[ANALYSIS] {status}: Scores: R:{scores.relevance_score}, I:{scores.importance_score}, U:{scores.urgency_score} | "
                        f"{article.title} | "
                        f"Reasoning: {scores.reasoning}"
                    )

                    should_publish = True

                    if is_selected:
                        # 4. Similarity Check
                        similar_title = self.fetcher.is_similar_already_published(article)
                        if similar_title:
                            logger.info(f"[SKIP] Similar article already published: '{similar_title}'")

                        else:
                            # 5. Fetch full text for better summaries
                            full_text = self.fetcher.fetch_full_text(article.link)
                            if full_text:
                                article.full_text = full_text
                                logger.info(f"[FULL-TEXT] Extracted full text for '{article.title}' ({len(full_text)} characters)")
                            else:
                                logger.warning(f"[FULL-TEXT] Failed or skipped full text extraction for '{article.title}'")

                            # 6. Analyze Summaries
                            summaries = self.analyzer.analyze_summaries(article, theme.language)

                            if summaries:
                                if not summaries.get('is_valid_news', True):
                                    rejection_reason = summaries.get('rejection_reason', 'No reason provided')
                                    logger.info(f"[REJECTED] Article rejected during summary generation: {rejection_reason}")
                                    scores.reasoning = f"REJECTED: {rejection_reason}" # update the reason in the database to reflect why it was rejected
                                    should_publish = False # still mark as seen but don't publish

                                else:
                                    article.short_summary = summaries['short_summary']
                                    article.long_summary = summaries['long_summary']
                                    logger.debug(f"[SUMMARIES] '{article.title}': {article.short_summary[:100]}... | {article.long_summary[:100]}...")

                            else:
                                logger.warning(f"Summary generation failed for '{article.title}'. Defaulting to RSS summary.")
                                article.short_summary = article.rss_summary
                                article.long_summary = None

                            # 7. Publish
                            if should_publish:
                                try:
                                    await self.publisher.publish(article, scores, theme.channel_id, include_image=theme.include_image)
                                    self.fetcher.mark_published(article)
                                except Exception as e:
                                    logger.error(f"Failed to publish '{article.title}': {e}")
                                    continue # do not mark as seen, will try again on the next cycle

                    self.fetcher.mark_seen(
                        article.link,
                        theme.name,
                        feed_name=article.source_name,
                        feed_url=article.source_feed,
                        relevance=scores.relevance_score,
                        importance=scores.importance_score,
                        urgency=scores.urgency_score,
                        reasoning=scores.reasoning
                    )

        finally:
            self._is_running_cycle = False
            logger.info(f"Update cycle completed in {(time.time() - cycle_start_time) / 60:.1f} minutes")

    def run(self):
        """
        Starts the scheduler loop.
        """
        startup_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logger.info("\n")
        logger.info("=" * 60)
        logger.info(f"🚀 NEWS FEED APP STARTUP 🚀")
        logger.info(f"Startup Time: {startup_time}")
        logger.info("=" * 60)

        # Initial run
        asyncio.run(self.run_cycle())

        # Schedule
        schedule.every(self.config.fetch_interval_minutes).minutes.do(
            lambda: asyncio.run(self.run_cycle())
        )

        # Maintenance tasks (Every day at 03:00 AM)
        schedule.every().day.at("03:00").do(
            lambda: self.db.purge_old_entries(days=30)
        )

        # Statistics export
        os.makedirs("logs", exist_ok=True)
        schedule.every().day.at("03:05").do(
        # schedule.every(180).minutes.do(
            lambda: self.db.export_statistics(f"logs/statistics_{datetime.now().strftime('%Y-%m-%d')}.txt")
        )

        # Cross-promotion schedule
        schedule.every().day.at("09:00").do(
        #schedule.every(180).minutes.do(
            lambda: asyncio.run(self.cross_promoter.promote_channels())
        )

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
