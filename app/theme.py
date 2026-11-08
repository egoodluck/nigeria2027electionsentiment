"""
Design system: colour tokens, typography, Plotly template and global CSS.

Rules this file enforces (see docs/IMPROVEMENT_REPORT.md for the rationale):
  * Candidate colours are assigned ALPHABETICALLY from a colour-blind-validated
    palette (orange / violet / teal). They carry no party meaning and never
    change when a filter removes a candidate.
  * Sentiment is a diverging scale: red (negative) - grey (neutral) - blue
    (positive). Blue/red do not collide with any candidate colour.
  * Status colours (good / warning / critical) are reserved for status.
  * Dark mode is a designed palette: every token has a dark value chosen for
    >= 3:1 contrast on the dark surface, not an automatic inversion.
  * Charts: thin marks, hairline grid, one axis, legend for >= 2 series,
    tooltips everywhere, a table twin behind every chart.
"""

from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

from pipeline.settings import CANDIDATE_ORDER, CANDIDATES

# ----------------------------------------------------------------- tokens

LIGHT = {
    "surface": "#FFFFFF", "surface_alt": "#F3F5F4", "page": "#FFFFFF",
    "ink": "#182019", "ink_2": "#4A524D", "ink_muted": "#7C847F",
    "grid": "#ECEFED", "axis": "#CFD5D1", "border": "#E1E5E2",
    "brand": "#008753", "brand_soft": "#E6F3EC", "brand_text": "#00502F",
    "amber": "#EDA100", "amber_soft": "#FFF4DB", "amber_text": "#7A4F00",
    "good": "#0CA30C", "warning": "#FAB219", "serious": "#EC835A", "critical": "#D03B3B",
    "neg": "#E34948", "neu": "#C3C2B7", "pos": "#2A78D6",
    "neg_soft": "#FBE7E7", "pos_soft": "#E4EFFB", "neu_soft": "#F0EFEC",
    "candidates": {"atiku": "#EB6834", "obi": "#6250D6", "tinubu": "#1BAF7A"},
    "candidates_soft": {"atiku": "#FDEDE6", "obi": "#ECE9FA", "tinubu": "#E3F6EE"},
    "seq": ["#E6F3EC", "#B9DFCB", "#8CCBAA", "#5DB688", "#2F9F68", "#008753", "#006B42", "#004F31"],
    "immature": "rgba(124,132,127,0.10)",
}
DARK = {
    "surface": "#161D19", "surface_alt": "#1E2622", "page": "#0F1412",
    "ink": "#E8ECEA", "ink_2": "#B9C1BC", "ink_muted": "#8E968F",
    "grid": "#222B26", "axis": "#3A443E", "border": "#283029",
    "brand": "#2DB37A", "brand_soft": "#113524", "brand_text": "#9BE3C1",
    "amber": "#FAB219", "amber_soft": "#3A2A05", "amber_text": "#FFD98A",
    "good": "#2DB37A", "warning": "#FAB219", "serious": "#EC835A", "critical": "#E66767",
    "neg": "#E66767", "neu": "#5C635F", "pos": "#3987E5",
    "neg_soft": "#3C1717", "pos_soft": "#13273F", "neu_soft": "#2A302C",
    "candidates": {"atiku": "#D95926", "obi": "#9085E9", "tinubu": "#199E70"},
    "candidates_soft": {"atiku": "#3A1D10", "obi": "#262146", "tinubu": "#0E3426"},
    "seq": ["#0E3F2A", "#0D5436", "#0C6A42", "#13804F", "#2DB37A", "#52C390", "#7AD2A8", "#A6E1C3"],
    "immature": "rgba(142,150,143,0.14)",
}

FONT_STACK = "Inter, system-ui, -apple-system, 'Segoe UI', sans-serif"


def is_dark() -> bool:
    try:
        return (st.context.theme.type or "light") == "dark"
    except Exception:
        return False


def tokens() -> dict:
    return DARK if is_dark() else LIGHT


def candidate_color(key: str) -> str:
    return tokens()["candidates"].get(key, tokens()["ink_muted"])


def candidate_label(key: str, style: str = "full") -> str:
    info = CANDIDATES.get(key)
    if not info:
        return {"_any": "All comments"}.get(key, key)
    if style == "short":
        return info["short"]
    if style == "party":
        return f"{info['short']} ({info['party']})"
    return f"{info['full_name']} ({info['party']})"


SENTIMENT_ORDER = ["negative", "neutral", "positive"]


