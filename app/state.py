"""
Global controls (sidebar) shared by every page, and the Filters object that
pages read. Streamlit re-runs the active page on every interaction; widget
state persists in st.session_state via stable keys.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import streamlit as st

from app import components as ui
from app.data import CATEGORY_LABELS, CATEGORY_ORDER, category_label, default_model, load_channels, db_signature, meta
from pipeline.settings import CANDIDATE_ORDER, SENTIMENT_MODELS

RANGE_PRESETS = {
    "Last 7 days": 7,
    "Last 14 days": 14,
    "Last 30 days": 30,
    "Last 90 days": 90,
    "All data": None,
    "Custom": "custom",
}


@dataclass
class Filters:
    model: str
    start: pd.Timestamp
    end: pd.Timestamp
    categories: list[str]
    channels: list[str]
    candidates: list[str]
    range_label: str
    mature_until: pd.Timestamp | None

    @property
    def days(self) -> int:
        return int((self.end - self.start).days) + 1

    @property
    def period_days(self) -> int:
        """Window used for 'vs previous period' comparisons: 7 for ranges >= 14 days, else the range length."""
        return 7 if self.days >= 14 else max(self.days, 1)

    @property
    def analysis_end(self) -> pd.Timestamp:
        """End of the window used for indices and comparisons: never inside the still-accumulating zone."""
        if self.mature_until is not None and self.mature_until < self.end:
            return max(self.mature_until, self.start)
        return self.end

    def describe(self) -> str:
        cats = "all outlet categories" if not self.categories else ", ".join(category_label(c) for c in self.categories)
        return f"{self.start:%d %b %Y} – {self.end:%d %b %Y} · {cats} · {SENTIMENT_MODELS.get(self.model, {}).get('short', self.model)}"


def sidebar_controls() -> Filters:
    m = meta()
    chans = load_channels(db_signature())
    first = pd.Timestamp(m["first_day"]) if m.get("first_day") else pd.Timestamp("2026-07-16")
    last = pd.Timestamp(m["last_day"]) if m.get("last_day") else pd.Timestamp.today().normalize()
    mature_until = pd.Timestamp(m["mature_until"]) if m.get("mature_until") else None

    with st.sidebar:
        st.markdown("<div class='nes-kicker' style='margin-top:0.2rem'>Global controls</div>", unsafe_allow_html=True)
        available = [k for k in SENTIMENT_MODELS if k in (m.get("models") or [])]
        if not available:
            available = ["textblob"]
        dm = default_model(m)
        model = st.selectbox("Sentiment model", available, index=available.index(dm) if dm in available else 0,
                             format_func=lambda k: SENTIMENT_MODELS[k]["short"], key="g_model",
                             help="Which classifier's labels every chart uses. The routed ensemble is the default; "
                                  "the others are there to check robustness. See Methodology.")

        preset = st.radio("Date range", list(RANGE_PRESETS.keys()), index=4, key="g_range", horizontal=False,
                          label_visibility="visible")
        if RANGE_PRESETS[preset] == "custom":
            rng = st.date_input("Custom range", value=(first.date(), last.date()), min_value=first.date(), max_value=last.date(), key="g_custom")
            if isinstance(rng, tuple) and len(rng) == 2:
                start, end = pd.Timestamp(rng[0]), pd.Timestamp(rng[1])
            else:
                start, end = first, last
        elif RANGE_PRESETS[preset] is None:
            start, end = first, last
        else:
            end = last
            start = max(first, end - pd.Timedelta(days=RANGE_PRESETS[preset] - 1))

        cats = st.multiselect("Outlet category", CATEGORY_ORDER, default=[], format_func=category_label, key="g_cats",
                              placeholder="All categories")
        chan_options = chans[chans["category"].isin(cats)]["label"].tolist() if cats else chans["label"].tolist()
        channels = st.multiselect("Channel", chan_options, default=[], key="g_chans", placeholder="All channels")
        cands = st.multiselect("Candidates", CANDIDATE_ORDER, default=[], placeholder="All three candidates",
                               format_func=lambda c: ui.theme.candidate_label(c, "party"), key="g_cands")
        if not cands:
            cands = CANDIDATE_ORDER

        st.markdown(
            f"<div class='nes-caption' style='margin-top:0.6rem'>Data {ui.fmt_date(first)} → {ui.fmt_date(last)}. "
            f"Days after <b>{ui.fmt_date(mature_until)}</b> are still accumulating comments and are excluded from "
            f"index and trend calculations.</div>", unsafe_allow_html=True)
        if st.button("Refresh data", help="Clear caches and re-read the database", key="g_refresh", type="secondary"):
            st.cache_data.clear()
            st.rerun()

    return Filters(model=model, start=start, end=end, categories=cats, channels=channels, candidates=cands,
                   range_label=preset, mature_until=mature_until)
