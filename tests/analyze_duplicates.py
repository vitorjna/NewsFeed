"""
analyze_duplicates.py
─────────────────────────────────────────────────────────────────────────────
Offline analysis script: reads ALL published articles from the database,
computes (or re-uses) their embeddings, and detects pairs that would have
been flagged as duplicates by the embeddings-based deduplication pipeline.

Usage (from the repo root):
    python -m tests.analyze_duplicates [--config config/config.yaml]
                                       [--min-threshold 0.70]
                                       [--max-threshold 0.84]
                                       [--days 7]
                                       [--theme "Tech News"]
                                       [--output results.txt]

Dependencies: all standard NewsFeed dependencies (openai, yaml, etc.)
"""

import argparse
import json
import math
import sqlite3
import sys
import os
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Optional

# ── Ensure the project root is importable ──────────────────────────────────
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.config import load_config, EmbeddingConfig
from openai import OpenAI

# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────

def cosine_similarity(a: list, b: list) -> float:
    """Compute cosine similarity between two vectors."""
    dot   = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def sequence_similarity(s1: str, s2: str) -> float:
    """SequenceMatcher similarity ratio between two strings."""
    return SequenceMatcher(None, s1.lower(), s2.lower()).ratio()


def fmt_date(dt_str: Optional[str]) -> str:
    if not dt_str:
        return "N/A"
    return dt_str[:16]


# ─────────────────────────────────────────────────────────────────────────
# Database helpers
# ─────────────────────────────────────────────────────────────────────────

def fetch_published_articles(db_path: str, theme: Optional[str], days: Optional[int]) -> list[dict]:
    """
    Returns published articles from the DB.
    Columns: id, title, rss_summary, short_summary, embedding, published_at, theme
    """
    conn = sqlite3.connect(db_path)
    c    = conn.cursor()

    query = """
        SELECT a.id, a.title, a.rss_summary, a.short_summary, a.embedding, a.published_at, f.theme
        FROM articles a
        JOIN feeds f ON a.feed_id = f.id
        WHERE a.post_id != -1
    """
    params: list = []

    if theme:
        query += " AND f.theme = ?"
        params.append(theme)

    if days:
        cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
        query += " AND a.published_at >= ?"
        params.append(cutoff)

    query += " ORDER BY f.theme, a.published_at"

    c.execute(query, params)
    rows = c.fetchall()
    conn.close()

    return [
        {
            "id":           row[0],
            "title":        row[1] or "",
            "rss_summary":  row[2] or "",
            "short_summary":row[3] or "",
            "embedding":    row[4],
            "published_at": row[5],
            "theme":        row[6],
        }
        for row in rows
    ]


def save_embedding(db_path: str, article_id: int, embedding_json: str) -> None:
    """Persist a computed embedding back to the database."""
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE articles SET embedding = ? WHERE id = ?", (embedding_json, article_id))
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────────────────────────────────
# Embedding helpers
# ─────────────────────────────────────────────────────────────────────────

def compute_embedding(client: OpenAI, model: str, text: str) -> Optional[list]:
    """Call the embeddings API and return the vector."""
    try:
        response = client.embeddings.create(input=text, model=model)
        return response.data[0].embedding
    except Exception as e:
        print(f"  [WARN] Embedding API error: {e}", file=sys.stderr)
        return None


# ─────────────────────────────────────────────────────────────────────────
# Core similarity analysis
# ─────────────────────────────────────────────────────────────────────────

