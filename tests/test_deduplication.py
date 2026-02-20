import os
import sqlite3
import time
from .fetcher import Article, FeedFetcher

def test_similarity_deduplication_and_summaries():
    db_path = "data/test_dedup_v3.db"
    if os.path.exists(db_path):
        os.remove(db_path)

    fetcher = FeedFetcher(db_path)

    test_article = Article(
        title="Apple releases new iPhone 16 with AI features",
        link="https://tech.com/iphone-16",
        rss_summary="Apple announced the new iPhone 16...",
        published=str(time.time()),
        source_feed="https://tech.com/rss",
        source_name="TechNews",
        theme="Tech",
        short_summary="A short summary of the iPhone 16 launch."
    )

    # Initially no similar article
    assert fetcher.is_similar_already_published(test_article) is None

    # Mark as published
    fetcher.mark_published(test_article)

    # Verify summary is in database
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute('SELECT short_summary, rss_summary FROM published_articles WHERE url = ?', (test_article.link,))
    short_in_db, rss_in_db = c.fetchone()
    conn.close()
    assert short_in_db == test_article.short_summary
    assert rss_in_db == test_article.rss_summary
    print(f"Verified short summary storage: {short_in_db}")
    print(f"Verified RSS summary storage: {rss_in_db}")

    # Exact match should be caught
    assert fetcher.is_similar_already_published(test_article) == test_article.title

    # Very similar title should be caught
    similar_article = Article(
        title="Apple releases new iPhone 16 with AI functionality",
        link="https://other.com/apple-iphone",
        rss_summary="Summary here",
        published=str(time.time()),
        source_feed="https://other.com/rss",
        source_name="OtherStuff",
        theme="Tech"
    )

    found_title = fetcher.is_similar_already_published(similar_article)
    print(f"Found similar title: {found_title}")
    assert found_title is not None

    # Similar summary check (with lower threshold 0.6)
    article_diff_title = Article(
        title="Something Totally Different",
        link="https://diff.com/article",
        rss_summary="Apple announced the new iPhone 16...", # Same summary as test_article
        published=str(time.time()),
        source_feed="https://diff.com/rss",
        source_name="DiffSource",
        theme="Tech"
    )
    found_title_by_sum = fetcher.is_similar_already_published(article_diff_title)
    print(f"Found similar by summary (title was different): {found_title_by_sum}")
    assert found_title_by_sum is not None

    print("Similarity and summary storage tests passed!")

if __name__ == "__main__":
    test_similarity_deduplication_and_summaries()
