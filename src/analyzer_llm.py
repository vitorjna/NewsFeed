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

        try:
            response = self.llm_client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ]
            )
            
            content = response.choices[0].message.content
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

    def analyze_summaries(self, article: Article) -> Optional[Dict[str, str]]:
        """
        Generates short and long summaries for an article.
        Returns a dictionary with 'short_summary' and 'long_summary'.
        """
        logger.info(f"Generating summaries for article: {article.title}")

        system_prompt = """
        You are a professional news editor.
        Your goal is to summarize news articles for a Telegram channel.

        Output must be strict JSON format with the following keys:
        - short_summary: string (1-2 sentences, engaging, suitable for a quick notification)
        - long_summary: string (2-3 paragraphs, summary of the content in a few short sentences, so the user gets all the info with a quick glance)

        IMPORTANT: Response must be ONLY the JSON object. Do not include any explanations, greetings, or markdown markers outside the JSON.
        """

        user_content = f"""
        Title: {article.title}
        Link: {article.link}
        Content/Summary: {article.summary}
        """

        try:
            response = self.llm_client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ]
            )

            content = response.choices[0].message.content
            content = extract_json(content)
            data = json.loads(content)

            return {
                'short_summary': data.get('short_summary', ''),
                'long_summary': data.get('long_summary', '')
            }

        except Exception as e:
            logger.error(f"Error generating summaries for {article.title}: {e}")
            return None