def analyse_theme(articles: list[dict], threshold: float) -> list[dict]:
    """
    Compare every pair of articles within a theme.
    Returns a list of 'hit' dicts for pairs above the threshold.
    """
    hits = []

    for i in range(len(articles)):
        a = articles[i]
        a_vec = json.loads(a["embedding"]) if a["embedding"] else None

        for j in range(i + 1, len(articles)):
            b = articles[j]
            b_vec = json.loads(b["embedding"]) if b["embedding"] else None

            # --- Embedding similarity ----------------------------------------
            emb_sim = None
            if a_vec and b_vec:
                emb_sim = cosine_similarity(a_vec, b_vec)

            # --- Fallback: SequenceMatcher on title + summary ----------------
            title_sim   = sequence_similarity(a["title"],        b["title"])
            summary_sim = sequence_similarity(
                a["short_summary"] or a["rss_summary"],
                b["short_summary"] or b["rss_summary"]
            )

            # Combined score: prefer embedding, fall back to text similarity
            combined = emb_sim if emb_sim is not None else max(title_sim, summary_sim)

            if combined >= threshold or title_sim >= 0.55 or summary_sim >= 0.50:
                hits.append({
                    "article_a":    a,
                    "article_b":    b,
                    "emb_sim":      emb_sim,
                    "title_sim":    title_sim,
                    "summary_sim":  summary_sim,
                    "combined":     combined,
                    "flagged_emb":  emb_sim is not None and emb_sim >= threshold,
                    "flagged_text": title_sim >= 0.55 or summary_sim >= 0.50,
                })

    return hits


# ─────────────────────────────────────────────────────────────────────────
# Report rendering
# ─────────────────────────────────────────────────────────────────────────

def render_report(
    all_hits: dict[str, list[dict]],
    articles_by_theme: dict[str, list[dict]],
    min_threshold: float,
    max_threshold: float,
    output_file: Optional[str],
) -> None:

    lines = []
    SEP = "=" * 100
    sep = "-" * 100

    lines.append(SEP)
    lines.append(f"  DUPLICATE ANALYSIS REPORT  —  range: {min_threshold:.2f} to {max_threshold:.2f}")
    lines.append(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(SEP)

    total_articles = sum(len(v) for v in articles_by_theme.values())
    total_hits     = sum(len(v) for v in all_hits.values())

    in_range_hits = 0
    in_range_emb_hits = 0
    in_range_text_hits = 0

    for v in all_hits.values():
        for h in v:
            if min_threshold <= (h["combined"] or 0) <= max_threshold:
                in_range_hits += 1
                if h["flagged_emb"]:
                    in_range_emb_hits += 1
                elif h["flagged_text"]:
                    in_range_text_hits += 1

    lines.append(f"\n  Total published articles analysed : {total_articles}")
    lines.append(f"  Total duplicates (>= {min_threshold:.2f})       : {total_hits}")
    lines.append(f"  Duplicates in range ({min_threshold:.2f}-{max_threshold:.2f}) : {in_range_hits}")
    lines.append(f"  ↳ flagged by EMBEDDINGS           : {in_range_emb_hits}")
    lines.append(f"  ↳ flagged by TEXT (no embedding)  : {in_range_text_hits}")

    for theme, hits in sorted(all_hits.items()):
        theme_articles = articles_by_theme.get(theme, [])
        display_hits = [h for h in hits if min_threshold <= (h["combined"] or 0) <= max_threshold]

        lines.append(f"\n\n{SEP}")
        lines.append(f"  THEME: {theme}  ({len(theme_articles)} articles, {len(hits)} total pairs, {len(display_hits)} in range)")
        lines.append(SEP)

        if not display_hits:
            if hits:
                lines.append(f"  ✅  No similar pairs in range ({min_threshold:.2f}-{max_threshold:.2f}), though {len(hits)} total pairs exist.")
            else:
                lines.append("  ✅  No similar pairs detected in this theme.")
            continue

        for idx, hit in enumerate(sorted(display_hits, key=lambda h: -(h["combined"] or 0)), start=1):
            a  = hit["article_a"]
            b  = hit["article_b"]

            # Determine method label
            if hit["flagged_emb"] and hit["flagged_text"]:
                method = "BOTH (embeddings + text)"
            elif hit["flagged_emb"]:
                method = "EMBEDDINGS"
            else:
                method = "TEXT (no embedding)"

            emb_str = f"{hit['emb_sim']:.3f}" if hit["emb_sim"] is not None else "N/A"

            lines.append(f"\n  [{idx:02d}] Flagged by: {method}")
            lines.append(sep)
            lines.append(f"  Article A  [{fmt_date(a['published_at'])}]  {a['title']}")
            lines.append(f"  Article B  [{fmt_date(b['published_at'])}]  {b['title']}")
            lines.append(f"  Emb. similarity : {emb_str}   (range: {min_threshold:.2f}-{max_threshold:.2f})")
            lines.append(f"  Title sim.      : {hit['title_sim']:.3f}   (threshold: 0.55)")
            lines.append(f"  Summary sim.    : {hit['summary_sim']:.3f}   (threshold: 0.50)")

            # Show the two summaries side by side for quick review
            sum_a = (a["short_summary"] or a["rss_summary"])[:120]
            sum_b = (b["short_summary"] or b["rss_summary"])[:120]
            lines.append(f"\n  Summary A: {sum_a}…")
            lines.append(f"  Summary B: {sum_b}…")

    lines.append(f"\n{SEP}")
    lines.append("  END OF REPORT")
    lines.append(SEP)

    report = "\n".join(lines)
    print(report)

    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"\n[INFO] Report saved to: {output_file}")


