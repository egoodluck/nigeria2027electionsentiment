"""
Plotly chart builders. Every builder returns a go.Figure already styled by
app.theme.apply(); pages render with st.plotly_chart(fig, width="stretch",
config=theme.PLOTLY_CONFIG).

Conventions (from the data-viz method the project follows):
  * one y-axis per chart -- never dual axes;
  * candidate colour follows the entity (fixed map), never the rank;
  * sentiment uses the diverging red/grey/blue scale with a neutral midpoint;
  * thin marks (2px lines, 8px markers), hairline grid, legend for >= 2 series,
    selective direct labels (endpoints), tooltips on everything;
  * cells with fewer than MIN_N_FOR_RATE observations are masked, not coloured.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from app import theme
from app.theme import candidate_color, candidate_label
from pipeline.settings import CANDIDATE_ORDER, MIN_N_FOR_RATE, TOPIC_LABELS

HOVER_DATE = "%{x|%a %d %b %Y}"


def _immature_shape(fig, start, end):
    t = theme.tokens()
    if start is None or end is None or pd.Timestamp(start) > pd.Timestamp(end):
        return
    fig.add_vrect(x0=pd.Timestamp(start), x1=pd.Timestamp(end) + pd.Timedelta(hours=12), fillcolor=t["immature"],
                  line_width=0, layer="below",
                  annotation_text="still accumulating", annotation_position="top left",
                  annotation_font=dict(size=10, color=t["ink_muted"]))


def _zero_line(fig, axis="y"):
    t = theme.tokens()
    if axis == "y":
        fig.add_hline(y=0, line=dict(color=t["axis"], width=1))
    else:
        fig.add_vline(x=0, line=dict(color=t["axis"], width=1))


# ---------------------------------------------------------------- trends

def trend_lines(daily: pd.DataFrame, candidates: list[str], mature_until=None, show_band: bool = True,
                height: int = 380, title: str = "Net sentiment, 7-day rolling") -> go.Figure:
    t = theme.tokens()
    fig = go.Figure()
    last_day = daily["day"].max() if not daily.empty else None
    for cand in [c for c in CANDIDATE_ORDER if c in candidates]:
        sub = daily[daily["candidate"] == cand].sort_values("day")
        if sub.empty:
            continue
        color = candidate_color(cand)
        if show_band and "rolling_lo" in sub:
            rgba = _rgba(color, 0.12)
            fig.add_trace(go.Scatter(x=pd.concat([sub["day"], sub["day"][::-1]]),
                                     y=pd.concat([sub["rolling_hi"], sub["rolling_lo"][::-1]]),
                                     fill="toself", fillcolor=rgba, line=dict(width=0), hoverinfo="skip",
                                     showlegend=False, name=f"{candidate_label(cand, 'short')} 95% band"))
        fig.add_trace(go.Scatter(
            x=sub["day"], y=sub["rolling_net"], mode="lines", name=candidate_label(cand, "party"),
            line=dict(color=color, width=2.2), connectgaps=True,
            customdata=np.stack([sub["rolling_n"], sub["n"]], axis=-1),
            hovertemplate=f"<b>{candidate_label(cand, 'short')}</b><br>{HOVER_DATE}<br>Net sentiment (7d): %{{y:+.2f}}"
                          "<br>Mentions in window: %{customdata[0]:,.0f}<br>Mentions that day: %{customdata[1]:,.0f}<extra></extra>",
        ))
        # endpoint direct label
        end = sub.dropna(subset=["rolling_net"]).tail(1)
        if not end.empty:
            fig.add_annotation(x=end["day"].iloc[0], y=end["rolling_net"].iloc[0], text=f"<b>{candidate_label(cand, 'short')}</b>",
                               showarrow=False, xanchor="left", xshift=6, font=dict(size=11, color=color))
    _zero_line(fig)
    if mature_until is not None and last_day is not None and pd.Timestamp(mature_until) < last_day:
        _immature_shape(fig, pd.Timestamp(mature_until) + pd.Timedelta(days=1), last_day)
    fig.update_layout(title=title, yaxis=dict(title="Net sentiment (−1 to +1)", range=_sym_range(daily["rolling_net"]) if not daily.empty else None,
                                              tickformat="+.1f"),
                      xaxis=dict(title=None), hovermode="x unified", margin=dict(r=70))
    return theme.apply(fig, height)


def volume_bars(daily: pd.DataFrame, candidates: list[str], mature_until=None, height: int = 240,
                title: str = "Daily candidate mentions") -> go.Figure:
    fig = go.Figure()
    last_day = daily["day"].max() if not daily.empty else None
    for cand in [c for c in CANDIDATE_ORDER if c in candidates]:
        sub = daily[daily["candidate"] == cand].sort_values("day")
        if sub.empty:
            continue
        fig.add_trace(go.Bar(x=sub["day"], y=sub["n"], name=candidate_label(cand, "party"), marker_color=candidate_color(cand),
                             marker_line_width=0,
                             hovertemplate=f"<b>{candidate_label(cand, 'short')}</b><br>{HOVER_DATE}<br>Mentions: %{{y:,}}<extra></extra>"))
    if mature_until is not None and last_day is not None and pd.Timestamp(mature_until) < last_day:
        _immature_shape(fig, pd.Timestamp(mature_until) + pd.Timedelta(days=1), last_day)
    fig.update_layout(title=title, barmode="stack", bargap=0.25, yaxis=dict(title="Mentions / day"), hovermode="x unified",
                      legend_traceorder="normal")
    return theme.apply(fig, height)


def sparkline(series: pd.Series, color: str, height: int = 64, baseline: float | None = 0.0) -> go.Figure:
    t = theme.tokens()
    fig = go.Figure()
    s = series.dropna()
    fig.add_trace(go.Scatter(x=s.index, y=s.values, mode="lines", line=dict(color=color, width=2), hoverinfo="skip",
                             fill="tozeroy" if baseline is not None else None, fillcolor=_rgba(color, 0.10)))
    if baseline is not None:
        fig.add_hline(y=baseline, line=dict(color=t["axis"], width=1))
    if not s.empty:
        fig.add_trace(go.Scatter(x=[s.index[-1]], y=[s.values[-1]], mode="markers", marker=dict(color=color, size=7,
                                 line=dict(color=t["surface"], width=2)), hoverinfo="skip"))
    fig.update_layout(template=theme.register_template(), height=height, margin=dict(l=0, r=0, t=4, b=0), showlegend=False,
                      xaxis=dict(visible=False), yaxis=dict(visible=False))
    return fig


# ------------------------------------------------------------- sentiment

def diverging_stacked(summaries: dict, candidates: list[str], height: int | None = None,
                      title: str = "Sentiment mix by candidate") -> go.Figure:
    """Likert-style diverging bar centred on neutral: neutral is split evenly
    across the midline so the negative and positive shares read directly."""
    t = theme.tokens()
    rows = [(c, summaries[c]) for c in CANDIDATE_ORDER if c in candidates and summaries.get(c, {}).get("n", 0) > 0]
    if not rows:
        return theme.apply(go.Figure(), height or 200)
    labels = [f"{candidate_label(c, 'party')}  ·  n={s['n']:,}" for c, s in rows]
    neg = [s["neg_share"] * 100 for _, s in rows]
    neu = [s["neu_share"] * 100 for _, s in rows]
    pos = [s["pos_share"] * 100 for _, s in rows]

    def _lbl(vals, min_pct=9):  # only label segments wide enough to hold the text
        return [f"{v:.0f}%" if v >= min_pct else "" for v in vals]

    fig = go.Figure()
    fig.add_trace(go.Bar(y=labels, x=[-v for v in neg], orientation="h", name="Negative", marker_color=t["neg"],
                         customdata=neg, hovertemplate="Negative: %{customdata:.1f}%<extra></extra>",
                         text=_lbl(neg), textposition="inside", insidetextanchor="middle", textangle=0, constraintext="none",
                         textfont=dict(color="#ffffff", size=11)))
    fig.add_trace(go.Bar(y=labels, x=[-v / 2 for v in neu], orientation="h", name="Neutral", marker_color=t["neu"],
                         customdata=neu, hovertemplate="Neutral: %{customdata:.1f}%<extra></extra>", showlegend=False))
    fig.add_trace(go.Bar(y=labels, x=[v / 2 for v in neu], orientation="h", name="Neutral", marker_color=t["neu"],
                         customdata=neu, hovertemplate="Neutral: %{customdata:.1f}%<extra></extra>",
                         text=_lbl(neu, 16), textposition="inside", insidetextanchor="middle", textangle=0, constraintext="none",
                         textfont=dict(color=t["ink"], size=11)))
    fig.add_trace(go.Bar(y=labels, x=pos, orientation="h", name="Positive", marker_color=t["pos"],
                         customdata=pos, hovertemplate="Positive: %{customdata:.1f}%<extra></extra>",
                         text=_lbl(pos), textposition="inside", insidetextanchor="middle", textangle=0, constraintext="none",
                         textfont=dict(color="#ffffff", size=11)))
    _zero_line(fig, "x")
    fig.update_layout(title=title, barmode="relative", bargap=0.38,
                      xaxis=dict(title="Share of comments", ticksuffix="%", tickvals=[-75, -50, -25, 0, 25, 50, 75],
                                 ticktext=["75%", "50%", "25%", "0", "25%", "50%", "75%"], range=[-100, 100], showgrid=True, gridcolor=t["grid"]),
                      yaxis=dict(autorange="reversed", showgrid=False), legend_traceorder="normal")
    fig.update_traces(marker_line=dict(color=t["surface"], width=2))
    return theme.apply(fig, height or (120 + 62 * len(rows)))


def net_dots(summaries: dict, candidates: list[str], height: int | None = None, title: str = "Net sentiment with 95% interval") -> go.Figure:
    t = theme.tokens()
    rows = [(c, summaries[c]) for c in CANDIDATE_ORDER if c in candidates and summaries.get(c, {}).get("n", 0) > 0]
    fig = go.Figure()
    for c, s in rows:
        lo, hi = s["ci"]
        thin = s["n"] < MIN_N_FOR_RATE
        fig.add_trace(go.Scatter(
            x=[s["net"]], y=[candidate_label(c, "party")], mode="markers+text",
            marker=dict(color=candidate_color(c), size=12 if not thin else 9, symbol="circle" if not thin else "circle-open",
                        line=dict(color=t["surface"], width=2)),
            error_x=dict(type="data", symmetric=False, array=[hi - s["net"]], arrayminus=[s["net"] - lo], color=candidate_color(c), thickness=2, width=0),
            text=[f"{s['net']:+.2f}"], textposition="middle right", textfont=dict(size=11, color=t["ink_2"]),
            name=candidate_label(c, "short"), showlegend=False,
            hovertemplate=f"<b>{candidate_label(c, 'short')}</b><br>Net sentiment: %{{x:+.3f}}<br>95% CI: {lo:+.2f} to {hi:+.2f}<br>n = {s['n']:,}"
                          + ("<br><i>Fewer than %d mentions — interpret with care</i>" % MIN_N_FOR_RATE if thin else "") + "<extra></extra>"))
    _zero_line(fig, "x")
    rng = max(0.25, max((abs(v) for c, s in rows for v in s["ci"] if not math.isnan(v)), default=0.25) * 1.15)
    fig.update_layout(title=title, xaxis=dict(title="Net sentiment (−1 to +1)", range=[-rng, rng], tickformat="+.1f", showgrid=True, gridcolor=t["grid"]),
                      yaxis=dict(autorange="reversed", showgrid=False))
    return theme.apply(fig, height or (110 + 55 * max(len(rows), 1)), legend=False)


def heatmap(values: pd.DataFrame, counts: pd.DataFrame, title: str, zlabel: str = "Net sentiment", diverging: bool = True,
            min_n: int = MIN_N_FOR_RATE, height: int | None = None, xlabels: dict | None = None, ylabels: dict | None = None,
            fmt: str = "+.2f") -> go.Figure:
    t = theme.tokens()
    z = values.to_numpy(dtype=float)
    n = counts.reindex(index=values.index, columns=values.columns).to_numpy(dtype=float)
    masked = np.where(n < min_n, np.nan, z)
    if diverging:
        # Asymmetric range anchored on a grey zero: when every cell is negative the
        # reds still spread across the full ramp instead of collapsing into one shade.
        lo = float(np.nanmin(masked)) if np.isfinite(masked).any() else -0.5
        hi = float(np.nanmax(masked)) if np.isfinite(masked).any() else 0.5
        zmin = min(-0.05, math.floor(lo * 20) / 20)
        zmax = max(0.05, math.ceil(hi * 20) / 20)
        colorscale = [[0, t["neg"]], [0.5, t["neu_soft"]], [1, t["pos"]]]
        zmid = 0
    else:
        zmin, zmax, zmid = 0, float(np.nanmax(masked)) if np.isfinite(masked).any() else 1, None
        colorscale = [[i / (len(t["seq"]) - 1), c] for i, c in enumerate(t["seq"])]
    xl = [xlabels.get(c, c) if xlabels else c for c in values.columns]
    yl = [ylabels.get(r, r) if ylabels else r for r in values.index]
    text = [[("" if np.isnan(masked[i, j]) else format(masked[i, j], fmt)) if n[i, j] >= min_n else f"n<{min_n}"
             for j in range(masked.shape[1])] for i in range(masked.shape[0])]
    fig = go.Figure(go.Heatmap(
        z=masked, x=xl, y=yl, colorscale=colorscale, zmin=zmin, zmax=zmax, zmid=zmid, xgap=3, ygap=3,
        text=text, texttemplate="%{text}", textfont=dict(size=11),
        customdata=n, hoverongaps=False,
        hovertemplate="%{y} × %{x}<br>" + zlabel + ": %{z:" + fmt + "}<br>n = %{customdata:,.0f}<extra></extra>",
        colorbar=dict(title=dict(text=zlabel, side="right"), thickness=10, len=0.8, outlinewidth=0, tickfont=dict(size=10)),
    ))
    fig.update_layout(title=title, xaxis=dict(side="top", showgrid=False, tickfont=dict(size=11)), yaxis=dict(showgrid=False, autorange="reversed"),
                      plot_bgcolor=t["surface_alt"], margin=dict(t=74))
    return theme.apply(fig, height or (110 + 42 * len(yl)), legend=False)


def confidence_hist(hist: pd.DataFrame, height: int = 260, title: str = "Model confidence by label") -> go.Figure:
    t = theme.tokens()
    fig = go.Figure()
    for label in ["negative", "neutral", "positive"]:
        sub = hist[hist["label"] == label]
        fig.add_trace(go.Bar(x=sub["bin"], y=sub["n"], name=label.capitalize(), marker_color=theme.sentiment_color(label),
                             hovertemplate=f"{label.capitalize()}<br>confidence %{{x:.2f}}–%{{x:.2f}}+0.05<br>%{{y:,}} comments<extra></extra>"))
    fig.update_layout(title=title, barmode="stack", bargap=0.1, xaxis=dict(title="Top-class probability", tickformat=".1f", range=[0.3, 1.0]),
                      yaxis=dict(title="Comments"))
    fig.update_traces(marker_line=dict(color=t["surface"], width=1))
    return theme.apply(fig, height)


# ------------------------------------------------------------------ ranks

def ranked_bars(df: pd.DataFrame, value: str, label: str, title: str, color: str | None = None, colors: list | None = None,
                value_fmt: str = ",.0f", suffix: str = "", height: int | None = None, hover_extra: str | None = None,
                customdata=None, xaxis_title: str | None = None, tick_fmt: str | None = None, text_inside: bool = False) -> go.Figure:
    t = theme.tokens()
    d = df.sort_values(value, ascending=True)
    if tick_fmt is None and value_fmt.endswith("%"):
        tick_fmt = ".0%"
    fig = go.Figure(go.Bar(
        x=d[value], y=d[label], orientation="h",
        marker_color=colors if colors is not None else (color or t["brand"]), marker_line_width=0,
        text=[format(v, value_fmt) + suffix for v in d[value]],
        textposition="inside" if text_inside else "outside", insidetextanchor="end" if text_inside else None,
        textfont=dict(size=11, color="#ffffff" if text_inside else t["ink_2"]),
        cliponaxis=False, customdata=customdata if customdata is not None else d[value],
        hovertemplate="<b>%{y}</b><br>" + (hover_extra or ("%{x:" + value_fmt + "}" + suffix)) + "<extra></extra>",
    ))
    fig.update_layout(title=title, xaxis=dict(title=xaxis_title, showgrid=True, gridcolor=t["grid"], tickformat=tick_fmt),
                      yaxis=dict(showgrid=False), bargap=0.3, margin=dict(r=48))
    return theme.apply(fig, height or (80 + 30 * len(d)), legend=False)


def keyword_bars(df: pd.DataFrame, polarity: str, title: str, height: int | None = None, top: int = 12) -> go.Figure:
    t = theme.tokens()
    color = {"positive": t["pos"], "negative": t["neg"], "emerging": t["amber"]}[polarity]
    d = df[df["polarity"] == polarity].sort_values("rank").head(top).sort_values("zscore", ascending=True)
    if d.empty:
        return theme.apply(go.Figure(), 120, legend=False)
    hover = ("<b>%{y}</b><br>weighted log-odds z = %{x:.2f}<br>" +
             ("in positive comments: %{customdata[0]:,} · in negative: %{customdata[1]:,}" if polarity == "positive" else
              "in negative comments: %{customdata[0]:,} · in positive: %{customdata[1]:,}" if polarity == "negative" else
              "last 7 days: %{customdata[0]:,} · previous 4 weeks: %{customdata[1]:,}") + "<extra></extra>")
    fig = go.Figure(go.Bar(x=d["zscore"], y=d["term"], orientation="h", marker_color=color, marker_line_width=0,
                           customdata=np.stack([d["count_a"], d["count_b"]], axis=-1), hovertemplate=hover,
                           text=[f"{z:.1f}" for z in d["zscore"]], textposition="outside", textfont=dict(size=10, color=t["ink_muted"]), cliponaxis=False))
    fig.update_layout(title=title, xaxis=dict(title="z-score", showgrid=True, gridcolor=t["grid"], rangemode="tozero"), yaxis=dict(showgrid=False, tickfont=dict(size=12)),
                      bargap=0.3, margin=dict(r=34))
    return theme.apply(fig, height or (70 + 26 * len(d)), legend=False)


# ------------------------------------------------------------------ topics

def topic_candidate_heatmap(ft: pd.DataFrame, start, end, min_n: int = MIN_N_FOR_RATE, metric: str = "net") -> go.Figure:
    sub = ft[(ft["day"] >= pd.Timestamp(start)) & (ft["day"] <= pd.Timestamp(end)) & (ft["candidate"].isin(CANDIDATE_ORDER)) & (ft["topic"] != "other")]
    if sub.empty:
        return theme.apply(go.Figure(), 200)
    g = sub.groupby(["topic", "candidate"]).agg(n=("n", "sum"), n_pos=("n_pos", "sum"), n_neg=("n_neg", "sum"))
    g["net"] = (g["n_pos"] - g["n_neg"]) / g["n"]
    order = sub.groupby("topic")["n"].sum().sort_values(ascending=False).index.tolist()
    if metric == "net":
        values = g["net"].unstack("candidate").reindex(index=order, columns=CANDIDATE_ORDER)
        counts = g["n"].unstack("candidate").reindex(index=order, columns=CANDIDATE_ORDER).fillna(0)
        return heatmap(values, counts, "Net sentiment by issue × candidate", zlabel="Net sentiment",
                       xlabels={c: candidate_label(c, "short") for c in CANDIDATE_ORDER}, ylabels=TOPIC_LABELS, min_n=min_n)
    # share of each candidate's mentions that touch the topic
    tot = sub.groupby("candidate")["n"].sum()
    share = (g["n"].unstack("candidate") / tot).reindex(index=order, columns=CANDIDATE_ORDER) * 100
    counts = g["n"].unstack("candidate").reindex(index=order, columns=CANDIDATE_ORDER).fillna(0)
    return heatmap(share, counts, "Share of each candidate's mentions touching the issue", zlabel="% of mentions", diverging=False,
                   xlabels={c: candidate_label(c, "short") for c in CANDIDATE_ORDER}, ylabels=TOPIC_LABELS, min_n=1, fmt=".0f")


def topic_trend(ft: pd.DataFrame, topics: list[str], candidate: str, mature_until=None, height: int = 340) -> go.Figure:
    """Weekly share of topic-tagged comments for selected topics (one hue per topic from the categorical palette)."""
    t = theme.tokens()
    palette = ["#2A78D6", "#EB6834", "#1BAF7A", "#EDA100", "#E87BA4", "#008300", "#6250D6", "#E34948"] if not theme.is_dark() else \
              ["#3987E5", "#D95926", "#199E70", "#C98500", "#D55181", "#008300", "#9085E9", "#E66767"]
    sub = ft[(ft["candidate"] == candidate) & (ft["topic"] != "other")].copy()
    if sub.empty:
        return theme.apply(go.Figure(), height)
    sub["week"] = sub["day"].dt.to_period("W-SUN").dt.start_time
    tot = sub.groupby("week")["n"].sum()
    fig = go.Figure()
    for i, topic in enumerate(topics[:8]):
        s = sub[sub["topic"] == topic].groupby("week")["n"].sum().reindex(tot.index).fillna(0)
        share = (s / tot * 100)
        fig.add_trace(go.Scatter(x=share.index, y=share.values, mode="lines+markers", name=TOPIC_LABELS.get(topic, topic),
                                 line=dict(color=palette[i % len(palette)], width=2), marker=dict(size=6),
                                 hovertemplate="<b>" + TOPIC_LABELS.get(topic, topic) + "</b><br>week of %{x|%d %b}<br>%{y:.1f}% of topic-tagged comments<extra></extra>"))
    if mature_until is not None:
        last = sub["week"].max()
        if pd.Timestamp(mature_until) < last + pd.Timedelta(days=6):
            _immature_shape(fig, pd.Timestamp(mature_until), last + pd.Timedelta(days=6))
    fig.update_layout(title="Issue prevalence by week", yaxis=dict(title="% of topic-tagged comments", ticksuffix="%", rangemode="tozero"),
                      hovermode="x unified")
    return theme.apply(fig, height)


# --------------------------------------------------------------- indices

def index_bars(df: pd.DataFrame, value: str, title: str, height: int | None = None, mid: float | None = 50) -> go.Figure:
    t = theme.tokens()
    d = df.sort_values(value, ascending=True)
    fig = go.Figure(go.Bar(x=d[value], y=[candidate_label(c, "party") for c in d["candidate"]], orientation="h",
                           marker_color=[candidate_color(c) for c in d["candidate"]], marker_line_width=0,
                           text=[f"{v:.0f}" for v in d[value]], textposition="outside", textfont=dict(size=12, color=t["ink"]), cliponaxis=False,
                           hovertemplate="<b>%{y}</b><br>" + title + ": %{x:.1f}<extra></extra>"))
    if mid is not None:
        fig.add_vline(x=mid, line=dict(color=t["axis"], width=1, dash="dot"), annotation_text="neutral", annotation_position="top",
                      annotation_font=dict(size=10, color=t["ink_muted"]))
    fig.update_layout(title=title, xaxis=dict(range=[0, 100], showgrid=True, gridcolor=t["grid"]), yaxis=dict(showgrid=False), bargap=0.35,
                      margin=dict(r=40))
    return theme.apply(fig, height or (90 + 48 * len(d)), legend=False)


def component_bars(mom: pd.DataFrame, height: int = 300) -> go.Figure:
    """Momentum components per candidate (0-1 each), grouped."""
    t = theme.tokens()
    comps = [("c_sentiment", "Sentiment<br>trend · 40%"), ("c_engagement", "Engagement<br>growth · 30%"),
             ("c_discussion", "Discussion<br>growth · 20%"), ("c_consistency", "Consistency<br>· 10%")]
    fig = go.Figure()
    for _, r in mom.iterrows():
        fig.add_trace(go.Bar(x=[lab for _, lab in comps], y=[r[k] for k, _ in comps], name=candidate_label(r["candidate"], "party"),
                             marker_color=candidate_color(r["candidate"]), marker_line_width=0,
                             hovertemplate="<b>" + candidate_label(r["candidate"], "short") + "</b><br>%{x}: %{y:.2f}<extra></extra>"))
    fig.add_hline(y=0.5, line=dict(color=t["axis"], width=1, dash="dot"))
    fig.update_layout(title="Momentum components (0.5 = no change)", barmode="group", bargap=0.3, bargroupgap=0.08,
                      yaxis=dict(range=[0, 1], tickformat=".1f"), xaxis=dict(tickangle=0))
    return theme.apply(fig, height)


def trajectory_lines(traj: pd.DataFrame, metric: str, title: str, height: int = 320, mid: float | None = 50) -> go.Figure:
    t = theme.tokens()
    fig = go.Figure()
    for cand in CANDIDATE_ORDER:
        sub = traj[traj["candidate"] == cand].sort_values("anchor")
        if sub.empty:
            continue
        fig.add_trace(go.Scatter(x=sub["anchor"], y=sub[metric], mode="lines+markers", name=candidate_label(cand, "party"),
                                 line=dict(color=candidate_color(cand), width=2.2), marker=dict(size=7, line=dict(color=t["surface"], width=2)),
                                 hovertemplate=f"<b>{candidate_label(cand, 'short')}</b><br>week ending %{{x|%d %b}}<br>{title}: %{{y:.1f}}<extra></extra>"))
        last = sub.tail(1)
        fig.add_annotation(x=last["anchor"].iloc[0], y=last[metric].iloc[0], text=f"<b>{candidate_label(cand, 'short')}</b>", showarrow=False,
                           xanchor="left", xshift=6, font=dict(size=11, color=candidate_color(cand)))
    if mid is not None:
        fig.add_hline(y=mid, line=dict(color=t["axis"], width=1, dash="dot"))
    fig.update_layout(title=title, yaxis=dict(range=[0, 100]), hovermode="x unified", margin=dict(r=70))
    return theme.apply(fig, height)


# --------------------------------------------------------------- forecast

def forecast_chart(history: pd.DataFrame, fc: pd.DataFrame, cand: str, metric: str, horizon: int, height: int = 360) -> go.Figure:
    t = theme.tokens()
    color = candidate_color(cand) if cand in CANDIDATE_ORDER else t["brand"]
    label = candidate_label(cand, "party") if cand in CANDIDATE_ORDER else "All comments"
    ycol = "rolling_net" if metric == "net_sentiment" else "rolling_vol"
    ytitle = "Net sentiment (7-day rolling)" if metric == "net_sentiment" else "Mentions per day (7-day mean)"
    fig = go.Figure()
    h = history.sort_values("day")
    fig.add_trace(go.Scatter(x=h["day"], y=h[ycol], mode="lines", name="Observed", line=dict(color=color, width=2.2),
                             hovertemplate=HOVER_DATE + "<br>Observed: %{y:.2f}<extra></extra>"))
    f = fc.sort_values("day").head(horizon)
    if not f.empty:
        # stitch to the last observed point
        last = h.dropna(subset=[ycol]).tail(1)
        if not last.empty:
            f = pd.concat([pd.DataFrame({"day": last["day"].values, "yhat": last[ycol].values, "lo80": last[ycol].values, "hi80": last[ycol].values,
                                         "lo95": last[ycol].values, "hi95": last[ycol].values}), f], ignore_index=True)
        fig.add_trace(go.Scatter(x=pd.concat([f["day"], f["day"][::-1]]), y=pd.concat([f["hi95"], f["lo95"][::-1]]), fill="toself",
                                 fillcolor=_rgba(color, 0.10), line=dict(width=0), name="95% interval", hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=pd.concat([f["day"], f["day"][::-1]]), y=pd.concat([f["hi80"], f["lo80"][::-1]]), fill="toself",
                                 fillcolor=_rgba(color, 0.20), line=dict(width=0), name="80% interval", hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=f["day"], y=f["yhat"], mode="lines", name="Projection", line=dict(color=color, width=2, dash="dash"),
                                 customdata=np.stack([f["lo80"], f["hi80"], f["lo95"], f["hi95"]], axis=-1),
                                 hovertemplate=HOVER_DATE + "<br>Projection: %{y:.2f}<br>80%: %{customdata[0]:.2f} to %{customdata[1]:.2f}"
                                               "<br>95%: %{customdata[2]:.2f} to %{customdata[3]:.2f}<extra></extra>"))
        fig.add_vline(x=last["day"].iloc[0] if not last.empty else f["day"].iloc[0], line=dict(color=t["axis"], width=1))
        fig.add_annotation(x=f["day"].iloc[-1], y=f["yhat"].iloc[-1], text="projection", showarrow=False, xanchor="left", xshift=6,
                           font=dict(size=10, color=t["ink_muted"]))
    if metric == "net_sentiment":
        _zero_line(fig)
    fig.update_layout(title=f"{label} — {ytitle}", yaxis=dict(title=ytitle, tickformat="+.1f" if metric == "net_sentiment" else ",.0f"),
                      hovermode="x unified", margin=dict(r=70))
    return theme.apply(fig, height)


# --------------------------------------------------------------- geography

def choropleth(df: pd.DataFrame, geojson: dict, value: str, title: str, zlabel: str, diverging: bool, min_n: int = MIN_N_FOR_RATE,
               height: int = 520) -> go.Figure:
    t = theme.tokens()
    d = df.copy()
    d["shown"] = np.where(d["n"] >= min_n, d[value], np.nan)
    if diverging:
        lo = float(np.nanmin(d["shown"])) if d["shown"].notna().any() else -0.5
        hi = float(np.nanmax(d["shown"])) if d["shown"].notna().any() else 0.5
        zmin, zmax, zmid = min(-0.05, math.floor(lo * 20) / 20), max(0.05, math.ceil(hi * 20) / 20), 0
        colorscale = [[0, t["neg"]], [0.5, t["neu_soft"]], [1, t["pos"]]]
    else:
        colorscale = [[i / (len(t["seq"]) - 1), c] for i, c in enumerate(t["seq"])]
        zmin, zmax, zmid = 0, float(np.nanmax(d["shown"])) if d["shown"].notna().any() else 1, None
    fig = go.Figure(go.Choropleth(
        geojson=geojson, locations=d["state"], featureidkey="id", z=d["shown"], colorscale=colorscale, zmin=zmin, zmax=zmax, zmid=zmid,
        marker_line_color=t["surface"], marker_line_width=0.8,
        customdata=np.stack([d["n"], d["n_pos"], d["n_neg"], d[value]], axis=-1),
        hovertemplate="<b>%{location}</b><br>" + zlabel + ": %{customdata[3]:.2f}<br>mentions: %{customdata[0]:,}<br>positive %{customdata[1]:,} · negative %{customdata[2]:,}<extra></extra>",
        colorbar=dict(title=dict(text=zlabel), thickness=10, len=0.6, outlinewidth=0, tickfont=dict(size=10)),
    ))
    # states below the threshold: outline only
    thin = d[d["n"] < min_n]
    if not thin.empty:
        fig.add_trace(go.Choropleth(geojson=geojson, locations=thin["state"], featureidkey="id", z=[0] * len(thin),
                                    colorscale=[[0, t["surface_alt"]], [1, t["surface_alt"]]], showscale=False,
                                    marker_line_color=t["axis"], marker_line_width=0.8, customdata=thin["n"],
                                    hovertemplate="<b>%{location}</b><br>mentions: %{customdata:,} (below the " + str(min_n) + " threshold)<extra></extra>"))
    # Direct labels for the most-mentioned states (centroid = mean of exterior-ring vertices).
    labelled = d[d["n"] >= max(min_n, 1)].sort_values("n", ascending=False).head(12)
    if not labelled.empty and geojson:
        cents = {}
        for feat in geojson.get("features", []):
            geom = feat["geometry"]
            ring = geom["coordinates"][0] if geom["type"] == "Polygon" else max(geom["coordinates"], key=lambda p: len(p[0]))[0]
            xs, ys = zip(*ring)
            cents[feat["id"]] = (sum(xs) / len(xs), sum(ys) / len(ys))
        pts = [(cents[s][0], cents[s][1], s) for s in labelled["state"] if s in cents]
        if pts:
            fig.add_trace(go.Scattergeo(lon=[p[0] for p in pts], lat=[p[1] for p in pts], text=[p[2] for p in pts], mode="text",
                                        textfont=dict(size=10, color=t["ink"]), hoverinfo="skip", showlegend=False))
    fig.update_geos(fitbounds="locations", visible=False, bgcolor="rgba(0,0,0,0)", projection_type="mercator",
                    domain=dict(x=[0, 1], y=[0, 1]))
    fig.update_layout(title=title, margin=dict(l=0, r=0, t=40, b=0), geo=dict(bgcolor="rgba(0,0,0,0)"))
    return theme.apply(fig, height, legend=False)


# ----------------------------------------------------------- authenticity

def risk_histogram(hist: pd.DataFrame, height: int = 240) -> go.Figure:
    t = theme.tokens()
    d = hist[hist["risk"] > 0]
    colors = [t["critical"] if r >= 0.5 else t["warning"] if r >= 0.3 else t["ink_muted"] for r in d["risk"]]
    fig = go.Figure(go.Bar(x=d["risk"], y=d["n"], marker_color=colors, marker_line_width=0, width=0.08,
                           hovertemplate="risk score %{x:.1f}<br>%{y:,} comments<extra></extra>"))
    fig.update_layout(title="Distribution of non-zero authenticity risk scores", xaxis=dict(title="Risk score", range=[0, 1.05], tickformat=".1f"),
                      yaxis=dict(title="Comments (log)", type="log", dtick=1, tickvals=[1, 10, 100, 1000, 10000], minor=dict(showgrid=False)))
    return theme.apply(fig, height, legend=False)


def burst_chart(daily_all: pd.DataFrame, height: int = 280) -> go.Figure:
    """Daily comment volume with a robust z-score; days above z=2.5 are bursts."""
    t = theme.tokens()
    d = daily_all.sort_values("day").copy()
    med = d["n"].rolling(14, min_periods=5, center=False).median()
    mad = (d["n"] - med).abs().rolling(14, min_periods=5).median()
    d["z"] = (d["n"] - med) / (1.4826 * mad.replace(0, np.nan))
    burst = d["z"] >= 2.5
    fig = go.Figure()
    fig.add_trace(go.Bar(x=d["day"], y=d["n"], marker_color=np.where(burst, t["warning"], _rgba(t["ink_muted"], 0.55)), marker_line_width=0,
                         name="Comments / day", customdata=d["z"],
                         hovertemplate=HOVER_DATE + "<br>%{y:,} comments<br>robust z = %{customdata:.1f}<extra></extra>"))
    fig.add_trace(go.Scatter(x=d["day"], y=med, mode="lines", name="14-day median", line=dict(color=t["ink_2"], width=1.5), hoverinfo="skip"))
    fig.update_layout(title="Daily comment volume — burst days highlighted (robust z ≥ 2.5)", yaxis=dict(title="Comments"), hovermode="x unified")
    return theme.apply(fig, height)


# --------------------------------------------------------------- methodology

def agreement_matrix(df: pd.DataFrame, labels: dict, height: int = 300) -> go.Figure:
    t = theme.tokens()
    models = sorted(set(df["model_a"]) | set(df["model_b"]), key=lambda m: list(labels).index(m) if m in labels else 99)
    mat = pd.DataFrame(np.nan, index=models, columns=models)
    kap = mat.copy()
    for _, r in df.iterrows():
        mat.loc[r["model_a"], r["model_b"]] = mat.loc[r["model_b"], r["model_a"]] = r["agreement"]
        kap.loc[r["model_a"], r["model_b"]] = kap.loc[r["model_b"], r["model_a"]] = r["kappa"]
    for m in models:
        mat.loc[m, m] = 1.0
        kap.loc[m, m] = 1.0
    text = [[f"{mat.iloc[i, j]:.0%}  ·  κ {kap.iloc[i, j]:.2f}" if not np.isnan(mat.iloc[i, j]) else ""
             for j in range(len(models))] for i in range(len(models))]
    fig = go.Figure(go.Heatmap(z=mat.to_numpy(), x=[labels.get(m, m) for m in models], y=[labels.get(m, m) for m in models],
                               colorscale=[[0, t["surface_alt"]], [1, t["brand"]]], zmin=0.3, zmax=1, xgap=3, ygap=3,
                               text=text, texttemplate="%{text}", customdata=kap.to_numpy(),
                               hovertemplate="%{y} vs %{x}<br>agreement %{z:.1%}<br>Cohen's κ %{customdata:.2f}<extra></extra>", showscale=False))
    fig.update_layout(title="Label agreement between models (κ = Cohen's kappa)", xaxis=dict(side="top", showgrid=False), yaxis=dict(autorange="reversed", showgrid=False),
                      margin=dict(t=74))
    return theme.apply(fig, height, legend=False)


def runs_chart(runs: pd.DataFrame, height: int = 240) -> go.Figure:
    t = theme.tokens()
    d = runs.copy()
    d["finished_at"] = pd.to_datetime(d["finished_at"], utc=True, errors="coerce")
    ycol = "new_comments" if "new_comments" in d else "comments_found"
    fig = go.Figure(go.Bar(x=d["finished_at"], y=d[ycol], marker_color=t["brand"], marker_line_width=0, width=36e5 * 20,
                           customdata=np.stack([d["videos_found"], d["quota_units_used"], d["comments_found"]], axis=-1),
                           hovertemplate="%{x|%d %b %Y %H:%M}<br>new comments stored: %{y:,}<br>rows fetched (incl. already stored): %{customdata[2]:,}"
                                         "<br>videos found: %{customdata[0]:,}<br>quota units: %{customdata[1]:,}<extra></extra>"))
    fig.update_layout(title="Collection runs — new comments stored per run", yaxis=dict(title="New comments"), xaxis=dict(title=None))
    return theme.apply(fig, height, legend=False)


# ---------------------------------------------------------------- helpers

def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def _sym_range(series: pd.Series, floor: float = 0.3):
    s = series.dropna()
    if s.empty:
        return [-floor, floor]
    m = max(floor, float(s.abs().max()) * 1.15)
    return [-min(1.05, m), min(1.05, m)]
