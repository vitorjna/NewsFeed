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
        caption += f"{article.short_summary}\n\n"
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

            # Determine where to post the long summary (comment)
            discussion_chat_id = None
            forwarded_message_id = None

            try:
                # 1. Check if the channel has a linked discussion group
                chat_info = await self.bot.get_chat(chat_id=channel_id)
                discussion_chat_id = chat_info.linked_chat_id
                
                if discussion_chat_id and message:
                    logger.info(f"Found linked discussion group ID: {discussion_chat_id}. Waiting for propagation...")
                    
                    # 2. Wait for Telegram to auto-forward the message to the group
                    await asyncio.sleep(4) 
                    
                    # 3. Find the forwarded message in the discussion group
                    # We look for updates in the discussion group that are forwards from the channel
                    # and have the same forward_from_message_id as our posted message.
                    # Note: handling updates without a webhook or long polling loop in a script
                    # that just runs periodically can be tricky. We might need to use get_updates
                    # with a short timeout/limit.
                    
                    # Check the last few updates
                    updates = await self.bot.get_updates(limit=20, offset=-20, timeout=2)
                    
                    for update in reversed(updates):
                        if (update.message and 
                            update.message.chat.id == discussion_chat_id and
                            update.message.forward_from_chat and
                            update.message.forward_from_chat.id == chat_info.id and
                            update.message.forward_from_message_id == message.message_id):
                                forwarded_message_id = update.message.message_id
                                logger.info(f"Found forwarded message {forwarded_message_id} in group {discussion_chat_id}")
                                break
                    
                    if not forwarded_message_id:
                        logger.warning("Could not find forwarded message in discussion group. Falling back to reply in channel.")

            except Exception as e:
                 logger.error(f"Error determining discussion group: {e}")

            if message:
                comment_text = f"<b>Summary:</b>\n\n{article.long_summary}"
                
                # Post to discussion group if found, otherwise reply to channel message (fallback)
                target_chat_id = discussion_chat_id if forwarded_message_id else channel_id
                reply_to = forwarded_message_id if forwarded_message_id else message.message_id
                
                await self.bot.send_message(
                    chat_id=target_chat_id,
                    text=comment_text,
                    reply_to_message_id=reply_to,
                    parse_mode=ParseMode.HTML
                )
                logger.info(f"Successfully published {article.title} (Comment in {target_chat_id})")
            
        except TelegramError as e:
            logger.error(f"Failed to publish article {article.title}: {e}")
