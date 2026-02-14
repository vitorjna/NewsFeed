import yaml
import os
from typing import Dict, Any, List
from dataclasses import dataclass
from .utils import setup_logger

logger = setup_logger("ConfigLoader")

@dataclass
class FeedConfig:
    name: str
    channel_id: str
    feeds: List[str]
    prompt_focus: str

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
    database_path: str
    themes: List[FeedConfig]

def load_config(config_path: str = "config/config.yaml") -> AppConfig:
    """
    Loads the YAML configuration file and validates it.
    """
    if not os.path.exists(config_path):
        logger.error(f"Config file not found at {config_path}")
        raise FileNotFoundError(f"Config file not found at {config_path}")

    with open(config_path, 'r') as f:
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
                prompt_focus=theme.get('prompt_focus', "")
            ))

        config = AppConfig(
            telegram_bot_token=raw_config['telegram_bot_token'],
            llm=llm_conf,
            fetch_interval_minutes=raw_config.get('fetch_interval_minutes', 15),
            database_path=raw_config.get('database_path', 'data/seen_urls.db'),
            themes=themes
        )
        logger.info("Configuration loaded successfully")
        return config

    except KeyError as e:
        logger.error(f"Missing configuration key: {e}")
        raise ValueError(f"Missing configuration key: {e}")
