"""
Reusable UI components. Pure Streamlit + a little HTML against the CSS
classes defined in app/theme.py.
"""

from __future__ import annotations

import html
import math

import pandas as pd
import streamlit as st

from app import theme
from app.data import meta
from pipeline.settings import CANDIDATE_ORDER, CANDIDATES, ELECTION_DAY, SENTIMENT_MODELS


def esc(x) -> str:
    return html.escape("" if x is None else str(x), quote=True)


def fmt_int(x) -> str:
    try:
        return f"{int(x):,}"
    except (TypeError, ValueError):
        return "—"


def fmt_pct(x, digits=0, signed=False) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    return f"{x * 100:+.{digits}f}%" if signed else f"{x * 100:.{digits}f}%"


def fmt_net(x, digits=2) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    return f"{x:+.{digits}f}"


def fmt_date(x, fmt="%d %b %Y") -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    try:
        return pd.Timestamp(x).strftime(fmt)
    except Exception:
        return str(x)


# ------------------------------------------------------------ headers

def page_header(title: str, subtitle: str = "", kicker: str = "Nigeria 2027 · Election Intelligence", show_meta: bool = True):
    m = meta()
    meta_html = ""
    if show_meta:
        days_left = (pd.Timestamp(ELECTION_DAY) - pd.Timestamp.utcnow().tz_localize(None).normalize()).days
        bits = [
            f"<span>Data through <b>{fmt_date(m['last_day'])}</b></span>",
            f"<span><b>{fmt_int(m['comments'])}</b> comments · <b>{fmt_int(m['videos'])}</b> videos · <b>{fmt_int(m['channels'])}</b> channels</span>",
            f"<span>Election day <b>{fmt_date(ELECTION_DAY)}</b> · {days_left} days away</span>" if days_left >= 0 else f"<span>Election day <b>{fmt_date(ELECTION_DAY)}</b></span>",
        ]
        meta_html = f"<div class='nes-meta'>{''.join(bits)}</div>"
    st.markdown(
        f"<div class='nes-kicker'>{esc(kicker)}</div><h1 class='nes-title'>{esc(title)}</h1>"
        + (f"<div class='nes-sub'>{subtitle}</div>" if subtitle else "")
        + meta_html + "<div class='nes-rule'></div>",
        unsafe_allow_html=True,
    )


def section(title: str, desc: str = ""):
    st.markdown(f"<div class='nes-h2'><span class='t'>{esc(title)}</span>"
                + (f"<span class='d'>{esc(desc)}</span>" if desc else "") + "</div>", unsafe_allow_html=True)


def caption(text: str):
    st.markdown(f"<div class='nes-caption'>{text}</div>", unsafe_allow_html=True)


def note(text: str, kind: str = "amber"):
    cls = {"amber": "", "brand": " brand", "crit": " crit"}.get(kind, "")
    st.markdown(f"<div class='nes-note{cls}'>{text}</div>", unsafe_allow_html=True)


def badge(text: str, kind: str = "neu") -> str:
    return f"<span class='nes-badge {kind}'>{esc(text)}</span>"


def candidate_chip(key: str, style: str = "party") -> str:
    color = theme.candidate_color(key)
    return (f"<span class='nes-badge outline'><span class='nes-dot' style='background:{color}'></span>"
            f"{esc(theme.candidate_label(key, style))}</span>")


def sentiment_badge(label: str) -> str:
    kind = {"positive": "pos", "negative": "neg", "neutral": "neu"}.get(label, "neu")
    return badge(label.capitalize() if label else "—", kind)


# --------------------------------------------------------------- tiles

def stat_tile(label: str, value: str, delta: str | None = None, direction: str = "flat", note_text: str | None = None,
              unit: str | None = None):
    delta_html = f"<div class='delta {direction}'>{esc(delta)}</div>" if delta else ""
    note_html = f"<div class='note'>{esc(note_text)}</div>" if note_text else ""
    unit_html = f"<small>{esc(unit)}</small>" if unit else ""
    st.markdown(f"<div class='nes-tile'><div class='lbl'>{esc(label)}</div><div class='val'>{esc(value)}{unit_html}</div>"
                f"{delta_html}{note_html}</div>", unsafe_allow_html=True)


