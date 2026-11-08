"""
Transformer sentiment scoring.

Two free Hugging Face models are run over every comment and stored side by
side in `comment_sentiment`:

  cardiffnlp   cardiffnlp/twitter-roberta-base-sentiment-latest   (English)
  naijasenti   Davlan/naija-twitter-sentiment-afriberta-large     (pcm/ha/yo/ig)

A third, derived "model" called `routed` picks one of the two per comment
using the language hint computed in pipeline/features.py (English -> CardiffNLP,
vernacular -> NaijaSenti). It is the dashboard default.

The scorer is resumable: it only scores comments that have no row for the
given model, sorts them by length for efficient padding, and commits after
every batch. Interrupting it loses at most one batch.

CPU only, no API, no cost. ~20-45 comments/sec on two cores.
"""

import argparse
import datetime as dt
import time

from pipeline.schema import connect, ensure_schema, log_run
from pipeline.settings import (
    DB_PATH,
    SENTIMENT_MODELS,
    TRANSFORMER_BATCH_SIZE,
    TRANSFORMER_MAX_LENGTH,
    TRANSFORMER_MODELS,
)

LABELS = ("negative", "neutral", "positive")


def _utcnow():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _load(hf_id):
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    torch.set_num_threads(max(1, torch.get_num_threads()))
    tok = AutoTokenizer.from_pretrained(hf_id)
    model = AutoModelForSequenceClassification.from_pretrained(hf_id)
    model.eval()
    # Map the model's own label order onto (negative, neutral, positive).
    id2label = {int(k): v.lower() for k, v in model.config.id2label.items()}
    order = []
    for want in LABELS:
        matches = [i for i, lab in id2label.items() if lab.startswith(want[:3])]
        if not matches:
            raise RuntimeError(f"{hf_id}: cannot find label {want!r} in {id2label}")
        order.append(matches[0])
    return tok, model, order


