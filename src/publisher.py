import asyncio
from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.request import HTTPXRequest
from .utils import setup_logger, format_markdown_as_html
from .fetcher import Article
from .analyzer_llm import AnalysisResult

logger = setup_logger("TelegramPublisher")

class TelegramPublisher:
    def __init__(self, item_token: str):
        # Increase connection pool size and timeout to prevent "Pool timeout" errors
        request = HTTPXRequest(connection_pool_size=20, read_timeout=20, write_timeout=20, connect_timeout=20, pool_timeout=20)
        self.bot = Bot(token=item_token, request=request)

    async def publish(self, article: Article, analysis: AnalysisResult, channel_id: str):
        """
        Publishes the article to the specified Telegram channel.
        1. Sends Photo/Message with Title and Short Summary.
        2. Replied to that message with Long Summary in the discussion group.
        """
        logger.info(f"Publishing article '{article.title}' to channel {channel_id}")

        # Construct the main message caption
        caption = f"<b>{article.title}</b>\n\n"
        caption += f"{format_markdown_as_html(article.short_summary)}\n\n"
        caption += f"<i>Source: <a href='{article.link}'>{article.source_name}</a></i>"

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

            if not message:
                return

            # Determine where to post the long summary (comment) only if it exists
            if article.long_summary:
                discussion_chat_id = None
                forwarded_message_id = None

                try:
                    # 1. Get linked discussion group
                    chat_info = await self.bot.get_chat(chat_id=channel_id)
                    discussion_chat_id = chat_info.linked_chat_id

                    if discussion_chat_id:
                        # 2. Sequential wait for propagation (usually fast if bot is admin)
                        await asyncio.sleep(5)

                        try:
                            updates = await self.bot.get_updates(limit=50, offset=-50)
                            for update in reversed(updates):
                                msg = update.message
                                if (msg and msg.chat.id == discussion_chat_id and
                                    msg.forward_from_chat and msg.forward_from_chat.id == chat_info.id and
                                    msg.forward_from_message_id == message.message_id):
                                    forwarded_message_id = msg.message_id
                                    logger.info(f"Found forwarded message {forwarded_message_id}")
                                    break
                        except Exception as update_err:
                            logger.warning(f"Error fetching updates for comment: {update_err}")

                except Exception as e:
                    logger.error(f"Error determining discussion group: {e}")

                # 3. Post the summary comment
                formatted_long_summary = format_markdown_as_html(article.long_summary)
                comment_text = f"<b>Summary:</b>\n\n{formatted_long_summary}"
                target_chat_id = discussion_chat_id if forwarded_message_id else channel_id
                reply_to = forwarded_message_id if forwarded_message_id else message.message_id

                await self.bot.send_message(
                    chat_id=target_chat_id,
                    text=comment_text,
                    reply_to_message_id=reply_to,
                    parse_mode=ParseMode.HTML,
                    disable_notification=True
                )
                logger.info(f"Successfully published {article.title} (Comment in {target_chat_id})")
            else:
                logger.info(f"Successfully published {article.title} (No long summary)")

        except TelegramError as e:
            logger.error(f"Failed to publish article {article.title}: {e}")