# ─────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Analyse published articles for duplicates using embeddings."
    )
    parser.add_argument(
        "--config", default="config/config.yaml",
        help="Path to the YAML config file (default: config/config.yaml)"
    )

    # ── Threshold options ─────────────────────────────────────────────────
    thr_group = parser.add_argument_group(
        "threshold",
        "Threshold ranges to filter the report."
    )
    thr_group.add_argument(
        "--min-threshold", type=float, default=0.70, dest="min_threshold",
        help="Lower bound for reporting duplicates (default: 0.70)."
    )
    thr_group.add_argument(
        "--max-threshold", type=float, default=0.76, dest="max_threshold",
        help="Upper bound for filtering report details (default: 0.76)."
    )

    parser.add_argument(
        "--days", type=int, default=None,
        help="Only consider articles published in the last N days (default: all)"
    )
    parser.add_argument(
        "--theme", type=str, default=None,
        help="Limit analysis to a specific theme name (default: all themes)"
    )
    parser.add_argument(
        "--output", type=str, default="duplicate_report.txt",
        help="Path to write the text report (default: duplicate_report.txt)"
    )
    args = parser.parse_args()

    # ── Load config ──────────────────────────────────────────────────────
    print(f"[INFO] Loading config from: {args.config}")
    try:
        config = load_config(args.config)
    except Exception as e:
        print(f"[ERROR] Could not load config: {e}", file=sys.stderr)
        sys.exit(1)

    db_path       = config.database_path
    min_threshold = args.min_threshold
    max_threshold = args.max_threshold

    print(f"[INFO] Database: {db_path}")
    print(f"[INFO] Analysis range: {min_threshold:.4f} → {max_threshold:.4f}")
    if args.days:
        print(f"[INFO] Analysing last {args.days} day(s)")
    if args.theme:
        print(f"[INFO] Filtering theme: {args.theme}")
    print()

    # ── Fetch articles (once — reused for every threshold step) ──────────
    articles = fetch_published_articles(db_path, args.theme, args.days)
    if not articles:
        print("[INFO] No published articles found matching the criteria. Exiting.")
        sys.exit(0)

    print(f"[INFO] Fetched {len(articles)} published article(s).")

    # ── Group by theme ────────────────────────────────────────────────────
    articles_by_theme: dict[str, list[dict]] = {}
    for art in articles:
        articles_by_theme.setdefault(art["theme"], []).append(art)

    print(f"[INFO] Themes: {list(articles_by_theme.keys())}\n")

    # ── Analyse ───────────────────────────────────────────────────────────
    all_hits: dict[str, list[dict]] = {}
    for theme, theme_articles in articles_by_theme.items():
        print(f"[INFO] Analysing theme '{theme}' ({len(theme_articles)} articles)…")
        hits = analyse_theme(theme_articles, min_threshold)
        all_hits[theme] = hits

        in_range_count = sum(1 for h in hits if min_threshold <= (h["combined"] or 0) <= max_threshold)
        print(f"       → {len(hits)} total similar pair(s), {in_range_count} in range.")

    print()
    render_report(all_hits, articles_by_theme, min_threshold, max_threshold, args.output)


if __name__ == "__main__":
    main()
