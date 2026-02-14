import json
from openai import OpenAI
from dataclasses import dataclass
from typing import Optional, Dict
from .utils import setup_logger
from .config import LLMConfig
from .fetcher import Article

logger = setup_logger("NewsAnalyzer")

@dataclass
class AnalysisResult:
    is_relevant: bool
    relevance_score: int # 1-10
    importance_score: int # 1-10
    urgency_score: int # 1-10
    short_summary: str # 1-2 sentences
    long_summary: str # 2-3 paragraphs
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

    def analyze_article(self, article: Article, prompt_focus: str) -> Optional[AnalysisResult]:
        """
        Analyzes an article using the configured LLM provider.
        """
        logger.info(f"Analyzing article: {article.title}")
        
        system_prompt = f"""
        You are a professional news editor and analyst.
        Your goal is to analyze news articles for a specific Telegram channel.
        
        Channel Focus: {prompt_focus}
        
        Output must be strict JSON format with the following keys:
        - is_relevant: boolean (true if it fits the channel focus well)
        - relevance_score: int (1-10)
        - importance_score: int (1-10)
        - urgency_score: int (1-10)
        - short_summary: string (1-2 sentences, engaging, suitable for a quick notification)
        - long_summary: string (2-3 paragraphs, detailed summary of the content)
        - reasoning: string (why you gave these scores)
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
                ],
                response_format={"type": "json_object"}
            )
            
            content = response.choices[0].message.content
            data = json.loads(content)
            
            return AnalysisResult(
                is_relevant=data.get('is_relevant', False),
                relevance_score=data.get('relevance_score', 0),
                importance_score=data.get('importance_score', 0),
                urgency_score=data.get('urgency_score', 0),
                short_summary=data.get('short_summary', ''),
                long_summary=data.get('long_summary', ''),
                reasoning=data.get('reasoning', '')
            )

        except Exception as e:
            logger.error(f"Error analyzing article {article.title}: {e}")
            return None
