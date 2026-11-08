"""
Per-comment features: language hint, text normalisation hash, author activity
and the authenticity risk score.

Everything here is deterministic, pure Python/pandas, and recomputed in full
on each run (40k comments take ~5 s; the design scales linearly).

Language hint
-------------
A lexicon-based *routing* heuristic, not a language identifier. It decides
which transformer scores a comment (see sentiment_models.build_routed) and
describes the corpus language mix on the methodology page. Labels:
    en   English (default)
    pcm  Nigerian Pidgin
    ha   Hausa
    yo   Yoruba
    ig   Igbo

Authenticity risk score (0..1)
------------------------------
A transparent weighted sum of observable signals, each in [0, 1]:
    0.50  duplicate text shared by several *different* authors (copy-paste campaign)
    0.25  duplicate text repeated by the *same* author (spam / flooding)
    0.15  author posted >= AUTH_BURST_MIN_COMMENTS comments within AUTH_BURST_WINDOW_MIN
    0.10  author posted >= AUTH_HEAVY_AUTHOR_DAY comments in one UTC day
A comment is "flagged" when the score >= AUTH_RISK_FLAG. These are
observational indicators of coordinated or automated behaviour, NOT proof.
"""

import datetime as dt
import hashlib
import re
import unicodedata

import pandas as pd

from pipeline.schema import connect, ensure_schema, log_run
from pipeline.settings import (
    AUTH_BURST_MIN_COMMENTS,
    AUTH_BURST_WINDOW_MIN,
    AUTH_DUP_MIN_LEN,
    AUTH_HEAVY_AUTHOR_DAY,
    AUTH_RISK_FLAG,
    DB_PATH,
    LANG_MARKERS,
    LANG_MIN_DENSITY,
    LANG_MIN_STRONG,
)

TOKEN_RE = re.compile(r"[a-zA-ZÀ-ɏḀ-ỿ']+")
EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF⭐⭕‼⁉™ℹ]"
)
PUNCT_RE = re.compile(r"[^\w\s]")
WS_RE = re.compile(r"\s+")


def _compile_markers():
    compiled = {}
    for lang, spec in LANG_MARKERS.items():
        def _rx(terms):
            terms = sorted(set(terms), key=len, reverse=True)
            return re.compile(r"(?<![\w'])(" + "|".join(re.escape(t) for t in terms) + r")(?![\w'])", re.IGNORECASE)
        compiled[lang] = (_rx(spec["strong"]), _rx(spec["weak"]))
    return compiled


MARKERS = _compile_markers()


def language_hint(text):
    """Return (lang, strong_hits) for a comment."""
    if not text:
        return "en", 0
    tokens = TOKEN_RE.findall(text)
    n = max(len(tokens), 1)
    best, best_hits, best_score = "en", 0, 0.0
    for lang, (strong_rx, weak_rx) in MARKERS.items():
        strong = len(strong_rx.findall(text))
        if strong == 0:
            continue
        weak = len(weak_rx.findall(text))
        density = (strong + 0.5 * weak) / n
        qualifies = strong >= LANG_MIN_STRONG or density >= LANG_MIN_DENSITY
        score = strong + 0.5 * weak
        if qualifies and score > best_score:
            best, best_hits, best_score = lang, strong, score
    return best, best_hits


def normalise_for_hash(text):
    """Lower-case, strip accents/punctuation/emoji/whitespace so trivially
    edited copies of a comment collide on the same hash."""
    t = unicodedata.normalize("NFKD", text or "")
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    t = EMOJI_RE.sub("", t.lower())
    t = PUNCT_RE.sub("", t)
    t = WS_RE.sub(" ", t).strip()
    return t


def text_hash(text):
    norm = normalise_for_hash(text)
    if len(norm) < AUTH_DUP_MIN_LEN:
        return None
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16]


