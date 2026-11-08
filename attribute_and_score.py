"""
Post-processing pass over stored comments:

  1. Clean text (unescape HTML entities, strip <br> tags and URLs, normalise
     whitespace).
  2. Attribute each comment to the candidate(s)/party(ies) it mentions.
     Aliases are matched as WHOLE WORDS (word-boundary, case-insensitive).
     The ADC/NDC disambiguation rule still applies (bare acronym must co-occur
     with "nigeria" or a candidate alias -- filters out "Aide-de-Camp" and
     Ghana-NDC false positives).
  3. Score sentiment with the TextBlob lexicon baseline.

TextBlob is kept only as the legacy baseline that the methodology page
compares against. The sentiment the dashboard shows by default comes from
the transformer models in pipeline/sentiment_models.py, which run after this
step as part of pipeline/enrich.py.

Incremental mode (default) only processes comments where text_clean IS NULL,
so it is safe to re-run after every collect_comments.py pass.

    python attribute_and_score.py                # incremental
    python attribute_and_score.py --reattribute  # redo attribution for ALL comments

--reattribute exists because the original release matched aliases as plain
substrings: "bat" inside "Abati"/"debate" produced ~1,600 false Tinubu
attributions and the missing bare "obi" alias dropped ~1,900 genuine Peter
Obi mentions. Run it once after upgrading; pipeline/enrich.py does so
automatically when it detects the legacy attribution.
"""

import argparse
import html
import re

from config import CANDIDATES, DISAMBIGUATORS, PARTIES
from db import get_conn

URL_RE = re.compile(r"http\S+|www\.\S+")
TAG_RE = re.compile(r"<br\s*/?>|</?[a-z][^>]{0,40}>", re.IGNORECASE)
WHITESPACE_RE = re.compile(r"\s+")


def _word_rx(terms):
    terms = sorted(set(terms), key=len, reverse=True)
    return re.compile(r"(?<![\w])(" + "|".join(re.escape(t) for t in terms) + r")(?![\w])", re.IGNORECASE)


CANDIDATE_RX = {key: _word_rx(info["aliases"]) for key, info in CANDIDATES.items()}
DISAMBIGUATOR_RX = _word_rx(DISAMBIGUATORS)
PARTY_FULL_RX = {key: _word_rx([info["full_name"]]) for key, info in PARTIES.items()}
PARTY_ACRONYM_RX = {key: _word_rx([info["acronym"]]) for key, info in PARTIES.items()}


def clean_text(raw):
    text = html.unescape(raw or "")
    text = TAG_RE.sub(" ", text)
    text = URL_RE.sub("", text)
    text = WHITESPACE_RE.sub(" ", text).strip()
    return text


def match_candidates(text):
    """Return the list of candidate keys whose aliases appear as whole words."""
    return [key for key, rx in CANDIDATE_RX.items() if rx.search(text)]


def matched_aliases(text):
    """{candidate: [aliases found]} -- used by the dashboard's explainability panel."""
    out = {}
    for key, rx in CANDIDATE_RX.items():
        hits = sorted({m.lower() for m in rx.findall(text or "")})
        if hits:
            out[key] = hits
    return out


def match_parties(text, matched_candidates):
    matches = []
    has_disambiguator = bool(matched_candidates) or DISAMBIGUATOR_RX.search(text) is not None
    for key, info in PARTIES.items():
        if PARTY_FULL_RX[key].search(text):
            matches.append(key)
        elif PARTY_ACRONYM_RX[key].search(text) and (not info["disambiguation_required"] or has_disambiguator):
            matches.append(key)
    return matches


def score_sentiment(text):
    """TextBlob lexicon polarity, thresholded at +/-0.1. Legacy baseline only.

    Imported lazily so the dashboard (which reuses the alias matcher above for
    its explainability panel) does not need TextBlob installed."""
    from textblob import TextBlob

    polarity = TextBlob(text).sentiment.polarity
    if polarity > 0.1:
        label = "positive"
    elif polarity < -0.1:
        label = "negative"
    else:
        label = "neutral"
    return polarity, label


def _write_mentions(conn, comment_id, candidates_matched, parties_matched):
    for cand in candidates_matched:
        conn.execute(
            "INSERT OR IGNORE INTO comment_candidate_mentions (comment_id, candidate) VALUES (?, ?)",
            (comment_id, cand),
        )
    for party in parties_matched:
        conn.execute(
            "INSERT OR IGNORE INTO comment_party_mentions (comment_id, party) VALUES (?, ?)",
            (comment_id, party),
        )


def run():
    """Incremental: clean, attribute and baseline-score comments not yet processed."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT comment_id, text_raw FROM comments WHERE text_clean IS NULL"
        ).fetchall()
        for row in rows:
            comment_id = row["comment_id"]
            clean = clean_text(row["text_raw"])
            candidates_matched = match_candidates(clean)
            parties_matched = match_parties(clean, candidates_matched)
            polarity, label = score_sentiment(clean)
            conn.execute(
                """UPDATE comments
                   SET text_clean = ?, sentiment_polarity = ?, sentiment_label = ?
                   WHERE comment_id = ?""",
                (clean, polarity, label, comment_id),
            )
            _write_mentions(conn, comment_id, candidates_matched, parties_matched)
        print(f"Processed {len(rows)} new comments (attribution + baseline sentiment).")
        return len(rows)


def reattribute_all():
    """Recompute candidate/party mentions for EVERY comment with the current
    alias rules, and re-clean text (HTML entities, <br> tags). Sentiment
    columns are left untouched."""
    with get_conn() as conn:
        rows = conn.execute("SELECT comment_id, text_raw, text_clean FROM comments").fetchall()
        conn.execute("DELETE FROM comment_candidate_mentions")
        conn.execute("DELETE FROM comment_party_mentions")
        n_cand = 0
        for row in rows:
            clean = clean_text(row["text_raw"])
            if clean != (row["text_clean"] or ""):
                conn.execute("UPDATE comments SET text_clean = ? WHERE comment_id = ?", (clean, row["comment_id"]))
            candidates_matched = match_candidates(clean)
            parties_matched = match_parties(clean, candidates_matched)
            n_cand += len(candidates_matched)
            _write_mentions(conn, row["comment_id"], candidates_matched, parties_matched)
        # Video titles carry HTML entities straight from the API; unescape them too.
        for v in conn.execute("SELECT video_id, title FROM videos WHERE title LIKE '%&%;%'").fetchall():
            conn.execute("UPDATE videos SET title = ? WHERE video_id = ?", (html.unescape(v["title"]), v["video_id"]))
        print(f"Re-attributed {len(rows)} comments: {n_cand} candidate mentions.")
        return len(rows)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--reattribute", action="store_true", help="recompute attribution for all comments")
    args = ap.parse_args()
    if args.reattribute:
        reattribute_all()
    else:
        run()
