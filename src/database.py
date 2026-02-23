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

        # Enable foreign keys
        conn.execute("PRAGMA foreign_keys = ON;")

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
                is_published INTEGER DEFAULT 0,
                published_at DATETIME,

                FOREIGN KEY(feed_id) REFERENCES feeds(id) ON DELETE CASCADE
            )
        ''')

        # Create indexes
        c.execute('CREATE INDEX IF NOT EXISTS idx_feeds_theme ON feeds(theme)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_feeds_url ON feeds(url)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_articles_url_feed ON articles(url, feed_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_articles_is_published ON articles(is_published)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_articles_date_seen ON articles(date_seen)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_articles_published_at ON articles(published_at)')

        conn.commit()
        conn.close()

    def get_or_create_feed(self, name: str, url: str, theme: str) -> Optional[int]:
        """Gets the feed ID, creating it if it doesn't exist."""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()

            # Try to find existing
            c.execute('SELECT id FROM feeds WHERE url = ? AND theme = ?', (url, theme))
            result = c.fetchone()

            if result:
                feed_id = result[0]
            else:
                # Insert new
                c.execute('INSERT INTO feeds (name, url, theme) VALUES (?, ?, ?)', (name, url, theme))
                feed_id = c.lastrowid
                conn.commit()

            conn.close()
            return feed_id
        except Exception as e:
            logger.error(f"Error getting/creating feed: {e}")
            return None

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
                        is_published = ?,
                        published_at = ?
                    WHERE id = ?
                ''', (article.relevance_score,
                      article.importance_score,
                      article.urgency_score,
                      article.reasoning,
                      article.full_content,
                      article.short_summary,
                      article.long_summary,
                      article.published_at is not None,
                      article.published_at,
                      row[0]))
            else:
                # Insert new
                c.execute('''
                    INSERT INTO articles (
                        feed_id, url, title, rss_summary, rss_date,
                        relevance_score, importance_score, urgency_score, reasoning,
                        full_content, short_summary, long_summary,
                        is_published, published_at
                    ) VALUES (?, ?, ?, ?, ?,
                              ?, ?, ?, ?,
                              ?, ?, ?,
                              ?, ?)
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
                    article.published_at is not None,
                    article.published_at,
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
                SELECT a.title, a.rss_summary
                FROM articles a
                JOIN feeds f ON a.feed_id = f.id
                WHERE f.theme = ? AND a.is_published = 1 AND a.published_at > datetime('now', ?)
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
            c.execute('DELETE FROM articles WHERE is_published = 0 AND date_seen < ?', (cutoff_unpublished,))
            unpub_deleted = c.rowcount

            # Purge published articles
            c.execute('DELETE FROM articles WHERE is_published = 1 AND published_at < ?', (cutoff_published,))
            pub_deleted = c.rowcount

            conn.commit()
            conn.close()

            logger.info(f"Purge completed: deleted {unpub_deleted} unpublished and {pub_deleted} published articles.")
        except Exception as e:
            logger.error(f"Error during database purge: {e}")

    def export_statistics(self, output_path: str) -> None:
        """Export statistics per feed to a text file, with daily and monthly tables."""
        try:
            logger.info(f"Exporting statistics to {output_path}...")
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()

            def get_stats(days: int):
                c.execute('''
                    SELECT
                        f.theme,
                        f.name as feed_name,
                        COUNT(a.id) as total_seen,
                        SUM(a.is_published) as total_published,
                        SUM(a.is_published) * 100.0 / COUNT(a.id) as publish_rate,
                        AVG(a.relevance_score) as avg_relevance,
                        AVG(a.importance_score) as avg_importance,
                        AVG(a.urgency_score) as avg_urgency,
                        MAX(a.published_at) as last_published
                    FROM articles a
                    JOIN feeds f ON a.feed_id = f.id
                    WHERE a.date_seen >= datetime('now', ? || ' days')
                    GROUP BY f.theme, f.name
                    ORDER BY f.theme, f.name
                ''', (f'-{days}',))
                return c.fetchall()

            daily_rows = get_stats(1)
            monthly_rows = get_stats(30)

            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(f"NewsFeed Statistics - Exported on {datetime.now().strftime(self.timestamp_format)}\n")
                f.write("="*100 + "\n\n")

                def write_table(title, rows):
                    f.write(f"### {title}\n")
                    f.write("="*100 + "\n")
                    if not rows:
                        f.write("No statistics available for this period.\n\n")
                        return

                    current_theme = None
                    for theme, feed, seen, pub, rate, avg_r, avg_i, avg_u, last_pub in rows:
                        if theme != current_theme:
                            if current_theme is not None:
                                f.write("-" * 100 + "\n")
                            f.write(f"\nTHEME: {theme}\n")
                            f.write("-" * 100 + "\n")
                            f.write(f"{'Feed Name':<40} | {'Seen':<5} | {'Pub':<5} | {'Rate':<5} | {'Avg R':<5} | {'Avg I':<5} | {'Avg U':<5} | {'Last Pub':<16}\n")
                            f.write("-" * 100 + "\n")
                            current_theme = theme

                        feed_str = str(feed or 'Unknown')[:38]
                        pub = pub if pub is not None else 0
                        rate = rate if rate is not None else 0.0
                        avg_r = avg_r if avg_r is not None else 0.0
                        avg_i = avg_i if avg_i is not None else 0.0
                        avg_u = avg_u if avg_u is not None else 0.0
                        last_pub_str = last_pub[:16] if last_pub else "Never"

                        f.write(f"{feed_str:<40} | {seen:<5} | {pub:<5} | {rate:<5.2f}% | {avg_r:<5.2f} | {avg_i:<5.2f} | {avg_u:<5.2f} | {last_pub_str:<16}\n")
                    f.write("-" * 100 + "\n\n")  # closing separator after last theme

                write_table("DAILY STATISTICS (Last 24 Hours)", daily_rows)
                write_table("MONTHLY STATISTICS (Last 30 Days)", monthly_rows)

            conn.close()
            logger.info("Statistics export completed.")
        except Exception as e:
            logger.error(f"Error exporting statistics: {e}")
            import traceback
            logger.error(traceback.format_exc())

    def get_current_timestamp(self) -> str:
        return datetime.now().strftime(self.timestamp_format)