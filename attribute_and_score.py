"""
Post-processing pass over stored comments:

  1. Clean text (strip URLs, normalize whitespace).
  2. Attribute each comment to the candidate(s)/party(ies) it mentions,
     applying the disambiguation rule for ADC/NDC (must co-occur with
     "nigeria" or a candidate alias -- filters out "Aide-de-Camp" and
     Ghana-NDC false positives).
  3. Score sentiment.

Only processes comments where text_clean IS NULL, so it's safe to re-run
after every collect_comments.py pass -- already-processed comments are
left untouched.
"""

import re
from textblob import TextBlob
from config import CANDIDATES, PARTIES, DISAMBIGUATORS
from db import get_conn

URL_RE = re.compile(r"http\S+|www\.\S+")
WHITESPACE_RE = re.compile(r"\s+")


def clean_text(raw):
    text = URL_RE.sub("", raw or "")
    text = WHITESPACE_RE.sub(" ", text).strip()
    return text


def match_candidates(text_lower):
    matches = []
    for key, info in CANDIDATES.items():
        if any(alias in text_lower for alias in info["aliases"]):
            matches.append(key)
    return matches


def match_parties(text_lower, matched_candidates):
    matches = []
    has_disambiguator = bool(matched_candidates) or any(d in text_lower for d in DISAMBIGUATORS)
    for key, info in PARTIES.items():
        full_name_hit = info["full_name"].lower() in text_lower
        acronym_hit = re.search(rf"\b{re.escape(info['acronym'])}\b", text_lower) is not None
        if full_name_hit:
            matches.append(key)
        elif acronym_hit and (not info["disambiguation_required"] or has_disambiguator):
            matches.append(key)
    return matches


def score_sentiment(text):
    """
    Baseline sentiment scorer (TextBlob, lexicon-based, English-only).

    KNOWN LIMITATION: not trained on Nigerian English or Pidgin, so it will
    misjudge a meaningful share of comments in this dataset. Before treating
    scores as final:
      1. Pull a random sample (e.g. 300-500 comments) and have it manually
         coded (positive/negative/neutral) by 2+ human raters.
      2. Compute agreement between TextBlob's labels and the human labels
         (e.g. Cohen's kappa) and report it in your methodology section.
      3. If agreement is weak, swap this function out for a stronger model
         (e.g. a multilingual or Nigerian-English-tuned transformer from
         Hugging Face) -- nothing else in the pipeline needs to change,
         this function is the only place sentiment logic lives.
    """
    polarity = TextBlob(text).sentiment.polarity
    if polarity > 0.1:
        label = "positive"
    elif polarity < -0.1:
        label = "negative"
    else:
        label = "neutral"
    return polarity, label


def run():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT comment_id, text_raw FROM comments WHERE text_clean IS NULL"
        ).fetchall()

        for row in rows:
            comment_id = row["comment_id"]
            clean = clean_text(row["text_raw"])
            text_lower = clean.lower()

            candidates_matched = match_candidates(text_lower)
            parties_matched = match_parties(text_lower, candidates_matched)
            polarity, label = score_sentiment(clean)

            conn.execute(
                """UPDATE comments
                   SET text_clean = ?, sentiment_polarity = ?, sentiment_label = ?
                   WHERE comment_id = ?""",
                (clean, polarity, label, comment_id),
            )
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

        print(f"Processed {len(rows)} new comments (attribution + sentiment).")


if __name__ == "__main__":
    run()
