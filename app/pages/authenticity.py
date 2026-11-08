"""Authenticity signals: duplicate campaigns, burst activity, heavy posters, manipulation risk indicator."""

import numpy as np
import pandas as pd
import streamlit as st

from app import analytics as an
from app import charts, components as ui, theme
from app.data import db_signature, load_fact_daily, load_risk_summary, meta
from app.state import sidebar_controls
from pipeline.settings import (
    AUTH_BURST_MIN_COMMENTS, AUTH_BURST_WINDOW_MIN, AUTH_HEAVY_AUTHOR_DAY, AUTH_RISK_FLAG, CANDIDATE_ORDER, MANIPULATION_BANDS,
)

f = sidebar_controls()
m = meta()
sig = db_signature()
ui.page_header("Authenticity signals", "Observable patterns that are consistent with coordinated or automated commenting — repeated text, "
               "copy-paste campaigns, bursts of posting — summarised into a risk indicator. These are indicators, not verdicts.")

ui.note("<b>Observational, not definitive.</b> A flagged comment is one whose text or posting pattern matches a heuristic. Enthusiastic supporters "
        "repeat slogans; journalists' fans post the same praise on every clip; none of that proves automation. Use the indicator to decide where "
        "to look, and read the flagged comments in the explorer before drawing conclusions.", "amber")

rs = load_risk_summary(sig)
fd_all = load_fact_daily(sig, f.model)
if not rs or fd_all.empty:
    ui.empty_state("Authenticity features are not available yet. Run `python -m pipeline.enrich --only features aggregates`.")
    st.stop()
fd = an.filter_facts(fd_all, f.start, f.end, f.categories, f.channels)

# ------------------------------------------------------------------ KPIs
ui.section("Corpus-wide signals", "whole database")
k1, k2, k3, k4, k5 = st.columns(5)
with k1:
    ui.stat_tile("Comments analysed", ui.fmt_int(rs["total"]))
with k2:
    ui.stat_tile("Flagged (risk ≥ %.1f)" % AUTH_RISK_FLAG, ui.fmt_int(rs["flagged"]), ui.fmt_pct(rs["flagged"] / rs["total"], 2) + " of corpus", "flat")
with k3:
    ui.stat_tile("Elevated (risk ≥ 0.3)", ui.fmt_int(rs["elevated"]), ui.fmt_pct(rs["elevated"] / rs["total"], 2) + " of corpus", "flat")
with k4:
    ui.stat_tile("Duplicate-text comments", ui.fmt_int(rs["duplicates"]), "exact or near-exact copies", "flat")
with k5:
    ui.stat_tile("Burst-posted comments", ui.fmt_int(rs["bursts"]), f"≥{AUTH_BURST_MIN_COMMENTS} by one author in {AUTH_BURST_WINDOW_MIN} min", "flat")

# ------------------------------------------------------ risk per candidate
ui.section("Manipulation risk indicator", f"share of each candidate's mentions that are flagged, {f.start:%d %b} – {f.end:%d %b %Y}")
cands_fd = an.candidates_only(fd)
summ = {c: an.summarize(cands_fd[cands_fd["candidate"] == c]) for c in CANDIDATE_ORDER}
cols = st.columns(3)
for col, c in zip(cols, CANDIDATE_ORDER):
    s = summ[c]
    band = an.manipulation_band(s["flagged_share"])
    with col, st.container(border=True):
        ui.candidate_card_header(c)
        color_kind = {"Low": "pos", "Medium": "amber", "High": "neg"}.get(band, "neu")
        st.markdown(f"<div class='nes-tile'><div class='lbl'>Risk indicator</div><div class='val'>{ui.badge(band, color_kind)}</div>"
                    f"<div class='note'>{ui.fmt_pct(s['flagged_share'], 2)} of {ui.fmt_int(s['n'])} mentions flagged</div></div>", unsafe_allow_html=True)
