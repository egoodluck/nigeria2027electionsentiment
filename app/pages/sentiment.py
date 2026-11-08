"""Sentiment deep dive: mix, net scores with intervals, trends, outlet categories, model confidence."""

import numpy as np
import pandas as pd
import streamlit as st

from app import analytics as an
from app import charts, components as ui, theme
from app.data import category_label, db_signature, load_confidence_hist, load_fact_daily, meta
from app.state import sidebar_controls
from pipeline.settings import CANDIDATE_ORDER, MIN_N_FOR_RATE, SENTIMENT_MODELS

f = sidebar_controls()
m = meta()
sig = db_signature()
ui.page_header("Sentiment", "How comments that mention each candidate are classified, how certain the classifier is, and how the picture "
               "differs by outlet type. Net sentiment = (positive − negative) ÷ all mentions, from −1 to +1.")

fd_all = load_fact_daily(sig, f.model)
if fd_all.empty:
    ui.note("No enrichment data available. Run <code>python -m pipeline.enrich</code>.", "crit")
    st.stop()
fd = an.filter_facts(fd_all, f.start, f.end, f.categories, f.channels)
cands_fd = an.candidates_only(fd)
summ = {c: an.summarize(cands_fd[cands_fd["candidate"] == c]) for c in CANDIDATE_ORDER}
cands = [c for c in f.candidates if summ[c]["n"] > 0]
if not cands:
    ui.empty_state()
    st.stop()

ui.caption(f"Selection: {f.describe()}")

# ----------------------------------------------------------------- overview
ui.section("Sentiment overview", "share of mentions by label, and net score with 95% confidence interval")
c1, c2 = st.columns([1.3, 1])
with c1:
    st.plotly_chart(charts.diverging_stacked(summ, cands), width="stretch", config=theme.PLOTLY_CONFIG, key="se_mix")
with c2:
    st.plotly_chart(charts.net_dots(summ, cands), width="stretch", config=theme.PLOTLY_CONFIG, key="se_net")

pc = an.compare_periods(fd, f.analysis_end, f.period_days)
cols = st.columns(len(cands))
for col, c in zip(cols, cands):
    s, cur, prev = summ[c], pc.current[c], pc.previous[c]
    with col, st.container(border=True):
        ui.candidate_card_header(c)
        d_net = cur["net"] - prev["net"] if not (np.isnan(cur["net"]) or np.isnan(prev["net"])) else np.nan
        trend = "improving" if d_net > 0.02 else "deteriorating" if d_net < -0.02 else "stable"
        a, b = st.columns(2)
        with a:
            ui.stat_tile("Positive", ui.fmt_pct(s["pos_share"]), f"{ui.fmt_int(s['n_pos'])} comments", "flat")
            ui.stat_tile("Negative", ui.fmt_pct(s["neg_share"]), f"{ui.fmt_int(s['n_neg'])} comments", "flat")
        with b:
            ui.stat_tile("Neutral", ui.fmt_pct(s["neu_share"]), f"{ui.fmt_int(s['n_neu'])} comments", "flat")
            ui.stat_tile("Net score", ui.fmt_net(s["net"]), f"{trend} · {d_net * 100:+.0f} pts vs prior {f.period_days}d" if not np.isnan(d_net) else "no prior-period data",
                         ui.delta_direction(d_net))
        ui.caption(f"Trend direction compares the last {f.period_days} mature days with the {f.period_days} before them. "
                   f"Mean classifier confidence {ui.fmt_pct(s['conf'])}.")

tbl = pd.DataFrame([{"Candidate": theme.candidate_label(c, "party"), "Mentions": summ[c]["n"], "Positive %": round(summ[c]["pos_share"] * 100, 1),
                     "Neutral %": round(summ[c]["neu_share"] * 100, 1), "Negative %": round(summ[c]["neg_share"] * 100, 1),
                     "Net": round(summ[c]["net"], 3), "CI low": round(summ[c]["ci"][0], 3), "CI high": round(summ[c]["ci"][1], 3),
                     "Likes": summ[c]["likes"]} for c in cands])
ui.data_table_expander(tbl, "View sentiment table", key="se_tbl")

# ------------------------------------------------------------------- trend
ui.section("Trend", "weekly and daily views; shaded days are still accumulating comments")
view = st.segmented_control("Granularity", ["Daily (7-day rolling)", "Weekly"], default="Daily (7-day rolling)", key="se_gran") or "Daily (7-day rolling)"
daily = an.daily_series(cands_fd, window=7, min_n=1)
if view.startswith("Daily"):
    st.plotly_chart(charts.trend_lines(daily, cands, f.mature_until, show_band=True), width="stretch", config=theme.PLOTLY_CONFIG, key="se_trend")
