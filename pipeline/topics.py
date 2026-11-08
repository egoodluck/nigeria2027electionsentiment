"""
Topic intelligence.

Two complementary layers, both free and fully reproducible:

1. Seeded lexicon taxonomy (method='lexicon')
   Thirteen election issue areas defined in settings.TOPICS with Nigerian-
   context vocabulary. Multi-label: a comment that mentions hunger and
   banditry carries both `economy` and `security`. Score = number of distinct
   matched terms. Comments with no match get the single topic `other`.
   This layer is what the dashboard's topic charts are built on, because
   its categories are stable across runs and can be audited term by term.

2. Unsupervised discovery (method='nmf')
   TF-IDF (1-2 grams) + Non-negative Matrix Factorisation (scikit-learn) with a
   fixed seed finds the data-driven themes the lexicon may have missed. Top
   terms per theme are stored in `discovered_themes`; each comment gets its
   dominant theme when the weight is meaningful. Shown on the topic page as
   "discovered themes" with the caveat that they are statistical clusters,
   not editorial categories.
"""

import datetime as dt
import re

import numpy as np
import pandas as pd

from pipeline.schema import connect, ensure_schema, log_run
from pipeline.settings import CANDIDATES, DB_PATH, OTHER_TOPIC, TOPICS

NMF_COMPONENTS = 12
NMF_TOP_TERMS = 12
NMF_MIN_WEIGHT = 0.05

# Candidate aliases, parties and generic chatter removed from the NMF
# vocabulary so themes describe *issues* rather than who is being discussed.
EXTRA_STOPWORDS = {
    "tinubu", "bola", "ahmed", "asiwaju", "jagaban", "bat", "atiku", "abubakar", "waziri",
    "peter", "obi", "okwute", "obidient", "obidients", "apc", "adc", "ndc", "pdp", "lp",
    "nigeria", "nigerians", "nigerian", "naija", "president", "presidency", "2027", "2023",
    "election", "elections", "vote", "votes", "voting", "people", "man", "men", "woman",
    "country", "government", "govt", "like", "just", "know", "want", "say", "said", "dey",
    "una", "wey", "dem", "don", "na", "abeg", "make", "go", "come", "did", "does", "doing",
    "god", "amen", "sir", "oga", "mr", "mrs", "dr", "prof", "let", "good", "bad", "thing",
    "things", "time", "way", "need", "yes", "day", "today", "year", "years", "ok", "okay",
    "lol", "really", "going", "think", "right", "better", "best", "guy", "guys", "ooo", "oo",
    "http", "https", "www", "com", "youtube", "video", "comment", "comments",
}
WORD_RE = re.compile(r"[a-z][a-z'\-]{1,}")


def _compile_topics():
    compiled = {}
    for key, spec in TOPICS.items():
        terms = sorted(set(spec["terms"]), key=len, reverse=True)
        compiled[key] = re.compile(
            r"(?<![\w'])(" + "|".join(re.escape(t) for t in terms) + r")(?![\w'])", re.IGNORECASE)
    return compiled


TOPIC_RX = _compile_topics()


def lexicon_topics(text):
    """Return {topic: n_distinct_terms} for a comment (empty dict = other)."""
    out = {}
    if not text:
        return out
    for key, rx in TOPIC_RX.items():
        hits = {m.lower() for m in rx.findall(text)}
        if hits:
            out[key] = len(hits)
    return out


def matched_terms(text, topic):
    """Terms from `topic`'s lexicon found in `text` — used for explainability."""
    if not text or topic not in TOPIC_RX:
        return []
    return sorted({m.lower() for m in TOPIC_RX[topic].findall(text)})


