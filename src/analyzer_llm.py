import json
from openai import OpenAI
from dataclasses import dataclass
from typing import Optional, Dict
from .utils import setup_logger, extract_json
from .config import LLMConfig
from .fetcher import Article

logger = setup_logger("NewsAnalyzer")

@dataclass
class AnalysisResult:
    relevance_score: int # 1-10
    importance_score: int # 1-10
    urgency_score: int # 1-10
    reasoning: str

class NewsAnalyzer:
    def __init__(self, config: LLMConfig):
        # We use the OpenAI client as it's compatible with most local providers
        # like LM Studio and Ollama.
        self.llm_client = OpenAI(
            api_key=config.api_key,
            base_url=config.base_url
        )
        self.model = config.model

    def analyze_scores(self, article: Article, prompt_focus: str) -> Optional[AnalysisResult]:
        """
        Analyzes an article for relevance, importance, and urgency.
        """
        logger.info(f"Analyzing scores for article: {article.title}")

        system_prompt = f"""
        You are a professional news editor and analyst.
        Your goal is to analyze news articles for a specific Telegram channel.

        Channel Focus: {prompt_focus}

        Output must be strict JSON format with the following keys:
        - relevance_score: int (1-10) - How well does this align with the specific channel focus? (1=Not at all, 10=Perfect match)
        - importance_score: int (1-10) - How significant is this event globally or within its domain? (1=Trivia, 10=Historic/Major Impact)
        - urgency_score: int (1-10) - Does this require immediate attention? (1=Evergreen/Slow, 10=Breaking/Immediate Action)
        - reasoning: string (1 sentence for why you gave these scores)

        IMPORTANT: Response must be ONLY the JSON object. Do not include any explanations, greetings, or markdown markers outside the JSON.
        """

        user_content = f"""
        Title: {article.title}
        Link: {article.link}
        Content/Summary: {article.summary}
        """

        # Gemini's OpenAI-compatible API often fails with 'system' role for some models (Gemma)
        if "google" in str(self.llm_client.base_url).lower():
            messages = [
                {"role": "user", "content": f"{system_prompt}\n\nUSER REQUEST:\n{user_content}"}
            ]

        else:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ]

        try:
            response = self.llm_client.chat.completions.create(
                model=self.model,
                messages=messages
            )

            content = response.choices[0].message.content
            if not content:
                logger.warning(f"Empty response from LLM for {article.title} (possibly safety block)")
                return None

            content = extract_json(content)
            data = json.loads(content)

            return AnalysisResult(
                relevance_score=data.get('relevance_score', 0),
                importance_score=data.get('importance_score', 0),
                urgency_score=data.get('urgency_score', 0),
                reasoning=data.get('reasoning', '')
            )

        except Exception as e:
            logger.error(f"Error analyzing scores for {article.title}: {e}")
            return None

    def analyze_summaries(self, article: Article, language: Optional[str] = None) -> Optional[Dict[str, str]]:
        """
        Generates short and long summaries for an article.
        Returns a dictionary with 'short_summary' and 'long_summary'.
        """
        logger.info(f"Generating summaries for article: {article.title}")

        lang_instruction = f"The summaries MUST be written in {language}." if language else "The summaries MUST be written in the same language as the news article provided."

        system_prompt = f"""
        You are a professional news editor.
        Your goal is to summarize news articles for a Telegram channel.

        CRITICAL: {lang_instruction}

        Output must be strict JSON format with the following keys:
        - short_summary: string (1-2 sentences, engaging, suitable for a quick notification.)
        - long_summary: string (2-3 paragraphs. Each paragraph MUST start with an appropriate emoji related to its content. The summary should be concise, covering the main points of the article.)

        FORMATTING RULES:
        - DO NOT USE MARKDOWN (no **, __, [], etc.).
        - Use HTML tags only for emphasis: <b>bold</b>, <i>italic</i>, <u>underline</u>.
        - If the text contains characters that might break HTML (like < or > that are not part of tags), escape them or ensure they don't break the structure.

        IMPORTANT: Response must be ONLY the JSON object. Do not include any explanations, greetings, or markdown markers outside the JSON.
        """

        content_to_summarize = article.full_text if article.full_text else article.summary
        content_type = "Full Article Text" if article.full_text else "RSS Summary"

        user_content = f"""
        Title: {article.title}
        Link: {article.link}
        {content_type}: {content_to_summarize}
        """

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]

        # Gemini's OpenAI-compatible API often fails with 'system' role for some models (Gemma)
        if "google" in str(self.llm_client.base_url).lower():
            messages = [
                {"role": "user", "content": f"{system_prompt}\n\nUSER REQUEST:\n{user_content}"}
            ]

        try:
            response = self.llm_client.chat.completions.create(
                model=self.model,
                messages=messages
            )

            content = response.choices[0].message.content
            if not content:
                logger.warning(f"Empty response from LLM summaries for {article.title} (possibly safety block)")
                return None

            content = extract_json(content)
            data = json.loads(content)

            return {
                'short_summary': data.get('short_summary', ''),
                'long_summary': data.get('long_summary', '')
            }

        except Exception as e:
            logger.error(f"Error generating summaries for {article.title}: {e}")
            return None
