import asyncio
from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError
from .utils import setup_logger, format_markdown_as_html
from .article import Article

logger = setup_logger("TelegramPublisher")

class TelegramPublisher:
    def __init__(self):
        # Cache: channel_id -> linked discussion group chat_id (or None)
        self._discussion_group_cache: dict[str, int | None] = {}

    async def publish(self, bot: Bot, article: Article, channel_id: str, include_image: bool = False, dev_mode: bool = False) -> None:
        """
        Publishes the article to the specified Telegram channel.
        1. Sends Photo/Message with Title and Short Summary.
        2. Replies to that message with Long Summary in the discussion group.
        """
        if dev_mode:
            logger.info(f"[DEV MODE] Skipping publication of article '{article.title}' to channel {channel_id}")
            return

        logger.info(f"[Telegram Publisher] Publishing article '{article.title}' to channel {channel_id}")

        # Construct the main message caption
        caption = f"<b>{article.title}</b>\n\n"
        caption += f"{format_markdown_as_html(article.short_summary)}\n\n"
        caption += f"<i><a href='{article.link}'>Source: {article.source_name}</a></i>"

        if article.hashtags:
            caption += f"\n\n{article.hashtags}"

        try:
            message = None
            published = False

            if include_image and article.image_url:
                try:
                    message = await bot.send_photo(
                        chat_id=channel_id,
                        photo=article.image_url,
                        caption=caption,
                        parse_mode=ParseMode.HTML
                    )
                    published = True

                except TelegramError as e:
                    logger.warning(f"[Telegram Publisher] Failed to send photo, falling back to text: {e}")

            if not published:
                # If include_image is False OR image_url is missing, rely on web page preview
                message = await bot.send_message(
                    chat_id=channel_id,
                    text=caption,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=False
                )

            if not message:
                return

            article.post_id = message.message_id

            # Determine where to post the long summary (as a comment) only if it exists

            if article.long_summary:
                discussion_chat_id = None
                forwarded_message_id = None

                try:
                    # 1. Get linked discussion group
                    chat_info = await bot.get_chat(chat_id=channel_id)
                    discussion_chat_id = chat_info.linked_chat_id

                    if discussion_chat_id:
                        # 2. Retry up to 5 times to find the forwarded message
                        max_attempts = 5
                        # Start with shorter sleep and increase slightly
                        sleep_times = [3, 5, 7, 10, 15]

                        for attempt in range(1, max_attempts + 1):
                            await asyncio.sleep(sleep_times[attempt-1])

                            try:
                                updates = await bot.get_updates(limit=20, offset=-20)
                                for update in reversed(updates):
                                    msg = update.message or update.channel_post
                                    # In discussion groups, it's often update.message
                                    if (msg and msg.chat.id == discussion_chat_id and
                                        msg.forward_from_chat and msg.forward_from_chat.id == chat_info.id and
                                        msg.forward_from_message_id == message.message_id):
                                        forwarded_message_id = msg.message_id
                                        logger.debug(f"[Telegram Publisher] Found forwarded message {forwarded_message_id} in discussion group on attempt {attempt}")
                                        break

                            except Exception as update_err:
                                logger.warning(f"[Telegram Publisher] Error fetching updates (attempt {attempt}/{max_attempts}): {update_err}")

                            if forwarded_message_id:
                                break

                    if not forwarded_message_id:
                        logger.error(f"[Telegram Publisher] Could not find forwarded message in discussion group for '{article.title}' after attempts. Skipping long summary comment.")
                    else:
                        # 3. Post the summary comment
                        formatted_long_summary = format_markdown_as_html(article.long_summary)
                        comment_text = f"<b>{article.title}</b>\n\n{formatted_long_summary}"

                        await bot.send_message(
                            chat_id=discussion_chat_id,
                            text=comment_text,
                            reply_to_message_id=forwarded_message_id,
                            parse_mode=ParseMode.HTML,
                            disable_notification=True
                        )
                        article.discussion_post_id = forwarded_message_id
                        logger.info(f"[Telegram Publisher] Successfully published '{article.title}' (Comment in discussion group {discussion_chat_id})")

                except Exception as e:
                    logger.error(f"[Telegram Publisher] Error handling discussion group publication for '{article.title}': {e}")
            else:
                logger.info(f"[Telegram Publisher] Successfully published '{article.title}' (No long summary generated)")

        except TelegramError as e:
            logger.error(f"[Telegram Publisher] Failed to publish article '{article.title}': {e}")
