"""
Aggregate layer: daily fact tables, keyword intelligence and model agreement.

The dashboard reads these tables instead of the raw comments, which is what
keeps it fast as the corpus grows: fact_daily has at most
(days x candidates x channels x models) rows regardless of comment volume.

Fact tables are rebuilt from scratch on every run (a few seconds at 40k
comments, still well under a minute at 1M), so they can never drift from the
raw rows.
"""

import datetime as dt
import math
import re
from collections import Counter

import numpy as np
import pandas as pd

from pipeline.schema import connect, ensure_schema, log_run
from pipeline.settings import ALL_KEY, CANDIDATE_ORDER, DB_PATH, SENTIMENT_MODELS

MODELS = list(SENTIMENT_MODELS.keys())

# --------------------------------------------------------------------------- facts

FACT_DAILY_SQL = """
INSERT INTO fact_daily (day, candidate, channel_id, model, n, n_pos, n_neu, n_neg, sum_conf,
                        sum_likes, n_authors, n_flagged, n_videos)
SELECT substr(c.published_at, 1, 10) AS day, m.candidate, v.channel_id, s.model,
       COUNT(*), SUM(s.label = 'positive'), SUM(s.label = 'neutral'), SUM(s.label = 'negative'),
       SUM(s.confidence), SUM(COALESCE(c.like_count, 0)), COUNT(DISTINCT c.author),
       SUM(COALESCE(f.flagged, 0)), COUNT(DISTINCT c.video_id)
FROM comments c
JOIN comment_candidate_mentions m ON m.comment_id = c.comment_id
JOIN videos v ON v.video_id = c.video_id
JOIN comment_sentiment s ON s.comment_id = c.comment_id
LEFT JOIN comment_features f ON f.comment_id = c.comment_id
WHERE c.published_at IS NOT NULL
GROUP BY 1, 2, 3, 4
UNION ALL
SELECT substr(c.published_at, 1, 10) AS day, ?, v.channel_id, s.model,
       COUNT(*), SUM(s.label = 'positive'), SUM(s.label = 'neutral'), SUM(s.label = 'negative'),
       SUM(s.confidence), SUM(COALESCE(c.like_count, 0)), COUNT(DISTINCT c.author),
       SUM(COALESCE(f.flagged, 0)), COUNT(DISTINCT c.video_id)
FROM comments c
JOIN videos v ON v.video_id = c.video_id
JOIN comment_sentiment s ON s.comment_id = c.comment_id
LEFT JOIN comment_features f ON f.comment_id = c.comment_id
WHERE c.published_at IS NOT NULL
GROUP BY 1, 3, 4
"""

FACT_TOPIC_SQL = """
INSERT INTO fact_daily_topic (day, candidate, topic, model, n, n_pos, n_neu, n_neg)
SELECT substr(c.published_at, 1, 10), m.candidate, t.topic, s.model,
       COUNT(*), SUM(s.label = 'positive'), SUM(s.label = 'neutral'), SUM(s.label = 'negative')
FROM comments c
JOIN comment_candidate_mentions m ON m.comment_id = c.comment_id
JOIN comment_topics t ON t.comment_id = c.comment_id AND t.method = 'lexicon'
JOIN comment_sentiment s ON s.comment_id = c.comment_id
WHERE c.published_at IS NOT NULL
GROUP BY 1, 2, 3, 4
UNION ALL
SELECT substr(c.published_at, 1, 10), ?, t.topic, s.model,
       COUNT(*), SUM(s.label = 'positive'), SUM(s.label = 'neutral'), SUM(s.label = 'negative')
FROM comments c
JOIN comment_topics t ON t.comment_id = c.comment_id AND t.method = 'lexicon'
JOIN comment_sentiment s ON s.comment_id = c.comment_id
WHERE c.published_at IS NOT NULL
GROUP BY 1, 3, 4
"""

FACT_LOCATION_SQL = """
INSERT INTO fact_daily_location (day, candidate, state, model, n, n_pos, n_neu, n_neg)
SELECT substr(c.published_at, 1, 10), m.candidate, l.state, s.model,
       COUNT(*), SUM(s.label = 'positive'), SUM(s.label = 'neutral'), SUM(s.label = 'negative')
FROM comments c
JOIN comment_candidate_mentions m ON m.comment_id = c.comment_id
JOIN comment_locations l ON l.comment_id = c.comment_id
JOIN comment_sentiment s ON s.comment_id = c.comment_id
WHERE c.published_at IS NOT NULL
GROUP BY 1, 2, 3, 4
UNION ALL
SELECT substr(c.published_at, 1, 10), ?, l.state, s.model,
       COUNT(*), SUM(s.label = 'positive'), SUM(s.label = 'neutral'), SUM(s.label = 'negative')
FROM comments c
JOIN comment_locations l ON l.comment_id = c.comment_id
JOIN comment_sentiment s ON s.comment_id = c.comment_id
WHERE c.published_at IS NOT NULL
GROUP BY 1, 3, 4
"""


