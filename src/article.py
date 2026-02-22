from dataclasses import dataclass
from typing import Optional, Dict
from .utils import setup_logger

logger = setup_logger("Article")

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
    relevance_score: Optional[int] = None
    importance_score: Optional[int] = None
    urgency_score: Optional[int] = None
    reasoning: Optional[str] = None
    is_valid_news: bool = True

    def fetch_full_content(self, fetcher, force: bool = False) -> Optional[str]:
        """
        Fetches full text if not present or if forced.
        """
        if self.full_text and not force:
            logger.debug(f"Full text already available for '{self.title}'")
            return self.full_text

        logger.debug(f"Fetching full content for '{self.title}'")
        full_text = fetcher.fetch_full_text(self.link)
        if full_text:
            logger.info(f"Full text fetched for '{self.title}', length: {len(full_text)} chars")
            self.full_text = full_text
            return full_text
        logger.warning(f"Could not fetch full text for '{self.title}'")
        return None

    def analyze_scores(self, analyzer: NewsAnalyzer, fetcher: Fetcher, prompt_focus: str, force: bool = False):
        """
        Analyzes scores if not present or if forced.
        """
        if self.relevance_score is not None and not force:
            logger.debug(f"Scores already analyzed for '{self.title}'")
            return

        logger.info(f"Analyzing scores for '{self.title}'")

        if not self.rss_summary or len(self.rss_summary) < 20:
            logger.debug(f"RSS summary missing or too short for '{self.title}', fetching full content before analysis.")
            self.fetch_full_content(fetcher)

        result = analyzer.analyze_scores(self.title, self.rss_summary, prompt_focus)
        if result:
            self.relevance_score = result.relevance_score
            self.importance_score = result.importance_score
            self.urgency_score = result.urgency_score
            self.reasoning = result.reasoning
        return result

    def generate_summaries(self, analyzer: NewsAnalyzer, fetcher: Fetcher, language: Optional[str] = None, force: bool = False):
        """
        Generates summaries if not present or if forced.
        """
        if self.short_summary and self.long_summary and not force:
            logger.debug(f"Summaries already available for '{self.title}'")
            return

        if not self.full_text:
            logger.debug(f"Fetching full content before analysis.")
            self.fetch_full_content(fetcher)

        logger.info(f"Generating summaries for '{self.title}'")
        summaries = analyzer.analyze_summaries(self.title, self.full_text, language)
        if summaries:
            self.is_valid_news = summaries.get('is_valid_news', True)
            if self.is_valid_news:
                self.short_summary = summaries.get('short_summary')
                self.long_summary = summaries.get('long_summary')
                logger.debug(f"[SUMMARIES] '{self.title}': {self.short_summary[:100]}... | {self.long_summary[:100]}...")
            else:
                self.reasoning = f"REJECTED: {summaries.get('rejection_reason', 'No reason provided')}"
        return summaries

    def save(self, db):
        """
        Marks as seen in the database, updating scores and reasoning.
        """
        db.mark_seen(
            self.link,
            self.theme,
            feed_name=self.source_name,
            feed_url=self.source_feed,
            relevance=self.relevance_score,
            importance=self.importance_score,
            urgency=self.urgency_score,
            reasoning=self.reasoning
        )

    def mark_published(self, db):
        """
        Marks article as published in the database.
        """
        db.mark_published(self)
