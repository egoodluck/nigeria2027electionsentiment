"""
Additive schema for the enrichment layer.

Everything here is CREATE ... IF NOT EXISTS, so it is safe to run on every
pipeline invocation and on a database produced by the original collector.
The original tables (channels, videos, comments, comment_candidate_mentions,
comment_party_mentions, pipeline_runs, discovery_state) are untouched.
"""

import sqlite3
from contextlib import contextmanager

from pipeline.settings import DB_PATH

ENRICHMENT_SCHEMA = """
-- Transformer sentiment, one row per (comment, model). `routed` is derived.
CREATE TABLE IF NOT EXISTS comment_sentiment (
    comment_id   TEXT NOT NULL,
    model        TEXT NOT NULL,
    label        TEXT NOT NULL,
    confidence   REAL NOT NULL,
    p_neg        REAL,
    p_neu        REAL,
    p_pos        REAL,
    scored_at    TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (comment_id, model)
);

-- Per-comment features used for routing, explainability and authenticity.
CREATE TABLE IF NOT EXISTS comment_features (
    comment_id            TEXT PRIMARY KEY,
    lang_hint             TEXT,
    lang_hits             INTEGER,
    n_tokens              INTEGER,
    n_emoji               INTEGER,
    caps_ratio            REAL,
    text_hash             TEXT,
    dup_count             INTEGER DEFAULT 1,
    dup_authors           INTEGER DEFAULT 1,
    author_total          INTEGER,
    author_day_count      INTEGER,
    author_burst          INTEGER DEFAULT 0,
    risk_score            REAL DEFAULT 0,
    flagged               INTEGER DEFAULT 0,
    updated_at            TEXT
);

-- Multi-label topics from the seeded lexicon (method='lexicon') and the
-- unsupervised NMF discovery layer (method='nmf').
CREATE TABLE IF NOT EXISTS comment_topics (
    comment_id   TEXT NOT NULL,
    topic        TEXT NOT NULL,
    score        REAL,
    method       TEXT NOT NULL DEFAULT 'lexicon',
    PRIMARY KEY (comment_id, topic, method)
);

-- Discovered (NMF) themes: top terms per theme, for the topic page.
CREATE TABLE IF NOT EXISTS discovered_themes (
    theme_id     INTEGER NOT NULL,
    rank         INTEGER NOT NULL,
    term         TEXT NOT NULL,
    weight       REAL,
    n_comments   INTEGER,
    computed_at  TEXT,
    PRIMARY KEY (theme_id, rank)
);

-- States / geopolitical zones mentioned in a comment (conversation geography).
CREATE TABLE IF NOT EXISTS comment_locations (
    comment_id   TEXT NOT NULL,
    state        TEXT NOT NULL,
    zone         TEXT NOT NULL,
    PRIMARY KEY (comment_id, state)
);

-- YouTube video statistics (reach), filled by pipeline/video_stats.py.
CREATE TABLE IF NOT EXISTS video_stats (
    video_id       TEXT PRIMARY KEY,
    view_count     INTEGER,
    like_count     INTEGER,
    comment_count  INTEGER,
    duration_s     INTEGER,
    fetched_at     TEXT
);

-- Daily fact table at (day, candidate, channel, model) grain. Rebuilt in full
-- on every enrichment run (cheap) so it is always consistent with the raw rows.
CREATE TABLE IF NOT EXISTS fact_daily (
    day          TEXT NOT NULL,
    candidate    TEXT NOT NULL,
    channel_id   TEXT NOT NULL,
    model        TEXT NOT NULL,
    n            INTEGER NOT NULL,
    n_pos        INTEGER NOT NULL,
    n_neu        INTEGER NOT NULL,
    n_neg        INTEGER NOT NULL,
    sum_conf     REAL,
    sum_likes    INTEGER,
    n_authors    INTEGER,
    n_flagged    INTEGER,
    n_videos     INTEGER,
    PRIMARY KEY (day, candidate, channel_id, model)
);

CREATE TABLE IF NOT EXISTS fact_daily_topic (
    day          TEXT NOT NULL,
    candidate    TEXT NOT NULL,
    topic        TEXT NOT NULL,
    model        TEXT NOT NULL,
    n            INTEGER NOT NULL,
    n_pos        INTEGER NOT NULL,
    n_neu        INTEGER NOT NULL,
    n_neg        INTEGER NOT NULL,
    PRIMARY KEY (day, candidate, topic, model)
);

CREATE TABLE IF NOT EXISTS fact_daily_location (
    day          TEXT NOT NULL,
    candidate    TEXT NOT NULL,
    state        TEXT NOT NULL,
    model        TEXT NOT NULL,
    n            INTEGER NOT NULL,
    n_pos        INTEGER NOT NULL,
    n_neu        INTEGER NOT NULL,
    n_neg        INTEGER NOT NULL,
    PRIMARY KEY (day, candidate, state, model)
);

-- Weighted log-odds keywords per candidate: polarity in
-- ('positive','negative','emerging').
CREATE TABLE IF NOT EXISTS keyword_stats (
    candidate    TEXT NOT NULL,
    polarity     TEXT NOT NULL,
    model        TEXT NOT NULL,
    rank         INTEGER NOT NULL,
    term         TEXT NOT NULL,
    zscore       REAL,
    count_a      INTEGER,
    count_b      INTEGER,
    computed_at  TEXT,
    PRIMARY KEY (candidate, polarity, model, rank)
);

-- Projections (not predictions). metric in ('net_sentiment','volume').
CREATE TABLE IF NOT EXISTS forecasts (
    candidate     TEXT NOT NULL,
    model         TEXT NOT NULL,
    metric        TEXT NOT NULL,
    day           TEXT NOT NULL,
    yhat          REAL,
    lo80          REAL,
    hi80          REAL,
    lo95          REAL,
    hi95          REAL,
    method        TEXT,
    history_days  INTEGER,
    generated_at  TEXT,
    PRIMARY KEY (candidate, model, metric, day)
);

-- Pairwise model agreement, recomputed each run for the methodology page.
CREATE TABLE IF NOT EXISTS model_agreement (
    model_a      TEXT NOT NULL,
    model_b      TEXT NOT NULL,
    n            INTEGER,
    agreement    REAL,
    kappa        REAL,
    computed_at  TEXT,
    PRIMARY KEY (model_a, model_b)
);

CREATE TABLE IF NOT EXISTS enrichment_runs (
    run_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    TEXT,
    finished_at   TEXT,
    step          TEXT,
    rows_written  INTEGER,
    notes         TEXT
);

-- Indexes the original schema lacked. They make the comment explorer and the
-- fact-table rebuild scale to 1M+ rows.
CREATE INDEX IF NOT EXISTS idx_comments_video      ON comments(video_id);
CREATE INDEX IF NOT EXISTS idx_comments_published  ON comments(published_at);
CREATE INDEX IF NOT EXISTS idx_comments_author     ON comments(author);
CREATE INDEX IF NOT EXISTS idx_videos_channel      ON videos(channel_id);
CREATE INDEX IF NOT EXISTS idx_ccm_candidate       ON comment_candidate_mentions(candidate, comment_id);
-- (comment_sentiment and comment_topics are always reached through their primary
--  keys from the comments side, so no secondary index is kept on them: at 1M
--  comments the two indexes would cost ~180 MB for no measurable gain.)
CREATE INDEX IF NOT EXISTS idx_locations_state     ON comment_locations(state);
CREATE INDEX IF NOT EXISTS idx_fact_daily_cand     ON fact_daily(candidate, model, day);
CREATE INDEX IF NOT EXISTS idx_fact_topic_cand     ON fact_daily_topic(candidate, model, day);
"""


def connect(db_path=DB_PATH, read_only=False, timeout=120):
    """Open a SQLite connection with sane defaults for a long-running writer
    sharing the file with a reading dashboard."""
    if read_only:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=timeout)
    else:
        conn = sqlite3.connect(db_path, timeout=timeout)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = %d" % (timeout * 1000))
    return conn


@contextmanager
def transaction(db_path=DB_PATH):
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def ensure_schema(db_path=DB_PATH):
    with transaction(db_path) as conn:
        conn.executescript(ENRICHMENT_SCHEMA)


def log_run(conn, step, started_at, rows_written, notes=""):
    import datetime as _dt
    conn.execute(
        "INSERT INTO enrichment_runs (started_at, finished_at, step, rows_written, notes) VALUES (?, ?, ?, ?, ?)",
        (started_at, _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"), step, rows_written, notes),
    )


if __name__ == "__main__":
    ensure_schema()
    print(f"Enrichment schema ensured on {DB_PATH}")
