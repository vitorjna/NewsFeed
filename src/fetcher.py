import feedparser
import sqlite3
import os
import time
from typing import List, Optional
from dataclasses import dataclass
from .utils import setup_logger

logger = setup_logger("FeedFetcher")

@dataclass
class Article:
    title: str
    link: str
    summary: str
    published: str
    source_feed: str
    source_name: str
    theme: str
    image_url: Optional[str] = None
    short_summary: Optional[str] = None
    long_summary: Optional[str] = None

class FeedFetcher:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initialize SQLite database for seen URLs."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS seen_urls (
                url TEXT PRIMARY KEY,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        conn.close()

    def is_seen(self, url: str) -> bool:
        """Check if URL has been seen before."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('SELECT 1 FROM seen_urls WHERE url = ?', (url,))
        result = c.fetchone()
        conn.close()
        return result is not None

    def mark_seen(self, url: str):
        """Mark URL as seen."""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute('INSERT OR IGNORE INTO seen_urls (url) VALUES (?)', (url,))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Error marking URL as seen: {e}")

    def _extract_image(self, entry) -> Optional[str]:
        """Try to extract a main image from the RSS entry."""
        # 1. Check 'media_content'
        if 'media_content' in entry:
            for media in entry.media_content:
                if media.get('medium') == 'image' and 'url' in media:
                    return media['url']
        
        # 2. Check 'links' for image types
        if 'links' in entry:
            for link in entry.links:
                if 'image' in link.get('type', ''):
                    return link.get('href')
        
        # 3. Check 'media_thumbnail'
        if 'media_thumbnail' in entry:
            return entry.media_thumbnail[0].get('url')

        return None

    def fetch_feeds(self, feeds: List[str], theme_name: str) -> List[Article]:
        """
        Fetch articles from a list of feeds.
        Returns a list of NEW articles.
        """
        new_articles = []
        for feed_url in feeds:
            try:
                logger.info(f"Fetching {feed_url} for theme '{theme_name}'")
                feed = feedparser.parse(feed_url)
                
                # Extract source name/publisher from feed metadata
                source_name = feed.feed.get('title', feed_url)

                if feed.bozo:
                    logger.warning(f"Feed {feed_url} has issues: {feed.bozo_exception}")

                for entry in feed.entries:
                    link = entry.get('link', '')
                    if not link:
                        continue

                    # Deduplication check
                    if self.is_seen(link):
                        continue

                    title = entry.get('title', 'No Title')
                    # Prefer summary, fall back to description or empty
                    summary = entry.get('summary', entry.get('description', ''))
                    published = entry.get('published', str(time.time()))
                    image_url = self._extract_image(entry)

                    article = Article(
                        title=title,
                        link=link,
                        summary=summary,
                        published=published,
                        source_feed=feed_url,
                        source_name=source_name,
                        theme=theme_name,
                        image_url=image_url
                    )
                    new_articles.append(article)

            except Exception as e:
                logger.error(f"Error fetching feed {feed_url}: {e}")

        logger.info(f"Found {len(new_articles)} new articles for theme '{theme_name}'")
        return new_articles
