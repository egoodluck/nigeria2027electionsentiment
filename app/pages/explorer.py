"""Comment explorer: search, filter, read, and see why each comment was classified the way it was."""

import html
import re

import numpy as np
import pandas as pd
import streamlit as st

from app import components as ui, theme
from app.data import CATEGORY_ORDER, category_label, count_comments, db_signature, load_channels, meta, query_comments
from app.state import sidebar_controls
from pipeline.settings import CANDIDATE_ORDER, CANDIDATES, LANG_LABELS, SENTIMENT_MODELS, TOPIC_LABELS, TOPIC_ORDER

f = sidebar_controls()
m = meta()
sig = db_signature()
ui.page_header("Comment explorer", "Search and filter the underlying comments, and inspect how each one was scored: model probabilities, the "
               "baseline's verdict, the words that triggered candidate and issue tags, and any authenticity signals.")

try:
    from attribute_and_score import matched_aliases
except Exception:  # pragma: no cover - config import problems should not break the page
    matched_aliases = None
try:
    from pipeline.topics import matched_terms
except Exception:  # pragma: no cover
    matched_terms = None

chans = load_channels(sig)

# ------------------------------------------------------------------ filters
with st.container(border=True):
    r1a, r1b = st.columns([2.2, 1])
    with r1a:
        search = st.text_input("Search comment text", placeholder="e.g. fuel subsidy, japa, rigging, Abati …", key="ex_q")
    with r1b:
        sort = st.selectbox("Sort by", ["newest", "oldest", "most liked", "highest confidence", "lowest confidence", "highest risk"], key="ex_sort")
    r2 = st.columns(4)
    with r2[0]:
        cands = st.multiselect("Candidate mentioned", CANDIDATE_ORDER, default=[c for c in f.candidates if c in CANDIDATE_ORDER] if len(f.candidates) < 3 else [],
                               format_func=lambda c: theme.candidate_label(c, "party"), key="ex_cands", placeholder="Any (incl. unattributed)")
    with r2[1]:
        sents = st.multiselect("Sentiment", ["positive", "neutral", "negative"], default=[], format_func=str.capitalize, key="ex_sent", placeholder="Any")
    with r2[2]:
        topics = st.multiselect("Issue", TOPIC_ORDER + ["other"], default=[], format_func=lambda k: TOPIC_LABELS.get(k, k), key="ex_topics", placeholder="Any")
    with r2[3]:
        langs = st.multiselect("Language", list(LANG_LABELS.keys()), default=[], format_func=lambda k: LANG_LABELS[k], key="ex_lang", placeholder="Any")
    r3 = st.columns([1, 1, 1, 1])
    with r3[0]:
        min_conf = st.slider("Minimum model confidence", 0.0, 0.95, 0.0, 0.05, key="ex_conf")
    with r3[1]:
        flag_mode = st.radio("Authenticity", ["All", "Only flagged", "Exclude flagged"], horizontal=True, key="ex_flag")
    with r3[2]:
        limit = st.select_slider("Show", options=[25, 50, 100, 200], value=50, key="ex_limit")
    with r3[3]:
        st.markdown("<div style='height:1.7rem'></div>", unsafe_allow_html=True)
        hl = st.toggle("Highlight cue words", value=True, key="ex_hl")

kwargs = dict(candidates=cands or None, sentiments=sents or None, topics=topics or None, categories=f.categories or None,
              channels=f.channels or None, langs=langs or None, start=f.start.strftime("%Y-%m-%d"), end=f.end.strftime("%Y-%m-%d"),
              search=search.strip() or None, min_conf=min_conf, only_flagged=flag_mode == "Only flagged", exclude_flagged=flag_mode == "Exclude flagged")
total = count_comments(sig, f.model, **kwargs)
df = query_comments(sig, f.model, sort=sort, limit=limit, **kwargs)