def delta_direction(x: float, good_when_up: bool = True, eps: float = 1e-9) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)) or abs(x) <= eps:
        return "flat"
    up = x > 0
    return "up" if (up == good_when_up) else "down"


def mix_bar(pos: float, neu: float, neg: float, legend: bool = True):
    t = theme.tokens()
    pos, neu, neg = [0 if (v is None or (isinstance(v, float) and math.isnan(v))) else v for v in (pos, neu, neg)]
    bar = (f"<div class='nes-mixbar'>"
           f"<span style='width:{neg * 100:.1f}%;background:{t['neg']}'></span>"
           f"<span style='width:{neu * 100:.1f}%;background:{t['neu']}'></span>"
           f"<span style='width:{pos * 100:.1f}%;background:{t['pos']}'></span></div>")
    leg = (f"<div class='nes-mixlegend'><span><b>{neg * 100:.0f}%</b> negative</span><span><b>{neu * 100:.0f}%</b> neutral</span>"
           f"<span><b>{pos * 100:.0f}%</b> positive</span></div>") if legend else ""
    st.markdown(bar + leg, unsafe_allow_html=True)


def candidate_card_header(key: str):
    info = CANDIDATES[key]
    st.markdown(
        f"<div class='nes-card-head'><span class='nes-swatch' style='background:{theme.candidate_color(key)}'></span>"
        f"<span class='name'>{esc(info['full_name'])}</span><span class='party'>{esc(info['party'])}</span></div>",
        unsafe_allow_html=True)


def kv_rows(rows: list[tuple[str, str]]):
    inner = "".join(f"<div class='k'>{esc(k)}</div><div class='v'>{esc(v)}</div>" for k, v in rows)
    st.markdown(f"<div class='nes-kv'>{inner}</div>", unsafe_allow_html=True)


def prob_bar(p_neg, p_neu, p_pos) -> str:
    t = theme.tokens()
    vals = [0 if (v is None or (isinstance(v, float) and math.isnan(v))) else float(v) for v in (p_neg, p_neu, p_pos)]
    return (f"<span class='nes-probbar' title='negative {vals[0]:.0%} · neutral {vals[1]:.0%} · positive {vals[2]:.0%}'>"
            f"<span style='width:{vals[0] * 100:.1f}%;background:{t['neg']}'></span>"
            f"<span style='width:{vals[1] * 100:.1f}%;background:{t['neu']}'></span>"
            f"<span style='width:{vals[2] * 100:.1f}%;background:{t['pos']}'></span></span>")


# ------------------------------------------------------------ helpers

def model_caption(model: str) -> str:
    info = SENTIMENT_MODELS.get(model, {})
    return info.get("short", model)


def data_table_expander(df: pd.DataFrame, label: str = "View data table", key: str | None = None, **kwargs):
    """Table twin for a chart (accessibility requirement)."""
    with st.expander(label, expanded=False):
        st.dataframe(df, width="stretch", hide_index=True, **kwargs)
        st.download_button("Download CSV", df.to_csv(index=False).encode("utf-8"),
                           file_name=f"{(key or label).lower().replace(' ', '_')}.csv", mime="text/csv",
                           key=f"dl_{key or label}")


def footer():
    m = meta()
    st.markdown(
        f"<div class='nes-footer'>Nigeria 2027 Election Intelligence Platform · open-source, free-tier stack (Streamlit, Plotly, "
        f"Hugging Face transformers, statsmodels, SQLite). Sentiment and topic labels are produced by statistical models and carry "
        f"the limitations described on the Methodology page. Last collection run: {fmt_date(m['last_run']['finished_at']) if m.get('last_run') else '—'} · "
        f"Last enrichment: {fmt_date(m.get('enrichment_last')) if m.get('enrichment_last') else '—'}.</div>",
        unsafe_allow_html=True,
    )


def empty_state(text: str = "No data for this selection. Widen the date range or clear a filter."):
    st.info(text, icon=":material/filter_alt_off:")


def candidates_with_data(summaries: dict, min_n: int = 1) -> list[str]:
    return [c for c in CANDIDATE_ORDER if summaries.get(c, {}).get("n", 0) >= min_n]
