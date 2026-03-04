import json
import math
from openai import OpenAI
from dataclasses import dataclass
import datetime
from typing import Optional, Dict
from .utils import setup_logger, extract_json
from .config import LLMConfig, EmbeddingConfig
from difflib import SequenceMatcher

logger = setup_logger("NewsAnalyzer")

@dataclass
class AnalysisResult:
    relevance_score: int # 1-10
    importance_score: int # 1-10
    urgency_score: int # 1-10
    reasoning: str

class NewsAnalyzer:
    def __init__(self, llm_config: LLMConfig, embedding_config: EmbeddingConfig):
        # Primary client for main analysis and summaries
        self.primary_client = OpenAI(
            api_key=llm_config.primary_api_key,
            base_url=llm_config.primary_base_url
        )
        self.primary_model = llm_config.primary_model

        # Secondary client for fast tasks like duplicate checks
        self.secondary_client = OpenAI(
            api_key=llm_config.secondary_api_key,
            base_url=llm_config.secondary_base_url
        )
        self.secondary_model = llm_config.secondary_model

        # Embedding client
        self.embedding_client = OpenAI(
            api_key=embedding_config.embedding_api_key,
            base_url=embedding_config.embedding_base_url
        )
        self.embedding_model = embedding_config.embedding_model

    def get_embedding(self, text: str) -> list:
        """
        Generates embedding for the given text.
        """
        try:
            response = self.embedding_client.embeddings.create(
                input=text,
                model=self.embedding_model
            )
            return response.data[0].embedding
        except Exception as e:
            logger.error(f"Error generating embedding: {e}")
            return []

    def _fallback_sequence_matcher(self, article, recent_articles: list, title_threshold: float = 0.55, summary_threshold: float = 0.5) -> Optional[str]:
        try:
            highest_title_similarity = 0
            highest_summary_similarity = 0
            matching_title_article = None
            matching_summary_article = None

            for row in recent_articles:
                existing_title = row[0]
                existing_summary = row[1]
                title_sim = SequenceMatcher(None, article.title.lower(), existing_title.lower()).ratio()

                if title_sim >= title_threshold:
                    logger.info(f"[DEDUP SeqMatcher] Match by TITLE: {title_sim:.2f} >= {title_threshold}, New: '{article.title}', Matching: '{existing_title}'")
                    return existing_title

                elif title_sim > highest_title_similarity:
                    highest_title_similarity = title_sim
                    matching_title_article = existing_title

                if article.rss_summary and existing_summary:
                    summary_sim = SequenceMatcher(None, article.rss_summary.lower(), existing_summary.lower()).ratio()

                    if summary_sim >= summary_threshold:
                        logger.info(f"[DEDUP SeqMatcher] Match by SUMMARY: {summary_sim:.2f} >= {summary_threshold}, New: '{article.title}', Matching: '{existing_title}'")
                        return existing_title

                    elif summary_sim > highest_summary_similarity:
                        highest_summary_similarity = summary_sim
                        matching_summary_article = existing_title

            if matching_title_article:
                logger.debug(f"[DEDUP SeqMatcher] No exact match for '{article.title}'. Highest title similarity: {highest_title_similarity:.2f} with '{matching_title_article}'")
            if matching_summary_article:
                logger.debug(f"[DEDUP SeqMatcher] No exact match for '{article.title}'. Highest summary similarity: {highest_summary_similarity:.2f} with '{matching_summary_article}'")

            return None
        except Exception as e:
            logger.error(f"[DEDUP SeqMatcher] Error: {e}")
            return None

    def check_for_duplicate(self, article: Article, recent_articles: list, similarity_threshold: float = 0.74) -> Optional[str]:
        """
        Uses text embeddings to check if a new article covers the exact same story as any recently published ones.
        Falls back to a sequence matcher if embeddings are not available.
        The value 0.74 is the optimal value found by testing past articles and analyzing where duplicates started being falsely flagged too often.
        """
        if not recent_articles:
            return None

        logger.info(f"[DEDUP] Checking for duplicate for: {article.title}")

        if not article.embedding:
            text_to_embed = f"{article.title} {article.rss_summary[:100] or ''}".strip()
            embedding_list = self.get_embedding(text_to_embed)
            if embedding_list:
                article.embedding = json.dumps(embedding_list)

        if article.embedding:
            try:
                new_emb = json.loads(article.embedding)
                highest_sim = 0
                matching_title = None

                for row in recent_articles:
                    existing_title = row[0]
                    existing_emb_str = row[2] if len(row) > 2 else None
                    if existing_emb_str:
                        existing_emb = json.loads(existing_emb_str)
                        norm_new = math.sqrt(sum(a * a for a in new_emb))
                        norm_exist = math.sqrt(sum(a * a for a in existing_emb))
                        if norm_new > 0 and norm_exist > 0:
                            sim = sum(a * b for a, b in zip(new_emb, existing_emb)) / (norm_new * norm_exist)
                        else:
                            sim = 0

                        if sim > highest_sim:
                            highest_sim = sim
                            matching_title = existing_title

                if highest_sim >= similarity_threshold:
                    logger.info(f"[DEDUP Embeds] POSITIVE (sim: {highest_sim:.3f}). '{article.title}' matches '{matching_title}'")
                    return matching_title
                else:
                    logger.info(f"[DEDUP Embeds] NEGATIVE (highest sim: {highest_sim:.3f}). '{article.title}' does not match '{matching_title}'")
                    return None
            except Exception as e:
                logger.error(f"[DEDUP Embeds] Error computing embedding similarity: {e}")
        else:
            logger.warning("[DEDUP Embeds] No embedding available for the new article, falling back to SequenceMatcher.")

        # Fallback to sequence matcher
        return self._fallback_sequence_matcher(article, recent_articles)

    def analyze_scores(self, article_title: str, article_content: str, prompt_focus: str) -> AnalysisResult:
        """
        Analyzes an article for relevance, importance, and urgency.
        """
        logger.info(f"[Score Analyzer] Analyzing scores for article: {article_title}")

        if not article_title and not article_content:
            logger.warning(f"[Score Analyzer] No content provided for article: {article_title}")
            return AnalysisResult(
                relevance_score=0,
                importance_score=0,
                urgency_score=0,
                reasoning="No content provided"
            )

        today_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

        system_prompt = f"""
    You are a professional news editor and analyst.
    Your goal is to analyze news articles for a specific Telegram channel.

    Channel Focus: {prompt_focus}
    Current Date: {today_str}

    Output must be strict JSON format with the following keys:
    - reasoning: string (Brief analysis of why this fits or doesn't fit the channel focus)
    - relevance_score: int (1-10) - How well does this align with the specific channel focus? (1=Irrelevant/Noise, 10=Perfect On-Topic Match)
    - importance_score: int (1-10) - How significant is this event globally or within its domain? (1=Trivia, 10=Historic/Major Impact)
    - urgency_score: int (1-10) - Does this require immediate attention? (1=Old/Evergreen, 10=Breaking/Immediate Action)

    Scoring Rules:
    - If relevance is below 6, the article will likely be discarded. Be critical.
    - Urgency should consider the Current Date vs the event date.
    - Importance reflects the magnitude of the event, not just user interest.

    IMPORTANT: Response must be ONLY the JSON object. Do not include any explanations, greetings, or markdown markers outside the JSON.
        """

        user_content = f"Title: {article_title}\nContent/Summary: {article_content}"

        # Gemini's OpenAI-compatible API often fails with 'system' role for some models (Gemma)
        if "google" in str(self.primary_client.base_url).lower():
            llm_message = [
                {"role": "user", "content": f"{system_prompt}\n\nUSER REQUEST:\n{user_content}"}
            ]

        else:
            llm_message = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ]

        # logger.debug(f"[Score Analyzer] LLM message for article scoring: {llm_message}")

        max_retries = 2
        response_content = None
        for attempt in range(1, max_retries + 1):
            try:
                response = self.primary_client.chat.completions.create(
                    model=self.primary_model,
                    messages=llm_message
                )

                response_content = response.choices[0].message.content
                if not response_content:
                    logger.warning(f"[Score Analyzer] Empty response from LLM for '{article_title}' (possibly safety block) - attempt {attempt}")
                    continue

                content = extract_json(response_content)
                data = json.loads(content, strict=False)

                return AnalysisResult(
                    relevance_score=data.get('relevance_score', 0),
                    importance_score=data.get('importance_score', 0),
                    urgency_score=data.get('urgency_score', 0),
                    reasoning=data.get('reasoning', 'No reasoning provided')
                )

            except Exception as e:
                logger.error(f"[Score Analyzer] Error analyzing scores for '{article_title}' (attempt {attempt}): {e}")
                logger.debug(f"[Score Analyzer] Error analyzing scores. Sent content: {llm_message}")
                logger.debug(f"[Score Analyzer] Error analyzing scores. Received content: {response_content}")

        return AnalysisResult(
            relevance_score=0,
            importance_score=0,
            urgency_score=0,
            reasoning="Analysis failed"
        )

    def generate_summaries(self, article_title: str, article_content: str, language: Optional[str] = None) -> Dict[str, str]:
        """
        Generates short and long summaries for an article.
        Returns a dictionary with 'short_summary', 'long_summary', and validity flags.
        """
        logger.info(f"[Summary Generator] Generating summaries for article: {article_title}")

        if not article_content or len(article_content) < 500:
            logger.warning(f"[Summary Generator] Not enough content available for article: {article_title}")
            return {
                'is_valid_news': False,
                'rejection_reason': 'No content available'
            }

        lang_instruction = f"The summaries MUST be written in {language}." if language else "The summaries MUST be written in the same language as the news article provided."

        system_prompt = f"""
    You are a professional news editor.
    Your goal is to summarize news articles for a Telegram channel.

    CRITICAL: {lang_instruction}

    First, analyze if the content is a valid individual news article.
    REJECT if:
    - It is a newsletter, a "digest" summarizing multiple different unrelated stories, or a podcast announcement post.
    - It is a generic landing page, login page, or error page.
    - It is a promotional or marketing piece masquerading as news.

    Output must be strict JSON format with the following keys:
    - is_valid_news: boolean (true if valid news article, false if rejected based on criteria above)
    - rejection_reason: string (if is_valid_news is false, explain why concisely. Otherwise null or empty string)
    - short_summary: string (1-2 sentences, engaging but factual. Suitable for a notification. No emojis)
    - long_summary: string (2-3 short paragraphs, max 2-3 sentences each. Each paragraph MUST start with an appropriate emoji. Focus on the "Who, What, Where, Why" for the content. Do not use headings, only the emoji. Leave an empty line between paragraphs.)

    Source Accuracy (CRITICAL):
    - Use ONLY the names, formal titles, and roles that appear verbatim in the article text.
    - If the article mentions only a formal title, do NOT guess or fill in a name. Use the formal title as written in the article.
    - If the article mentions only a name, do NOT add formal titles like "President", "Chancellor", etc.
    - NEVER add qualifiers like "former", "ex-", "current" to any title unless the article itself uses that exact word.
    - Ensure all key entities are preserved accurately as they appear in the text.
    - Do not hallucinate facts, formal titles, names, events, or anything not present in the source text.

    Formatting:
    - DO NOT USE MARKDOWN (no **, __, [], etc.).
    - Use HTML tags ONLY for specific emphasis: <b>bold</b>, <i>italic</i>.
    - Escape any quotes in the text to ensure the JSON is valid.

    IMPORTANT: Response must be ONLY the JSON object. Do not include any text outside the JSON.
        """

        user_content = f"Title: {article_title}\nContent/Summary: {article_content}"

        # Gemini's OpenAI-compatible API often fails with 'system' role for some models (Gemma)
        if "google" in str(self.primary_client.base_url).lower():
            llm_message = [
                {"role": "user", "content": f"{system_prompt}\n\nUSER REQUEST:\n{user_content}"}
            ]
        else:
            llm_message = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ]

        # logger.debug(f"[Summary Generator] LLM message for article summaries: {llm_message}")

        max_retries = 2
        response_content = None
        for attempt in range(1, max_retries + 1):
            try:
                response = self.primary_client.chat.completions.create(
                    model=self.primary_model,
                    messages=llm_message
                )

                response_content = response.choices[0].message.content
                if not response_content:
                    logger.warning(f"[Summary Generator] Empty response from LLM for '{article_title}' (possibly safety block) - attempt {attempt}")
                    continue

                response_content = extract_json(response_content)
                data = json.loads(response_content, strict=False) # allow non-strict JSON parsing, in case the LLM doesn't follow the instructions and returns actual line breaks instead of \n

                return {
                    'short_summary': data.get('short_summary', ''),
                    'long_summary': data.get('long_summary', ''),
                    'is_valid_news': data.get('is_valid_news', True),
                    'rejection_reason': data.get('rejection_reason', '')
                }

            except Exception as e:
                logger.error(f"[Summary Generator] Error generating summaries for '{article_title}' (attempt {attempt}): {e}")
                logger.debug(f"[Summary Generator] Error generating summaries. Sent content: {llm_message}")
                logger.debug(f"[Summary Generator] Error generating summaries. Received content: {response_content}")

        return {
            'short_summary': '',
            'long_summary': '',
            'is_valid_news': False,
            'rejection_reason': 'Analysis failed'
        }

    def generate_hashtags(self, article_title: str, article_content: str, language: Optional[str] = None) -> str:
        """
        Generates hashtags for an article using the secondary LLM.
        """
        logger.info(f"[Hashtag Generator] Generating hashtags for article: {article_title}")

        lang_instruction = f"The hashtags MUST be written in {language}." if language else "The hashtags MUST be written in the same language as the news article provided."

        system_prompt = f"""
    You are a social media expert specializing in Telegram.
    Your goal is to generate 2 to 3 highly relevant, discoverable hashtags for a news article.

    CRITICAL: {lang_instruction}

    Hashtag Selection Priority (pick in this order until you have 2-3):
    1. Key Entity: The most prominent person, company, or organization in the story (e.g., #NASA, #Tesla, #EU).
    2. Core Topic: The broad subject area (e.g., #AI, #ClimateChange, #Elections).
    3. Geography: Only if the location is central to the story (e.g., #Ukraine, #California).

    Formatting Rules:
    - Use CamelCase for multi-word hashtags (e.g., #ClimateChange, NOT #climatechange or #climate_change).
    - Each hashtag must be a single word or CamelCase compound with NO spaces, punctuation, hyphens, or special characters.
    - Keep each hashtag short: maximum 20 characters.

    AVOID these generic, low-value hashtags:
    - #News, #BreakingNews, #Update, #Latest, #Breaking, #Alert, #Trending, #World, #Today
    - Hashtags that merely describe the format (e.g., #Article, #Report, #Story)
    - Overly specific or conversational hashtags that nobody would search for

    Output format:
    - Output ONLY the hashtags, separated by a single space.
    - Do NOT include any other text, explanations, numbering, or markdown.
        """

        user_content = f"Title: {article_title}\nContent/Summary: {article_content[:2000]}" # Limit content for secondary LLM

        if "google" in str(self.secondary_client.base_url).lower():
            llm_message = [
                {"role": "user", "content": f"{system_prompt}\n\nUSER REQUEST:\n{user_content}"}
            ]
        else:
            llm_message = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ]

        max_retries = 2
        response_content = None
        for attempt in range(1, max_retries + 1):
            try:
                response = self.secondary_client.chat.completions.create(
                    model=self.secondary_model,
                    messages=llm_message
                )

                response_content = response.choices[0].message.content.strip()
                if not response_content:
                    logger.warning(f"[Hashtag Generator] Empty response from LLM for '{article_title}' (possibly safety block) - attempt {attempt}")
                    continue

                hashtags = response_content
                if hashtags:
                    # Ensure it looks like hashtags (start with #)
                    if not hashtags.startswith('#'):
                        # Split and add # if missing
                        words = hashtags.split()
                        hashtags = " ".join([f"#{w.lstrip('#')}" for w in words])

                    logger.debug(f"[Hashtag Generator] Generated: {hashtags}")
                    return hashtags

            except Exception as e:
                logger.error(f"[Hashtag Generator] Error generating hashtags for '{article_title}' (attempt {attempt}): {e}")
                logger.debug(f"[Hashtag Generator] Error generating hashtags. Sent content: {llm_message}")
                logger.debug(f"[Hashtag Generator] Error generating hashtags. Received content: {response_content}")
                # if more attempts are available, sleep 5 seconds before retrying (to avoid rate limiting)
                if attempt < max_retries:
                    time.sleep(5)

        return ""