# ------------------------------------------------------------------ summary
ui.section(f"{total:,} matching comments", f"showing {len(df):,} · {ui.model_caption(f.model)} · {f.start:%d %b} – {f.end:%d %b %Y}")
if not df.empty:
    k1, k2, k3, k4 = st.columns(4)
    mix = df["label"].value_counts(normalize=True)
    with k1:
        ui.stat_tile("Positive (shown)", ui.fmt_pct(mix.get("positive", 0.0)))
    with k2:
        ui.stat_tile("Negative (shown)", ui.fmt_pct(mix.get("negative", 0.0)))
    with k3:
        ui.stat_tile("Mean confidence", ui.fmt_pct(df["confidence"].mean()))
    with k4:
        ui.stat_tile("Flagged (shown)", ui.fmt_int(int(df["flagged"].fillna(0).sum())))
    export = df.drop(columns=["author"]).copy()
    export["published_at"] = export["published_at"].dt.strftime("%Y-%m-%d %H:%M")
    st.download_button("Download shown comments (CSV, authors removed)", export.to_csv(index=False).encode("utf-8"),
                       file_name="comments_filtered.csv", mime="text/csv", key="ex_dl")

if df.empty:
    ui.empty_state("No comments match. Try fewer filters or a different search term.")
    st.stop()

view = st.segmented_control("View", ["Cards with explanations", "Table"], default="Cards with explanations", key="ex_view") or "Cards with explanations"

# ------------------------------------------------------------------ helpers
CUE_LIMIT = 12


def _list(x) -> list[str]:
    """GROUP_CONCAT results arrive as 'a,b' strings or NaN."""
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return []
    return [t for t in str(x).split(",") if t]


def highlight(text: str, cand_terms: list[str], topic_terms: list[str]) -> str:
    out = html.escape(text or "")
    if not hl:
        return out
    for terms, cls in ((cand_terms, "nes-hl"), (topic_terms, "nes-hl topic")):
        for t in sorted(set(terms), key=len, reverse=True)[:CUE_LIMIT]:
            if not t:
                continue
            pattern = re.compile(r"(?<![\w])(" + re.escape(html.escape(t)) + r")(?![\w])", re.IGNORECASE)
            out = pattern.sub(lambda mt: f"<mark class='{cls}'>{mt.group(1)}</mark>", out)
    return out


def explain(row) -> tuple[str, list[str], list[str]]:
    model_name = SENTIMENT_MODELS.get(f.model, {}).get("short", f.model)
    routed_note = ""
    if f.model == "routed":
        chosen = "NaijaSenti AfriBERTa" if row["lang_hint"] in ("pcm", "ha", "yo", "ig") else "CardiffNLP RoBERTa"
        routed_note = f" (routed to {chosen} because the text reads as {LANG_LABELS.get(row['lang_hint'], 'English')})"
    conf = row["confidence"] if pd.notna(row["confidence"]) else np.nan
    parts = [f"Classified <b>{row['label']}</b> with {conf:.0%} confidence by {model_name}{routed_note}." if pd.notna(conf) else f"Classified <b>{row['label']}</b> by {model_name}."]
    if pd.notna(row["p_neg"]):
        second = sorted([("negative", row["p_neg"]), ("neutral", row["p_neu"]), ("positive", row["p_pos"])], key=lambda x: -x[1])[1]
        if second[1] >= 0.3:
            parts.append(f"The runner-up class was {second[0]} ({second[1]:.0%}), so this call is uncertain.")
    if row["baseline_label"]:
        if row["baseline_label"] == row["label"]:
            parts.append(f"The TextBlob lexicon baseline agrees ({row['baseline_label']}, polarity {row['baseline_polarity']:+.2f}).")
        else:
            parts.append(f"The TextBlob lexicon baseline disagrees ({row['baseline_label']}, polarity {row['baseline_polarity']:+.2f}) — lexicons miss sarcasm, Pidgin and context.")
    cand_terms, topic_terms = [], []
    if matched_aliases and _list(row["candidates"]):
        hits = matched_aliases(row["text"] or "")
        for c, aliases in hits.items():
            cand_terms += aliases
        if hits:
            parts.append("Candidate cues: " + "; ".join(f"{CANDIDATES[c]['short']} ← " + ", ".join(f"“{a}”" for a in al) for c, al in hits.items()) + ".")
    if matched_terms and _list(row["topics"]):
        bits = []
        for t in _list(row["topics"]):
            if t == "other":
                continue
            terms = matched_terms(row["text"] or "", t)
            topic_terms += terms
            if terms:
                bits.append(f"{TOPIC_LABELS.get(t, t)} ← " + ", ".join(f"“{x}”" for x in terms[:5]))
        if bits:
            parts.append("Issue cues: " + "; ".join(bits) + ".")
    risk_bits = []
    if (row["dup_count"] or 1) > 1:
        risk_bits.append(f"text appears {int(row['dup_count'])}× from {int(row['dup_authors'])} author(s)")
    if row["author_burst"]:
        risk_bits.append("part of a posting burst")
    if pd.notna(row["author_total"]) and row["author_total"] >= 50:
        risk_bits.append(f"author has {int(row['author_total'])} comments in the corpus")
    if risk_bits:
        parts.append(("<b>Authenticity signals:</b> " if row["flagged"] else "Authenticity notes: ") + "; ".join(risk_bits) + f" (risk {row['risk_score']:.2f}).")
    return " ".join(parts), cand_terms, topic_terms


