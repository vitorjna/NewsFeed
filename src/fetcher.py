import feedparser
import time
import calendar
from typing import List, Optional
from dataclasses import dataclass
from .utils import setup_logger, clean_html
from .database import DatabaseManager

logger = setup_logger("FeedFetcher")

@dataclass
class Article:
    title: str
    link: str
    rss_summary: str
    published: str
    source_feed: str
    source_name: str
    theme: str
    image_url: Optional[str] = None
    short_summary: Optional[str] = None
    long_summary: Optional[str] = None
    full_text: Optional[str] = None

class FeedFetcher:
    def __init__(self, db: DatabaseManager):
        self.db = db

    def mark_seen(self, url: str, theme: str, feed_name: Optional[str] = None, feed_url: Optional[str] = None, relevance: Optional[int] = None, importance: Optional[int] = None, urgency: Optional[int] = None, reasoning: Optional[str] = None):
        """Mark URL as seen, optionally storing scores."""
        self.db.mark_seen(url, theme, feed_name, feed_url, relevance, importance, urgency, reasoning)

    def mark_published(self, article: Article):
        """Mark article as published in the database."""
        self.db.mark_published(article)

    def is_similar_already_published(self, article: Article, title_threshold: float = 0.6, summary_threshold: float = 0.5, days: int = 1) -> Optional[str]:
        """
        Check if an article with a similar title or summary was published in the same theme
        within the last `days`. Returns the title of the similar article if found.
        """
        from difflib import SequenceMatcher

        try:
            recent_articles = self.db.get_recent_published(article.theme, days)
            # store highest similarity found by title and summary
            highest_title_similarity = 0
            highest_summary_similarity = 0
            matching_title_article = None
            matching_summary_article = None

            for existing_title, existing_summary in recent_articles:
                # 1. Check title similarity first
                title_sim = SequenceMatcher(None, article.title.lower(), existing_title.lower()).ratio()

                if title_sim >= title_threshold:
                    logger.info(f"Similarity match by TITLE: Score: {title_sim:.2f} >= {title_threshold}, New: '{article.title}', Matching: '{existing_title}'")
                    return existing_title

                elif title_sim > highest_title_similarity:
                    highest_title_similarity = title_sim
                    matching_title_article = existing_title

                # 2. Check summary similarity (if title didn't match and both have summaries)
                if article.rss_summary and existing_summary:
                    # Clean the existing summary in case it was stored with HTML previously
                    cleaned_existing_summary = clean_html(existing_summary)
                    summary_sim = SequenceMatcher(None, article.rss_summary.lower(), cleaned_existing_summary.lower()).ratio()

                    if summary_sim >= summary_threshold:
                        logger.info(f"Similarity match by SUMMARY for '{article.title}': Score: {summary_sim:.2f} >= {summary_threshold}, New Summary: '{article.rss_summary[:300]}...', Matching Summary: '{cleaned_existing_summary[:300]}...'")
                        return existing_title

                    elif summary_sim > highest_summary_similarity:
                        highest_summary_similarity = summary_sim
                        matching_summary_article = existing_title

            if matching_title_article:
                logger.debug(f"No exact match for '{article.title}'. Highest title similarity: {highest_title_similarity:.2f} with '{matching_title_article}'")
            if matching_summary_article:
                logger.debug(f"No exact match for '{article.title}'. Highest summary similarity: {highest_summary_similarity:.2f} with '{matching_summary_article}'")

            return None
        except Exception as e:
            logger.error(f"Error checking for similar articles: {e}")
            return None

    def fetch_full_text(self, url: str) -> Optional[str]:
        """
        Extract the full article text from the corresponding webpage.
        Uses trafilatura for robust extraction.
        """
        import trafilatura
        try:
            logger.info(f"Fetching full text from: {url}")
            downloaded = trafilatura.fetch_url(url)
            if downloaded:
                result = trafilatura.extract(downloaded)
                if result:
                    return result
            logger.warning(f"Could not extract full text from {url}")
            return None
        except Exception as e:
            logger.error(f"Error extracting full text from {url}: {e}")
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
                    if self.db.is_seen(link):
                        continue

                    # Age check (ignore everything older than X hours)
                    published_parsed = entry.get('published_parsed')
                    if published_parsed:
                        # entry.published_parsed is a struct_time in UTC
                        pub_time = calendar.timegm(published_parsed)
                        age_seconds = time.time() - pub_time
                        if age_seconds > (max_age_hours * 3600):
                            logger.debug(f"Skipping old article ({int(age_seconds/3600)}h old): {entry.get('title')}")

                            self.mark_seen(
                                link,
                                theme_name,
                                feed_name=source_name,
                                feed_url=feed_url,
                                relevance=0,
                                importance=0,
                                urgency=0,
                                reasoning="Article is too old"
                            )
                            continue
                    else:
                        logger.warning(f"No publication date for: {link}. Proceeding with article.")

                    title = clean_html(entry.get('title', 'No Title'))
                    # Prefer summary, fall back to description or empty
                    rss_summary = clean_html(entry.get('summary', entry.get('description', '')))
                    published = entry.get('published', str(time.time()))
                    image_url = self._extract_image(entry)

                    article = Article(
                        title=title,
                        link=link,
                        rss_summary=rss_summary,
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
