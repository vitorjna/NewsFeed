from typing import Dict
from telegram import Bot
from telegram.error import TelegramError
from telegram.request import HTTPXRequest
from .config import AppConfig
from .utils import setup_logger

logger = setup_logger("CrossPromoter")

class CrossPromoter:
    def __init__(self, config: AppConfig, analyzer):
        self.config = config
        # Increase connection pool size and timeout to prevent "Pool timeout" errors
        request = HTTPXRequest(connection_pool_size=20, read_timeout=20, write_timeout=20, connect_timeout=20, pool_timeout=20)
        self.bot = Bot(token=config.telegram_bot_token, request=request)
        self.analyzer = analyzer

    async def _get_channel_details(self, channel_id: str) -> Dict[str, str]:
        """
        Fetches channel details: title, username and invite link.
        """
        try:
            chat = await self.bot.get_chat(chat_id=channel_id)
            logger.debug(f"Fetched chat details for {channel_id}: Title='{chat.title}', Username='{chat.username}', InviteLink='{chat.invite_link}'")
            return {
                "title": chat.title,
                "username": f"@{chat.username}" if chat.username else None,
                "invite_link": chat.invite_link,
                "id": channel_id
            }
        except TelegramError as e:
            logger.error(f"Failed to fetch chat info for {channel_id}: {e}")
            return None

    def _get_theme_content(self, theme_name: str) -> tuple[str, str]:
        """Returns (emoji, description) for a given theme."""
        name_lower = theme_name.lower()

        if "portugal" in name_lower:
            return "🇵🇹", "Breaking news & updates from Portugal, in Portuguese"
        if "world" in name_lower:
            return "🌍", "Breaking world news & major global events"
        if "science" in name_lower:
            return "🔬", "Science news & space exploration"
        if "tech" in name_lower:
            return "💻", "Tech news & AI, gadgets & tech trends"
        if "entertainment" in name_lower:
            return "🎬", "Movies, TV & celebrity news"

        return "📰", "Top stories & daily updates"

    async def generate_promo_message(self) -> str:
        """
        Constructs the promotional message with hardcoded engaging descriptions.
        """
        lines = [
            "<b>📢 Expand your worldview with our network!</b>\n",
            "<i>Select your interests and join our other channels:</i>\n"
        ]

        channels_added = 0
        for theme in self.config.themes:
            details = await self._get_channel_details(theme.channel_id)
            if not details:
                logger.debug(f"Skipping theme '{theme.name}': Could not fetch channel details.")
                continue

            # Determine how to link to the channel
            link_display = None
            if details['username']:
                link_display = details['username']
            elif details['invite_link']:
                # Fallback to title with invite link if no public username
                link_display = f"<a href='{details['invite_link']}'>{details['title']}</a>"

            if not link_display:
                logger.debug(f"Skipping theme '{theme.name}': No username or invite link available for channel {theme.channel_id}.")
                continue

            emoji, description = self._get_theme_content(theme.name)
            lines.append(f"{emoji} <b>{link_display}</b>: {description}")
            channels_added += 1

        lines.append("\n👉 <i>Subscribe now and stay updated on the topics you care about!</i>")

        message = "\n".join(lines)
        logger.debug(f"Generated cross-promotion message (channels found: {channels_added}):\n{message}")
        return message

    async def promote_channels(self):
        """
        Sends the promo message to all configured channels.
        """
        message = await self.generate_promo_message()
        if not message:
            logger.warning("No promo message generated.")
            return

        logger.info("Sending cross-promotion message...")
        for theme in self.config.themes:
            try:
                await self.bot.send_message(
                    chat_id=theme.channel_id,
                    text=message,
                    parse_mode='HTML',
                    disable_notification=True
                )
                logger.info(f"Sent promo to {theme.name} ({theme.channel_id})")
                logger.debug(f"Promo message: {message}")
            except TelegramError as e:
                logger.error(f"Failed to send promo to {theme.name}: {e}")
