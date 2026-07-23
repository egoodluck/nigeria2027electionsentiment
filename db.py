"""
SQLite storage layer for the pipeline.

SQLite (not CSV/JSON files) is used deliberately: the collection runs daily
over a ~6-month window, and primary keys give automatic de-duplication for
free -- re-running the pipeline, or recovering from a crash mid-run, never
produces duplicate videos or comments.
"""

import sqlite3
from contextlib import contextmanager
from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
    channel_id   TEXT PRIMARY KEY,
    handle       TEXT NOT NULL,
    label        TEXT NOT NULL,
    category     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS videos (
    video_id      TEXT PRIMARY KEY,
    channel_id    TEXT NOT NULL,
    title         TEXT,
    published_at  TEXT,
    query_used    TEXT,
    fetched_at    TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (channel_id) REFERENCES channels(channel_id)
);

CREATE TABLE IF NOT EXISTS comments (
    comment_id          TEXT PRIMARY KEY,
    video_id             TEXT NOT NULL,
    author                TEXT,
    text_raw              TEXT,
    text_clean            TEXT,
    published_at          TEXT,
    like_count            INTEGER,
    fetched_at            TEXT DEFAULT CURRENT_TIMESTAMP,
    sentiment_polarity    REAL,
    sentiment_label       TEXT,
    FOREIGN KEY (video_id) REFERENCES videos(video_id)
);

CREATE TABLE IF NOT EXISTS comment_candidate_mentions (
    comment_id   TEXT NOT NULL,
    candidate    TEXT NOT NULL,
    PRIMARY KEY (comment_id, candidate),
    FOREIGN KEY (comment_id) REFERENCES comments(comment_id)
);

CREATE TABLE IF NOT EXISTS comment_party_mentions (
    comment_id   TEXT NOT NULL,
    party        TEXT NOT NULL,
    PRIMARY KEY (comment_id, party),
    FOREIGN KEY (comment_id) REFERENCES comments(comment_id)
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at         TEXT DEFAULT CURRENT_TIMESTAMP,
    finished_at        TEXT,
    videos_found       INTEGER,
    comments_found     INTEGER,
    quota_units_used   INTEGER
);

-- Tracks progress through a single video-discovery "pass" (one search.list
-- call per channel x query pair) so it can be rationed across multiple
-- runs when the roster is too large to search in one day's quota. cursor=0
-- with published_after IS NULL means no pass is currently in flight -- the
-- next run will start a fresh one anchored at last_pass_end.
--
-- published_before is NOT "now" -- it's always config.COLLECTION_END (a
-- fixed, far-future date), so it's guaranteed to be after published_after
-- regardless of when a pass happens to start. pass_started_at separately
-- records the moment the in-flight pass began; once the pass completes,
-- that becomes last_pass_end (the next pass's published_after). Conflating
-- published_before with "now" caused publishedBefore < publishedAfter (and
-- a YouTube API 400) whenever a run happened before COLLECTION_START.
CREATE TABLE IF NOT EXISTS discovery_state (
    id                 INTEGER PRIMARY KEY CHECK (id = 1),
    cursor             INTEGER NOT NULL DEFAULT 0,
    published_after    TEXT,
    published_before   TEXT,
    pass_started_at    TEXT,
    last_pass_end       TEXT NOT NULL
);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def upsert_channel(conn, channel_id, handle, label, category):
    conn.execute(
        "INSERT OR REPLACE INTO channels (channel_id, handle, label, category) VALUES (?, ?, ?, ?)",
        (channel_id, handle, label, category),
    )


def upsert_video(conn, video_id, channel_id, title, published_at, query_used):
    conn.execute(
        """INSERT OR IGNORE INTO videos (video_id, channel_id, title, published_at, query_used)
           VALUES (?, ?, ?, ?, ?)""",
        (video_id, channel_id, title, published_at, query_used),
    )


def upsert_comment(conn, comment_id, video_id, author, text_raw, published_at, like_count):
    conn.execute(
        """INSERT OR IGNORE INTO comments (comment_id, video_id, author, text_raw, published_at, like_count)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (comment_id, video_id, author, text_raw, published_at, like_count),
    )


def get_discovery_state(conn):
    """Returns the current discovery_state row, or None if no pass has ever
    started (in which case config.COLLECTION_START anchors the first pass)."""
    return conn.execute(
        """SELECT cursor, published_after, published_before, pass_started_at, last_pass_end
           FROM discovery_state WHERE id = 1"""
    ).fetchone()


def save_discovery_state(conn, cursor, published_after, published_before, pass_started_at, last_pass_end):
    conn.execute(
        """INSERT INTO discovery_state
               (id, cursor, published_after, published_before, pass_started_at, last_pass_end)
           VALUES (1, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
               cursor = excluded.cursor,
               published_after = excluded.published_after,
               published_before = excluded.published_before,
               pass_started_at = excluded.pass_started_at,
               last_pass_end = excluded.last_pass_end""",
        (cursor, published_after, published_before, pass_started_at, last_pass_end),
    )
