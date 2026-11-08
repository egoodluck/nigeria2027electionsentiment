"""
Produce a slim copy of the database for hosting.

The working database keeps everything (raw text, every model's probabilities,
all indexes). The hosted dashboard needs less, and GitHub refuses files over
100 MB, so this script writes `<name>.app.db` with:

  * text_raw dropped from comments (text_clean is what the app shows);
  * only the sentiment rows the app can display (all models by default;
    pass --models routed textblob to keep just those);
  * VACUUM applied so freed pages are released.

    python -m pipeline.publish                    # -> election_sentiment.app.db
    python -m pipeline.publish --out hosted.db --models routed textblob

Point the hosted app at the slim file with DB_PATH (or rename it) and commit it
instead of the working copy.
"""

import argparse
import os
import sqlite3

from pipeline.settings import DB_PATH


def publish(src=DB_PATH, out=None, models=None):
    out = out or os.path.splitext(src)[0] + ".app.db"
    if os.path.exists(out):
        os.remove(out)
    conn = sqlite3.connect(src)
    conn.execute("VACUUM INTO ?", (out,))
    conn.close()

    slim = sqlite3.connect(out)
    cur = slim.cursor()
    cols = [r[1] for r in cur.execute("PRAGMA table_info(comments)").fetchall()]
    if "text_raw" in cols:
        cur.execute("UPDATE comments SET text_raw = NULL")
    if models:
        placeholders = ",".join("?" * len(models))
        cur.execute(f"DELETE FROM comment_sentiment WHERE model NOT IN ({placeholders})", list(models))
        cur.execute(f"DELETE FROM fact_daily WHERE model NOT IN ({placeholders})", list(models))
        cur.execute(f"DELETE FROM fact_daily_topic WHERE model NOT IN ({placeholders})", list(models))
        cur.execute(f"DELETE FROM fact_daily_location WHERE model NOT IN ({placeholders})", list(models))
        cur.execute(f"DELETE FROM keyword_stats WHERE model NOT IN ({placeholders})", list(models))
        cur.execute(f"DELETE FROM forecasts WHERE model NOT IN ({placeholders})", list(models))
    for idx in ("idx_sentiment_model", "idx_topics_topic"):
        cur.execute(f"DROP INDEX IF EXISTS {idx}")
    slim.commit()
    slim.execute("VACUUM")
    slim.close()
    print(f"published {out}: {os.path.getsize(out) / 1e6:.1f} MB (working copy {os.path.getsize(src) / 1e6:.1f} MB)")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=DB_PATH)
    ap.add_argument("--out", default=None)
    ap.add_argument("--models", nargs="*", default=None)
    args = ap.parse_args()
    publish(args.src, args.out, args.models)
