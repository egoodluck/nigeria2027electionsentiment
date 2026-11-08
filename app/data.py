"""
Cached data access for the dashboard.

The app reads only the pre-aggregated tables the enrichment pipeline writes
(fact_daily, fact_daily_topic, keyword_stats, forecasts, ...) plus small
dimension tables. Comment-level rows are touched only by the explorer, via
parameterised SQL with LIMIT. That is what keeps every page under a second
even if the corpus grows to a million comments.

Every loader is keyed on the database file's (mtime, size) so caches
invalidate automatically when a new snapshot is deployed.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

from pipeline.settings import ALL_KEY, DB_PATH, DEFAULT_MODEL, MATURITY_DAYS

ASSETS = Path(__file__).parent / "assets"
CACHE_TTL = 900  # seconds; snapshots change at most daily


def db_path() -> str:
    return os.environ.get("DB_PATH", DB_PATH)


def db_signature() -> tuple:
    p = db_path()
    try:
        s = os.stat(p)
        return (p, int(s.st_mtime), s.st_size)
    except FileNotFoundError:
        return (p, 0, 0)


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path()}?mode=ro", uri=True, timeout=30, check_same_thread=False)
    conn.execute("PRAGMA query_only = 1")
    return conn


def _read(sql: str, params: tuple = ()) -> pd.DataFrame:
    conn = _conn()
    try:
        return pd.read_sql_query(sql, conn, params=params)
    finally:
        conn.close()


def _table_exists(name: str) -> bool:
    conn = _conn()
    try:
        return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None
    finally:
        conn.close()


# ------------------------------------------------------------------ meta

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def load_meta(_sig: tuple) -> dict:
    conn = _conn()
    try:
        q = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
        meta = {
            "channels": q("SELECT COUNT(*) FROM channels"),
            "videos": q("SELECT COUNT(*) FROM videos"),
            "comments": q("SELECT COUNT(*) FROM comments"),
            "attributed": q("SELECT COUNT(DISTINCT comment_id) FROM comment_candidate_mentions"),
            "authors": q("SELECT COUNT(DISTINCT author) FROM comments"),
            "first_day": q("SELECT MIN(substr(published_at,1,10)) FROM comments"),
            "last_day": q("SELECT MAX(substr(published_at,1,10)) FROM comments"),
            "last_fetch": q("SELECT MAX(fetched_at) FROM comments"),
            "has_enrichment": conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='fact_daily'").fetchone() is not None,
        }
        if meta["has_enrichment"]:
            meta["models"] = [r[0] for r in conn.execute("SELECT DISTINCT model FROM comment_sentiment").fetchall()]
            meta["scored"] = q("SELECT COUNT(DISTINCT comment_id) FROM comment_sentiment WHERE model != 'textblob'")
            meta["has_video_stats"] = q("SELECT COUNT(*) FROM video_stats") > 0
            meta["has_forecasts"] = q("SELECT COUNT(*) FROM forecasts") > 0
            meta["enrichment_last"] = conn.execute(
                "SELECT MAX(finished_at) FROM enrichment_runs").fetchone()[0]
        else:
            meta.update(models=["textblob"], scored=0, has_video_stats=False, has_forecasts=False, enrichment_last=None)
        runs = pd.read_sql_query(
            """SELECT r.*, (SELECT COUNT(*) FROM comments c
                            WHERE c.fetched_at >= replace(substr(r.started_at, 1, 19), 'T', ' ')
                              AND c.fetched_at <= replace(substr(r.finished_at, 1, 19), 'T', ' ')) AS new_comments
               FROM pipeline_runs r ORDER BY r.run_id DESC""", conn)
        meta["runs"] = runs
        meta["last_run"] = runs.iloc[0].to_dict() if not runs.empty else None
    finally:
        conn.close()
    last_fetch = pd.to_datetime(meta["last_fetch"], utc=True, errors="coerce") if meta["last_fetch"] else pd.NaT
    meta["mature_until"] = (
        (last_fetch - pd.Timedelta(days=MATURITY_DAYS)).strftime("%Y-%m-%d") if pd.notna(last_fetch) else meta["last_day"]
    )
    return meta


def meta() -> dict:
    return load_meta(db_signature())


def default_model(m: dict | None = None) -> str:
    m = m or meta()
    models = m.get("models") or ["textblob"]
    return DEFAULT_MODEL if DEFAULT_MODEL in models else ("cardiffnlp" if "cardiffnlp" in models else models[0])


# ------------------------------------------------------------ dimensions

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def load_channels(_sig: tuple) -> pd.DataFrame:
    df = _read("SELECT channel_id, handle, label, category FROM channels ORDER BY label")
    df["category_label"] = df["category"].map(category_label)
    return df


CATEGORY_LABELS = {
    "broadcast_network": "Broadcast networks",
    "investigative_digital": "Investigative & digital",
    "print_backed_digital": "Print-backed digital",
    "radio_talk_show": "Radio & talk shows",
    "vernacular_regional": "Vernacular & regional",
    "civil_society_advocacy": "Civil society & advocacy",
}
CATEGORY_ORDER = list(CATEGORY_LABELS.keys())
# Noun phrases for generated prose ("... generated 80% of mentions").
CATEGORY_PHRASES = {
    "broadcast_network": "Broadcast-network channels",
    "investigative_digital": "Investigative and digital outlets",
    "print_backed_digital": "Print-backed digital outlets",
    "radio_talk_show": "Radio and talk-show channels",
    "vernacular_regional": "Vernacular and regional-language channels",
    "civil_society_advocacy": "Civil-society and advocacy channels",
}


def category_phrase(key: str) -> str:
    return CATEGORY_PHRASES.get(key, category_label(key) + " channels")


def category_label(key: str) -> str:
    return CATEGORY_LABELS.get(key, (key or "").replace("_", " ").title())


# ------------------------------------------------------------ fact tables

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def load_fact_daily(_sig: tuple, model: str) -> pd.DataFrame:
    if not _table_exists("fact_daily"):
        return pd.DataFrame()
    df = _read(
        """SELECT f.day, f.candidate, f.channel_id, ch.category, ch.label AS channel, f.n, f.n_pos, f.n_neu, f.n_neg,
                  f.sum_conf, f.sum_likes, f.n_authors, f.n_flagged, f.n_videos
           FROM fact_daily f JOIN channels ch ON ch.channel_id = f.channel_id
           WHERE f.model = ?""", (model,))
    if df.empty:
        return df
    df["day"] = pd.to_datetime(df["day"])
    return df


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def load_fact_topic(_sig: tuple, model: str) -> pd.DataFrame:
    if not _table_exists("fact_daily_topic"):
        return pd.DataFrame()
    df = _read("SELECT day, candidate, topic, n, n_pos, n_neu, n_neg FROM fact_daily_topic WHERE model = ?", (model,))
    if not df.empty:
        df["day"] = pd.to_datetime(df["day"])
    return df


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def load_fact_location(_sig: tuple, model: str) -> pd.DataFrame:
    if not _table_exists("fact_daily_location"):
        return pd.DataFrame()
    df = _read("SELECT day, candidate, state, n, n_pos, n_neu, n_neg FROM fact_daily_location WHERE model = ?", (model,))
    if not df.empty:
        df["day"] = pd.to_datetime(df["day"])
    return df


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def load_keywords(_sig: tuple, model: str) -> pd.DataFrame:
    if not _table_exists("keyword_stats"):
        return pd.DataFrame()
    return _read("SELECT candidate, polarity, rank, term, zscore, count_a, count_b, computed_at FROM keyword_stats WHERE model = ? ORDER BY candidate, polarity, rank", (model,))


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def load_forecasts(_sig: tuple, model: str) -> pd.DataFrame:
    if not _table_exists("forecasts"):
        return pd.DataFrame()
    df = _read("SELECT candidate, metric, day, yhat, lo80, hi80, lo95, hi95, method, history_days, generated_at FROM forecasts WHERE model = ?", (model,))
    if not df.empty:
        df["day"] = pd.to_datetime(df["day"])
    return df


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def load_agreement(_sig: tuple) -> pd.DataFrame:
    if not _table_exists("model_agreement"):
        return pd.DataFrame()
    return _read("SELECT model_a, model_b, n, agreement, kappa FROM model_agreement")


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def load_themes(_sig: tuple) -> pd.DataFrame:
    if not _table_exists("discovered_themes"):
        return pd.DataFrame()
    return _read("SELECT theme_id, rank, term, weight, n_comments FROM discovered_themes ORDER BY theme_id, rank")


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def load_language_mix(_sig: tuple) -> pd.DataFrame:
    if not _table_exists("comment_features"):
        return pd.DataFrame()
    return _read("SELECT lang_hint, COUNT(*) AS n FROM comment_features GROUP BY lang_hint ORDER BY n DESC")


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def load_confidence_hist(_sig: tuple, model: str) -> pd.DataFrame:
    if not _table_exists("comment_sentiment"):
        return pd.DataFrame()
    return _read(
        """SELECT label, CAST(confidence * 20 AS INTEGER) / 20.0 AS bin, COUNT(*) AS n
           FROM comment_sentiment WHERE model = ? GROUP BY 1, 2 ORDER BY 2""", (model,))


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def load_risk_summary(_sig: tuple) -> dict:
    if not _table_exists("comment_features"):
        return {}
    conn = _conn()
    try:
        hist = pd.read_sql_query(
            "SELECT ROUND(risk_score, 1) AS risk, COUNT(*) AS n FROM comment_features GROUP BY 1 ORDER BY 1", conn)
        campaigns = pd.read_sql_query(
            """SELECT f.text_hash, MAX(c.text_clean) AS text, COUNT(*) AS copies, COUNT(DISTINCT c.author) AS authors,
                      MIN(substr(c.published_at,1,10)) AS first_seen, MAX(substr(c.published_at,1,10)) AS last_seen,
                      GROUP_CONCAT(DISTINCT m.candidate) AS candidates
               FROM comment_features f
               JOIN comments c ON c.comment_id = f.comment_id
               LEFT JOIN comment_candidate_mentions m ON m.comment_id = c.comment_id
               WHERE f.text_hash IS NOT NULL AND f.dup_count >= 3
               GROUP BY f.text_hash ORDER BY copies DESC LIMIT 40""", conn)
        authors = pd.read_sql_query(
            """SELECT c.author, COUNT(*) AS comments, COUNT(DISTINCT c.video_id) AS videos,
                      MAX(f.author_day_count) AS max_per_day, SUM(f.author_burst) AS burst_comments,
                      ROUND(AVG(f.risk_score), 2) AS avg_risk, GROUP_CONCAT(DISTINCT m.candidate) AS candidates
               FROM comments c JOIN comment_features f ON f.comment_id = c.comment_id
               LEFT JOIN comment_candidate_mentions m ON m.comment_id = c.comment_id
               WHERE c.author IS NOT NULL
               GROUP BY c.author ORDER BY comments DESC LIMIT 30""", conn)
        lang = pd.read_sql_query("SELECT lang_hint, COUNT(*) n FROM comment_features GROUP BY 1", conn)
        totals = conn.execute(
            "SELECT COUNT(*), SUM(flagged), SUM(risk_score >= 0.3), SUM(dup_count > 1), SUM(author_burst) FROM comment_features"
        ).fetchone()
    finally:
        conn.close()
    return {"hist": hist, "campaigns": campaigns, "authors": authors, "lang": lang,
            "total": totals[0], "flagged": totals[1] or 0, "elevated": totals[2] or 0,
            "duplicates": totals[3] or 0, "bursts": totals[4] or 0}


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def load_video_table(_sig: tuple, model: str) -> pd.DataFrame:
    has_stats = _table_exists("video_stats")
    stats_cols = "s.view_count, s.like_count AS video_likes, s.comment_count AS yt_comment_count," if has_stats else "NULL AS view_count, NULL AS video_likes, NULL AS yt_comment_count,"
    stats_join = "LEFT JOIN video_stats s ON s.video_id = v.video_id" if has_stats else ""
    sent_join = "LEFT JOIN comment_sentiment cs ON cs.comment_id = c.comment_id AND cs.model = ?" if _table_exists("comment_sentiment") else ""
    sent_cols = ("SUM(cs.label = 'positive') AS n_pos, SUM(cs.label = 'negative') AS n_neg,"
                 if sent_join else "0 AS n_pos, 0 AS n_neg,")
    params = (model,) if sent_join else ()
    df = _read(
        f"""SELECT v.video_id, v.title, v.published_at, ch.label AS channel, ch.category,
                   COUNT(c.comment_id) AS comments, SUM(COALESCE(c.like_count, 0)) AS comment_likes,
                   {sent_cols} {stats_cols}
                   (SELECT GROUP_CONCAT(DISTINCT m.candidate) FROM comment_candidate_mentions m
                     JOIN comments c2 ON c2.comment_id = m.comment_id WHERE c2.video_id = v.video_id) AS candidates
            FROM videos v
            JOIN channels ch ON ch.channel_id = v.channel_id
            LEFT JOIN comments c ON c.video_id = v.video_id
            {sent_join} {stats_join}
            GROUP BY v.video_id HAVING comments > 0
            ORDER BY comments DESC LIMIT 400""", params)
    df["published_at"] = pd.to_datetime(df["published_at"], utc=True, errors="coerce")
    df["category_label"] = df["category"].map(category_label)
    return df


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def load_enrichment_runs(_sig: tuple) -> pd.DataFrame:
    if not _table_exists("enrichment_runs"):
        return pd.DataFrame()
    return _read("SELECT run_id, started_at, finished_at, step, rows_written, notes FROM enrichment_runs ORDER BY run_id DESC LIMIT 60")


@st.cache_data(show_spinner=False)
def load_geojson() -> dict | None:
    p = ASSETS / "nigeria_states.geojson"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


# ------------------------------------------------------------- explorer

def _explorer_filters(model, candidates, sentiments, topics, categories, channels, langs, start, end, search,
                      min_conf, only_flagged, exclude_flagged):
    has_enrich = _table_exists("comment_sentiment")
    where, params = ["1=1"], []
    if candidates:
        where.append(f"EXISTS (SELECT 1 FROM comment_candidate_mentions m WHERE m.comment_id = c.comment_id AND m.candidate IN ({','.join('?' * len(candidates))}))")
        params += list(candidates)
    if topics:
        where.append(f"EXISTS (SELECT 1 FROM comment_topics t WHERE t.comment_id = c.comment_id AND t.method = 'lexicon' AND t.topic IN ({','.join('?' * len(topics))}))")
        params += list(topics)
    if categories:
        where.append(f"ch.category IN ({','.join('?' * len(categories))})")
        params += list(categories)
    if channels:
        where.append(f"ch.label IN ({','.join('?' * len(channels))})")
        params += list(channels)
    if langs and has_enrich:
        where.append(f"COALESCE(f.lang_hint, 'en') IN ({','.join('?' * len(langs))})")
        params += list(langs)
    if start:
        where.append("c.published_at >= ?")
        params.append(f"{start}T00:00:00Z")
    if end:
        where.append("c.published_at <= ?")
        params.append(f"{end}T23:59:59Z")
    if search:
        where.append("c.text_clean LIKE ? ESCAPE '\\'")
        params.append("%" + search.replace("%", "\\%").replace("_", "\\_") + "%")
    if has_enrich:
        if sentiments:
            where.append(f"s.label IN ({','.join('?' * len(sentiments))})")
            params += list(sentiments)
        if min_conf > 0:
            where.append("s.confidence >= ?")
            params.append(float(min_conf))
        if only_flagged:
            where.append("COALESCE(f.flagged, 0) = 1")
        if exclude_flagged:
            where.append("COALESCE(f.flagged, 0) = 0")
    elif sentiments:
        where.append(f"c.sentiment_label IN ({','.join('?' * len(sentiments))})")
        params += list(sentiments)
    joins = ("LEFT JOIN comment_sentiment s ON s.comment_id = c.comment_id AND s.model = ? "
             "LEFT JOIN comment_features f ON f.comment_id = c.comment_id") if has_enrich else ""
    join_params = [model] if has_enrich else []
    return has_enrich, " AND ".join(where), joins, join_params + params


@st.cache_data(ttl=300, show_spinner=False)
def query_comments(_sig: tuple, model: str, candidates=None, sentiments=None, topics=None, categories=None,
                   channels=None, langs=None, start=None, end=None, search=None, min_conf: float = 0.0,
                   only_flagged: bool = False, exclude_flagged: bool = False, sort: str = "newest",
                   limit: int = 200) -> pd.DataFrame:
    """Parameterised comment search for the explorer. Returns at most `limit` rows."""
    has_enrich, where, joins, params = _explorer_filters(
        model, candidates, sentiments, topics, categories, channels, langs, start, end, search,
        min_conf, only_flagged, exclude_flagged)
    order = {"newest": "c.published_at DESC", "oldest": "c.published_at ASC", "most liked": "c.like_count DESC",
             "highest confidence": "s.confidence DESC" if has_enrich else "ABS(c.sentiment_polarity) DESC",
             "lowest confidence": "s.confidence ASC" if has_enrich else "ABS(c.sentiment_polarity) ASC",
             "highest risk": "f.risk_score DESC, c.published_at DESC" if has_enrich else "c.published_at DESC"}.get(sort, "c.published_at DESC")
    sent_cols = ("s.label AS label, s.confidence, s.p_neg, s.p_neu, s.p_pos, f.lang_hint, f.risk_score, f.flagged, "
                 "f.dup_count, f.dup_authors, f.author_burst, f.author_total,"
                 if has_enrich else
                 "c.sentiment_label AS label, ABS(c.sentiment_polarity) AS confidence, NULL AS p_neg, NULL AS p_neu, "
                 "NULL AS p_pos, 'en' AS lang_hint, 0 AS risk_score, 0 AS flagged, 1 AS dup_count, 1 AS dup_authors, "
                 "0 AS author_burst, NULL AS author_total,")
    sql = f"""
        SELECT c.comment_id, c.text_clean AS text, c.author, c.published_at, c.like_count,
               c.sentiment_polarity AS baseline_polarity, c.sentiment_label AS baseline_label,
               v.title AS video_title, v.video_id, ch.label AS channel, ch.category,
               {sent_cols}
               (SELECT GROUP_CONCAT(m.candidate) FROM comment_candidate_mentions m WHERE m.comment_id = c.comment_id) AS candidates,
               (SELECT GROUP_CONCAT(t.topic) FROM comment_topics t WHERE t.comment_id = c.comment_id AND t.method = 'lexicon') AS topics
        FROM comments c
        JOIN videos v ON v.video_id = c.video_id
        JOIN channels ch ON ch.channel_id = v.channel_id
        {joins}
        WHERE {where}
        ORDER BY {order}
        LIMIT ?"""
    df = _read(sql, tuple(params + [int(limit)]))
    if not df.empty:
        df["published_at"] = pd.to_datetime(df["published_at"], utc=True, errors="coerce")
    return df


@st.cache_data(ttl=300, show_spinner=False)
def count_comments(_sig: tuple, model: str, candidates=None, sentiments=None, topics=None, categories=None,
                   channels=None, langs=None, start=None, end=None, search=None, min_conf: float = 0.0,
                   only_flagged: bool = False, exclude_flagged: bool = False) -> int:
    _, where, joins, params = _explorer_filters(
        model, candidates, sentiments, topics, categories, channels, langs, start, end, search,
        min_conf, only_flagged, exclude_flagged)
    sql = f"""SELECT COUNT(*) AS n FROM comments c
              JOIN videos v ON v.video_id = c.video_id
              JOIN channels ch ON ch.channel_id = v.channel_id
              {joins} WHERE {where}"""
    return int(_read(sql, tuple(params)).iloc[0, 0])
