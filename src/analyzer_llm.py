import json
from openai import OpenAI
from dataclasses import dataclass
import datetime
from typing import Optional, Dict
from .utils import setup_logger, extract_json
from .config import LLMConfig
from difflib import SequenceMatcher

logger = setup_logger("NewsAnalyzer")

@dataclass
class AnalysisResult:
    relevance_score: int # 1-10
    importance_score: int # 1-10
    urgency_score: int # 1-10
    reasoning: str

class NewsAnalyzer:
    def __init__(self, config: LLMConfig):
        # Primary client for main analysis and summaries
        self.primary_client = OpenAI(
            api_key=config.primary_api_key,
            base_url=config.primary_base_url
        )
        self.primary_model = config.primary_model

        # Secondary client for fast tasks like duplicate checks
        self.secondary_client = OpenAI(
            api_key=config.secondary_api_key,
            base_url=config.secondary_base_url
        )
        self.secondary_model = config.secondary_model

    def _fallback_sequence_matcher(self, article, recent_articles: list, title_threshold: float = 0.55, summary_threshold: float = 0.5) -> Optional[str]:
        try:
            highest_title_similarity = 0
            highest_summary_similarity = 0
            matching_title_article = None
            matching_summary_article = None

            for existing_title, existing_summary in recent_articles:
                title_sim = SequenceMatcher(None, article.title.lower(), existing_title.lower()).ratio()

                if title_sim >= title_threshold:
                    logger.info(f"[Fallback SequenceMatcher] Match by TITLE: {title_sim:.2f} >= {title_threshold}, New: '{article.title}', Matching: '{existing_title}'")
                    return existing_title

                elif title_sim > highest_title_similarity:
                    highest_title_similarity = title_sim
                    matching_title_article = existing_title

                if article.rss_summary and existing_summary:
                    summary_sim = SequenceMatcher(None, article.rss_summary.lower(), existing_summary.lower()).ratio()

                    if summary_sim >= summary_threshold:
                        logger.info(f"[Fallback SequenceMatcher] Match by SUMMARY: {summary_sim:.2f} >= {summary_threshold}, New: '{article.title}', Matching: '{existing_title}'")
                        return existing_title

                    elif summary_sim > highest_summary_similarity:
                        highest_summary_similarity = summary_sim
                        matching_summary_article = existing_title

            if matching_title_article:
                logger.debug(f"[Fallback SequenceMatcher] No exact match. Highest title similarity: {highest_title_similarity:.2f} with '{matching_title_article}'")
            if matching_summary_article:
                logger.debug(f"[Fallback SequenceMatcher] No exact match. Highest summary similarity: {highest_summary_similarity:.2f} with '{matching_summary_article}'")
            return None
        except Exception as e:
            logger.error(f"[Fallback SequenceMatcher] Error: {e}")
            return None

    def check_for_duplicate(self, article, recent_articles: list) -> Optional[str]:
        """
        Uses a fast secondary LLM to check if a new article covers the exact same story as any recently published ones.
        Falls back to a sequence matcher if the LLM fails or returns invalid structured output.
        """
        if not recent_articles:
            return None

        logger.info(f"Checking for duplicate for: {article.title}")
        # logger.debug(f"Recent articles: {recent_articles}")

        system_prompt = (
            "You are an AI tasked with identifying duplicate news stories.\n"
            "Your goal is to compare a 'New Article' against a list of 'Recently Published Articles'.\n"
            "Determine if the New Article covers the EXACT same news event involving the SAME primary actors as one of the recent articles.\n"
            "Compare the content of the new article to the content of the recent articles one by one.\n"
            "Output MUST be valid JSON format with these keys:\n"
            "- reasoning: string (Identify primary actors/subjects and specific event. Compare them to the candidates).\n"
            "- is_duplicate: boolean (true ONLY if it's the same event with same actors).\n"
            "- duplicate_of_title: string (Exact title of match, else null).\n\n"
            "STRICT GUIDELINES:\n"
            "1. DIFFERENT ACTORS = NOT DUPLICATE. If one story is about Company A and another is about Company B, they are DIFFERENT even if both are taking the same kind of action.\n"
            "2. DIFFERENT EVENTS = NOT DUPLICATE. If they are different steps in a process (e.g., rumor vs announcement), they are usually NOT duplicates unless the content is nearly identical.\n"
            "3. UPDATES: A \"breaking news\" alert followed by a \"detailed report\" of the SAME event IS a duplicate."
            "4. BE CONSERVATIVE. If in doubt, it is NOT a duplicate.\n"
            "Response must be ONLY the JSON object."
        )

        recent_articles_text = "\n".join([f"{title}" for title in recent_articles])

        user_content = (
            f"NEW ARTICLE:\n"
            f"Title: {article.title}\n"
            f"Summary: {article.rss_summary[:350] if article.rss_summary else 'No summary'}\n\n"
            f"RECENTLY PUBLISHED ARTICLES:\n"
            f"{recent_articles_text}"
        )

        if "google" in str(self.secondary_client.base_url).lower():
            llm_message = [{"role": "user", "content": f"{system_prompt}\n\nUSER REQUEST:\n{user_content}"}]
        else:
            llm_message = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ]

        try:
            response = self.secondary_client.chat.completions.create(
                model=self.secondary_model,
                messages=llm_message,
                timeout=30 # Prevent it from hanging indefinitely
            )

            content = response.choices[0].message.content
            if content:
                content = extract_json(content)
                data = json.loads(content, strict=False)

                is_duplicate = data.get('is_duplicate', False)
                if is_duplicate:
                    duplicate_title = data.get('duplicate_of_title')
                    logger.info(f"LLM Duplicate Check: POSITIVE. Marked as duplicate of '{duplicate_title}'. Reasoning: {data.get('reasoning')}")
                    return duplicate_title
                else:
                    logger.info(f"LLM Duplicate Check: NEGATIVE. Not a duplicate. Reasoning: {data.get('reasoning')}")
                    return None
            else:
                logger.warning("Empty response from secondary LLM for duplicate check. Using fallback.")

        except json.JSONDecodeError as je:
            logger.error(f"LLM Duplicate Check: JSON parsing error '{je}', content: {content}. Using fallback.")
        except Exception as e:
            logger.error(f"LLM Duplicate Check: Error calling secondary LLM '{self.secondary_model}': {e}. Using fallback.")

        # Fallback to sequence matcher
        return self._fallback_sequence_matcher(article, recent_articles)

    def analyze_scores(self, article_title: str, article_content: str, prompt_focus: str) -> AnalysisResult:
        """
        Analyzes an article for relevance, importance, and urgency.
        """
        logger.info(f"Analyzing scores for article: {article_title}")

        if not article_title and not article_content:
            logger.warning(f"No content provided for article: {article_title}")
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

        # logger.debug(f"LLM message for article scoring: {llm_message}")

        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = self.primary_client.chat.completions.create(
                    model=self.primary_model,
                    messages=llm_message
                )

                content = response.choices[0].message.content
                if not content:
                    logger.warning(f"Empty response from LLM for '{article_title}' (possibly safety block) - attempt {attempt + 1}")
                    continue

                content = extract_json(content)
                data = json.loads(content, strict=False)

                return AnalysisResult(
                    relevance_score=data.get('relevance_score', 0),
                    importance_score=data.get('importance_score', 0),
                    urgency_score=data.get('urgency_score', 0),
                    reasoning=data.get('reasoning', 'No reasoning provided')
                )

            except Exception as e:
                logger.error(f"Error analyzing scores for '{article_title}' (attempt {attempt + 1}): {e}")
                logger.debug(f"Error analyzing scores. Sent content: {llm_message}")
                logger.debug(f"Error analyzing scores. Received content: {content}")

        return AnalysisResult(
            relevance_score=0,
            importance_score=0,
            urgency_score=0,
            reasoning="Analysis failed"
        )

    def analyze_summaries(self, article_title: str, article_content: str, language: Optional[str] = None) -> Dict[str, str]:
        """
        Generates short and long summaries for an article.
        Returns a dictionary with 'short_summary', 'long_summary', and validity flags.
        """
        logger.info(f"Generating summaries for article: {article_title}")

        lang_instruction = f"The summaries MUST be written in {language}." if language else "The summaries MUST be written in the same language as the news article provided."

        system_prompt = f"""
    You are a professional news editor.
    Your goal is to summarize news articles for a Telegram channel.

    CRITICAL: {lang_instruction}

    First, analyze if the content is a valid individual news article.
    REJECT if:
    - It is video-only content without substantial text.
    - It is a newsletter or a "digest" summarizing multiple different unrelated stories.
    - It is a generic landing page, login page, or error page.
    - It is a promotional or marketing piece masquerading as news.
    - The content is too short to generate a meaningful summary.

    Output must be strict JSON format with the following keys:
    - is_valid_news: boolean (true if valid news article, false if rejected based on criteria above)
    - rejection_reason: string (if is_valid_news is false, explain why concisely. Otherwise null or empty string)
    - short_summary: string (1-2 sentences, engaging but factual. Suitable for a notification. No emojis)
    - long_summary: string (2-3 short paragraphs, max 2-3 sentences each. Each paragraph MUST start with an appropriate emoji. Focus on the "Who, What, Where, Why" for the content. Do not use headings, only the emoji. Leave an empty line between paragraphs.)

    Formatting:
    - DO NOT USE MARKDOWN (no **, __, [], etc.).
    - Use HTML tags ONLY for specific emphasis: <b>bold</b>, <i>italic</i>.
    - Ensure all key entities (names, places, organizations) are preserved accurately.
    - Do not hallucinate facts not present in the source text.

    IMPORTANT: Response must be ONLY the JSON object. Do not include any explanations, greetings, or markdown markers outside the JSON.
        """

        if not article_content or len(article_content) < 10:
            logger.warning(f"No content available for article: {article_title}")
            return {
                'is_valid_news': False,
                'rejection_reason': 'No content available'
            }

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

        # logger.debug(f"LLM message for article summaries: {llm_message}")

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
                    logger.warning(f"Empty response from LLM summaries for '{article_title}' (possibly safety block) - attempt {attempt}")
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
                logger.error(f"Error generating summaries for '{article_title}' (attempt {attempt}): {e}")
                logger.debug(f"Error generating summaries. Sent content: {llm_message}")
                logger.debug(f"Error generating summaries. Received content: {response_content}")

        return {
            'short_summary': '',
            'long_summary': '',
            'is_valid_news': False,
            'rejection_reason': 'Analysis failed'
        }