def rebuild_facts(conn, verbose=True):
    started = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    conn.execute("DELETE FROM fact_daily")
    conn.execute(FACT_DAILY_SQL, (ALL_KEY,))
    n1 = conn.execute("SELECT COUNT(*) FROM fact_daily").fetchone()[0]
    conn.execute("DELETE FROM fact_daily_topic")
    conn.execute(FACT_TOPIC_SQL, (ALL_KEY,))
    n2 = conn.execute("SELECT COUNT(*) FROM fact_daily_topic").fetchone()[0]
    conn.execute("DELETE FROM fact_daily_location")
    conn.execute(FACT_LOCATION_SQL, (ALL_KEY,))
    n3 = conn.execute("SELECT COUNT(*) FROM fact_daily_location").fetchone()[0]
    log_run(conn, "facts", started, n1 + n2 + n3, f"daily={n1} topic={n2} location={n3}")
    conn.commit()
    if verbose:
        print(f"[facts] fact_daily={n1} fact_daily_topic={n2} fact_daily_location={n3}")
    return n1 + n2 + n3


# ------------------------------------------------------------------ keywords

STOPWORDS = set("""
a about above after again against all am an and any are aren't as at be because been before being below
between both but by can can't cannot could couldn't did didn't do does doesn't doing don't down during each
few for from further had hadn't has hasn't have haven't having he he'd he'll he's her here here's hers herself
him himself his how how's i i'd i'll i'm i've if in into is isn't it it's its itself let's me more most mustn't
my myself no nor not of off on once only or other ought our ours ourselves out over own same shan't she she'd
she'll she's should shouldn't so some such than that that's the their theirs them themselves then there there's
these they they'd they'll they're they've this those through to too under until up very was wasn't we we'd we'll
we're we've were weren't what what's when when's where where's which while who who's whom why why's with won't
would wouldn't you you'd you'll you're you've your yours yourself yourselves
just like get got also even still one two will may might must shall much many every always never ever yet
dey una wey dem wetin abeg na sef sha abi oga make say go come don wan dis dat dey na im nah
people man men woman person thing things time way country nigeria nigerians nigerian naija god sir mr mrs dr
know think want need see said says tell told going back give take made make let keep put well really
amen lol ooo oo omo day today year years today's
now another someone anyone anything nothing something everything called wants want gets getting
still already yet maybe perhaps actually literally basically simply okay oh ah hmm
""".split())
TOKEN_RE = re.compile(r"[a-z][a-z'\-]{2,}")


def _candidate_stopwords():
    from pipeline.settings import CANDIDATES
    words = set()
    for key, info in CANDIDATES.items():
        words.add(key)
        for part in (info["full_name"] + " " + info["party"] + " " + info["party_full"]).lower().split():
            words.add(part)
    # nicknames handled in config aliases; keep the common ones here
    words |= {"asiwaju", "jagaban", "bat", "okwute", "obidient", "obidients", "atikulated", "pbat", "waziri"}
    return words


def tokenize(text, stop):
    toks = [t.strip("'-") for t in TOKEN_RE.findall((text or "").lower())]
    toks = [t for t in toks if t and t not in stop and not t.isdigit()]
    grams = list(toks)
    grams += [f"{a} {b}" for a, b in zip(toks, toks[1:])]
    return grams


def weighted_log_odds(counts_a, counts_b, prior_counts, alpha_scale=0.5):
    """Monroe, Colaresi & Quinn (2008) log-odds ratio with informative Dirichlet
    prior. Returns {term: z}. Positive z favours corpus A."""
    n_a = sum(counts_a.values())
    n_b = sum(counts_b.values())
    n_prior = sum(prior_counts.values())
    if n_a == 0 or n_b == 0 or n_prior == 0:
        return {}
    alpha0 = alpha_scale * n_prior / max(len(prior_counts), 1)  # overall prior strength
    out = {}
    for term in set(counts_a) | set(counts_b):
        y_a = counts_a.get(term, 0)
        y_b = counts_b.get(term, 0)
        a_w = alpha0 * prior_counts.get(term, 0) / n_prior + 0.01
        num_a = y_a + a_w
        num_b = y_b + a_w
        den_a = n_a + alpha0 - num_a
        den_b = n_b + alpha0 - num_b
        if den_a <= 0 or den_b <= 0:
            continue
        delta = math.log(num_a / den_a) - math.log(num_b / den_b)
        var = 1.0 / num_a + 1.0 / num_b
        out[term] = delta / math.sqrt(var)
    return out


def _counts(texts, stop):
    c = Counter()
    for t in texts:
        c.update(set(tokenize(t, stop)))  # presence per comment, not raw frequency
    return c


