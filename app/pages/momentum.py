"""Momentum & influence indices: composite scores, components, ranking and weekly trajectory."""

import numpy as np
import pandas as pd
import streamlit as st

from app import analytics as an
from app import charts, components as ui, theme
from app.data import db_signature, load_fact_daily, meta
from app.state import sidebar_controls
from pipeline.settings import CANDIDATE_ORDER, CANDIDATES, MIN_N_FOR_RATE

f = sidebar_controls()
m = meta()
sig = db_signature()
ui.page_header("Momentum & influence", "Two composite indices summarise direction of travel and overall standing in the online conversation. "
               "They are descriptive summaries of comment data — not vote-share estimates.")

fd_all = load_fact_daily(sig, f.model)
if fd_all.empty:
    ui.note("No enrichment data available. Run <code>python -m pipeline.enrich</code>.", "crit")
    st.stop()
fd = an.filter_facts(fd_all, None, f.end, f.categories, f.channels)   # indices need history before the range start

c_win, c_info = st.columns([1, 2.4])
with c_win:
    window = st.segmented_control("Window", [7, 14, 30], default=7, format_func=lambda d: f"{d} days", key="mo_win") or 7
with c_info:
    ui.caption(f"Current window: the {window} mature days ending {f.analysis_end:%d %b %Y}; compared with the {window} days before. "
               f"Days after {ui.fmt_date(f.mature_until)} are excluded because their comments are still arriving.")

mom = an.momentum_index(fd, f.analysis_end, window)
inf = an.influence_index(fd, f.analysis_end, window, mom)

# ---------------------------------------------------------------- summary cards
ui.section("Index summary")
cols = st.columns(3)
for col, c in zip(cols, CANDIDATE_ORDER):
    mr = mom[mom["candidate"] == c].iloc[0]
    ir = inf[inf["candidate"] == c].iloc[0]
    with col, st.container(border=True):
        ui.candidate_card_header(c)
        a, b = st.columns(2)
        with a:
            ui.stat_tile("Momentum", f"{mr['momentum']:.0f}", "gaining" if mr["momentum"] > 55 else "losing" if mr["momentum"] < 45 else "steady",
                         "up" if mr["momentum"] > 55 else "down" if mr["momentum"] < 45 else "flat", unit="/100")
        with b:
            rank_move = int(ir["rank_prev"] - ir["rank"])
            ui.stat_tile("Influence", f"{ir['influence']:.0f}", f"rank #{int(ir['rank'])} · {ir['change']:+.1f} pts" + (f" · {'▲' if rank_move > 0 else '▼'}{abs(rank_move)}" if rank_move else ""),
                         ui.delta_direction(ir["change"]), unit="/100")
        if mr["n_cur"] < MIN_N_FOR_RATE or mr["n_prev"] < MIN_N_FOR_RATE:
            st.markdown(ui.badge(f"low sample: {int(mr['n_cur'])} vs {int(mr['n_prev'])} mentions — indicative only", "amber"), unsafe_allow_html=True)
        ui.kv_rows([
            ("Net sentiment change", f"{mr['d_net'] * 100:+.0f} pts" if not np.isnan(mr["d_net"]) else "n/a"),
            ("Engagement (likes) growth", ui.fmt_pct(mr["g_eng"], 0, True) if not np.isnan(mr["g_eng"]) else "n/a"),
            ("Discussion growth", ui.fmt_pct(mr["g_vol"], 0, True) if not np.isnan(mr["g_vol"]) else "n/a"),
            ("Consistency", f"{mr['consistency']:.2f}"),
            ("Mentions (window / prior)", f"{int(mr['n_cur']):,} / {int(mr['n_prev']):,}"),
        ])

