"""
Standalone script to export NewsFeed statistics for a given day.

Opens the database in read-only mode so it does not block
the main application from writing.

Usage:
    python export_statistics.py <YYYY-MM-DD> [--output <path>] [--db <path>]

Examples:
    python export_statistics.py 2026-03-04
    python export_statistics.py 2026-03-04 --output reports/march.txt
    python export_statistics.py 2026-03-04 --db data/news_feed.db
"""

import sys
import os
import sqlite3
import argparse
import re
from datetime import datetime


# ── Helpers ──────────────────────────────────────────────────────────────────

TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


def open_readonly(db_path: str) -> sqlite3.Connection:
    """Open a SQLite database in read-only mode using a URI connection."""
    # Convert to absolute path so the URI is valid on every OS
    abs_path = os.path.abspath(db_path)
    uri = f"file:{abs_path}?mode=ro"
    return sqlite3.connect(uri, uri=True)


# ── Queries ──────────────────────────────────────────────────────────────────

def get_daily_stats(cursor: sqlite3.Cursor, date_str: str) -> list:
    cursor.execute('''
        SELECT
            f.theme,
            f.name   AS feed_name,
            COUNT(a.id) AS total_seen,
            SUM(CASE WHEN a.post_id != -1 THEN 1 ELSE 0 END) AS total_published,
            SUM(CASE WHEN a.post_id != -1 THEN 1 ELSE 0 END) * 100.0 / COUNT(a.id) AS publish_rate,
            AVG(a.relevance_score)  AS avg_relevance,
            AVG(a.importance_score) AS avg_importance,
            AVG(a.urgency_score)    AS avg_urgency,
            MAX(a.published_at)     AS last_published
        FROM articles a
        JOIN feeds f ON a.feed_id = f.id
        WHERE DATE(a.date_seen) = ? OR DATE(a.published_at) = ?
        GROUP BY f.theme, f.name
        ORDER BY f.theme, f.name
    ''', (date_str, date_str))
    return cursor.fetchall()


def get_theme_stats(cursor: sqlite3.Cursor, date_str: str) -> list:
    """Get total seen and published articles per theme for a given day."""
    cursor.execute('''
        SELECT
            f.theme,
            COUNT(a.id) AS total_seen,
            SUM(CASE WHEN a.post_id != -1 THEN 1 ELSE 0 END) AS total_published
        FROM articles a
        JOIN feeds f ON a.feed_id = f.id
        WHERE DATE(a.date_seen) = ? OR DATE(a.published_at) = ?
        GROUP BY f.theme
        ORDER BY f.theme
    ''', (date_str, date_str))
    return cursor.fetchall()


def get_monthly_stats(cursor: sqlite3.Cursor, end_date_str: str) -> list:
    cursor.execute('''
        SELECT
            f.theme,
            f.name   AS feed_name,
            COUNT(a.id) AS total_seen,
            SUM(CASE WHEN a.post_id != -1 THEN 1 ELSE 0 END) AS total_published,
            SUM(CASE WHEN a.post_id != -1 THEN 1 ELSE 0 END) * 100.0 / COUNT(a.id) AS publish_rate,
            AVG(a.relevance_score)  AS avg_relevance,
            AVG(a.importance_score) AS avg_importance,
            AVG(a.urgency_score)    AS avg_urgency,
            MAX(a.published_at)     AS last_published
        FROM articles a
        JOIN feeds f ON a.feed_id = f.id
        WHERE (DATE(a.date_seen) <= ? AND DATE(a.date_seen) > date(?, '-30 days'))
           OR (DATE(a.published_at) <= ? AND DATE(a.published_at) > date(?, '-30 days'))
        GROUP BY f.theme, f.name
        ORDER BY f.theme, f.name
    ''', (end_date_str, end_date_str, end_date_str, end_date_str))
    return cursor.fetchall()


# ── Formatting ───────────────────────────────────────────────────────────────

