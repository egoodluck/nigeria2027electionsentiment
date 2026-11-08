"""Projections (not predictions): 7/14/30-day ETS projections of net sentiment and volume with intervals."""

import pandas as pd
import streamlit as st

from app import analytics as an
from app import charts, components as ui, theme
from app.data import db_signature, load_fact_daily, load_forecasts, meta
from app.state import sidebar_controls
from pipeline.settings import ALL_KEY, CANDIDATE_ORDER, FORECAST_MIN_HISTORY_DAYS

f = sidebar_controls()
m = meta()
sig = db_signature()
ui.page_header("Projections", "Statistical extrapolations of the recent trend in net sentiment and discussion volume, with uncertainty bands.")

ui.note("<b>Projection, not prediction.</b> These curves answer one question only: <i>if the recent pattern simply continued, where would the "
        "series be?</i> They know nothing about campaigns, debates, defections, security events or the election itself, and they say nothing "
        "about votes. The bands widen quickly for a reason. Treat them as a baseline against which real movements can be judged.", "amber")

fc = load_forecasts(sig, f.model)
fd_all = load_fact_daily(sig, f.model)
if fc.empty or fd_all.empty:
    ui.empty_state("No projections available for this model yet. Run `python -m pipeline.enrich --only forecast`.")
    st.stop()
if f.categories or f.channels:
    ui.caption("Projections are fitted on all outlets; the outlet filters do not apply on this page.")

c1, c2, c3 = st.columns([1, 1, 2])
with c1:
    horizon = st.segmented_control("Horizon", [7, 14, 30], default=14, format_func=lambda d: f"{d} days", key="pr_h") or 14
with c2:
    metric = st.segmented_control("Series", ["net_sentiment", "volume"], default="net_sentiment",
                                  format_func=lambda k: {"net_sentiment": "Net sentiment", "volume": "Daily mentions"}[k], key="pr_m") or "net_sentiment"
with c3:
    gen = fc["generated_at"].iloc[0]
    hist_days = int(fc["history_days"].max())
    ui.caption(f"Generated {ui.fmt_date(gen)} from {hist_days} days of mature history. Model: {fc['method'].iloc[0]} (statsmodels). "
               f"Minimum history {FORECAST_MIN_HISTORY_DAYS} days.")

# history for the chart: last 60 mature days
hist_fd = an.filter_facts(fd_all, f.analysis_end - pd.Timedelta(days=60), f.analysis_end)
daily = an.daily_series(hist_fd, window=7, min_n=1)

targets = [c for c in CANDIDATE_ORDER if c in f.candidates] + [ALL_KEY]
for cand in targets:
    sub_fc = fc[(fc["candidate"] == cand) & (fc["metric"] == metric)]
    sub_h = daily[daily["candidate"] == cand]
    if sub_fc.empty or sub_h.empty:
        continue
    with st.container(border=True):
        st.plotly_chart(charts.forecast_chart(sub_h, sub_fc, cand, metric, horizon), width="stretch", config=theme.PLOTLY_CONFIG, key=f"pr_{cand}")
        last = sub_fc.sort_values("day").head(horizon).tail(1).iloc[0]
        first_obs = sub_h.dropna(subset=["rolling_net" if metric == "net_sentiment" else "rolling_vol"]).tail(1)
        cur_val = float(first_obs["rolling_net" if metric == "net_sentiment" else "rolling_vol"].iloc[0]) if not first_obs.empty else float("nan")
        fmt = (lambda v: f"{v:+.2f}") if metric == "net_sentiment" else (lambda v: f"{v:,.0f}")
        a, b, c, d = st.columns(4)
        with a:
            ui.stat_tile("Latest observed", fmt(cur_val), "7-day rolling", "flat")
        with b:
            ui.stat_tile(f"Projected in {horizon} days", fmt(last["yhat"]), f"{fmt(last['yhat'] - cur_val)} vs now" if metric == "net_sentiment" else None, "flat")
        with c:
            ui.stat_tile("80% interval", f"{fmt(last['lo80'])} to {fmt(last['hi80'])}")
        with d:
            ui.stat_tile("95% interval", f"{fmt(last['lo95'])} to {fmt(last['hi95'])}")

with st.expander("How the projections are produced"):
    st.markdown("""
* **Series.** Daily net sentiment = (positive − negative) ÷ mentions per candidate, from the fact table; days with fewer than five mentions
  are treated as missing and linearly interpolated (gaps ≤ 3 days). Volume is modelled on a log1p scale and back-transformed.
* **Model.** Exponential smoothing (ETS) with additive error and an additive *damped* trend, fitted by maximum likelihood with `statsmodels`;
  the volume model adds a 7-day additive season because comment activity has a weekly rhythm. ARIMA(1,0,0) and a naive mean ± sd band
  are fallbacks if ETS does not converge.
* **Intervals.** 80% and 95% prediction intervals from the fitted state-space model; clipped to [−1, 1] for net sentiment and to ≥ 0 for volume.
* **Maturity.** Only days at least three days older than the last collection run are used, so still-arriving comments do not drag the end of the series down.
* **What it is not.** Not a forecast of the election; not conditioned on events; not a measure of public opinion beyond YouTube commenters.
""")
    tbl = fc[fc["metric"] == metric].copy()
    tbl["candidate"] = tbl["candidate"].map(lambda c: theme.candidate_label(c, "short") if c in CANDIDATE_ORDER else "All comments")
    tbl["day"] = tbl["day"].dt.date
    ui.data_table_expander(tbl.round(3), "View projection table", key="pr_tbl")

ui.footer()