# --------------------------------------------------------------- momentum
ui.section("Candidate Momentum Index", "40% sentiment trend · 30% engagement growth · 20% discussion growth · 10% consistency → 0–100, 50 = no change")
c1, c2 = st.columns([1, 1.4])
with c1:
    st.plotly_chart(charts.index_bars(mom, "momentum", "Momentum index"), width="stretch", config=theme.PLOTLY_CONFIG, key="mo_bars")
with c2:
    st.plotly_chart(charts.component_bars(mom), width="stretch", config=theme.PLOTLY_CONFIG, key="mo_comp")
ui.caption("Each component maps a change onto 0–1 with a tanh squash (0.5 = no change), so a single viral day cannot dominate the index. "
           "Consistency rewards a stable daily net sentiment inside the window. Full formulas on the Methodology page.")

# --------------------------------------------------------------- influence
ui.section("Election Influence Index", "35% sentiment · 25% mention share · 20% engagement share · 20% momentum → 0–100")
c1, c2 = st.columns([1, 1.4])
with c1:
    st.plotly_chart(charts.index_bars(inf, "influence", "Influence index", mid=None), width="stretch", config=theme.PLOTLY_CONFIG, key="in_bars")
with c2:
    tbl = pd.DataFrame({
        "Rank": inf["rank"].astype(int),
        "Candidate": inf["candidate"].map(lambda c: theme.candidate_label(c, "party")),
        "Influence": inf["influence"].round(1),
        "Change": inf["change"].round(1),
        "Prev. rank": inf["rank_prev"].astype(int),
        "Net sentiment": inf["sentiment"].round(3),
        "Share of voice": (inf["sov"] * 100).round(1),
        "Engagement share": (inf["engagement"] * 100).round(1),
        "Momentum": inf["momentum"].round(1),
        "Mentions": inf["n"].astype(int),
    })
    st.dataframe(tbl, width="stretch", hide_index=True,
                 column_config={"Share of voice": st.column_config.NumberColumn(format="%.1f%%"),
                                "Engagement share": st.column_config.NumberColumn(format="%.1f%%"),
                                "Change": st.column_config.NumberColumn(format="%+.1f"),
                                "Net sentiment": st.column_config.NumberColumn(format="%+.3f")})
    ui.caption("Mention share and engagement share are computed among the three candidates, so they sum to 100%. Sentiment enters as (net + 1) / 2.")

# -------------------------------------------------------------- trajectory
ui.section("Historical trajectory", "indices recomputed at each weekly anchor")
@st.cache_data(ttl=900, show_spinner="Recomputing weekly anchors…")
def _trajectory(_sig, model, end, window, cats, chans, fd_df):
    return an.index_trajectory(fd_df, end, window, weeks=16)


traj = _trajectory(sig, f.model, f.analysis_end, window, tuple(f.categories), tuple(f.channels), fd)
if traj.empty or traj["anchor"].nunique() < 2:
    ui.empty_state("Not enough history yet for a trajectory (needs at least two full windows).")
else:
    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(charts.trajectory_lines(traj, "influence", "Influence index", mid=None), width="stretch", config=theme.PLOTLY_CONFIG, key="tr_inf")
    with c2:
        st.plotly_chart(charts.trajectory_lines(traj, "momentum", "Momentum index"), width="stretch", config=theme.PLOTLY_CONFIG, key="tr_mom")
    out = traj.copy()
    out["candidate"] = out["candidate"].map(lambda c: theme.candidate_label(c, "short"))
    out["anchor"] = out["anchor"].dt.date
    out["sov"] = (out["sov"] * 100).round(1)
    ui.data_table_expander(out.round(3).rename(columns={"anchor": "week ending", "sov": "share of voice %"}), "View trajectory data", key="tr_tbl")

ui.note("<b>Reading the indices.</b> Momentum measures change inside the online conversation; influence measures standing within it. Neither is a "
        "poll: YouTube commenters are a self-selected, mostly urban and diaspora audience, and a single viral clip can move both indices for a week. "
        "Use them to prioritise where to look, then read the comments.", "brand")
ui.footer()
