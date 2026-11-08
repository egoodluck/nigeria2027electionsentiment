"""
Conversation geography: which Nigerian states and geopolitical zones a
comment *talks about*.

YouTube exposes no commenter location, and channel metadata carries none
either, so true audience geography cannot be measured from this data. What
can be measured honestly is where the conversation points: mentions of the
36 states + FCT (and their capitals / major cities) in comment text.

The dashboard labels this explicitly as "where the conversation is about,
not where commenters are".
"""

import datetime as dt
import re

import pandas as pd

from pipeline.schema import connect, ensure_schema, log_run
from pipeline.settings import DB_PATH, STATE_ALIASES, STATE_EXCLUSIONS, STATE_TO_ZONE


def _compile():
    rx = {}
    for state, aliases in STATE_ALIASES.items():
        terms = sorted(set(aliases), key=len, reverse=True)
        rx[state] = re.compile(r"(?<![\w'])(" + "|".join(re.escape(t) for t in terms) + r")(?![\w'])", re.IGNORECASE)
    excl = re.compile("|".join(re.escape(t) for t in STATE_EXCLUSIONS), re.IGNORECASE)
    return rx, excl


STATE_RX, EXCL_RX = _compile()


def states_in(text):
    if not text:
        return []
    scrubbed = EXCL_RX.sub(" ", text)
    return [s for s, rx in STATE_RX.items() if rx.search(scrubbed)]


def run(db_path=DB_PATH, verbose=True):
    ensure_schema(db_path)
    started = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    conn = connect(db_path)
    df = pd.read_sql_query("SELECT comment_id, COALESCE(text_clean, text_raw, '') AS text FROM comments", conn)
    rows = []
    for cid, text in zip(df["comment_id"], df["text"]):
        for s in states_in(text):
            rows.append((cid, s, STATE_TO_ZONE[s]))
    conn.execute("DELETE FROM comment_locations")
    conn.executemany("INSERT OR REPLACE INTO comment_locations (comment_id, state, zone) VALUES (?, ?, ?)", rows)
    log_run(conn, "locations", started, len(rows))
    conn.commit()
    conn.close()
    if verbose:
        counts = pd.Series([r[1] for r in rows]).value_counts()
        print(f"[locations] {len(rows)} state mentions in {len({r[0] for r in rows})} comments")
        print(counts.head(12).to_string())
    return len(rows)


if __name__ == "__main__":
    run()