def pending_comments(conn, model_key, limit=None):
    sql = """
        SELECT c.comment_id, COALESCE(c.text_clean, c.text_raw, '') AS text
        FROM comments c
        WHERE NOT EXISTS (
            SELECT 1 FROM comment_sentiment s
            WHERE s.comment_id = c.comment_id AND s.model = ?
        )
        ORDER BY length(COALESCE(c.text_clean, c.text_raw, ''))
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    return conn.execute(sql, (model_key,)).fetchall()


def score_model(model_key, db_path=DB_PATH, batch_size=TRANSFORMER_BATCH_SIZE,
                max_length=TRANSFORMER_MAX_LENGTH, limit=None, verbose=True):
    import torch

    hf_id = SENTIMENT_MODELS[model_key]["hf_id"]
    started = _utcnow()
    conn = connect(db_path)
    rows = pending_comments(conn, model_key, limit)
    if not rows:
        if verbose:
            print(f"[{model_key}] nothing to score.")
        conn.close()
        return 0

    if verbose:
        print(f"[{model_key}] loading {hf_id} ...")
    tok, model, order = _load(hf_id)
    if verbose:
        print(f"[{model_key}] scoring {len(rows)} comments in batches of {batch_size}")

    t0 = time.time()
    written = 0
    for start in range(0, len(rows), batch_size):
        batch = rows[start:start + batch_size]
        texts = [(r["text"] or "").strip() or "." for r in batch]
        with torch.inference_mode():
            enc = tok(texts, padding=True, truncation=True, max_length=max_length, return_tensors="pt")
            probs = torch.softmax(model(**enc).logits, dim=-1)[:, order].tolist()
        now = _utcnow()
        out = []
        for r, p in zip(batch, probs):
            idx = max(range(3), key=lambda i: p[i])
            out.append((r["comment_id"], model_key, LABELS[idx], float(p[idx]),
                        float(p[0]), float(p[1]), float(p[2]), now))
        conn.executemany(
            """INSERT OR REPLACE INTO comment_sentiment
               (comment_id, model, label, confidence, p_neg, p_neu, p_pos, scored_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            out,
        )
        conn.commit()
        written += len(out)
        if verbose and (start // batch_size) % 20 == 0:
            rate = written / max(time.time() - t0, 1e-6)
            eta = (len(rows) - written) / max(rate, 1e-6)
            print(f"[{model_key}] {written}/{len(rows)}  {rate:.1f}/s  ETA {eta/60:.1f} min")

    log_run(conn, f"sentiment:{model_key}", started, written, hf_id)
    conn.commit()
    conn.close()
    if verbose:
        print(f"[{model_key}] done: {written} comments in {(time.time()-t0)/60:.1f} min")
    return written


def build_routed(db_path=DB_PATH, verbose=True):
    """Derive the `routed` model from the two transformer models + lang_hint.

    English (or unknown) -> cardiffnlp; pcm/ha/yo/ig -> naijasenti. Falls back
    to whichever model has scored the comment if the preferred one is missing.
    """
    started = _utcnow()
    conn = connect(db_path)
    n = conn.execute("""
        INSERT OR REPLACE INTO comment_sentiment
            (comment_id, model, label, confidence, p_neg, p_neu, p_pos, scored_at)
        SELECT s.comment_id, 'routed', s.label, s.confidence, s.p_neg, s.p_neu, s.p_pos, s.scored_at
        FROM comment_sentiment s
        LEFT JOIN comment_features f ON f.comment_id = s.comment_id
        WHERE s.model = CASE
                WHEN COALESCE(f.lang_hint, 'en') IN ('pcm', 'ha', 'yo', 'ig') THEN 'naijasenti'
                ELSE 'cardiffnlp' END
    """).rowcount
    # Fallback for comments where the preferred model has no row yet.
    n2 = conn.execute("""
        INSERT OR IGNORE INTO comment_sentiment
            (comment_id, model, label, confidence, p_neg, p_neu, p_pos, scored_at)
        SELECT s.comment_id, 'routed', s.label, s.confidence, s.p_neg, s.p_neu, s.p_pos, s.scored_at
        FROM comment_sentiment s
        WHERE s.model IN ('cardiffnlp', 'naijasenti')
          AND NOT EXISTS (SELECT 1 FROM comment_sentiment r WHERE r.comment_id = s.comment_id AND r.model = 'routed')
    """).rowcount
    # TextBlob baseline mirrored into the same table so every model is queried alike.
    n3 = conn.execute("""
        INSERT OR REPLACE INTO comment_sentiment
            (comment_id, model, label, confidence, p_neg, p_neu, p_pos, scored_at)
        SELECT comment_id, 'textblob', sentiment_label, ABS(sentiment_polarity),
               CASE WHEN sentiment_label='negative' THEN 1 ELSE 0 END,
               CASE WHEN sentiment_label='neutral' THEN 1 ELSE 0 END,
               CASE WHEN sentiment_label='positive' THEN 1 ELSE 0 END,
               COALESCE(fetched_at, CURRENT_TIMESTAMP)
        FROM comments
        WHERE sentiment_label IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM comment_sentiment t WHERE t.comment_id = comments.comment_id AND t.model = 'textblob')
    """).rowcount
    log_run(conn, "sentiment:routed", started, n + n2, f"fallback={n2} textblob_mirrored={n3}")
    conn.commit()
    conn.close()
    if verbose:
        print(f"[routed] {n} routed rows (+{n2} fallback), {n3} TextBlob rows mirrored")
    return n + n2


def run(db_path=DB_PATH, models=None, limit=None, verbose=True):
    ensure_schema(db_path)
    total = 0
    for key in (models or TRANSFORMER_MODELS):
        total += score_model(key, db_path=db_path, limit=limit, verbose=verbose)
    build_routed(db_path, verbose=verbose)
    return total


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Score comments with transformer sentiment models.")
    ap.add_argument("--models", nargs="*", default=None, help="subset of: cardiffnlp naijasenti")
    ap.add_argument("--limit", type=int, default=None, help="score at most N pending comments per model")
    ap.add_argument("--db", default=DB_PATH)
    args = ap.parse_args()
    run(db_path=args.db, models=args.models, limit=args.limit)
