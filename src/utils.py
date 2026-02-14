import logging
import sys

def setup_logger(name: str = "NewsFeedApp", level=logging.INFO):
    """
    Sets up a logger with stdout handler.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    
    return logger

def extract_json(content: str) -> str:
    """
    Cleans the LLM response to extract only the JSON part.
    Removes markdown code blocks if present.
    """
    content = content.strip()
    if content.startswith("```json"):
        content = content[7:]
    elif content.startswith("```"):
        content = content[3:]
    
    if content.endswith("```"):
        content = content[:-3]
        
    return content.strip()
