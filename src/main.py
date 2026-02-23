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
            logger.debug("Debug mode enabled")

        self.db = DatabaseManager(self.config.database_path)
        self.fetcher = FeedFetcher(self.db)
        self.analyzer = NewsAnalyzer(self.config.llm)
        self.bot_manager = TelegramBotManager(self.config.telegram_bot_token)
        self.publisher = TelegramPublisher()
        self.cross_promoter = cross_promoter.CrossPromoter(self.config, self.analyzer, self.bot_manager)

    async def run_cycle(self):
        """
        Runs one cycle of fetching, analyzing, and publishing.
        """
        if self._is_running_cycle:
            logger.warning("Previous update cycle still running, skipping this run.")
            return

        self._is_running_cycle = True

        bot = self.bot_manager.create_bot()

        try:
            logger.info("Starting update cycle")
            cycle_start_time = time.time()

            for theme in self.config.themes:
                logger.info(f"[{theme.name}] Processing theme start")

                # 1. Fetch
                new_articles = self.fetcher.fetch_feeds(
                    theme.feeds,
                    theme.name,
                    max_age_hours=self.config.max_article_age_hours
                )

                if not new_articles:
                    logger.info(f"[{theme.name}] No new articles found.")
                    continue

                for article in new_articles:
                    # Add a small delay to respect rate limits (especially for Gemini free tier)
                    if self.config.llm.base_url and "google" in self.config.llm.base_url.lower():
                        await asyncio.sleep(2) # 30 RPM limit = 2s per request.

                    logger.info(f"[{theme.name}] Processing article: {article.title[:50]}... | Source: {article.source_name[:30]}...")

                    # 2. Analyze Scores
                    scores = await asyncio.to_thread(article.analyze_scores, self.analyzer, self.fetcher, theme.prompt_focus)

                    if not scores:
                        logger.warning(f"[{theme.name}] Score analysis failed for '{article.title}'. Skipping marking as seen to retry later.")
                        continue

                    # Theme scores and decision
                    is_selected = (
                        scores.relevance_score >= theme.min_relevance_score and
                        scores.importance_score >= theme.min_importance_score and
                        scores.urgency_score >= theme.min_urgency_score
                    )
                    status = "SELECTED" if is_selected else "SKIPPED"

                    logger.info(
                        f"[{theme.name}] [ANALYSIS] {status}: Scores: R:{scores.relevance_score}, I:{scores.importance_score}, U:{scores.urgency_score} | "
                        f"{article.title} | Reasoning: {scores.reasoning}"
                    )

                    if is_selected:
                        # 3. Similarity Check
                        similar_title = self.fetcher.is_similar_already_published(article)
                        if similar_title:
                            logger.info(f"[{theme.name}] [SKIP] Similar article already published: '{similar_title}'")
                        else:
                            # 4. Analyze Summaries
                            await asyncio.to_thread(article.generate_summaries, self.analyzer, self.fetcher, theme.language)

                            if not article.is_valid_news:
                                logger.info(f"[{theme.name}] [REJECTED] Article rejected: {article.reasoning}")

                            else:
                                # 5. Publish
                                try:
                                    if not article.short_summary:
                                        logger.warning(f"[{theme.name}] Summary generation failed for '{article.title}'. Defaulting to RSS summary.")
                                        article.short_summary = article.rss_summary

                                    await self.publisher.publish(bot, article, theme.channel_id, include_image=theme.include_image)
                                    article.mark_published(self.db.get_current_timestamp())
                                except Exception as e:
                                    logger.error(f"[{theme.name}] Failed to publish '{article.title}': {e}")

                    self.db.save_article(article)

                logger.info(f"[{theme.name}] Processing theme end")

        finally:
            self._is_running_cycle = False
            logger.info(f"Update cycle completed in {(time.time() - cycle_start_time) / 60:.1f} minutes")

    def _perform_daily_maintenance(self):
        logger.debug("Performing daily maintenance tasks...")
        self.db.purge_old_entries(days_delete_unpublished=30, days_delete_published=90)
        # find the log file handler and rollover to a new file
        #for handler in logger.handlers:
            #if isinstance(handler, logging.handlersRotatingFileHandler):
                #handler.doRollover()
                #break

        logger.debug("Daily maintenance tasks completed.")


    def run(self):
        #for handler in logger.handlers:
            #if isinstance(handler, logging.handlersRotatingFileHandler):
                #handler.doRollover()
                #break

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
        schedule.every().day.at("03:00").do(self._perform_daily_maintenance)

        # Statistics export
        os.makedirs("logs", exist_ok=True)
        schedule.every().day.at("03:05").do(
            lambda: self.db.export_statistics(f"logs/statistics_{datetime.now().strftime('%Y-%m-%d')}.txt")
        )

        # Cross-promotion schedule
        schedule.every().day.at("09:00").do(
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