bands_txt = " · ".join(f"{label} &lt; {thr:.0%}" if thr <= 1 else f"{label} ≥ {MANIPULATION_BANDS[i-1][0]:.0%}" for i, (thr, label) in enumerate(MANIPULATION_BANDS))
ui.caption(f"Bands: {bands_txt} of mentions flagged. Thresholds are heuristic and documented on the Methodology page.")

# ------------------------------------------------- distribution and bursts
ui.section("Risk distribution and burst days")
c1, c2 = st.columns([1, 1.5])
with c1:
    st.plotly_chart(charts.risk_histogram(rs["hist"]), width="stretch", config=theme.PLOTLY_CONFIG, key="au_hist")
    ui.caption("Score = 0.50 × cross-author copies + 0.25 × same-author repeats + 0.15 × burst posting + 0.10 × heavy daily posting (each component 0–1). "
               f"Flagged at ≥ {AUTH_RISK_FLAG}. Log scale.")
with c2:
    daily_all = an.daily_series(an.all_comments(fd), window=1)
    if daily_all.empty:
        ui.empty_state()
    else:
        st.plotly_chart(charts.burst_chart(daily_all), width="stretch", config=theme.PLOTLY_CONFIG, key="au_burst")
        ui.caption("Burst days are days whose comment volume is 2.5 robust standard deviations above the trailing 14-day median. Most correspond to "
                   "a viral interview or a collection run that caught up after a gap — check the most-discussed videos for that date.")

# -------------------------------------------------------------- campaigns
ui.section("Repeated-text campaigns", "identical or near-identical texts (normalised: case, punctuation, emoji, accents) posted three or more times")
camp = rs["campaigns"].copy()
if camp.empty:
    ui.empty_state("No text was repeated three or more times.")
else:
    camp["type"] = np.where(camp["authors"] >= 3, "Cross-author (copy-paste campaign)", np.where(camp["authors"] == 2, "Two authors", "Single author (flooding)"))
    camp["candidates"] = camp["candidates"].fillna("").map(lambda s: ", ".join(theme.candidate_label(c, "short") for c in sorted(set(s.split(","))) if c) if s else "—")
    st.dataframe(camp[["text", "copies", "authors", "type", "candidates", "first_seen", "last_seen"]].rename(
        columns={"text": "Text", "copies": "Copies", "authors": "Distinct authors", "type": "Pattern", "candidates": "Candidates mentioned",
                 "first_seen": "First seen", "last_seen": "Last seen"}),
        width="stretch", hide_index=True, height=min(560, 60 + 35 * len(camp)), column_config={"Text": st.column_config.TextColumn(width="large")})

# ------------------------------------------------------------ heavy posters
ui.section("Most active authors", "volume alone is not suspicious; combined with bursts and repeats it is worth a look")
auth = rs["authors"].copy()
if auth.empty:
    ui.empty_state()
else:
    auth["candidates"] = auth["candidates"].fillna("").map(lambda s: ", ".join(theme.candidate_label(c, "short") for c in sorted(set(s.split(","))) if c) if s else "—")
    auth["author"] = auth["author"].map(lambda a: (a[:3] + "•" * max(3, len(a) - 5) + a[-2:]) if isinstance(a, str) and len(a) > 6 else a)
    st.dataframe(auth.rename(columns={"author": "Author (masked)", "comments": "Comments", "videos": "Videos", "max_per_day": "Max in one day",
                                      "burst_comments": "Burst-posted", "avg_risk": "Avg. risk", "candidates": "Candidates mentioned"}),
                 width="stretch", hide_index=True, height=min(520, 60 + 35 * len(auth)))
    ui.caption("Author handles are masked in the interface; the underlying data keeps the public YouTube display name only (no user IDs or profiles). "
               f"'Burst-posted' counts comments that were part of a run of ≥{AUTH_BURST_MIN_COMMENTS} within {AUTH_BURST_WINDOW_MIN} minutes; "
               f"heavy daily posting is ≥{AUTH_HEAVY_AUTHOR_DAY} comments in a UTC day.")

ui.footer()
