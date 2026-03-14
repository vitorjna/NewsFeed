import feedparser
import time
import calendar
from typing import List, Optional
from .utils import setup_logger, clean_html
from .database import DatabaseManager
import trafilatura
import requests

logger = setup_logger("FeedFetcher")

DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Referer': 'https://www.google.com/',
    'DNT': '1',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'cross-site',
    'Sec-Fetch-User': '?1'
}


class FeedFetcher:
    def __init__(self, db: DatabaseManager):
        self.db = db

    def fetch_full_content(self, url: str) -> Optional[str]:
        """
        Extract the full article content from the corresponding webpage.
        Uses trafilatura for robust extraction. If trafilatura fails, it will try requests and cloudscraper.
        """
        try:
            logger.info(f"[Content Fetcher] Fetching full content from: {url}")
            downloaded = trafilatura.fetch_url(url)

            if not downloaded:
                # Trafilatura can fail if website blocks non-browser requests
                # Using Requests with proper browser headers as the first fallback
                logger.warning(f"[Content Fetcher] Trafilatura fetch failed for {url}. Trying requests fallback...")
                try:
                    response = requests.get(url, headers=DEFAULT_HEADERS, timeout=15)
                    response.raise_for_status()
                    downloaded = response.text

                except Exception as req_e:
                    # Requests can fail if protections like Cloudflare (or other JS based) exist
                    # However, Requests is used first as Cloudscraper uses JS processing
                    # which can cut JS protected content (happens with NY Times, cuts on the first Ad break)
                    logger.warning(f"[Content Fetcher] Requests fallback failed for {url} ({req_e}). Trying cloudscraper fallback...")
                    try:
                        import cloudscraper
                        scraper = cloudscraper.create_scraper()
                        response = scraper.get(url, timeout=15)
                        response.raise_for_status()
                        downloaded = response.text
                    except ImportError:
                        logger.error("[Content Fetcher] cloudscraper is not installed. Fallback failed.")
                        return None
                    except Exception as cs_e:
                        logger.error(f"[Content Fetcher] Error extracting full content from {url} even with cloudscraper: {cs_e}")
                        return None

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

    def _filter_most_recent_entries(self, entries_data: List[dict]) -> List[dict]:
        """
        Deduplicates a list of entry dictionaries based on their link,
        keeping the entry with the most recent publication date.
        """
        seen = {}
        for item in entries_data:
            link = item['entry'].get('link', '')
            if link not in seen:
                seen[link] = item
            else:
                new_date = item['entry'].get('published_parsed')
                old_date = seen[link]['entry'].get('published_parsed')

                if new_date:
                    if not old_date or (calendar.timegm(new_date) > calendar.timegm(old_date)):
                        seen[link] = item

        return list(seen.values())

    def fetch_feeds(self, feeds: List[str], theme_name: str, max_age_hours: int = 24) -> List['Article']:
        """
        Fetch articles from a list of feeds.
        Returns a list of NEW articles.
        """
        from .article import Article

        logger.info(f"[Feed Fetcher] Fetching feeds for theme '{theme_name}'")

        all_entries = []

        for feed_url in feeds:
            try:
                logger.debug(f"[Feed Fetcher] Fetching {feed_url} for theme '{theme_name}'")
                feed = feedparser.parse(feed_url)
                feed_name = feed.feed.title

                feed_id, feed_name = self.db.get_or_create_feed(feed_name, feed_url, theme_name)
                if not feed_id:
                    logger.error(f"[Feed Fetcher] Failed to resolve feed for {feed_url}")
                    continue

                for entry in feed.entries:
                    link = entry.get('link', '')
                    if not link:
                        continue

                    # Deduplication check (database)
                    if self.db.is_seen(link, feed_id):
                        continue

                    all_entries.append({
                        'entry': entry,
                        'feed_id': feed_id,
                        'feed_name': feed_name,
                        'feed_url': feed_url
                    })

            except Exception as e:
                logger.error(f"[Feed Fetcher] Error fetching feed {feed_url}: {e}")

        # Deduplicate entries from this cycle, keeping the most recent
        # Some feeds can have duplicate entries, for example if an article is updated and the feed is updated with the same link
        unique_entries = self._filter_most_recent_entries(all_entries)

        new_articles = []
        for item in unique_entries:
            entry = item['entry']
            feed_id = item['feed_id']
            feed_name = item['feed_name']
            feed_url = item['feed_url']

            link = entry.get('link', '')
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
                    logger.debug(f"[Feed Fetcher] Skipping old article ({int(age_seconds/3600)}h old): {title}")

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

        logger.info(f"[Feed Fetcher] Found {len(new_articles)} new articles for theme '{theme_name}'")
        return new_articles
