import feedparser
import time
import calendar
from typing import List, Optional
from .utils import setup_logger, clean_html
from .database import DatabaseManager
import trafilatura

logger = setup_logger("FeedFetcher")

class FeedFetcher:
    def __init__(self, db: DatabaseManager):
        self.db = db

    def fetch_full_content(self, url: str) -> Optional[str]:
        """
        Extract the full article content from the corresponding webpage.
        Uses trafilatura for robust extraction.
        """
        try:
            logger.info(f"[Content Fetcher] Fetching full content from: {url}")
            downloaded = trafilatura.fetch_url(url)
            if downloaded:
                result = trafilatura.extract(downloaded)
                if result:
                    return result
            logger.warning(f"[Content Fetcher] Could not extract full content from {url}")
            return None
        except Exception as e:
            logger.error(f"[Content Fetcher] Error extracting full content from {url}: {e}")
            return None

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

    def fetch_feeds(self, feeds: List[str], theme_name: str, max_age_hours: int = 24) -> List[Article]:
        """
        Fetch articles from a list of feeds.
        Returns a list of NEW articles.
        """
        from .article import Article

        logger.info(f"[Feed Fetcher] Fetching feeds for theme '{theme_name}'")

        new_articles = []
        for feed_url in feeds:
            try:
                logger.debug(f"[Feed Fetcher] Fetching {feed_url} for theme '{theme_name}'")
                feed = feedparser.parse(feed_url)
                feed_name = feed.feed.title

                feed_id = self.db.get_or_create_feed(feed_name, feed_url, theme_name)
                if not feed_id:
                    logger.error(f"[Feed Fetcher] Failed to resolve feed for {feed_url}")
                    continue

                for entry in feed.entries:
                    link = entry.get('link', '')
                    if not link:
                        continue

                    # Deduplication check
                    if self.db.is_seen(link, feed_id):
                        continue

                    title = clean_html(entry.get('title', 'No Title'))
                    # Prefer summary, fall back to description or empty
                    rss_summary = clean_html(entry.get('summary', entry.get('description', '')))
                    published = entry.get('published', str(time.time()))

                    # Age check (ignore everything older than X hours)
                    published_parsed = entry.get('published_parsed')
                    if published_parsed:
                        # entry.published_parsed is a struct_time in UTC
                        pub_time = calendar.timegm(published_parsed)
                        age_seconds = time.time() - pub_time
                        if age_seconds > (max_age_hours * 3600):
                            logger.debug(f"[Feed Fetcher] Skipping old article ({int(age_seconds/3600)}h old): {entry.get('title')}")

                            article = Article(
                                title=title,
                                link=link,
                                rss_summary=rss_summary,
                                rss_date=published,
                                source_feed=feed_url,
                                source_name=feed_name,
                                theme=theme_name,
                                image_url=self._extract_image(entry),
                                relevance_score=0,
                                importance_score=0,
                                urgency_score=0,
                                reasoning="Article is too old",
                                feed_id=feed_id
                            )
                            self.db.save_article(article)
                            continue
                    else:
                        logger.warning(f"[Feed Fetcher] No publication date for: {link}. Proceeding with article.")

                    image_url = self._extract_image(entry)

                    article = Article(
                        title=title,
                        link=link,
                        rss_summary=rss_summary,
                        rss_date=published,
                        source_feed=feed_url,
                        source_name=feed_name,
                        theme=theme_name,
                        image_url=image_url,
                        feed_id=feed_id
                    )
                    new_articles.append(article)

            except Exception as e:
                logger.error(f"[Feed Fetcher] Error fetching feed {feed_url}: {e}")

        logger.info(f"[Feed Fetcher] Found {len(new_articles)} new articles for theme '{theme_name}'")
        return new_articles
