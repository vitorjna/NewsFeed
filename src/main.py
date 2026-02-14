import asyncio
import time
import schedule
import signal
from .config import load_config
from .utils import setup_logger
from .fetcher import FeedFetcher
from .analyzer_llm import NewsAnalyzer
from .publisher import TelegramPublisher

logger = setup_logger("Main")

class NewsFeedApp:
    def __init__(self, config_path: str = "config/config.yaml"):
        from . import analyzer_llm, fetcher, publisher, config as config_mod
        self.config = load_config(config_path)

        if self.config.debug:
            import logging
            level = logging.DEBUG
            logger.setLevel(level)
            analyzer_llm.logger.setLevel(level)
            fetcher.logger.setLevel(level)
            publisher.logger.setLevel(level)
            config_mod.logger.setLevel(level)
            logger.debug("Debug mode enabled")

        self.fetcher = FeedFetcher(self.config.database_path)
        self.analyzer = NewsAnalyzer(self.config.llm)
        self.publisher = TelegramPublisher(self.config.telegram_bot_token)

    async def run_cycle(self):
        """
        Runs one cycle of fetching, analyzing, and publishing.
        """
        logger.info("Starting update cycle")

        for theme in self.config.themes:
            logger.info(f"Processing theme: {theme.name}")

            # 1. Fetch
            new_articles = self.fetcher.fetch_feeds(theme.feeds, theme.name)

            for article in new_articles:
                # 2. Analyze Scores first
                scores = self.analyzer.analyze_scores(article, theme.prompt_focus)

                if not scores:
                    logger.warning(f"Score analysis failed for {article.title}. Skipping marking as seen to retry later.")
                    continue

                # Check criteria (Relevance OR Importance OR Urgency)
                is_relevant_enough = scores.relevance_score >= self.config.min_relevance_score
                is_important_enough = scores.importance_score >= self.config.min_importance_score
                is_urgent_enough = scores.urgency_score >= self.config.min_urgency_score

                # 3. Decision and Logging
                is_selected = is_relevant_enough or is_important_enough or is_urgent_enough
                status = "SELECTED" if is_selected else "SKIPPED"

                logger.info(
                    f"[ANALYSIS] {status}: {article.title} | "
                    f"Scores: R:{scores.relevance_score}, I:{scores.importance_score}, U:{scores.urgency_score} | "
                    f"Reasoning: {scores.reasoning}"
                )

                if is_selected:
                    # 4. Analyze Summaries
                    summaries = self.analyzer.analyze_summaries(article)

                    if not summaries:
                        logger.warning(f"Summary generation failed for {article.title}. Skipping.")
                        continue

                    # Store summaries in Article
                    article.short_summary = summaries['short_summary']
                    article.long_summary = summaries['long_summary']

                    logger.debug(f"[SUMMARIES] {article.title}\nShort: {article.short_summary}\nLong: {article.long_summary}")

                    # 5. Publish
                    try:
                        await self.publisher.publish(article, scores, theme.channel_id)
                        # Mark as seen only after successful publication attempts
                        self.fetcher.mark_seen(article.link)
                    except Exception as e:
                        logger.error(f"Failed to publish {article.title}: {e}")
                else:
                    # Mark as seen anyway since it's not selected
                    self.fetcher.mark_seen(article.link)

        logger.info("Update cycle completed")

    def run(self):
        """
        Starts the scheduler loop.
        """
        logger.info(f"Starting News Feed App. Interval: {self.config.fetch_interval_minutes} minutes")

        # Initial run
        asyncio.run(self.run_cycle())

        # Schedule
        schedule.every(self.config.fetch_interval_minutes).minutes.do(
            lambda: asyncio.run(self.run_cycle())
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
