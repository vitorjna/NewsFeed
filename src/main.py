import asyncio
import time
import schedule
import signal
import sys
from .config import load_config
from .utils import setup_logger
from .fetcher import FeedFetcher
from .analyzer_llm import NewsAnalyzer
from .publisher import TelegramPublisher

logger = setup_logger("Main")

class NewsFeedApp:
    def __init__(self, config_path: str = "config/config.yaml"):
        self.config = load_config(config_path)
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
                # 2. Analyze
                analysis = self.analyzer.analyze_article(article, theme.prompt_focus)
                
                if not analysis:
                    logger.warning(f"Analysis failed for {article.title}")
                    continue
                
                # Check criteria (e.g., relevance score > 6)
                if analysis.is_relevant and analysis.relevance_score >= 6:
                    logger.info(f"Article '{article.title}' is relevant (Score: {analysis.relevance_score}). Publishing.")
                    
                    # 3. Publish
                    await self.publisher.publish(article, analysis, theme.channel_id)
                else:
                    logger.info(f"Article '{article.title}' skipped (Relevant: {analysis.is_relevant}, Score: {analysis.relevance_score})")
        
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