else:
    wk = an.weekly_series(cands_fd)
    t = theme.tokens()
    import plotly.graph_objects as go
    fig = go.Figure()
    for c in cands:
        sub = wk[wk["candidate"] == c]
        thin = sub["n"] < MIN_N_FOR_RATE
        fig.add_trace(go.Scatter(x=sub["week"], y=sub["net"], mode="lines+markers", name=theme.candidate_label(c, "party"),
                                 line=dict(color=theme.candidate_color(c), width=2.2),
                                 marker=dict(size=8, symbol=np.where(thin, "circle-open", "circle"), line=dict(color=t["surface"], width=2)),
                                 customdata=sub["n"], hovertemplate=f"<b>{theme.candidate_label(c, 'short')}</b><br>week of %{{x|%d %b}}<br>net %{{y:+.2f}}<br>n = %{{customdata:,}}<extra></extra>"))
    fig.add_hline(y=0, line=dict(color=t["axis"], width=1))
    fig.update_layout(title="Weekly net sentiment (open markers: fewer than %d mentions)" % MIN_N_FOR_RATE, yaxis=dict(title="Net sentiment", tickformat="+.1f"), hovermode="x unified")
    st.plotly_chart(theme.apply(fig, 380), width="stretch", config=theme.PLOTLY_CONFIG, key="se_weekly")
st.plotly_chart(charts.volume_bars(daily, cands, f.mature_until), width="stretch", config=theme.PLOTLY_CONFIG, key="se_vol")

# -------------------------------------------------------------- by outlet
ui.section("By outlet category", f"cells with fewer than {MIN_N_FOR_RATE} mentions are masked")
cat = cands_fd[cands_fd["candidate"].isin(cands)].groupby(["category", "candidate"]).agg(n=("n", "sum"), n_pos=("n_pos", "sum"), n_neg=("n_neg", "sum"))
if cat.empty:
    ui.empty_state()
else:
    cat["net"] = (cat["n_pos"] - cat["n_neg"]) / cat["n"]
    order = cat.groupby("category")["n"].sum().sort_values(ascending=False).index.tolist()
    values = cat["net"].unstack("candidate").reindex(index=order, columns=cands)
    counts = cat["n"].unstack("candidate").reindex(index=order, columns=cands).fillna(0)
    st.plotly_chart(charts.heatmap(values, counts, "Net sentiment by outlet category × candidate",
                                   xlabels={c: theme.candidate_label(c, "short") for c in cands},
                                   ylabels={k: category_label(k) for k in order}), width="stretch", config=theme.PLOTLY_CONFIG, key="se_cat_heat")
    chan = cands_fd[cands_fd["candidate"].isin(cands)].groupby(["channel", "category", "candidate"]).agg(n=("n", "sum"), n_pos=("n_pos", "sum"), n_neg=("n_neg", "sum")).reset_index()
    chan["net"] = (chan["n_pos"] - chan["n_neg"]) / chan["n"]
    wide = chan.pivot_table(index=["channel", "category"], columns="candidate", values=["n", "net"])
    rows = []
    for (ch, cg), r in wide.iterrows():
        row = {"Channel": ch, "Category": category_label(cg)}
        for c in cands:
            n = r.get(("n", c), np.nan)
            row[f"{theme.candidate_label(c, 'short')} n"] = int(n) if not np.isnan(n) else 0
            row[f"{theme.candidate_label(c, 'short')} net"] = round(r.get(("net", c), np.nan), 2) if n >= MIN_N_FOR_RATE else np.nan
        row["Total"] = int(sum(row[f"{theme.candidate_label(c, 'short')} n"] for c in cands))
        rows.append(row)
    chan_tbl = pd.DataFrame(rows).sort_values("Total", ascending=False)
    ui.data_table_expander(chan_tbl, "View channel-level table (net shown only where n ≥ %d)" % MIN_N_FOR_RATE, key="se_chan_tbl")

# -------------------------------------------------------- model confidence
ui.section("Classifier confidence", f"{SENTIMENT_MODELS.get(f.model, {}).get('label', f.model)}")
hist = load_confidence_hist(sig, f.model)
if hist.empty or f.model == "textblob":
    ui.caption("Confidence histograms are available for the transformer models only; TextBlob returns a polarity, not a class probability.")
else:
    c1, c2 = st.columns([1.5, 1])
    with c1:
        st.plotly_chart(charts.confidence_hist(hist), width="stretch", config=theme.PLOTLY_CONFIG, key="se_conf")
    with c2:
        tot = hist.groupby("label")["n"].sum()
        low = hist[hist["bin"] < 0.6].groupby("label")["n"].sum().reindex(tot.index).fillna(0)
        st.markdown("**Low-confidence share (top-class probability < 0.60)**")
        for lab in ["negative", "neutral", "positive"]:
            if lab in tot:
                st.markdown(f"{ui.sentiment_badge(lab)} &nbsp; {low[lab] / tot[lab]:.0%} of {int(tot[lab]):,} comments", unsafe_allow_html=True)
        ui.caption("Low-confidence comments are typically short, sarcastic, code-mixed or off-topic. The explorer lets you filter by a minimum "
                   "confidence to see how robust a finding is to classifier uncertainty.")

ui.footer()
