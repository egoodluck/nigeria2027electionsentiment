"""
Enrichment orchestrator. Runs after collection (or standalone) and turns raw
comments into everything the dashboard reads:

    1. schema          additive tables + indexes
    2. reattribute     one-off: fix legacy substring attribution (auto-detected)
    3. features        language hint, duplicate hashes, author activity, risk score
    4. sentiment       CardiffNLP + NaijaSenti transformers, then the routed view
    5. topics          seeded lexicon + NMF discovery
    6. locations       state / zone mentions
    7. video_stats     views / likes per video (needs API key; skipped otherwise)
    8. aggregates      fact tables, keyword log-odds, model agreement
    9. forecast        30-day projections with intervals

Usage:
    python -m pipeline.enrich               # everything
    python -m pipeline.enrich --skip sentiment video_stats
    python -m pipeline.enrich --only aggregates forecast

Steps are idempotent and resumable. The transformer step is the only slow
one (minutes for a daily increment, ~1 hour for a 40k-comment backfill on
two CPU cores); everything else finishes in seconds.
"""

import argparse
import datetime as dt
import sqlite3
import time

from pipeline.schema import connect, ensure_schema
from pipeline.settings import DB_PATH

STEPS = ["reattribute", "features", "sentiment", "topics", "locations", "video_stats", "aggregates", "forecast"]


def _needs_reattribution(db_path):
    """Legacy databases carry 'bat'-substring false positives: comments attributed
    to Tinubu that contain none of the whole-word aliases. Detect by sampling."""
    try:
        import re
        from config import CANDIDATES
    except Exception:
        return False
    conn = connect(db_path, read_only=True)
    try:
        rows = conn.execute(
            """SELECT c.text_clean FROM comments c
               JOIN comment_candidate_mentions m ON m.comment_id = c.comment_id AND m.candidate = 'tinubu'
               WHERE c.text_clean IS NOT NULL LIMIT 2000"""
        ).fetchall()
        meta = conn.execute("SELECT COUNT(*) FROM enrichment_runs WHERE step = 'reattribute'").fetchone()[0]
    except sqlite3.Error:
        return False
    finally:
        conn.close()
    if meta or not rows:
        return False
    aliases = CANDIDATES["tinubu"]["aliases"]
    rx = re.compile(r"(?<![\w])(" + "|".join(re.escape(a) for a in aliases) + r")(?![\w])", re.IGNORECASE)
    bad = sum(1 for (t,) in rows if t and not rx.search(t))
    return bad / len(rows) > 0.05


def step_reattribute(db_path, verbose):
    if not _needs_reattribution(db_path):
        if verbose:
            print("[reattribute] attribution already uses whole-word aliases - nothing to do")
        return 0
    import attribute_and_score
    started = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    n = attribute_and_score.reattribute_all()
    conn = connect(db_path)
    from pipeline.schema import log_run
    log_run(conn, "reattribute", started, n, "whole-word aliases; HTML unescaped")
    conn.commit()
    conn.close()
    return n


def run(db_path=DB_PATH, only=None, skip=None, verbose=True):
    ensure_schema(db_path)
    steps = [s for s in STEPS if (not only or s in only) and (not skip or s not in skip)]
    timings, failed = {}, {}
    for step in steps:
        t0 = time.time()
        if verbose:
            print(f"\n--- enrichment: {step} ---")
        try:
            _run_step(step, db_path, verbose)
        except Exception as exc:  # a failing step must not take the daily run down with it
            failed[step] = f"{type(exc).__name__}: {exc}"
            print(f"[{step}] FAILED: {failed[step]}")
            if step == "sentiment":
                print("   -> install the enrichment requirements (pip install torch --index-url https://download.pytorch.org/whl/cpu && "
                      "pip install -r requirements-pipeline.txt) and re-run `python -m pipeline.enrich --only sentiment aggregates forecast`.")
        timings[step] = round(time.time() - t0, 1)
    if verbose:
        print("\nEnrichment complete. Seconds per step:", timings)
        if failed:
            print("Steps that failed:", failed)
    return timings


def _run_step(step, db_path, verbose):
    if True:
        if step == "reattribute":
            step_reattribute(db_path, verbose)
        elif step == "features":
            from pipeline import features
            features.run(db_path, verbose)
        elif step == "sentiment":
            from pipeline import sentiment_models
            sentiment_models.run(db_path, verbose=verbose)
        elif step == "topics":
            from pipeline import topics
            topics.run(db_path, verbose)
        elif step == "locations":
            from pipeline import locations
            locations.run(db_path, verbose)
        elif step == "video_stats":
            from pipeline import video_stats
            video_stats.run(db_path, verbose)
        elif step == "aggregates":
            from pipeline import aggregates
            aggregates.run(db_path, verbose)
        elif step == "forecast":
            from pipeline import forecast
            forecast.run(db_path, verbose=verbose)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Run the enrichment pipeline.")
    ap.add_argument("--only", nargs="*", choices=STEPS)
    ap.add_argument("--skip", nargs="*", choices=STEPS)
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    run(db_path=args.db, only=args.only, skip=args.skip, verbose=not args.quiet)
