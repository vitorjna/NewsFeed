import logging
import sys
import os
import re
import html
import logging.handlers
from datetime import datetime

_shared_file_handler = None
_shared_stream_handler = None

def setup_logger(name: str = "NewsFeedApp", level=logging.INFO):
    """
    Sets up a logger with stdout and rotating file handler.
    """
    global _shared_file_handler, _shared_stream_handler

    logger = logging.getLogger(name)
    logger.setLevel(level)

    if not logger.handlers:
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )

        # Console handler
        if _shared_stream_handler is None:
            _shared_stream_handler = logging.StreamHandler(sys.stdout)
            _shared_stream_handler.setFormatter(formatter)
        logger.addHandler(_shared_stream_handler)

        # Rotating file handler
        log_dir = "logs"
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)

        if _shared_file_handler is None:
            date_str = datetime.now().strftime("%Y-%m-%d")
            _shared_file_handler = logging.handlers.RotatingFileHandler(
                filename=os.path.join(log_dir, f"app_{date_str}.log"),
                maxBytes=0, # Disable automatic rollover
                backupCount=9,
                encoding='utf-8'
            )
            # _shared_file_handler.doRollover() # we now use a new file every day
            _shared_file_handler.setFormatter(formatter)
        logger.addHandler(_shared_file_handler)

    return logger

def extract_json(content: str) -> str:
    """
    Cleans the LLM response to extract only the JSON part.
    Removes markdown code blocks if present.
    """
    content = content.strip()

    # Try to find the first '{' and last '}'
    start = content.find('{')
    end = content.rfind('}')

    if start != -1 and end != -1:
        return content[start:end+1]

    return content.strip()

def clean_html(text: str) -> str:
    """
    Removes HTML tags and unescapes entities.
    Normalizes whitespace.
    """
    if not text:
        return ""
    # Remove HTML tags
    clean = re.sub(r'<[^>]*>', ' ', text)
    # Unescape HTML entities
    clean = html.unescape(clean)
    # Normalize whitespace
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean

def format_markdown_as_html(text: str) -> str:
    """
    Converts basic markdown (bold, italic, links) to HTML for Telegram.
    This acts as a safety layer in case the LLM uses markdown instead of HTML.
    """
    if not text:
        return ""

    # 1. Escape characters that break HTML but keep existing tags?
    # This is tricky. Let's do simple MD to HTML conversion first.

    # Bold: **text** -> <b>text</b>
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
    # Bold: __text__ -> <b>text</b>
    text = re.sub(r'__(.*?)__', r'<b>\1</b>', text)

    # Italic: *text* -> <i>text</i>
    # We use a lazy match and ensure it's not part of a tag
    text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', text)
    # Italic: _text_ -> <i>text</i>
    text = re.sub(r'_(.*?)_', r'<i>\1</i>', text)

    # Links: [text](url) -> <a href="url">text</a>
    text = re.sub(r'\[(.*?)\]\((.*?)\)', r'<a href="\2">\1</a>', text)

    return text
