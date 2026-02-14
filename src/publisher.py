import asyncio
from telegram import Bot, InputMediaPhoto
from telegram.constants import ParseMode
from telegram.error import TelegramError
from .utils import setup_logger
from .fetcher import Article
from .analyzer_llm import AnalysisResult

logger = setup_logger("TelegramPublisher")

class TelegramPublisher:
    def __init__(self, item_token: str):
        self.bot = Bot(token=item_token)

    async def publish(self, article: Article, analysis: AnalysisResult, channel_id: str):
        """
        Publishes the article to the specified Telegram channel.
        1. Sends Photo/Message with Title and Short Summary.
        2. Replied to that message with Long Summary.
        """
        logger.info(f"Publishing article '{article.title}' to channel {channel_id}")

        # Construct the main message caption
        # Title as link, then short summary.
        caption = f"<b><a href='{article.link}'>{article.title}</a></b>\n\n"
        caption += f"{analysis.short_summary}\n\n"
        caption += f"<i>Source: {article.source_feed}</i>"

        try:
            message = None
            if article.image_url:
                try:
                    message = await self.bot.send_photo(
                        chat_id=channel_id,
                        photo=article.image_url,
                        caption=caption,
                        parse_mode=ParseMode.HTML
                    )
                except TelegramError as e:
                    logger.warning(f"Failed to send photo, falling back to text: {e}")
                    # Fallback if photo fails
                    message = await self.bot.send_message(
                        chat_id=channel_id,
                        text=caption,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=False
                    )
            else:
                message = await self.bot.send_message(
                    chat_id=channel_id,
                    text=caption,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=False
                )

            if message:
                # Post the long summary as a comment (reply)
                # Split if too long, though 2-3 paragraphs should fit in 4096 chars.
                comment_text = f"<b>Summary:</b>\n\n{analysis.long_summary}"
                
                await self.bot.send_message(
                    chat_id=channel_id,
                    text=comment_text,
                    reply_to_message_id=message.message_id,
                    parse_mode=ParseMode.HTML
                )
                logger.info(f"Successfully published {article.title}")
            
        except TelegramError as e:
            logger.error(f"Failed to publish article {article.title}: {e}")