def sentiment_color(label: str) -> str:
    t = tokens()
    return {"negative": t["neg"], "neutral": t["neu"], "positive": t["pos"]}[label]


# ------------------------------------------------------------ plotly template

def register_template() -> str:
    """Register (once per theme) a Plotly template that matches the tokens and
    return its name."""
    t = tokens()
    name = "nes_dark" if is_dark() else "nes_light"
    if name in pio.templates:
        return name
    layout = go.Layout(
        font=dict(family=FONT_STACK, size=13, color=t["ink_2"]),
        title=dict(font=dict(size=15, color=t["ink"], weight=600), x=0, xanchor="left", y=0.96, yanchor="top", pad=dict(l=0, t=0)),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        colorway=[t["candidates"][c] for c in CANDIDATE_ORDER],
        # 70px top margin: title band (~24px) + legend band (~24px) + breathing room, so a
        # horizontal legend above the plot never collides with the title.
        margin=dict(l=8, r=8, t=70, b=8),
        hoverlabel=dict(bgcolor=t["surface"], bordercolor=t["border"], font=dict(family=FONT_STACK, size=12, color=t["ink"])),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, font=dict(size=12), itemwidth=30,
                    bgcolor="rgba(0,0,0,0)"),
        xaxis=dict(showgrid=False, zeroline=False, linecolor=t["axis"], linewidth=1, ticks="outside", tickcolor=t["axis"],
                   tickfont=dict(size=11, color=t["ink_muted"]), title=dict(font=dict(size=12, color=t["ink_muted"]))),
        yaxis=dict(showgrid=True, gridcolor=t["grid"], gridwidth=1, zeroline=False, linecolor="rgba(0,0,0,0)",
                   tickfont=dict(size=11, color=t["ink_muted"]), title=dict(font=dict(size=12, color=t["ink_muted"]))),
        bargap=0.35,
        hovermode="closest",
    )
    pio.templates[name] = go.layout.Template(layout=layout)
    return name


def apply(fig: go.Figure, height: int | None = None, legend: bool = True) -> go.Figure:
    """Attach the template, fix the height, and size the top margin for the header band.

    Title + horizontal legend live above the plot. The legend is bottom-anchored
    just above the plot and grows upward, so a two-row legend (narrow screens)
    needs ~90px of top margin to stay clear of the title; charts without a
    legend only need room for the title."""
    fig.update_layout(template=register_template(), showlegend=legend)
    if fig.layout.margin.t is None:
        fig.update_layout(margin_t=92 if legend else 48)
    if height:
        fig.update_layout(height=height)
    return fig


PLOTLY_CONFIG = {
    "displayModeBar": False,
    "responsive": True,
    "scrollZoom": False,
    "doubleClick": "reset",
}


# ------------------------------------------------------------------- CSS