def run_lexicon(conn, verbose=True):
    started = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    df = pd.read_sql_query("SELECT comment_id, COALESCE(text_clean, text_raw, '') AS text FROM comments", conn)
    rows = []
    for cid, text in zip(df["comment_id"], df["text"]):
        topics = lexicon_topics(text)
        if not topics:
            rows.append((cid, OTHER_TOPIC, 0.0, "lexicon"))
        else:
            rows.extend((cid, t, float(s), "lexicon") for t, s in topics.items())
    conn.execute("DELETE FROM comment_topics WHERE method = 'lexicon'")
    conn.executemany("INSERT OR REPLACE INTO comment_topics (comment_id, topic, score, method) VALUES (?, ?, ?, ?)", rows)
    log_run(conn, "topics:lexicon", started, len(rows))
    conn.commit()
    if verbose:
        counts = pd.Series([r[1] for r in rows]).value_counts()
        print(f"[topics:lexicon] {len(rows)} labels over {len(df)} comments\n{counts.to_string()}")
    return len(rows)


def run_nmf(conn, verbose=True):
    try:
        from sklearn.decomposition import NMF
        from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer
    except ImportError:
        if verbose:
            print("[topics:nmf] scikit-learn not installed - skipping discovery layer")
        return 0

    started = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    df = pd.read_sql_query(
        "SELECT comment_id, COALESCE(text_clean, text_raw, '') AS text FROM comments WHERE length(COALESCE(text_clean, text_raw, '')) >= 25",
        conn,
    )
    if len(df) < 500:
        if verbose:
            print("[topics:nmf] fewer than 500 usable comments - skipping")
        return 0
    stop = set(ENGLISH_STOP_WORDS) | EXTRA_STOPWORDS
    vec = TfidfVectorizer(
        lowercase=True, token_pattern=WORD_RE.pattern, stop_words=list(stop),
        ngram_range=(1, 2), min_df=15, max_df=0.4, max_features=20000, sublinear_tf=True,
    )
    X = vec.fit_transform(df["text"])
    nmf = NMF(n_components=NMF_COMPONENTS, init="nndsvda", random_state=42, max_iter=400, beta_loss="frobenius")
    W = nmf.fit_transform(X)
    H = nmf.components_
    terms = np.array(vec.get_feature_names_out())

    # Normalise document weights so the dominant-theme threshold is comparable.
    row_sum = W.sum(axis=1, keepdims=True)
    row_sum[row_sum == 0] = 1
    Wn = W / row_sum
    dominant = Wn.argmax(axis=1)
    weight = Wn.max(axis=1)
    keep = weight >= NMF_MIN_WEIGHT

    conn.execute("DELETE FROM comment_topics WHERE method = 'nmf'")
    conn.executemany(
        "INSERT OR REPLACE INTO comment_topics (comment_id, topic, score, method) VALUES (?, ?, ?, 'nmf')",
        [(cid, f"theme_{int(t)}", float(w)) for cid, t, w, k in zip(df["comment_id"], dominant, weight, keep) if k],
    )
    conn.execute("DELETE FROM discovered_themes")
    now = started
    theme_rows = []
    sizes = pd.Series(dominant[keep]).value_counts()
    for t in range(NMF_COMPONENTS):
        top = np.argsort(H[t])[::-1][:NMF_TOP_TERMS]
        for rank, j in enumerate(top, start=1):
            theme_rows.append((t, rank, str(terms[j]), float(H[t, j]), int(sizes.get(t, 0)), now))
    conn.executemany(
        "INSERT OR REPLACE INTO discovered_themes (theme_id, rank, term, weight, n_comments, computed_at) VALUES (?, ?, ?, ?, ?, ?)",
        theme_rows,
    )
    log_run(conn, "topics:nmf", started, int(keep.sum()), f"components={NMF_COMPONENTS} vocab={len(terms)}")
    conn.commit()
    if verbose:
        print(f"[topics:nmf] {int(keep.sum())} comments assigned to {NMF_COMPONENTS} themes (vocab {len(terms)})")
        for t in range(NMF_COMPONENTS):
            top = [str(terms[j]) for j in np.argsort(H[t])[::-1][:8]]
            print(f"   theme_{t} (n={int(sizes.get(t, 0))}): {', '.join(top)}")
    return int(keep.sum())


def run(db_path=DB_PATH, verbose=True):
    ensure_schema(db_path)
    conn = connect(db_path)
    n1 = run_lexicon(conn, verbose)
    n2 = run_nmf(conn, verbose)
    conn.close()
    return n1 + n2


if __name__ == "__main__":
    run()
