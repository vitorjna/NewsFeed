import os
import sqlite3
import time
from .fetcher import Article, FeedFetcher

def test_score_storage():
    db_path = "data/test_scores.db"
    if os.path.exists(db_path):
        os.remove(db_path)

    fetcher = FeedFetcher(db_path)

    url = "https://example.com/test-article"
    relevance = 8
    importance = 7
    urgency = 5
    reasoning = "This is a test article about scores."

    # Mark as seen with scores
    fetcher.mark_seen(url, relevance=relevance, importance=importance, urgency=urgency, reasoning=reasoning)

    # Verify storage
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute('SELECT relevance_score, importance_score, urgency_score, reasoning FROM seen_urls WHERE url = ?', (url,))
    row = c.fetchone()
    conn.close()

    assert row is not None
    assert row[0] == relevance
    assert row[1] == importance
    assert row[2] == urgency
    assert row[3] == reasoning
    print("Score storage test passed!")

    # Test update (ON CONFLICT)
    new_relevance = 10
    fetcher.mark_seen(url, relevance=new_relevance, importance=importance, urgency=urgency, reasoning="Updated reasoning")

    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute('SELECT relevance_score, reasoning FROM seen_urls WHERE url = ?', (url,))
    row = c.fetchone()
    conn.close()

    assert row[0] == new_relevance
    assert row[1] == "Updated reasoning"
    print("Score update (ON CONFLICT) test passed!")

if __name__ == "__main__":
    test_score_storage()
