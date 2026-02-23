import os
import sqlite3
from src.database import DatabaseManager
from src.article import Article

def test_article_uniqueness():
    db_path = os.path.join(os.getcwd(), "test_newsfeed.db")
    if os.path.exists(db_path):
        os.remove(db_path)

    db = DatabaseManager(db_path)

    # 1. Create two feeds for same URL (different themes)
    feed_url = "https://example.com/rss"
    feed_id1 = db.get_or_create_feed("Feed 1", feed_url, "Theme 1")
    feed_id2 = db.get_or_create_feed("Feed 2", feed_url, "Theme 2")

    print(f"Feed IDs: {feed_id1}, {feed_id2}")

    article_url = "https://example.com/article/1"

    # 2. Check if seen (should be False)
    print(f"Is seen (Feed 1)? {db.is_seen(article_url, feed_id1)}")
    print(f"Is seen (Feed 2)? {db.is_seen(article_url, feed_id2)}")

    # 3. Mark seen for Feed 1
    art1 = Article(
        title="Test Article",
        link=article_url,
        rss_summary="Summary",
        published="now",
        source_feed=feed_url,
        source_name="Feed 1",
        theme="Theme 1",
        feed_id=feed_id1
    )
    db.mark_seen(art1)
    print("Marked seen for Feed 1")

    # 4. Check again
    seen1 = db.is_seen(article_url, feed_id1)
    seen2 = db.is_seen(article_url, feed_id2)
    print(f"Is seen (Feed 1)? {seen1}")
    print(f"Is seen (Feed 2)? {seen2}")

    assert seen1 is True
    assert seen2 is False

    # 5. Mark seen for Feed 2
    art2 = Article(
        title="Test Article",
        link=article_url,
        rss_summary="Summary",
        published="now",
        source_feed=feed_url,
        source_name="Feed 2",
        theme="Theme 2",
        feed_id=feed_id2
    )
    db.mark_seen(art2)
    print("Marked seen for Feed 2")

    # 6. Check again
    seen2_final = db.is_seen(article_url, feed_id2)
    print(f"Is seen (Feed 2) final? {seen2_final}")
    assert seen2_final is True

    # Check database count
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM articles")
    count = c.fetchone()[0]
    print(f"Total articles in DB: {count}")
    assert count == 2

    print("Test PASSED!")
    os.remove(db_path)

if __name__ == "__main__":
    test_article_uniqueness()
