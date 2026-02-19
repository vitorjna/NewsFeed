import yaml
import os
from typing import List, Optional
from dataclasses import dataclass
from .utils import setup_logger

logger = setup_logger("ConfigLoader")

@dataclass
class FeedConfig:
    name: str
    channel_id: str
    feeds: List[str]
    prompt_focus: str
    language: Optional[str] = None
    min_relevance_score: Optional[int] = None
    min_importance_score: Optional[int] = None
    min_urgency_score: Optional[int] = None
    include_image: bool = False

@dataclass
class LLMConfig:
    api_key: str
    base_url: str
    model: str

@dataclass
class AppConfig:
    telegram_bot_token: str
    llm: LLMConfig
    fetch_interval_minutes: int
    max_article_age_hours: int
    database_path: str
    min_relevance_score: int
    min_importance_score: int
    min_urgency_score: int
    themes: List[FeedConfig]
    debug: bool = False

def load_config(config_path: str = "config/config.yaml") -> AppConfig:
    """
    Loads the YAML configuration file and validates it.
    """
    if not os.path.exists(config_path):
        logger.error(f"Config file not found at {config_path}")
        raise FileNotFoundError(f"Config file not found at {config_path}")

    with open(config_path, 'r', encoding='utf-8') as f:
        try:
            raw_config = yaml.safe_load(f)
        except yaml.YAMLError as e:
            logger.error(f"Error parsing YAML config: {e}")
            raise

    try:
        llm_conf = LLMConfig(
            api_key=raw_config['llm'].get('api_key', 'not-needed'),
            base_url=raw_config['llm'].get('base_url', "http://localhost:1234/v1"),
            model=raw_config['llm'].get('model', "local-model")
        )

        themes = []
        for theme in raw_config['themes']:
            themes.append(FeedConfig(
                name=theme['name'],
                channel_id=theme['channel_id'],
                feeds=theme['feeds'],
                prompt_focus=theme.get('prompt_focus', ""),
                language=theme.get('language'),
                min_relevance_score=theme.get('min_relevance_score'),
                min_importance_score=theme.get('min_importance_score'),
                min_urgency_score=theme.get('min_urgency_score'),
                include_image=theme.get('include_image', False)
            ))

        config = AppConfig(
            telegram_bot_token=raw_config['telegram_bot_token'],
            llm=llm_conf,
            fetch_interval_minutes=raw_config.get('fetch_interval_minutes', 15),
            max_article_age_hours=raw_config.get('max_article_age_hours', 8),
            database_path=raw_config.get('database_path', 'data/seen_urls.db'),
            min_relevance_score=raw_config.get('min_relevance_score', 8),
            min_importance_score=raw_config.get('min_importance_score', 8),
            min_urgency_score=raw_config.get('min_urgency_score', 8),
            themes=themes,
            debug=raw_config.get('debug', False)
        )
        logger.info("Configuration loaded successfully")
        return config

    except KeyError as e:
        logger.error(f"Missing configuration key: {e}")
        raise ValueError(f"Missing configuration key: {e}")
