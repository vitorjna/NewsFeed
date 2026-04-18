import asyncio
import os
import sys
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

HEARTBEAT_FILE = "/tmp/newsfeed_heartbeat"
logger = None

class NewsFeedApp:
    def __init__(self, config_path: str = "config/config.yaml"):
        from . import analyzer_llm, article, fetcher, publisher, config as config_mod, cross_promoter, database
        self._is_running_cycle = False
        self.config = load_config(config_path)

        global logger
        logger = setup_logger("Main", log_dir=self.config.logs_folder)

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
            logger.info("[Update Cycle] Starting")
            cycle_article_count = 0
            cycle_start_time = time.time()

            for theme in self.config.themes:
                logger.info(f"[{theme.name}] Processing theme start")

                articles_to_process = self._get_pending_articles(theme)

                new_posts = self.fetcher.fetch_feeds(
                    theme.feeds,
                    theme.name
                )

                for post in new_posts:
                    article = Article(
                        title=post.title,
                        link=post.link,
                        rss_summary=post.rss_summary,
                        rss_date=post.rss_date,
                        source_feed=post.source_feed,
                        source_name=post.source_name,
                        theme=post.theme,
                        image_url=post.image_url,
                        feed_id=post.feed_id
                    )
                    self.db.save_article(article)
                    articles_to_process.append(article)

                if not articles_to_process:
                    logger.info(f"[{theme.name}] No articles to process.")
                    continue

                bWasProcessed = False
                cycle_article_count += len(articles_to_process)

                for article in articles_to_process:
                    # Add a small delay to respect rate limits (especially for Gemini free tier)
                    if bWasProcessed:
                        if self.config.llm.primary_base_url and "google" in self.config.llm.primary_base_url.lower():
                            await asyncio.sleep(2) # 30 RPM limit = 2s per request.

                    logger.info(f"[{theme.name}] Processing article: {article.title[:50]}... | Source: {article.source_name[:30]}...")

                    bWasProcessed = await article.process(self.db, self.analyzer, self.fetcher, self.publisher, bot, theme, self.config)

                logger.info(f"[{theme.name}] Processing theme end")

        finally:
            self._is_running_cycle = False
            logger.info(f"[Update Cycle] Completed in {(time.time() - cycle_start_time) / 60:.1f} minutes | Articles processed: {cycle_article_count}")

    def _get_pending_articles(self, theme) -> list[Article]:
        """
        Returns a list of Article objects that haven't finish processing.
        """
        pending_data = self.db.get_pending_articles(theme.name)
        pending_articles = []
        if not pending_data:
            return pending_articles

        logger.info(f"[{theme.name}] Found {len(pending_data)} pending articles")
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
                feed_id=p_data['feed_id'],
                stage=p_data['stage'],
                date_seen=p_data['date_seen']
            )
            pending_articles.append(p_article)

        return pending_articles

    def _perform_daily_maintenance(self):
        logger.info("[Maintenance] Starting DB maintenance")
        self.db.purge_old_entries(days_delete_unpublished=180, days_delete_published=365)
        self.db.cleanup_embeddings(days=self.config.duplicate_check_days + 1)
        self.db.optimize()
        logger.info("[Maintenance] DB maintenance completed")

        if self.config.backup_folder:
            import shutil
            try:
                os.makedirs(self.config.backup_folder, exist_ok=True)
                db_filename = os.path.basename(self.config.database_path)
                backup_path = os.path.join(self.config.backup_folder, db_filename)
                logger.info(f"[Maintenance] Backing up database to {backup_path}")
                # Using copyfile to avoid copying permissions which could fail across drives with different permission models
                shutil.copyfile(self.config.database_path, backup_path)
                logger.debug("[Maintenance] Database backup completed")
            except Exception as e:
                logger.error(f"[Maintenance] Error backing up database: {e}")

        # Cleanup old log and stats files
        self._cleanup_old_files(self.config.logs_folder, self.config.log_retention_days)
        self._cleanup_old_files(self.config.stats_folder, self.config.stats_retention_days)

    def _cleanup_old_files(self, directory: str, retention_days: int):
        """Deletes files in the specified directory older than retention_days."""
        if not os.path.exists(directory):
            return

        cutoff = time.time() - (retention_days * 86400)
        logger.info(f"[Maintenance] Cleaning up files in '{directory}' older than {retention_days} days")

        count = 0
        try:
            for filename in os.listdir(directory):
                file_path = os.path.join(directory, filename)
                if os.path.isfile(file_path):
                    if os.path.getmtime(file_path) < cutoff:
                        try:
                            os.remove(file_path)
                            count += 1
                            logger.debug(f"[Maintenance] Deleted old file: {filename}")
                        except Exception as e:
                            logger.error(f"[Maintenance] Failed to delete {filename}: {e}")
        except Exception as e:
            logger.error(f"[Maintenance] Error listing directory '{directory}': {e}")

        if count > 0:
            logger.info(f"[Maintenance] Deleted {count} old files in '{directory}'")
        else:
            logger.info(f"[Maintenance] No old files found in '{directory}'")

    def _restart_application(self):
        logger.info("[Maintenance] Restarting application to force log rotation")

        # Determine how the app was started to preserve package context
        if __package__:
            # If run as: python -m src.main
            # We use the module name to avoid relative import errors
            cmd = [sys.executable, "-m", f"{__package__}.main"] + sys.argv[1:]
        else:
            # Fallback for direct script execution
            cmd = [sys.executable] + sys.argv

        logger.info(f"Restarting with command: {' '.join(cmd)}")

        # Allow logs to flush
        time.sleep(2)

        if os.name == 'nt':
            # On Windows, os.execv can be unreliable with file locks and handles.
            # Using subprocess.Popen followed by sys.exit is the standard way to restart.
            import subprocess
            subprocess.Popen(cmd)
            sys.exit(0)
        else:
            # On Unix, os.execv correctly replaces the current process
            os.execv(sys.executable, cmd)

    def _nightly_routine(self):
        logger.info("[Maintenance] Starting daily maintenance")
        self._perform_daily_maintenance()

        # Export stats for yesterday
        os.makedirs(self.config.stats_folder, exist_ok=True)
        yesterday_str = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        self.db.export_statistics(os.path.join(self.config.stats_folder, f"statistics_{yesterday_str}.txt"), target_date_str=yesterday_str)
        self.db.export_daily_theme_totals(self.config.stats_folder, target_date_str=yesterday_str)

        self._restart_application()
        # logger.info("[Maintenance] Nightly routine completed")


    def _write_heartbeat(self):
        try:
            with open(HEARTBEAT_FILE, "w") as f:
                f.write(str(time.time()))
        except Exception:
            pass

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

        # Write initial heartbeat before anything else
        try:
            with open(HEARTBEAT_FILE, "w") as f:
                f.write(str(time.time()))
        except Exception:
            pass

        # Initial run
        asyncio.run(self.run_cycle())

        # Schedule
        schedule.every(self.config.fetch_interval_minutes).minutes.do(
            lambda: asyncio.run(self.run_cycle())
        )

        # Nightly routine (Maintenance, Stats, Restart) at 03:00 AM
        schedule.every().day.at("03:00").do(self._nightly_routine)

        # Heartbeat schedule
        schedule.every(5).minutes.do(self._write_heartbeat)

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
