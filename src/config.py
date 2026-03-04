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
    default_hashtags: Optional[str] = None

@dataclass
class LLMConfig:
    primary_api_key: str
    primary_base_url: str
    primary_model: str
    secondary_api_key: str
    secondary_base_url: str
    secondary_model: str

@dataclass
class EmbeddingConfig:
    embedding_api_key: str
    embedding_base_url: str
    embedding_model: str

@dataclass
class AppConfig:
    telegram_bot_token: str
    llm: LLMConfig
    embeddings: EmbeddingConfig
    fetch_interval_minutes: int
    max_article_age_hours: int
    database_path: str
    min_relevance_score: int
    min_importance_score: int
    min_urgency_score: int
    themes: List[FeedConfig]
    debug: bool = False
    dev_mode: bool = False

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
            primary_api_key=raw_config['llm'].get('primary_api_key', 'not-needed'),
            primary_base_url=raw_config['llm'].get('primary_base_url', "http://localhost:1234/v1"),
            primary_model=raw_config['llm'].get('primary_model', "gemma-3-27b-it"),
            secondary_api_key=raw_config['llm'].get('secondary_api_key', 'not-needed'),
            secondary_base_url=raw_config['llm'].get('secondary_base_url', "http://localhost:1234/v1"),
            secondary_model=raw_config['llm'].get('secondary_model', "gemma-3-12b-it")
        )

        emb_conf = EmbeddingConfig(
            embedding_api_key=raw_config.get('embeddings', {}).get('embedding_api_key', 'not-needed'),
            embedding_base_url=raw_config.get('embeddings', {}).get('embedding_base_url', "http://localhost:1234/v1"),
            embedding_model=raw_config.get('embeddings', {}).get('embedding_model', "text-embedding-3-small")
        )

        themes = []

        config = AppConfig(
            telegram_bot_token=raw_config['telegram_bot_token'],
            llm=llm_conf,
            embeddings=emb_conf,
            fetch_interval_minutes=raw_config.get('fetch_interval_minutes', 15),
            max_article_age_hours=raw_config.get('max_article_age_hours', 8),
            database_path=raw_config.get('database_path', 'data/newsfeed.db'),
            min_relevance_score=raw_config.get('min_relevance_score', 8),
            min_importance_score=raw_config.get('min_importance_score', 7),
            min_urgency_score=raw_config.get('min_urgency_score', 7),
            themes=themes,
            debug=raw_config.get('debug', False),
            dev_mode=raw_config.get('dev_mode', False)
        )

        for theme in raw_config['themes']:
            themes.append(FeedConfig(
                name=theme['name'],
                channel_id=theme['channel_id'],
                feeds=theme['feeds'],
                prompt_focus=theme.get('prompt_focus', ""),
                language=theme.get('language'),
                min_relevance_score=theme.get('min_relevance_score', config.min_relevance_score),
                min_importance_score=theme.get('min_importance_score', config.min_importance_score),
                min_urgency_score=theme.get('min_urgency_score', config.min_urgency_score),
                include_image=theme.get('include_image', False),
                default_hashtags=theme.get('default_hashtags')
            ))

        return config

    except KeyError as e:
        logger.error(f"Missing configuration key: {e}")
        raise ValueError(f"Missing configuration key: {e}")
