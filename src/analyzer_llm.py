import json
from openai import OpenAI
from dataclasses import dataclass
import datetime
from typing import Optional, Dict
from .utils import setup_logger, extract_json
from .config import LLMConfig

logger = setup_logger("NewsAnalyzer")

@dataclass
class AnalysisResult:
    relevance_score: int # 1-10
    importance_score: int # 1-10
    urgency_score: int # 1-10
    reasoning: str

class NewsAnalyzer:
    def __init__(self, config: LLMConfig):
        # We use the OpenAI client as it's compatible with most providers (local or cloud)
        self.llm_client = OpenAI(
            api_key=config.api_key,
            base_url=config.base_url
        )
        self.model = config.model

    def analyze_scores(self, article_title: str, article_content: str, prompt_focus: str) -> Optional[AnalysisResult]:
        """
        Analyzes an article for relevance, importance, and urgency.
        """
        logger.info(f"Analyzing scores for article: {article_title}")

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
        if "google" in str(self.llm_client.base_url).lower():
            llm_message = [
                {"role": "user", "content": f"{system_prompt}\n\nUSER REQUEST:\n{user_content}"}
            ]

        else:
            llm_message = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ]

        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = self.llm_client.chat.completions.create(
                    model=self.model,
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
                    reasoning=data.get('reasoning', '')
                )

            except Exception as e:
                logger.error(f"Error analyzing scores for '{article_title}' (attempt {attempt + 1}): {e}")

        return None

    def analyze_summaries(self, article_title: str, article_content: str, language: Optional[str] = None) -> Optional[Dict[str, str]]:
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
    - long_summary: string (2-3 paragraphs. Each paragraph MUST start with an appropriate emoji. Focus on the "Who, What, Where, Why" for the content. Do not use headings, only the emoji. Leave an empty line between paragraphs.)

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
        if "google" in str(self.llm_client.base_url).lower():
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
                response = self.llm_client.chat.completions.create(
                    model=self.model,
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
                logger.debug(f"Error generating summaries. Received content: {response_content}")

        return None
