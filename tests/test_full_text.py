from src.fetcher import FeedFetcher, Article
import logging
import sys

# Setup a basic logger to see what's happening
logging.basicConfig(level=logging.INFO, stream=sys.stdout)

def test_extraction():
    fetcher = FeedFetcher("data/test_database.db")
    # Using a known stable URL for testing
    test_url = "https://www.theverge.com/2024/2/15/24074001/openai-sora-generative-video-model-announcement"

    print(f"Testing extraction for: {test_url}")
    full_text = fetcher.fetch_full_text(test_url)

    if full_text:
        print("\nSUCCESS: Extracted full text!")
        print(f"Length: {len(full_text)} characters")
        print("\nPreview (first 500 chars):")
        print(full_text[:500] + "...")
    else:
        print("\nFAILURE: Could not extract full text.")

if __name__ == "__main__":
    test_extraction()
