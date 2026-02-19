from typing import Dict, Optional
from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError
from .config import AppConfig
from .utils import setup_logger
from .bot_manager import TelegramBotManager

logger = setup_logger("CrossPromoter")

class CrossPromoter:
    def __init__(self, config: AppConfig, analyzer, bot_manager: TelegramBotManager):
        self.config = config
        self._bot_manager = bot_manager
        self.analyzer = analyzer
        self._channel_cache: Dict[str, dict] = {}

        self.intro = "<b>📢 Expand your worldview!</b>\n\n<i>Select your interests and join our other channels:</i>"
        self.outro = "👉 <i>Subscribe now and stay updated on the topics you care about!</i>"

    async def _get_channel_details(self, bot: Bot, channel_id: str) -> Optional[Dict[str, str]]:
        """
        Fetches channel details: title, username and invite link with local caching.
        """
        if channel_id in self._channel_cache:
            return self._channel_cache[str(channel_id)]

        try:
            chat = await bot.get_chat(chat_id=channel_id)
            logger.debug(f"Fetched chat details for {channel_id}: Title='{chat.title}', Username='{chat.username}', InviteLink='{chat.invite_link}'")
            details = {
                "title": chat.title,
                "username": f"@{chat.username}" if chat.username else None,
                "invite_link": chat.invite_link,
                "id": channel_id
            }
            self._channel_cache[channel_id] = details
            return details
        except TelegramError as e:
            logger.error(f"Failed to fetch chat info for {channel_id}: {e}")
            return None

    def _get_theme_content(self, theme_name: str) -> tuple[str, str]:
        """Returns (emoji, tagline) for a given theme with improved descriptions."""
        name_lower = theme_name.lower()

        if "portugal" in name_lower:
            return "🇵🇹", "Top news and updates from Portugal"
        if "world" in name_lower:
            return "🌍", "Major events and global perspectives"
        if "science" in name_lower:
            return "🔬", "Space news and scientific discoveries"
        if "tech" in name_lower:
            return "💻", "AI, gadgets, and tech industry news"
        if "entertainment" in name_lower:
            return "🎬", "Latest movie, TV, and celebrity news"

        return "📰", "Curated daily news and top stories"

    async def generate_promo_message(self, bot: Bot, exclude_channel_id: Optional[str] = None) -> str:
        """
        Constructs the promotional message with engaging descriptions,
        optionally excluding a specific channel.
        """
        blocks = [self.intro]

        channels_added = 0
        for theme in self.config.themes:
            # Skip the current channel if requested
            if exclude_channel_id and theme.channel_id == exclude_channel_id:
                continue

            details = await self._get_channel_details(bot, theme.channel_id)
            if not details:
                logger.warning(f"Skipping theme '{theme.name}': Could not fetch channel details.")
                continue

            # Link to the channel
            link_display = None
            if details['username']:
                link_display = details['username']
            elif details['invite_link']:
                # Use title with invite link if no public username
                link_display = f"<a href='{details['invite_link']}'>{details['title']}</a>"

            if not link_display:
                logger.warning(f"Skipping theme '{theme.name}': No username or invite link available for channel {theme.channel_id}.")
                continue

            emoji, description = self._get_theme_content(theme.name)

            # channel link
            #   channel description
            channel_block = f"<b>{link_display}</b>\n  {emoji} {description}"
            blocks.append(channel_block)
            channels_added += 1

        if channels_added == 0:
            return ""

        blocks.append(self.outro)

        # Separate blocks with double newline for whitespace
        message = "\n\n".join(blocks)
        return message

    async def promote_channels(self):
        """
        Sends a tailored promo message to all configured channels,
        showing only the other channels in the network.
        """
        async with self._bot_manager.create_bot() as bot:
            logger.info("Starting tailored cross-promotion sequence...")

            # Pre-cache all channel details to ensure efficiency
            for theme in self.config.themes:
                await self._get_channel_details(bot, theme.channel_id)

            for theme in self.config.themes:
                message = await self.generate_promo_message(bot, exclude_channel_id=theme.channel_id)

                if not message:
                    logger.warning(f"No promo message generated for {theme.name}.")
                    continue

                try:
                    await bot.send_message(
                        chat_id=theme.channel_id,
                        text=message,
                        parse_mode=ParseMode.HTML,
                        disable_notification=True
                    )
                    logger.info(f"Sent tailored promo to {theme.name} ({theme.channel_id})")
                except TelegramError as e:
                    logger.error(f"Failed to send promo to {theme.name}: {e}")
