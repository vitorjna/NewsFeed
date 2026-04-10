import sqlite3
import os
from datetime import datetime, timedelta
from typing import List, Optional
from .utils import setup_logger

logger = setup_logger("DatabaseManager")

class DatabaseManager:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()
        self.timestamp_format = '%Y-%m-%d %H:%M:%S'

    def _init_db(self):
        """Initialize SQLite database with required tables."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path)

        # Enable foreign keys and auto_vacuum
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA auto_vacuum = FULL;")

        c = conn.cursor()

        c.execute('''
            CREATE TABLE IF NOT EXISTS feeds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                url TEXT NOT NULL,
                theme TEXT NOT NULL,
                UNIQUE(url, theme)
            )
        ''')

        c.execute('''
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                feed_id INTEGER NOT NULL,

                -- 1. RAW RSS DATA (Inserted initially)
                url TEXT NOT NULL,
                title TEXT NOT NULL,
                rss_summary TEXT,
                rss_date DATETIME,
                date_seen DATETIME DEFAULT CURRENT_TIMESTAMP,

                -- 2. SCORES & REASONING (Updated for ALL articles)
                relevance_score INTEGER,
                importance_score INTEGER,
                urgency_score INTEGER,
                reasoning TEXT,

                -- 3. CONTENT & PUBLICATION (Updated ONLY if scores pass validation)
                full_content TEXT,
                short_summary TEXT,
                long_summary TEXT,
                hashtags TEXT,
                embedding TEXT,
                published_at DATETIME,
                post_id INTEGER DEFAULT -1,
                discussion_post_id INTEGER DEFAULT -1,

                stage TEXT DEFAULT 'NEW',

                FOREIGN KEY(feed_id) REFERENCES feeds(id) ON DELETE CASCADE
            )
        ''')

        # Create indexes
        c.execute('CREATE INDEX IF NOT EXISTS idx_feeds_theme ON feeds(theme)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_feeds_url ON feeds(url)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_articles_url_feed ON articles(url, feed_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_articles_post_id ON articles(post_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_articles_date_seen ON articles(date_seen)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_articles_published_at ON articles(published_at)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_articles_stage ON articles(stage)')

        conn.commit()
        conn.close()

    def get_or_create_feed(self, feed_name: str, feed_url: str, feed_theme: str) -> Optional[int, str]:
        """Gets the feed ID and name from the database, or creates it if it doesn't exist."""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()

            # Try to find existing
            c.execute('SELECT id, name FROM feeds WHERE url = ? AND theme = ?', (feed_url, feed_theme))
            result = c.fetchone()

            if result:
                feed_id = result[0]
                feed_name = result[1]
            else:
                # Insert new
                c.execute('INSERT INTO feeds (name, url, theme) VALUES (?, ?, ?)', (feed_name, feed_url, feed_theme))
                feed_id = c.lastrowid
                conn.commit()

            conn.close()
            return feed_id, feed_name
        except Exception as e:
            logger.error(f"Error getting/creating feed: {e}")
            return None, None

    def is_seen(self, url: str, feed_id: int) -> bool:
        """Check if URL for a specific feed has been seen before."""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute('SELECT 1 FROM articles WHERE url = ? AND feed_id = ?', (url, feed_id))
            result = c.fetchone()
            conn.close()
            return result is not None
        except Exception as e:
            logger.error(f"Error checking if URL is seen: {e}")
            return False

    def save_article(self, article):
        """Save all known information about an article."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA foreign_keys = ON;")

            if not article.feed_id:
                article.feed_id = self.get_or_create_feed(article.source_name, article.source_feed, article.theme)
                if not article.feed_id:
                    logger.error(f"Failed to resolve feed for article {article.link}")
                    return

            c = conn.cursor()

            # Check if article exists
            c.execute('SELECT id FROM articles WHERE url = ? AND feed_id = ?', (article.link, article.feed_id))
            row = c.fetchone()

            if row:
                c.execute('''
                    UPDATE articles SET
                        relevance_score = ?,
                        importance_score = ?,
                        urgency_score = ?,
                        reasoning = ?,
                        full_content = ?,
                        short_summary = ?,
                        long_summary = ?,
                        hashtags = ?,
                        embedding = ?,
                        published_at = ?,
                        post_id = ?,
                        discussion_post_id = ?,
                        stage = ?
                    WHERE id = ?
                ''', (article.relevance_score,
                      article.importance_score,
                      article.urgency_score,
                      article.reasoning,
                      article.full_content,
                      article.short_summary,
                      article.long_summary,
                      article.hashtags,
                      article.embedding,
                      article.published_at,
                      article.post_id,
                      article.discussion_post_id,
                      article.stage,
                      row[0]))
            else:
                # Insert new
                c.execute('''
                    INSERT INTO articles (
                        feed_id, url, title, rss_summary, rss_date,
                        relevance_score, importance_score, urgency_score, reasoning,
                        full_content, short_summary, long_summary, hashtags, embedding,
                        published_at, post_id, discussion_post_id, stage
                    ) VALUES (?, ?, ?, ?, ?,
                              ?, ?, ?, ?,
                              ?, ?, ?, ?, ?,
                              ?, ?, ?, ?)
                ''', (
                    article.feed_id,
                    article.link,
                    article.title,
                    article.rss_summary,
                    article.rss_date,
                    article.relevance_score,
                    article.importance_score,
                    article.urgency_score,
                    article.reasoning,
                    article.full_content,
                    article.short_summary,
                    article.long_summary,
                    article.hashtags,
                    article.embedding,
                    article.published_at,
                    article.post_id,
                    article.discussion_post_id,
                    article.stage,
                ))

            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Error saving article: {e}")

    def get_recent_published(self, theme: str, days: int) -> List[tuple]:
        """Get articles published in the same theme within the last X days."""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute('''
                SELECT a.title, a.rss_summary, a.embedding, a.published_at
                FROM articles a
                JOIN feeds f ON a.feed_id = f.id
                WHERE f.theme = ? AND a.stage = 'PUBLISHED' AND a.published_at > datetime('now', ?)
            ''', (theme, f'-{days} days'))
            results = c.fetchall()
            conn.close()
            return results
        except Exception as e:
            logger.error(f"Error getting recent published articles: {e}")
            return []

    def purge_old_entries(self, days_delete_unpublished: int = 30, days_delete_published: int = 90) -> None:
        """Delete entries older than specified days from articles."""
        try:
            cutoff_unpublished = (datetime.now() - timedelta(days=days_delete_unpublished)).strftime(self.timestamp_format)
            cutoff_published = (datetime.now() - timedelta(days=days_delete_published)).strftime(self.timestamp_format)
            logger.info(f"Purging database entries older than {days_delete_unpublished} days (before {cutoff_unpublished})...")

            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA foreign_keys = ON;")
            c = conn.cursor()

            # Purge unpublished articles
            c.execute('DELETE FROM articles WHERE post_id = -1 AND date_seen < ?', (cutoff_unpublished,))
            unpub_deleted = c.rowcount

            # Purge published articles
            c.execute('DELETE FROM articles WHERE post_id != -1 AND published_at < ?', (cutoff_published,))
            pub_deleted = c.rowcount

            conn.commit()
            conn.close()

            logger.info(f"Purge completed: deleted {unpub_deleted} unpublished and {pub_deleted} published articles.")
        except Exception as e:
            logger.error(f"Error during database purge: {e}")

    def cleanup_embeddings(self, days: int = 3) -> None:
        """Delete embedding data for articles published X or more days ago."""
        try:
            cutoff_date = (datetime.now() - timedelta(days=days)).strftime(self.timestamp_format)
            logger.info(f"Cleaning up embeddings for articles published before {cutoff_date} ({days} days ago)...")

            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()

            # Set embedding to NULL for articles published before the cutoff
            c.execute('''
                UPDATE articles
                SET embedding = NULL
                WHERE (published_at IS NULL OR published_at < ?) AND embedding IS NOT NULL
            ''', (cutoff_date,))

            cleaned_count = c.rowcount
            conn.commit()
            conn.close()

            if cleaned_count > 0:
                logger.info(f"Embedding cleanup completed: cleared {cleaned_count} entries.")
            else:
                logger.debug("No old embeddings found to clean up.")
        except Exception as e:
            logger.error(f"Error during embedding cleanup: {e}")

    def optimize(self) -> None:
        """Run PRAGMA optimize and VACUUM to keep the database healthy."""
        try:
            logger.info("Running database optimization (VACUUM & PRAGMA optimize)...")
            conn = sqlite3.connect(self.db_path)
            # VACUUM is especially useful after purge_old_entries and cleanup_embeddings
            # It also applies auto_vacuum setting if it was changed for an existing database
            conn.execute("VACUUM;")
            conn.execute("PRAGMA optimize;")
            conn.close()
            logger.info("Database optimization completed.")
        except Exception as e:
            logger.error(f"Error during database optimization: {e}")

    def export_statistics(self, output_path: str, target_date_str: Optional[str] = None) -> None:
        """Export statistics per feed to a text file, with daily and monthly tables."""
        try:
            logger.info(f"Exporting statistics to {output_path}...")
            if not target_date_str:
                target_date_str = datetime.now().strftime('%Y-%m-%d')

            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()

            def get_daily_stats(date_str: str):
                c.execute('''
                    SELECT
                        f.theme,
                        f.name as feed_name,
                        COUNT(a.id) as total_seen,
                        SUM(CASE WHEN a.stage = 'PUBLISHED' THEN 1 ELSE 0 END) as total_published,
                        SUM(CASE WHEN a.stage = 'PUBLISHED' THEN 1 ELSE 0 END) * 100.0 / COUNT(a.id) as publish_rate,
                        AVG(a.relevance_score) as avg_relevance,
                        AVG(a.importance_score) as avg_importance,
                        AVG(a.urgency_score) as avg_urgency,
                        MAX(a.published_at) as last_published
                    FROM articles a
                    JOIN feeds f ON a.feed_id = f.id
                    WHERE DATE(a.date_seen) = ? OR DATE(a.published_at) = ?
                    GROUP BY f.theme, f.name
                    ORDER BY f.theme, f.name
                ''', (date_str, date_str))
                return c.fetchall()

            def get_monthly_stats(end_date_str: str):
                c.execute('''
                    SELECT
                        f.theme,
                        f.name as feed_name,
                        COUNT(a.id) as total_seen,
                        SUM(CASE WHEN a.stage = 'PUBLISHED' THEN 1 ELSE 0 END) as total_published,
                        SUM(CASE WHEN a.stage = 'PUBLISHED' THEN 1 ELSE 0 END) * 100.0 / COUNT(a.id) as publish_rate,
                        AVG(a.relevance_score) as avg_relevance,
                        AVG(a.importance_score) as avg_importance,
                        AVG(a.urgency_score) as avg_urgency,
                        MAX(a.published_at) as last_published
                    FROM articles a
                    JOIN feeds f ON a.feed_id = f.id
                    WHERE (DATE(a.date_seen) <= ? AND DATE(a.date_seen) > date(?, '-30 days'))
                       OR (DATE(a.published_at) <= ? AND DATE(a.published_at) > date(?, '-30 days'))
                    GROUP BY f.theme, f.name
                    ORDER BY f.theme, f.name
                ''', (end_date_str, end_date_str, end_date_str, end_date_str))
                return c.fetchall()

            daily_rows = get_daily_stats(target_date_str)
            monthly_rows = get_monthly_stats(target_date_str)

            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(f"NewsFeed Statistics - Exported on {datetime.now().strftime(self.timestamp_format)}\n")
                f.write("="*100 + "\n\n")

                def write_theme_total(theme, seen, pub):
                    theme_rate = (pub * 100.0 / seen) if seen > 0 else 0.0
                    f.write("-" * 100 + "\n")
                    f.write(f"{'TOTAL ' + theme:<40} | {seen:<5} | {pub:<5} | {theme_rate:<4.1f}% |\n")
                    f.write("-" * 100 + "\n")

                def write_table(title, rows):
                    f.write(f"### {title}\n")
                    f.write("="*100 + "\n")
                    if not rows:
                        f.write("No statistics available for this period.\n\n")
                        return

                    current_theme = None
                    theme_seen = 0
                    theme_pub = 0
                    for theme, feed, seen, pub, rate, avg_r, avg_i, avg_u, last_pub in rows:
                        if theme != current_theme:
                            if current_theme is not None:
                                write_theme_total(current_theme, theme_seen, theme_pub)

                            f.write(f"\nTHEME: {theme}\n")
                            f.write("-" * 100 + "\n")
                            f.write(f"{'Feed Name':<40} | {'Seen':<5} | {'Pub':<5} | {'Rate':<5} | {'Avg R':<5} | {'Avg I':<5} | {'Avg U':<5} | {'Last Pub':<16}\n")
                            f.write("-" * 100 + "\n")
                            current_theme = theme
                            theme_seen = 0
                            theme_pub = 0

                        pub = pub if pub is not None else 0
                        theme_seen += seen
                        theme_pub += pub

                        feed_str = str(feed or 'Unknown')[:38]
                        rate = rate if rate is not None else 0.0
                        avg_r = avg_r if avg_r is not None else 0.0
                        avg_i = avg_i if avg_i is not None else 0.0
                        avg_u = avg_u if avg_u is not None else 0.0
                        last_pub_str = last_pub[:16] if last_pub else "Never"

                        f.write(f"{feed_str:<40} | {seen:<5} | {pub:<5} | {rate:<4.1f}% | {avg_r:<5.1f} | {avg_i:<5.1f} | {avg_u:<5.1f} | {last_pub_str:<16}\n")

                    # Write summary for the last theme
                    if current_theme is not None:
                        write_theme_total(current_theme, theme_seen, theme_pub)

                    f.write("-" * 100 + "\n\n")  # closing separator after last theme

                write_table("DAILY STATISTICS (Last 24 Hours)", daily_rows)
                write_table("MONTHLY STATISTICS (Last 30 Days)", monthly_rows)

            conn.close()
            logger.info("Statistics export completed.")
        except Exception as e:
            logger.error(f"Error exporting statistics: {e}")
            import traceback
            logger.error(traceback.format_exc())

    def export_daily_theme_totals(self, directory: str, target_date_str: Optional[str] = None) -> None:
        """Export daily totals per theme to separate files, appending new data."""
        try:
            import re
            def slugify(text: str) -> str:
                text = text.lower()
                text = re.sub(r'[^a-z0-9]+', '_', text)
                return text.strip('_')

            if not target_date_str:
                target_date_str = datetime.now().strftime('%Y-%m-%d')

            os.makedirs(directory, exist_ok=True)

            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()

            # Get totals grouped by theme
            c.execute('''
                SELECT
                    f.theme,
                    COUNT(a.id) as total_seen,
                    SUM(CASE WHEN a.stage = 'PUBLISHED' THEN 1 ELSE 0 END) as total_published
                FROM articles a
                JOIN feeds f ON a.feed_id = f.id
                WHERE DATE(a.date_seen) = ? OR DATE(a.published_at) = ?
                GROUP BY f.theme
                ORDER BY f.theme
            ''', (target_date_str, target_date_str))

            rows = c.fetchall()
            conn.close()

            for theme, seen, pub in rows:
                filename = f"daily_{slugify(theme)}.txt"
                output_path = os.path.join(directory, filename)
                file_exists = os.path.exists(output_path)

                rate = (pub * 100.0 / seen) if seen > 0 else 0.0

                with open(output_path, 'a', encoding='utf-8') as f:
                    if not file_exists:
                        f.write(f"{'Date':<10} | {'Seen':<5} | {'Pub':<5} | {'Rate':<6}\n")
                        f.write("-" * 35 + "\n")

                    f.write(f"{target_date_str:<10} | {seen:<5} | {pub:<5} | {rate:<5.1f}%\n")

            logger.info(f"Daily theme totals exported to {directory}")
        except Exception as e:
            logger.error(f"Error exporting daily theme totals: {e}")

    def get_current_timestamp(self) -> str:
        return datetime.now().strftime(self.timestamp_format)

    def get_pending_articles(self, theme: str) -> List[dict]:
        """
        Get articles that haven't finished processing.
        This is used to retry processing articles that failed due to network issues or other problems.
        """
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute('''
                SELECT
                    a.title, a.url, a.rss_summary, a.rss_date,
                    f.url as source_feed, f.name as source_name, f.theme,
                    a.short_summary, a.long_summary, a.hashtags, a.full_content,
                    a.relevance_score, a.importance_score, a.urgency_score, a.reasoning,
                    a.embedding, a.post_id, a.discussion_post_id, a.feed_id, a.date_seen, a.stage
                FROM articles a
                JOIN feeds f ON a.feed_id = f.id
                WHERE f.theme = ?
                  AND a.post_id = -1
                  AND a.stage IN ('NEW', 'SCORE', 'DEDUP', 'SUMMARY', 'HASHTAGS', 'PUBLISH')
            ''', (theme,))

            columns = [column[0] for column in c.description]
            results = []
            for row in c.fetchall():
                results.append(dict(zip(columns, row)))
            conn.close()
            return results
        except Exception as e:
            logger.error(f"Error getting pending articles: {e}")
            return []