# ------------------------------------------------------------------ render
if view == "Table":
    t = df.copy()
    t["published_at"] = t["published_at"].dt.strftime("%Y-%m-%d %H:%M")
    t["candidates"] = t["candidates"].map(lambda s: ", ".join(CANDIDATES[c]["short"] for c in _list(s) if c in CANDIDATES))
    t["topics"] = t["topics"].map(lambda s: ", ".join(TOPIC_LABELS.get(x, x) for x in _list(s) if x != "other"))
    t["language"] = t["lang_hint"].map(lambda k: LANG_LABELS.get(k, k))
    cols = ["published_at", "text", "label", "confidence", "baseline_label", "candidates", "topics", "language", "channel", "like_count", "risk_score", "flagged"]
    st.dataframe(t[cols].rename(columns={"published_at": "Published (UTC)", "text": "Comment", "label": "Sentiment", "confidence": "Confidence",
                                         "baseline_label": "Baseline", "candidates": "Candidates", "topics": "Issues", "language": "Language",
                                         "channel": "Channel", "like_count": "Likes", "risk_score": "Risk", "flagged": "Flagged"}),
                 width="stretch", hide_index=True, height=640,
                 column_config={"Comment": st.column_config.TextColumn(width="large"), "Confidence": st.column_config.ProgressColumn(format="%.2f", min_value=0, max_value=1),
                                "Risk": st.column_config.NumberColumn(format="%.2f")})
else:
    for _, row in df.iterrows():
        why, cand_terms, topic_terms = explain(row)
        text_html = highlight(row["text"], cand_terms, topic_terms)
        cands_html = " ".join(ui.candidate_chip(c, "short") for c in _list(row["candidates"]) if c in CANDIDATES)
        topics_html = " ".join(ui.badge(TOPIC_LABELS.get(t, t), "amber") for t in _list(row["topics"]) if t != "other")
        flag_html = ui.badge("flagged", "neg") if (pd.notna(row["flagged"]) and row["flagged"]) else ""
        lang_html = ui.badge(LANG_LABELS.get(row["lang_hint"], "English"), "outline") if row["lang_hint"] and row["lang_hint"] != "en" else ""
        prob = ui.prob_bar(row["p_neg"], row["p_neu"], row["p_pos"]) if pd.notna(row["p_neg"]) else ""
        when = row["published_at"].strftime("%d %b %Y %H:%M UTC") if pd.notna(row["published_at"]) else ""
        st.markdown(
            f"<div class='nes-comment'><div class='txt'>{text_html}</div>"
            f"<div class='meta'>{ui.sentiment_badge(row['label'])} {prob} <span>{(row['confidence'] if pd.notna(row['confidence']) else 0):.0%} conf.</span> {cands_html} {topics_html} {lang_html} {flag_html}"
            f"<span>· {ui.esc(row['channel'])} · {when} · {int(row['like_count'] or 0)} likes</span></div>"
            f"<details style='margin-top:0.45rem'><summary style='cursor:pointer;color:var(--nes-brand-text);font-size:0.8rem;font-weight:600'>Why this classification?</summary>"
            f"<div class='nes-caption' style='margin-top:0.35rem'>{why}<br><span style='opacity:0.8'>Video: {ui.esc(row['video_title'])}</span></div></details></div>",
            unsafe_allow_html=True)

ui.footer()
