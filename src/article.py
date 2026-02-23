from dataclasses import dataclass
from typing import Optional
from .utils import setup_logger
from .analyzer_llm import NewsAnalyzer

logger = setup_logger("Article")

@dataclass
class Article:
    title: str
    link: str
    rss_summary: str
    rss_date: str
    source_feed: str
    source_name: str
    theme: str
    image_url: Optional[str] = None
    short_summary: Optional[str] = None
    long_summary: Optional[str] = None
    full_content: Optional[str] = None
    relevance_score: Optional[int] = None
    importance_score: Optional[int] = None
    urgency_score: Optional[int] = None
    reasoning: Optional[str] = None
    is_valid_news: bool = True
    feed_id: Optional[int] = None
    published_at: Optional[str] = None

    def fetch_full_content(self, fetcher, force: bool = False) -> Optional[str]:
        """
        Fetches full text if not present or if forced.
        """
        if self.full_content and not force:
            logger.debug(f"Full text already available for '{self.title}'")
            return self.full_content

        logger.debug(f"Fetching full content for '{self.title}'")
        full_content = fetcher.fetch_full_content(self.link)
        if full_content:
            logger.info(f"Full text fetched for '{self.title}', length: {len(full_content)} chars")
            self.full_content = full_content
            return full_content
        logger.warning(f"Could not fetch full text for '{self.title}'")
        return None

    def analyze_scores(self, analyzer: NewsAnalyzer, fetcher: Fetcher, prompt_focus: str, force: bool = False) -> Optional[AnalysisResult]:
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

    def generate_summaries(self, analyzer: NewsAnalyzer, fetcher: Fetcher, language: Optional[str] = None, force: bool = False) -> Optional[Dict[str, str]]:
        """
        Generates summaries if not present or if forced.
        """
        if self.short_summary and self.long_summary and not force:
            logger.debug(f"Summaries already available for '{self.title}'")
            return

        if not self.full_content:
            logger.debug(f"Fetching full content before analysis.")
            self.fetch_full_content(fetcher)

        logger.info(f"Generating summaries for '{self.title}'")
        summaries = analyzer.analyze_summaries(self.title, self.full_content, language)
        if summaries:
            self.is_valid_news = summaries.get('is_valid_news', True)
            if self.is_valid_news:
                self.short_summary = summaries.get('short_summary')
                self.long_summary = summaries.get('long_summary')
                logger.debug(f"[SUMMARIES] '{self.title}': {self.short_summary[:100]}... | {self.long_summary[:100]}...")
            else:
                self.reasoning = f"REJECTED: {summaries.get('rejection_reason', 'No reason provided')}"
        return summaries

    def mark_published(self, published_at: str) -> None:
        self.published_at = published_at