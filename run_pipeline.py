"""
Orchestrates a full pipeline run: video discovery -> comment collection ->
attribution & baseline scoring -> enrichment (transformer sentiment, topics,
authenticity, aggregates, projections). Designed to be run once daily for
the duration of the collection window in config.py.

    python run_pipeline.py                 # collection + enrichment
    python run_pipeline.py --no-enrich     # collection only (original behaviour)
    python -m pipeline.enrich              # enrichment only (no API key needed)

First-time setup:
    python resolve_channels.py      # once, and whenever CHANNELS changes
    python run_pipeline.py          # first collection run

Daily use (example cron entry, runs at 02:00 server time):
    0 2 * * * cd /path/to/project && /path/to/venv/bin/python run_pipeline.py >> pipeline.log 2>&1
"""

import argparse
import datetime

from db import init_db, get_conn
from collect_videos import collect_videos
from collect_comments import collect_comments
from attribute_and_score import run as attribute_and_score


def main(enrich=True):
    init_db()
    started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    print("=" * 60)
    print(f"Pipeline run started: {started_at}")
    print("=" * 60)

    print("\n--- Step 1/4: Video discovery ---")
    videos_found, quota_a = collect_videos()

    print("\n--- Step 2/4: Comment collection ---")
    comments_found, quota_b = collect_comments()

    print("\n--- Step 3/4: Attribution & baseline sentiment scoring ---")
    attribute_and_score()

    if enrich:
        print("\n--- Step 4/4: Enrichment (transformers, topics, authenticity, aggregates, projections) ---")
        try:
            from pipeline.enrich import run as run_enrichment
            run_enrichment()
        except Exception as exc:  # collection results are already committed; never lose them to an enrichment error
            print(f"Enrichment did not complete: {type(exc).__name__}: {exc}\n"
                  "Collection succeeded. Fix the enrichment environment (see requirements-pipeline.txt) and run "
                  "`python -m pipeline.enrich`, or use --no-enrich to skip this step.")
    else:
        print("\n--- Step 4/4: Enrichment skipped (--no-enrich) ---")

    finished_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    total_quota = quota_a + quota_b

    with get_conn() as conn:
        conn.execute(
            """INSERT INTO pipeline_runs
               (started_at, finished_at, videos_found, comments_found, quota_units_used)
               VALUES (?, ?, ?, ?, ?)""",
            (started_at, finished_at, videos_found, comments_found, total_quota),
        )

    print("\n" + "=" * 60)
    print(f"Pipeline run complete: {videos_found} new videos, {comments_found} new comments, "
          f"{total_quota} quota units used.")
    print("=" * 60)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-enrich", action="store_true", help="run collection only")
    args = ap.parse_args()
    main(enrich=not args.no_enrich)
