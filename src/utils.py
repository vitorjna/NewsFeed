import logging
import sys
import os
import re
import html
import logging.handlers
from datetime import datetime

_shared_file_handler = None
_shared_stream_handler = None
_MULTI_LINE_JSON_PATTERN = re.compile(r'("[^"]*")\s*\n\s*("[^"]*")(?!\s*:)')
_HTML_TAG_PATTERN = re.compile(r'<[^>]*>')
_WHITESPACE_PATTERN = re.compile(r'\s+')

_MD_BOLD_STAR_PATTERN = re.compile(r'\*\*(.*?)\*\*')
_MD_BOLD_UNDERSCORE_PATTERN = re.compile(r'__(.*?)__')
_MD_ITALIC_STAR_PATTERN = re.compile(r'\*(.*?)\*')
_MD_ITALIC_UNDERSCORE_PATTERN = re.compile(r'_(.*?)_')
_MD_LINK_PATTERN = re.compile(r'\[(.*?)\]\((.*?)\)')

_RETRY_DELAY_PATTERN_1 = re.compile(r'retry in ([\d\.]+)s', re.IGNORECASE)
_RETRY_DELAY_PATTERN_2 = re.compile(r"['\"]retryDelay['\"]\s*:\s*['\"]([\d\.]+)s['\"]")

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
    Also fixes common JSON formatting issues like multi-line strings returned as separate quoted tokens instead of a single value.
    """
    # Try to find the first '{' and last '}'
    start = content.find('{')
    end = content.rfind('}')

    # if no '{' or '}' found, return the original content
    if start == -1 or end == -1:
        return content

    json_str = content[start:end+1]

    # Fix an issue where multiple quoted strings follow each other on separate lines
    # instead of being one long value.
    # Example: "long_summary": "Text1." \n "Text2."
    # The second string must NOT be followed by a colon (using negative lookahead).
    previous_str = None
    while previous_str != json_str:
        previous_str = json_str
        # Merge them with \n\n.
        # m.group(1)[:-1] removes trailing quote, m.group(2)[1:] removes leading quote
        json_str = _MULTI_LINE_JSON_PATTERN.sub(lambda m: f'{m.group(1)[:-1]}\\n\\n{m.group(2)[1:]}', json_str)

    return json_str

def clean_html(text: str) -> str:
    """
    Removes HTML tags and unescapes entities.
    Normalizes whitespace.
    """
    if not text:
        return ""
    # Remove HTML tags
    clean = _HTML_TAG_PATTERN.sub(' ', text)
    # Unescape HTML entities
    clean = html.unescape(clean)
    # Normalize whitespace
    clean = _WHITESPACE_PATTERN.sub(' ', clean).strip()
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
    text = _MD_BOLD_STAR_PATTERN.sub(r'<b>\1</b>', text)
    # Bold: __text__ -> <b>text</b>
    text = _MD_BOLD_UNDERSCORE_PATTERN.sub(r'<b>\1</b>', text)

    # Italic: *text* -> <i>text</i>
    # We use a lazy match and ensure it's not part of a tag
    text = _MD_ITALIC_STAR_PATTERN.sub(r'<i>\1</i>', text)
    # Italic: _text_ -> <i>text</i>
    text = _MD_ITALIC_UNDERSCORE_PATTERN.sub(r'<i>\1</i>', text)

    # Links: [text](url) -> <a href="url">text</a>
    text = _MD_LINK_PATTERN.sub(r'<a href="\2">\1</a>', text)

    return text

def extract_retry_delay(error_message) -> float:
    """
    Parses a rate limit error message to extract the wait time.
    Returns the wait time in seconds, or 0.0 if not found.
    """
    error_str = str(error_message)

    # Check for "retry in 44.793077872s"
    match = _RETRY_DELAY_PATTERN_1.search(error_str)
    if match:
        return float(match.group(1))

    # Check for "retryDelay": "44s" or 'retryDelay': '44s'
    match = _RETRY_DELAY_PATTERN_2.search(error_str)
    if match:
        return float(match.group(1))

    return 0.0