def compute_keywords(conn, model, verbose=True, top_k=20, min_count=5):
    started = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    stop = STOPWORDS | _candidate_stopwords()
    df = pd.read_sql_query(
        """SELECT m.candidate, s.label, substr(c.published_at, 1, 10) AS day,
                  COALESCE(c.text_clean, c.text_raw, '') AS text
           FROM comments c
           JOIN comment_candidate_mentions m ON m.comment_id = c.comment_id
           JOIN comment_sentiment s ON s.comment_id = c.comment_id AND s.model = ?""",
        conn, params=(model,),
    )
    if df.empty:
        return 0
    prior = _counts(df["text"], stop)
    last_day = pd.to_datetime(df["day"]).max()
    recent_start = (last_day - pd.Timedelta(days=6)).strftime("%Y-%m-%d")
    base_start = (last_day - pd.Timedelta(days=34)).strftime("%Y-%m-%d")

    conn.execute("DELETE FROM keyword_stats WHERE model = ?", (model,))
    rows = []
    for cand in CANDIDATE_ORDER:
        sub = df[df["candidate"] == cand]
        pos = _counts(sub.loc[sub["label"] == "positive", "text"], stop)
        neg = _counts(sub.loc[sub["label"] == "negative", "text"], stop)
        z = weighted_log_odds(pos, neg, prior)
        eligible = {t: v for t, v in z.items() if pos.get(t, 0) + neg.get(t, 0) >= min_count}
        top_pos = sorted(eligible.items(), key=lambda kv: -kv[1])[:top_k]
        top_neg = sorted(eligible.items(), key=lambda kv: kv[1])[:top_k]
        for rank, (term, zz) in enumerate(top_pos, 1):
            rows.append((cand, "positive", model, rank, term, float(zz), int(pos.get(term, 0)), int(neg.get(term, 0)), started))
        for rank, (term, zz) in enumerate(top_neg, 1):
            rows.append((cand, "negative", model, rank, term, float(-zz), int(neg.get(term, 0)), int(pos.get(term, 0)), started))

        recent = _counts(sub.loc[sub["day"] >= recent_start, "text"], stop)
        base = _counts(sub.loc[(sub["day"] >= base_start) & (sub["day"] < recent_start), "text"], stop)
        ze = weighted_log_odds(recent, base, prior)
        emerging = sorted(
            ((t, v) for t, v in ze.items() if recent.get(t, 0) >= 3 and v > 1.0),
            key=lambda kv: -kv[1])[:top_k]
        for rank, (term, zz) in enumerate(emerging, 1):
            rows.append((cand, "emerging", model, rank, term, float(zz), int(recent.get(term, 0)), int(base.get(term, 0)), started))

    conn.executemany(
        """INSERT OR REPLACE INTO keyword_stats
           (candidate, polarity, model, rank, term, zscore, count_a, count_b, computed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""", rows)
    log_run(conn, f"keywords:{model}", started, len(rows), f"recent>={recent_start} base>={base_start}")
    conn.commit()
    if verbose:
        print(f"[keywords:{model}] {len(rows)} rows (recent window from {recent_start})")
    return len(rows)


# ------------------------------------------------------------ model agreement

def compute_agreement(conn, verbose=True):
    started = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    df = pd.read_sql_query("SELECT comment_id, model, label FROM comment_sentiment", conn)
    if df.empty:
        return 0
    wide = df.pivot_table(index="comment_id", columns="model", values="label", aggfunc="first")
    rows = []
    models = [m for m in MODELS if m in wide.columns]
    for i, a in enumerate(models):
        for b in models[i + 1:]:
            pair = wide[[a, b]].dropna()
            if len(pair) < 50:
                continue
            agree = float((pair[a] == pair[b]).mean())
            ct = pd.crosstab(pair[a], pair[b])
            n = ct.values.sum()
            po = np.trace(ct.values) / n if ct.shape[0] == ct.shape[1] else agree
            pe = float((ct.sum(axis=1) / n).reindex(ct.columns, fill_value=0).values @ (ct.sum(axis=0) / n).values)
            kappa = (po - pe) / (1 - pe) if pe < 1 else 0.0
            rows.append((a, b, int(len(pair)), round(agree, 4), round(float(kappa), 4), started))
    conn.execute("DELETE FROM model_agreement")
    conn.executemany("INSERT INTO model_agreement (model_a, model_b, n, agreement, kappa, computed_at) VALUES (?, ?, ?, ?, ?, ?)", rows)
    log_run(conn, "agreement", started, len(rows))
    conn.commit()
    if verbose:
        for r in rows:
            print(f"[agreement] {r[0]} vs {r[1]}: n={r[2]} agree={r[3]:.3f} kappa={r[4]:.3f}")
    return len(rows)


def run(db_path=DB_PATH, verbose=True):
    ensure_schema(db_path)
    conn = connect(db_path)
    rebuild_facts(conn, verbose)
    present = [r[0] for r in conn.execute("SELECT DISTINCT model FROM comment_sentiment").fetchall()]
    for model in present:
        compute_keywords(conn, model, verbose)
    compute_agreement(conn, verbose)
    conn.close()


if __name__ == "__main__":
    run()
