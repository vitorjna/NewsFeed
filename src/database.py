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

    def _init_db(self):
        """Initialize SQLite database with required tables."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        # Table for deduplication and score tracking
        c.execute('''
            CREATE TABLE IF NOT EXISTS seen_urls (
                url TEXT PRIMARY KEY,
                theme TEXT,
                feed_name TEXT,
                feed_url TEXT,
                relevance_score INTEGER,
                importance_score INTEGER,
                urgency_score INTEGER,
                reasoning TEXT,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Table for published articles history
        c.execute('''
            CREATE TABLE IF NOT EXISTS published_articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                url TEXT,
                theme TEXT,
                feed_name TEXT,
                feed_url TEXT,
                short_summary TEXT,
                rss_summary TEXT,
                published_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        conn.commit()
        conn.close()

    def is_seen(self, url: str) -> bool:
        """Check if URL has been seen before."""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute('SELECT 1 FROM seen_urls WHERE url = ?', (url,))
            result = c.fetchone()
            conn.close()
            return result is not None
        except Exception as e:
            logger.error(f"Error checking if URL is seen: {e}")
            return False

    def mark_seen(self, url: str, theme: str, feed_name: Optional[str] = None, feed_url: Optional[str] = None, relevance: Optional[int] = None, importance: Optional[int] = None, urgency: Optional[int] = None, reasoning: Optional[str] = None):
        """Mark URL as seen, optionally storing scores."""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute('''
                INSERT INTO seen_urls (url, theme, feed_name, feed_url, relevance_score, importance_score, urgency_score, reasoning)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    theme=excluded.theme,
                    feed_name=excluded.feed_name,
                    feed_url=excluded.feed_url,
                    relevance_score=excluded.relevance_score,
                    importance_score=excluded.importance_score,
                    urgency_score=excluded.urgency_score,
                    reasoning=excluded.reasoning
            ''', (url, theme, feed_name, feed_url, relevance, importance, urgency, reasoning))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Error marking URL as seen: {e}")

    def mark_published(self, article):
        """Mark article as published in the database."""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute(
                'INSERT INTO published_articles (title, url, theme, feed_name, feed_url, short_summary, rss_summary) VALUES (?, ?, ?, ?, ?, ?, ?)',
                (article.title, article.link, article.theme, article.source_name, article.source_feed, article.short_summary, article.rss_summary)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Error marking article as published: {e}")

    def get_recent_published(self, theme: str, days: int) -> List[tuple]:
        """Get articles published in the same theme within the last X days."""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute('''
                SELECT title, rss_summary FROM published_articles
                WHERE theme = ? AND published_at > datetime('now', ?)
            ''', (theme, f'-{days} days'))
            results = c.fetchall()
            conn.close()
            return results
        except Exception as e:
            logger.error(f"Error getting recent published articles: {e}")
            return []

    def purge_old_entries(self, days_delete_unpublished: int = 30, days_delete_published: int = 90):
        """Delete entries older than specified days from seen_urls and published_articles."""
        try:
            cutoff_unpublished = (datetime.now() - timedelta(days=days_delete_unpublished)).strftime('%Y-%m-%d %H:%M:%S')
            cutoff_published = (datetime.now() - timedelta(days=days_delete_published)).strftime('%Y-%m-%d %H:%M:%S')
            logger.info(f"Purging database entries older than {days_delete_unpublished} days (before {cutoff_unpublished})...")

            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()

            # Purge seen_urls
            c.execute('DELETE FROM seen_urls WHERE first_seen < ?', (cutoff_unpublished,))
            seen_deleted = c.rowcount

            # Purge published_articles (maybe keep them longer? but following user request "delete entries older than a month")
            c.execute('DELETE FROM published_articles WHERE published_at < ?', (cutoff_published,))
            pub_deleted = c.rowcount

            conn.commit()
            conn.close()

            logger.info(f"Purge completed: deleted {seen_deleted} seen URLs and {pub_deleted} published articles.")
        except Exception as e:
            logger.error(f"Error during database purge: {e}")

    def export_statistics(self, output_path: str):
        """Export statistics per feed to a text file, with daily and monthly tables."""
        try:
            logger.info(f"Exporting statistics to {output_path}...")
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()

            def get_stats(days: int):
                c.execute('''
                    SELECT
                        s.theme,
                        s.feed_name,
                        COUNT(s.url) as total_seen,
                        COUNT(p.url) as total_published,
                        COUNT(p.url) * 100.0 / COUNT(s.url) as publish_rate,
                        AVG(s.relevance_score) as avg_relevance,
                        AVG(s.importance_score) as avg_importance,
                        AVG(s.urgency_score) as avg_urgency,
                        MAX(p.published_at) as last_published
                    FROM seen_urls s
                    LEFT JOIN published_articles p ON s.url = p.url
                    WHERE s.first_seen >= datetime('now', ? || ' days')
                    GROUP BY s.theme, s.feed_name
                    ORDER BY s.theme, s.feed_name
                ''', (f'-{days}',))
                return c.fetchall()

            daily_rows = get_stats(1)
            monthly_rows = get_stats(30)

            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(f"NewsFeed Statistics - Exported on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
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