def inject_css() -> None:
    t = tokens()
    # NOTE: the string must START with <style> so Markdown treats the whole block
    # as a type-1 HTML block (which runs to </style> regardless of blank lines);
    # a leading <link> tag would open a type-7 block that ends at the first blank
    # line and the rest of the CSS would render as text.
    css = f"""<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
:root {{
  --nes-brand: {t['brand']}; --nes-brand-soft: {t['brand_soft']}; --nes-brand-text: {t['brand_text']};
  --nes-ink: {t['ink']}; --nes-ink-2: {t['ink_2']}; --nes-muted: {t['ink_muted']};
  --nes-border: {t['border']}; --nes-surface: {t['surface']}; --nes-surface-alt: {t['surface_alt']};
  --nes-amber: {t['amber']}; --nes-amber-soft: {t['amber_soft']}; --nes-amber-text: {t['amber_text']};
  --nes-neg: {t['neg']}; --nes-neu: {t['neu']}; --nes-pos: {t['pos']};
  --nes-neg-soft: {t['neg_soft']}; --nes-pos-soft: {t['pos_soft']}; --nes-neu-soft: {t['neu_soft']};
  --nes-good: {t['good']}; --nes-critical: {t['critical']}; --nes-warning: {t['warning']};
}}
html, body, [class*="css"], .stApp {{ font-feature-settings: "cv11", "ss01"; -webkit-font-smoothing: antialiased; }}
.block-container {{ padding-top: 3.4rem; padding-bottom: 3rem; max-width: 1380px; }}
h1, h2, h3 {{ letter-spacing: -0.01em; }}
h1 {{ margin-bottom: 0.1rem; }}
[data-testid="stSidebarNav"] a span, [data-testid="stSidebarNav"] li a {{ font-size: 0.92rem; }}
[data-testid="stMetricValue"] {{ font-variant-numeric: proportional-nums; letter-spacing: -0.01em; }}
[data-testid="stMetricLabel"] p {{ color: var(--nes-muted); font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.04em; font-weight: 600; }}
[data-testid="stDataFrame"] {{ font-variant-numeric: tabular-nums; }}
div[data-testid="stVerticalBlockBorderWrapper"] {{ border-radius: 10px; }}
.stPlotlyChart {{ margin-top: -0.25rem; }}

/* --- platform header --- */
.nes-kicker {{ font-size: 0.72rem; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase; color: var(--nes-brand); margin-bottom: 0.15rem; }}
.nes-title {{ font-size: 1.9rem; font-weight: 700; line-height: 1.15; color: var(--nes-ink); margin: 0; letter-spacing: -0.015em; }}
.nes-sub {{ color: var(--nes-ink-2); font-size: 0.98rem; margin-top: 0.3rem; max-width: 70ch; line-height: 1.5; }}
.nes-meta {{ display: flex; flex-wrap: wrap; gap: 0.4rem 1.1rem; color: var(--nes-muted); font-size: 0.8rem; margin-top: 0.6rem; }}
.nes-meta b {{ color: var(--nes-ink-2); font-weight: 600; }}
.nes-rule {{ height: 3px; width: 56px; background: var(--nes-brand); border-radius: 2px; margin: 0.9rem 0 1.1rem 0; }}

/* --- section headings --- */
.nes-h2 {{ display: flex; align-items: baseline; gap: 0.6rem; margin: 1.4rem 0 0.2rem 0; }}
.nes-h2 .t {{ font-size: 1.22rem; font-weight: 650; color: var(--nes-ink); letter-spacing: -0.01em; }}
.nes-h2 .d {{ font-size: 0.85rem; color: var(--nes-muted); }}
.nes-caption {{ color: var(--nes-muted); font-size: 0.8rem; line-height: 1.45; margin-top: -0.2rem; }}

/* --- badges & chips --- */
.nes-badge {{ display: inline-flex; align-items: center; gap: 0.35rem; padding: 0.15rem 0.55rem; border-radius: 999px; font-size: 0.74rem; font-weight: 600; letter-spacing: 0.02em; border: 1px solid transparent; white-space: nowrap; }}
.nes-badge.brand {{ background: var(--nes-brand-soft); color: var(--nes-brand-text); }}
.nes-badge.amber {{ background: var(--nes-amber-soft); color: var(--nes-amber-text); }}
.nes-badge.neg {{ background: var(--nes-neg-soft); color: var(--nes-neg); }}
.nes-badge.pos {{ background: var(--nes-pos-soft); color: var(--nes-pos); }}
.nes-badge.neu {{ background: var(--nes-neu-soft); color: var(--nes-ink-2); }}
.nes-badge.outline {{ border-color: var(--nes-border); color: var(--nes-ink-2); background: transparent; }}
.nes-dot {{ width: 8px; height: 8px; border-radius: 50%; display: inline-block; }}

/* --- brief card --- */
.nes-brief {{ border-left: 4px solid var(--nes-brand); padding: 0.2rem 0 0.2rem 1rem; }}
.nes-brief p {{ font-size: 1.02rem; line-height: 1.6; color: var(--nes-ink); margin: 0 0 0.6rem 0; }}
.nes-brief p:last-child {{ margin-bottom: 0; }}
.nes-brief .lead {{ font-size: 1.12rem; font-weight: 500; }}
.nes-facts {{ display: flex; flex-wrap: wrap; gap: 0.45rem; margin-top: 0.8rem; }}

/* --- stat tile --- */
.nes-tile {{ padding: 0.1rem 0 0.2rem 0; }}
.nes-tile .lbl {{ font-size: 0.74rem; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; color: var(--nes-muted); }}
.nes-tile .val {{ font-size: 1.85rem; font-weight: 650; color: var(--nes-ink); line-height: 1.15; margin-top: 0.15rem; letter-spacing: -0.02em; }}
.nes-tile .val small {{ font-size: 1rem; font-weight: 500; color: var(--nes-ink-2); margin-left: 0.15rem; }}
.nes-tile .delta {{ font-size: 0.82rem; margin-top: 0.25rem; font-weight: 500; }}
.nes-tile .delta.up {{ color: var(--nes-good); }}
.nes-tile .delta.down {{ color: var(--nes-critical); }}
.nes-tile .delta.flat {{ color: var(--nes-muted); }}
.nes-tile .note {{ font-size: 0.78rem; color: var(--nes-muted); margin-top: 0.2rem; }}

/* --- candidate scorecard --- */
.nes-card-head {{ display: flex; align-items: center; gap: 0.6rem; margin-bottom: 0.35rem; }}
.nes-card-head .name {{ font-size: 1.05rem; font-weight: 650; color: var(--nes-ink); }}
.nes-card-head .party {{ font-size: 0.78rem; color: var(--nes-muted); font-weight: 500; }}
.nes-swatch {{ width: 12px; height: 12px; border-radius: 3px; display: inline-block; flex: none; }}
.nes-mixbar {{ display: flex; height: 8px; border-radius: 4px; overflow: hidden; gap: 2px; margin: 0.35rem 0 0.25rem 0; }}
.nes-mixbar span {{ display: block; height: 100%; }}
.nes-mixlegend {{ display: flex; gap: 0.9rem; font-size: 0.76rem; color: var(--nes-muted); }}
.nes-mixlegend b {{ color: var(--nes-ink-2); font-weight: 600; }}
.nes-kv {{ display: grid; grid-template-columns: 1fr auto; gap: 0.15rem 0.8rem; font-size: 0.86rem; margin-top: 0.5rem; }}
.nes-kv .k {{ color: var(--nes-muted); }}
.nes-kv .v {{ color: var(--nes-ink); font-weight: 600; text-align: right; font-variant-numeric: tabular-nums; }}

/* --- callouts --- */
.nes-note {{ border: 1px solid var(--nes-border); border-left: 4px solid var(--nes-amber); background: var(--nes-amber-soft); color: var(--nes-ink); padding: 0.65rem 0.9rem; border-radius: 8px; font-size: 0.88rem; line-height: 1.5; }}
.nes-note.brand {{ border-left-color: var(--nes-brand); background: var(--nes-brand-soft); }}
.nes-note.crit {{ border-left-color: var(--nes-critical); background: var(--nes-neg-soft); }}
.nes-note b {{ font-weight: 650; }}

/* --- comment card (explorer) --- */
.nes-comment {{ border: 1px solid var(--nes-border); border-radius: 10px; padding: 0.75rem 0.95rem; margin-bottom: 0.6rem; background: var(--nes-surface); }}
.nes-comment .txt {{ font-size: 0.95rem; line-height: 1.55; color: var(--nes-ink); }}
.nes-comment .meta {{ display: flex; flex-wrap: wrap; gap: 0.35rem 0.6rem; margin-top: 0.5rem; align-items: center; font-size: 0.76rem; color: var(--nes-muted); }}
.nes-probbar {{ display: flex; height: 6px; border-radius: 3px; overflow: hidden; gap: 2px; width: 160px; }}
.nes-probbar span {{ display: block; height: 100%; }}
mark.nes-hl {{ background: var(--nes-brand-soft); color: var(--nes-brand-text); padding: 0 0.15rem; border-radius: 3px; font-weight: 600; }}
mark.nes-hl.topic {{ background: var(--nes-amber-soft); color: var(--nes-amber-text); }}

/* --- footer --- */
.nes-footer {{ color: var(--nes-muted); font-size: 0.78rem; border-top: 1px solid var(--nes-border); padding-top: 0.8rem; margin-top: 2.5rem; line-height: 1.5; }}

@media (max-width: 760px) {{
  .block-container {{ padding-top: 3rem; padding-left: 0.9rem; padding-right: 0.9rem; }}
  .nes-h2 {{ flex-direction: column; gap: 0.1rem; align-items: flex-start; }}
  .nes-meta {{ gap: 0.25rem 0.8rem; }}
  .nes-kv {{ font-size: 0.82rem; }}
  .nes-title {{ font-size: 1.45rem; }}
  .nes-tile .val {{ font-size: 1.5rem; }}
  .nes-brief p {{ font-size: 0.96rem; }}
  .nes-brief .lead {{ font-size: 1.02rem; }}
}}
</style>"""
    # Strip blank lines defensively: a blank line inside a Markdown HTML block is harmless for
    # type-1 blocks, but keeping the CSS compact also keeps the DOM payload small.
    css = "\n".join(line for line in css.splitlines() if line.strip())
    st.markdown(css, unsafe_allow_html=True)