def _author_bursts(df):
    """Flag comments whose author posted >= AUTH_BURST_MIN_COMMENTS within a
    sliding AUTH_BURST_WINDOW_MIN-minute window."""
    flags = pd.Series(0, index=df.index, dtype="int8")
    window = pd.Timedelta(minutes=AUTH_BURST_WINDOW_MIN)
    sub = df.dropna(subset=["author", "published_at"]).sort_values(["author", "published_at"])
    for _, grp in sub.groupby("author", sort=False):
        if len(grp) < AUTH_BURST_MIN_COMMENTS:
            continue
        times = grp["published_at"].to_numpy()
        idx = grp.index.to_numpy()
        j = 0
        for i in range(len(times)):
            while times[i] - times[j] > window:
                j += 1
            if i - j + 1 >= AUTH_BURST_MIN_COMMENTS:
                flags.loc[idx[j:i + 1]] = 1
    return flags


def compute_features(comments):
    df = comments.copy()
    df["text"] = df["text_clean"].fillna(df["text_raw"]).fillna("")
    df["published_at"] = pd.to_datetime(df["published_at"], utc=True, errors="coerce")

    lang = df["text"].map(language_hint)
    df["lang_hint"] = [l for l, _ in lang]
    df["lang_hits"] = [h for _, h in lang]
    df["n_tokens"] = df["text"].map(lambda t: len(TOKEN_RE.findall(t)))
    df["n_emoji"] = df["text"].map(lambda t: len(EMOJI_RE.findall(t)))

    def caps_ratio(t):
        letters = [c for c in t if c.isalpha()]
        return round(sum(c.isupper() for c in letters) / len(letters), 3) if len(letters) >= 10 else 0.0
    df["caps_ratio"] = df["text"].map(caps_ratio)

    df["text_hash"] = df["text"].map(text_hash)
    dup = df.dropna(subset=["text_hash"]).groupby("text_hash").agg(
        dup_count=("comment_id", "size"), dup_authors=("author", "nunique"))
    df = df.merge(dup, left_on="text_hash", right_index=True, how="left")
    df["dup_count"] = df["dup_count"].fillna(1).astype(int)
    df["dup_authors"] = df["dup_authors"].fillna(1).astype(int)

    df["author_total"] = df.groupby("author")["comment_id"].transform("size").fillna(1).astype(int)
    df["day"] = df["published_at"].dt.strftime("%Y-%m-%d")
    df["author_day_count"] = df.groupby(["author", "day"])["comment_id"].transform("size").fillna(1).astype(int)
    df["author_burst"] = _author_bursts(df)

    # Risk components, each clipped to [0, 1].
    campaign = ((df["dup_authors"] - 1) / 3).clip(0, 1) * (df["dup_count"] >= 3)
    flooding = ((df["dup_count"] - df["dup_authors"]) / 4).clip(0, 1)
    burst = df["author_burst"].astype(float)
    heavy = (df["author_day_count"] >= AUTH_HEAVY_AUTHOR_DAY).astype(float)
    df["risk_score"] = (0.50 * campaign + 0.25 * flooding + 0.15 * burst + 0.10 * heavy).round(3)
    df["flagged"] = (df["risk_score"] >= AUTH_RISK_FLAG).astype(int)
    return df


def run(db_path=DB_PATH, verbose=True):
    ensure_schema(db_path)
    started = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    conn = connect(db_path)
    comments = pd.read_sql_query(
        "SELECT comment_id, author, text_raw, text_clean, published_at FROM comments", conn)
    feats = compute_features(comments)
    now = started
    rows = [
        (r.comment_id, r.lang_hint, int(r.lang_hits), int(r.n_tokens), int(r.n_emoji), float(r.caps_ratio),
         r.text_hash, int(r.dup_count), int(r.dup_authors), int(r.author_total), int(r.author_day_count),
         int(r.author_burst), float(r.risk_score), int(r.flagged), now)
        for r in feats.itertuples(index=False)
    ]
    conn.executemany(
        """INSERT OR REPLACE INTO comment_features
           (comment_id, lang_hint, lang_hits, n_tokens, n_emoji, caps_ratio, text_hash, dup_count,
            dup_authors, author_total, author_day_count, author_burst, risk_score, flagged, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    mix = feats["lang_hint"].value_counts().to_dict()
    log_run(conn, "features", started, len(rows), f"lang_mix={mix} flagged={int(feats['flagged'].sum())}")
    conn.commit()
    conn.close()
    if verbose:
        print(f"[features] {len(rows)} comments. Language mix: {mix}. Flagged: {int(feats['flagged'].sum())}")
    return len(rows)


if __name__ == "__main__":
    run()
