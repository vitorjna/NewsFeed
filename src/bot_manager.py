from telegram import Bot
from telegram.request import HTTPXRequest
from .utils import setup_logger

logger = setup_logger("TelegramBotManager")

class TelegramBotManager:
    """Centralized manager for Telegram Bot instances."""

    def __init__(self, token: str):
        self._token = token

    def create_bot(self) -> Bot:
        """Creates a fresh Bot instance with proper connection pool settings."""
        request = HTTPXRequest(
            connection_pool_size=20,
            read_timeout=30,
            write_timeout=30,
            connect_timeout=30,
            pool_timeout=10,
        )
        return Bot(token=self._token, request=request)
