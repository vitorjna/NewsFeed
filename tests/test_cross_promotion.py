import asyncio
from unittest.mock import MagicMock, AsyncMock
from src.cross_promoter import CrossPromoter
from src.config import AppConfig, FeedConfig

async def test_generate_promo_message():
    # Mock Config
    mock_config = MagicMock(spec=AppConfig)
    mock_config.telegram_bot_token = "fake_token"
    mock_config.themes = [
        FeedConfig(name="Breaking News - Portugal", channel_id="-1001", feeds=[], prompt_focus=""),
        FeedConfig(name="Breaking News - World", channel_id="-1002", feeds=[], prompt_focus=""),
        FeedConfig(name="Tech News", channel_id="-1003", feeds=[], prompt_focus=""),
        FeedConfig(name="Science News", channel_id="-1004", feeds=[], prompt_focus=""),
    ]

    # Mock Analyzer
    mock_analyzer = MagicMock()

    # Initialize Promoter
    promoter = CrossPromoter(mock_config, mock_analyzer)

    # Mock Bot methods
    promoter.bot = AsyncMock()

    # Mock get_chat return values
    async def get_chat_side_effect(chat_id):
        mock_chat = MagicMock()
        mock_chat.invite_link = None
        if chat_id == "-1001":
            mock_chat.title = "Portugal News"
            mock_chat.username = "portugal_news_feed"
        elif chat_id == "-1002":
            mock_chat.title = "World News"
            mock_chat.username = "world_news_feed"
        elif chat_id == "-1003":
            mock_chat.title = "Tech News"
            mock_chat.username = "tech_news_feed"
        elif chat_id == "-1004":
            mock_chat.title = "Science Channel"
            mock_chat.username = None
            mock_chat.invite_link = "https://t.me/+invite_link"
        return mock_chat

    promoter.bot.get_chat.side_effect = get_chat_side_effect

    # Generate message
    message = await promoter.generate_promo_message()

    # Handle Windows encoding for console print
    import sys
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    print("\n--- Generated Promo Message ---\n")
    print(message)
    print("\n-------------------------------\n")

    # Assertions
    assert "🇵🇹" in message
    assert "@portugal_news_feed" in message
    assert "Breaking news & updates from Portugal" in message

    assert "🌍" in message
    assert "@world_news_feed" in message

    assert "💻" in message
    assert "@tech_news_feed" in message

    # Check fallback for Science News
    assert "🔬" in message
    assert "Science Channel" in message
    assert "https://t.me/+invite_link" in message

if __name__ == "__main__":
    asyncio.run(test_generate_promo_message())
