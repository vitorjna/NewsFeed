from dataclasses import dataclass
from typing import Optional
import asyncio
from datetime import datetime
from .utils import setup_logger
from .analyzer_llm import NewsAnalyzer
from .fetcher import FeedFetcher

logger = setup_logger("Article")

STAGE_NEW = "NEW" # new article
STAGE_SCORE = "SCORE" # article to be scored
STAGE_DEDUP = "DEDUP" # article to be deduped, could be done before scoring, but generating embeddings is expensive, often more so than scoring
STAGE_SUMMARY = "SUMMARY" # article to be summarized
STAGE_HASHTAGS = "HASHTAGS" # article to be hashtagged
STAGE_PUBLISH = "PUBLISH" # article to be published

STAGE_PUBLISHED = "PUBLISHED" # article published
STAGE_DUPLICATE = "DUPLICATE" # similar article already published
STAGE_REJECTED = "REJECTED" # article rejected, scores too low, not enough content, too long, etc.
STAGE_SKIPPED = "SKIPPED" # article skipped, too old
STAGE_ERROR = "ERROR" # error processing article

PROCESSING_STAGES = {STAGE_NEW, STAGE_SCORE, STAGE_DEDUP, STAGE_SUMMARY, STAGE_HASHTAGS, STAGE_PUBLISH}
TERMINAL_STAGES = {STAGE_PUBLISHED, STAGE_DUPLICATE, STAGE_REJECTED, STAGE_SKIPPED, STAGE_ERROR}

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
    hashtags: Optional[str] = None
    full_content: Optional[str] = None
    relevance_score: Optional[int] = None
    importance_score: Optional[int] = None
    urgency_score: Optional[int] = None
    reasoning: Optional[str] = None
    embedding: Optional[str] = None
    is_valid_news: bool = True
    feed_id: Optional[int] = None
    published_at: Optional[str] = None
    post_id: int = -1
    discussion_post_id: int = -1
    stage: str = STAGE_NEW
    date_seen: Optional[str] = None

    async def process(self, db, analyzer: NewsAnalyzer, fetcher: FeedFetcher, publisher, bot, theme_obj, config) -> bool:
        """
        Processes the article through the state machine until it reaches a terminal state.
        Saves state to the database after each transition.
        Returns if the article was processed or not
        """
        if self.is_old(config.max_article_age_hours, db.timestamp_format, theme_obj.name):
            db.save_article(self)
            return False

        while self.stage not in TERMINAL_STAGES:
            logger.debug(f"[{self.stage}] [{theme_obj.name}] Processing '{self.title[:50]}...'")
            try:
                if self.stage == STAGE_NEW:
                    self.stage = STAGE_SCORE

                elif self.stage == STAGE_SCORE:
                    self.analyze_scores(analyzer, fetcher, theme_obj.prompt_focus)

                    if not self.is_valid_news:
                        self.stage = STAGE_REJECTED  # e.g., Not enough content, too long
                    else:
                        is_selected = (
                            self.relevance_score >= theme_obj.min_relevance_score and
                            self.importance_score >= theme_obj.min_importance_score and
                            self.urgency_score >= theme_obj.min_urgency_score
                        )

                        if not is_selected:
                            # Fuzzy matching: allow one score to be 1 point below the threshold, but the sum of the scores must meet the threshold
                            is_selected = (
                                self.relevance_score >= theme_obj.min_relevance_score and
                                (self.importance_score >= theme_obj.min_importance_score - 1 and
                                self.urgency_score >= theme_obj.min_urgency_score - 1)
                                and (self.importance_score + self.urgency_score) >= (theme_obj.min_importance_score + theme_obj.min_urgency_score)
                            )
                            if is_selected:
                                logger.info(f"[{self.stage}] [{theme_obj.name}] {self.title} selected due to fuzzy matching (R:{self.relevance_score}, I:{self.importance_score}, U:{self.urgency_score})")
                                self.reasoning += " (Fuzzy matching)"

                        status = "SELECTED" if is_selected else "REJECTED"
                        logger.info(
                            f"[{self.stage}] [{theme_obj.name}] {status}: Scores: R:{self.relevance_score}, I:{self.importance_score}, U:{self.urgency_score} | "
                            f"{self.title[:50]}... | Reasoning: {self.reasoning}"
                        )

                        self.stage = STAGE_DEDUP if is_selected else STAGE_REJECTED

                elif self.stage == STAGE_DEDUP:
                    recent_articles = db.get_recent_published(theme_obj.name, days=config.duplicate_check_days)
                    duplicate = analyzer.check_for_duplicate(self, recent_articles)
                    if duplicate:
                        similar_title, similar_published_at = duplicate
                        try:
                            dt = datetime.strptime(similar_published_at, db.timestamp_format)
                            hours_ago = round((datetime.now() - dt).total_seconds() / 3600)
                            pub_date_str = f", published at {similar_published_at} ({hours_ago} hours ago)"
                        except Exception:
                            pub_date_str = f", published at {similar_published_at}"

                        logger.info(f"[{self.stage}] [{theme_obj.name}] Similar article already published: '{similar_title}'{pub_date_str}")
                        self.short_summary = f"DUPLICATE of {similar_title}"
                        self.embedding = None
                        self.stage = STAGE_DUPLICATE
                    else:
                        self.stage = STAGE_SUMMARY

                elif self.stage == STAGE_SUMMARY:
                    self.generate_summaries(analyzer, fetcher, theme_obj.language)
                    if not self.is_valid_news:
                        logger.info(f"[{self.stage}] [{theme_obj.name}] Article rejected/skipped: {self.reasoning}")
                        self.embedding = None
                        self.stage = STAGE_REJECTED
                    else:
                        self.stage = STAGE_HASHTAGS

                elif self.stage == STAGE_HASHTAGS:
                    self.generate_hashtags(analyzer, fetcher, theme_obj.language, theme_obj.default_hashtags)
                    self.stage = STAGE_PUBLISH

                elif self.stage == STAGE_PUBLISH:
                    logger.info(f"[{self.stage}] [{theme_obj.name}] {self.title}")
                    try:
                        await publisher.publish(bot, self, theme_obj.channel_id, include_image=theme_obj.include_image, dev_mode=config.dev_mode)
                        self.mark_published(db.get_current_timestamp())
                        self.stage = STAGE_PUBLISHED
                    except Exception as e:
                        logger.error(f"[{self.stage}] [{theme_obj.name}] Failed to publish '{self.title}': {e}")
                        self.stage = STAGE_ERROR

                db.save_article(self) # Save state after each transition

            except Exception as e:
                logger.error(f"[{self.stage}] [{self.theme}] Error processing article '{self.title}': {e}")
                import traceback
                logger.error(traceback.format_exc())
                self.stage = STAGE_ERROR
                db.save_article(self)
                return False

        return True

    def check_content_length(self, phase: str) -> tuple[bool, Optional[str]]:
        """
        Checks if the full content length is within acceptable bounds.
        Returns a tuple of (is_valid, rejection_reason).
        """
        content_len = len(self.full_content) if self.full_content else 0
        action_word = "Scoring" if phase == "Score Analyzer" else "Summarizing"

        # 750 characters was chosen as a threshold to filter out short articles that are not suitable for summarization
        # Value obtained by analyzing previously seen articles in the database
        if content_len < 750:
            logger.warning(f"[{phase}] Not enough content available for article: '{self.title}'. Available: {content_len} characters")
            return False, f"{action_word}: Not enough content available"

        # 20000 characters was chosen as a threshold to filter out too in depth articles and reporting that don't generally fit the channel's purpose
        if content_len > 20000:
            logger.warning(f"[{phase}] Article content is too long: {content_len} characters")
            return False, f"{action_word}: Article content is too long"

        return True, None

    def fetch_full_content(self, fetcher: FeedFetcher, force: bool = False) -> None:
        """
        Fetches full text if not present or if forced.
        """
        if self.full_content and not force:
            logger.debug(f"[Content Fetcher] Full text already available for '{self.title}'")
            return

        logger.debug(f"[Content Fetcher] Fetching full content for '{self.title}'")
        full_content = fetcher.fetch_full_content(self.link)
        if full_content:
            logger.info(f"[Content Fetcher] Full text fetched for '{self.title}', length: {len(full_content)} chars")
            self.full_content = full_content
        else:
            logger.warning(f"[Content Fetcher] Could not fetch full text for '{self.title}'")

    def analyze_scores(self, analyzer: NewsAnalyzer, fetcher: FeedFetcher, prompt_focus: str, force: bool = False) -> None:
        """
        Analyzes scores if not present or if forced.
        """
        if self.relevance_score is not None and not force:
            logger.debug(f"[Score Analyzer] Scores already analyzed for '{self.title}'")
            return

        logger.info(f"[Score Analyzer] Analyzing scores for '{self.title}'")

        if not self.rss_summary or len(self.rss_summary) < 20:
            logger.debug(f"[Score Analyzer] RSS summary missing or too short for '{self.title}', fetching full content before analysis.")
            self.fetch_full_content(fetcher)

            self.is_valid_news, rejection_reason = self.check_content_length("Score Analyzer")
            if not self.is_valid_news:
                self.reasoning = rejection_reason
                logger.debug(f"[Score Analyzer] '{self.title}': REJECTED: {self.reasoning}")
                return

            result = analyzer.analyze_scores(self.title, self.full_content[:2000], prompt_focus)

        else:
            # some publishers have the full content in the rss summary, so for the scoring we limit it
            result = analyzer.analyze_scores(self.title, self.rss_summary[:2000], prompt_focus)

        self.relevance_score = result.relevance_score
        self.importance_score = result.importance_score
        self.urgency_score = result.urgency_score
        self.reasoning = result.reasoning

    def generate_summaries(self, analyzer: NewsAnalyzer, fetcher: FeedFetcher, language: Optional[str] = None, force: bool = False) -> None:
        """
        Generates summaries if not present or if forced.
        """
        if self.short_summary and self.long_summary and not force:
            logger.debug(f"[Summary Generator] Summaries already available for '{self.title}'")
            return

        if not self.full_content:
            logger.debug(f"[Summary Generator] Fetching full content before analysis.")
            self.fetch_full_content(fetcher)

        logger.info(f"[Summary Generator] Generating summaries for '{self.title}'")

        self.is_valid_news, rejection_reason = self.check_content_length("Summary Generator")
        if not self.is_valid_news:
            self.reasoning = rejection_reason
            logger.debug(f"[Summary Generator] '{self.title}': REJECTED: {self.reasoning}")
            return

        summaries = analyzer.generate_summaries(self.title, self.full_content, language)

        self.is_valid_news = summaries.get('is_valid_news', True)
        if self.is_valid_news:
            self.short_summary = summaries.get('short_summary')
            if not self.short_summary:
                logger.warning(f"[{theme_obj.name}] Summary generation failed for '{self.title}'. Defaulting to RSS summary.")
                self.short_summary = self.rss_summary

            self.long_summary = summaries.get('long_summary')
            logger.debug(f"[Summary Generator] '{self.title}': {self.short_summary[:100]}... | {self.long_summary[:100]}...")
        else:
            self.reasoning = summaries.get('rejection_reason', 'No reason provided')
            logger.debug(f"[Summary Generator] '{self.title}': REJECTED: {self.reasoning}")

    def generate_hashtags(self, analyzer: NewsAnalyzer, fetcher: FeedFetcher, language: Optional[str] = None, default_hashtags: Optional[str] = None, force: bool = False) -> None:
        """
        Generates hashtags if not present or if forced.
        """
        if self.hashtags and not force:
            logger.debug(f"[Hashtag Generator] Hashtags already available for '{self.title}'")
            return

        if not self.short_summary:
            logger.debug(f"[Hashtag Generator] Summaries not available, generating summaries.")
            self.generate_summaries(analyzer, fetcher, language)

        logger.info(f"[Hashtag Generator] Generating hashtags for '{self.title}'")
        hashtags = analyzer.generate_hashtags(self.title, self.short_summary, language)

        if len(hashtags) < 3:
            if default_hashtags:
                self.hashtags = default_hashtags
                logger.warning(f"[Hashtag Generator] Hashtag generation failed for '{self.title}'. Using defaults: {self.hashtags}")
            else:
                self.hashtags = None
                logger.warning(f"[Hashtag Generator] Hashtag generation failed for '{self.title}' and no defaults provided.")
        else:
            self.hashtags = hashtags
            logger.debug(f"[Hashtag Generator] '{self.title}': {self.hashtags}")

    def mark_published(self, published_at: str) -> None:
        self.published_at = published_at

    def is_old(self, max_age_hours: int, timestamp_format: str, theme_name: str) -> bool:
        """
        Checks if the article is older than max_age_hours.
        If too old, updates stage to STAGE_SKIPPED and returns True.
        """
        if not self.rss_date:
            return False

        try:
            rss_date_parsed = datetime.strptime(self.rss_date, timestamp_format)
            age_hours = (datetime.now() - rss_date_parsed).total_seconds() / 3600

            if age_hours > max_age_hours:
                logger.info(f"[{self.stage}] [{theme_name}] Skipping old article: '{self.title}' ({int(age_hours)}h old)")
                self.reasoning = f"SKIPPED: Article is too old on stage {self.stage}"
                self.short_summary = None
                self.long_summary = None
                self.embedding = None
                self.stage = STAGE_SKIPPED
                return True
        except Exception as e:
            logger.error(f"[{self.stage}] [{theme_name}] Error checking age for article '{self.title}': {e}")

        return False