def write_table(f, title: str, rows: list) -> None:
    """Write a statistics table (daily or monthly) to the file object *f*."""

    def write_theme_total(theme, seen, pub):
        theme_rate = (pub * 100.0 / seen) if seen > 0 else 0.0
        f.write("-" * 100 + "\n")
        f.write(f"{'TOTAL ' + theme:<40} | {seen:<5} | {pub:<5} | {theme_rate:<4.1f}% |\n")
        f.write("-" * 100 + "\n")

    f.write(f"### {title}\n")
    f.write("=" * 100 + "\n")

    if not rows:
        f.write("No statistics available for this period.\n\n")
        return

    current_theme = None
    theme_seen = 0
    theme_pub = 0

    for theme, feed, seen, pub, rate, avg_r, avg_i, avg_u, last_pub in rows:
        if theme != current_theme:
            if current_theme is not None:
                write_theme_total(current_theme, theme_seen, theme_pub)

            f.write(f"\nTHEME: {theme}\n")
            f.write("-" * 100 + "\n")
            f.write(
                f"{'Feed Name':<40} | {'Seen':<5} | {'Pub':<5} | {'Rate':<5} | "
                f"{'Avg R':<5} | {'Avg I':<5} | {'Avg U':<5} | {'Last Pub':<16}\n"
            )
            f.write("-" * 100 + "\n")
            current_theme = theme
            theme_seen = 0
            theme_pub = 0

        pub = pub if pub is not None else 0
        theme_seen += seen
        theme_pub += pub

        feed_str = str(feed or "Unknown")[:38]
        rate = rate if rate is not None else 0.0
        avg_r = avg_r if avg_r is not None else 0.0
        avg_i = avg_i if avg_i is not None else 0.0
        avg_u = avg_u if avg_u is not None else 0.0
        last_pub_str = last_pub[:16] if last_pub else "Never"

        f.write(
            f"{feed_str:<40} | {seen:<5} | {pub:<5} | {rate:<4.1f}% | "
            f"{avg_r:<5.1f} | {avg_i:<5.1f} | {avg_u:<5.1f} | {last_pub_str:<16}\n"
        )

    # Write summary for the last theme
    if current_theme is not None:
        write_theme_total(current_theme, theme_seen, theme_pub)

    f.write("-" * 100 + "\n\n")  # closing separator after last theme


def write_theme_stats(rows: list, date_str: str, directory: str) -> None:
    """Append theme-level statistics to historical theme files."""

    def slugify(text: str) -> str:
        text = text.lower()
        text = re.sub(r'[^a-z0-9]+', '_', text)
        return text.strip('_')

    os.makedirs(directory, exist_ok=True)
    for theme, seen, pub in rows:
        filename = f"daily_{slugify(theme)}.txt"
        output_path = os.path.join(directory, filename)
        file_exists = os.path.exists(output_path)
        rate = (pub * 100.0 / seen) if seen > 0 else 0.0

        with open(output_path, "a", encoding="utf-8") as f:
            if not file_exists:
                f.write(f"{'Date':<10} | {'Seen':<5} | {'Pub':<5} | {'Rate':<6}\n")
                f.write("-" * 35 + "\n")

            f.write(f"{date_str:<10} | {seen:<5} | {pub:<5} | {rate:<5.1f}%\n")
    print(f"Daily theme totals exported to {directory}")


# ── Main ─────────────────────────────────────────────────────────────────────

def export_statistics(db_path: str, target_date_str: str, output_path: str, themes_dir: str | None = None) -> None:
    """Run all queries and write the statistics files."""
    conn = open_readonly(db_path)
    try:
        cursor = conn.cursor()

        if themes_dir:
            # Only export theme-level statistics
            theme_rows = get_theme_stats(cursor, target_date_str)
            write_theme_stats(theme_rows, target_date_str, themes_dir)
        else:
            # Only export regular feed-level statistics
            daily_rows = get_daily_stats(cursor, target_date_str)
            monthly_rows = get_monthly_stats(cursor, target_date_str)

            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

            with open(output_path, "w", encoding="utf-8") as f:
                f.write(
                    f"NewsFeed Statistics - Exported on "
                    f"{datetime.now().strftime(TIMESTAMP_FORMAT)}\n"
                )
                f.write("=" * 100 + "\n\n")

                write_table(f, "DAILY STATISTICS (Last 24 Hours)", daily_rows)
                write_table(f, "MONTHLY STATISTICS (Last 30 Days)", monthly_rows)

            print(f"Feed-level statistics exported to {output_path}")

    finally:
        conn.close()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export NewsFeed statistics for a given day (read-only DB access)."
    )
    parser.add_argument(
        "date",
        help="Target date in YYYY-MM-DD format.",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Output file path.  Defaults to stats/statistics_<DATE>.txt",
    )
    parser.add_argument(
        "--db",
        default="data/news_feed.db",
        help="Path to the SQLite database.  Defaults to data/news_feed.db",
    )
    parser.add_argument(
        "--themes",
        nargs='?',
        const='stats',
        default=None,
        help="Also export daily theme totals to the specified directory (defaults to 'stats' if flag is present).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    # Validate date format
    try:
        datetime.strptime(args.date, "%Y-%m-%d")
    except ValueError:
        print(f"Error: '{args.date}' is not a valid date. Use YYYY-MM-DD format.", file=sys.stderr)
        sys.exit(1)

    # Validate database exists
    if not os.path.isfile(args.db):
        print(f"Error: Database file not found at '{args.db}'.", file=sys.stderr)
        sys.exit(1)

    output_path = args.output or f"stats/statistics_{args.date}.txt"

    export_statistics(args.db, args.date, output_path, themes_dir=args.themes)


if __name__ == "__main__":
    main()
