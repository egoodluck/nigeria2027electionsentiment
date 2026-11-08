"""Overview: executive intelligence brief, headline indicators and candidate scorecards."""

import numpy as np
import pandas as pd
import streamlit as st

from app import analytics as an
from app import charts, components as ui, theme
from app.data import db_signature, load_fact_daily, load_fact_topic, load_keywords, meta
from app.state import sidebar_controls
from pipeline.settings import ALL_KEY, CANDIDATE_ORDER, CANDIDATES, MIN_N_FOR_RATE, TOPIC_LABELS

f = sidebar_controls()
m = meta()
sig = db_signature()

ui.page_header(
    "Election intelligence brief",
    "What Nigerians are saying under the news: sentiment, visibility, momentum and the issues driving them, for the three leading "
    "2027 presidential contenders — from public YouTube comments on 50 Nigerian news, radio, vernacular and civic channels.",
)

fd_all = load_fact_daily(sig, f.model)
if fd_all.empty:
    ui.note("The enrichment tables are empty. Run <code>python -m pipeline.enrich</code> to populate sentiment, topics and aggregates.", "crit")
    st.stop()

fd = an.filter_facts(fd_all, f.start, f.end, f.categories, f.channels)
ft = load_fact_topic(sig, f.model)
kw = load_keywords(sig, f.model)

# ------------------------------------------------------------------ brief
period_opts = {"Daily": (1, "day"), "Weekly": (7, "week"), "Monthly": (30, "month")}
col_a, col_b = st.columns([3, 1.2])
with col_b:
    period = st.segmented_control("Brief period", list(period_opts.keys()), default="Weekly", key="ov_period",
                                  help="Window summarised by the brief; the comparison is always with the preceding window of the same length.")
    period = period or "Weekly"
days, word = period_opts[period]
brief = an.intelligence_brief(fd, ft if f.categories == [] and not f.channels else pd.DataFrame(), kw, f.analysis_end, days, word,
                              m.get("mature_until"), last_day=m.get("last_day"))
with col_a:
    ui.section(f"{period} intelligence summary", f"{brief['window'][0]:%d %b} – {brief['window'][1]:%d %b %Y} · generated locally from the data, no external AI")

with st.container(border=True):
    paras = brief["paragraphs"]
    html_paras = "".join(f"<p class='{'lead' if i == 0 else ''}'>{ui.esc(p)}</p>" for i, p in enumerate(paras))
    facts_html = "".join(f"<span class='nes-badge {kind}'>{ui.esc(k)}: {ui.esc(v)}</span>" for k, v, kind in brief["facts"])
    st.markdown(f"<div class='nes-brief'>{html_paras}<div class='nes-facts'>{facts_html}</div></div>", unsafe_allow_html=True)

# --------------------------------------------------------------- headline KPIs
pc = brief["compare"]
cur_all, prev_all = pc.current[ALL_KEY], pc.previous[ALL_KEY]
cands = {c: pc.current[c] for c in CANDIDATE_ORDER}
prevs = {c: pc.previous[c] for c in CANDIDATE_ORDER}
sov = an.share_of_voice(cands)
mom = an.momentum_index(fd, f.analysis_end, max(days, 7) if days > 1 else 7)
inf = an.influence_index(fd, f.analysis_end, max(days, 7) if days > 1 else 7, mom)

ui.section("Headline indicators", f"{period.lower()} window vs the previous {word}")
k1, k2, k3, k4, k5, k6 = st.columns(6)
with k1:
    total = sum(s["n"] for s in cands.values())
    chg = an.pct_change(total, sum(s["n"] for s in prevs.values()))
    delta_txt = (ui.fmt_pct(chg, 0, True) + f" vs prior {word}" + (" · provisional" if brief.get("lagging") else "")) if not np.isnan(chg) else None
    ui.stat_tile("Candidate mentions", ui.fmt_int(total), delta_txt, "flat" if brief.get("lagging") else ui.delta_direction(chg),
                 note_text=f"{ui.fmt_int(cur_all['n'])} comments overall" + (" · collection lag" if brief.get("lagging") else ""))
with k2:
    overall = an.summarize(an.candidates_only(an.filter_facts(fd, pc.cur_start, pc.cur_end)))
    prev_overall = an.summarize(an.candidates_only(an.filter_facts(fd, pc.prev_start, pc.prev_end)))
    d = overall["net"] - prev_overall["net"] if not (np.isnan(overall["net"]) or np.isnan(prev_overall["net"])) else np.nan
    ui.stat_tile("Net sentiment (all candidates)", ui.fmt_net(overall["net"]), f"{d * 100:+.0f} pts" if not np.isnan(d) else None,
                 ui.delta_direction(d), note_text=f"95% CI {ui.fmt_net(overall['ci'][0])} to {ui.fmt_net(overall['ci'][1])}")
with k3:
    leader = max(sov, key=lambda c: (sov[c] if not np.isnan(sov[c]) else -1)) if sov else None
    ui.stat_tile("Share-of-voice leader", CANDIDATES[leader]["short"] if leader else "—", ui.fmt_pct(sov[leader]) + " of mentions" if leader else None, "flat")
with k4:
    top_m = mom.sort_values("momentum", ascending=False).iloc[0]
    ui.stat_tile("Momentum leader", CANDIDATES[top_m["candidate"]]["short"], f"index {top_m['momentum']:.0f} / 100",
                 "up" if top_m["momentum"] > 55 else "flat", note_text="7-day momentum index")
with k5:
    top_i = inf.iloc[0]
    ui.stat_tile("Influence rank #1", CANDIDATES[top_i["candidate"]]["short"], f"index {top_i['influence']:.0f} ({top_i['change']:+.1f})",
                 ui.delta_direction(top_i["change"]), note_text="Election Influence Index")
with k6:
    band = an.manipulation_band(cur_all["flagged_share"])
    ui.stat_tile("Manipulation risk", band, ui.fmt_pct(cur_all["flagged_share"], 1) + " of comments flagged" if not np.isnan(cur_all["flagged_share"]) else None,
                 "down" if band == "High" else "flat", note_text="duplicates & bursts, observational")

# ------------------------------------------------------------ scorecards
ui.section("Candidate scorecards", f"{f.start:%d %b} – {f.end:%d %b %Y}, {ui.model_caption(f.model)}")
full = {c: an.summarize(fd[fd["candidate"] == c]) for c in CANDIDATE_ORDER}
daily = an.daily_series(an.candidates_only(fd), window=7, min_n=1)
cols = st.columns(3)
for col, cand in zip(cols, CANDIDATE_ORDER):
    s = full[cand]
    with col, st.container(border=True):
        ui.candidate_card_header(cand)
        if s["n"] == 0:
            ui.empty_state("No mentions in this selection.")
            continue
        a, b = st.columns([1.1, 1])
        with a:
            ui.stat_tile("Net sentiment", ui.fmt_net(s["net"]), f"CI {ui.fmt_net(s['ci'][0])} … {ui.fmt_net(s['ci'][1])}", "flat")
        with b:
            ui.stat_tile("Share of voice", ui.fmt_pct(s["n"] / max(sum(x["n"] for x in full.values()), 1)),
                         f"{ui.fmt_int(s['n'])} mentions", "flat")
        ui.mix_bar(s["pos_share"], s["neu_share"], s["neg_share"])
        sub = daily[daily["candidate"] == cand].set_index("day")["rolling_net"]
        if len(sub.dropna()) >= 3:
            st.plotly_chart(charts.sparkline(sub, theme.candidate_color(cand)), width="stretch", config={"displayModeBar": False, "staticPlot": True},
                            key=f"spark_{cand}")
            ui.caption("7-day rolling net sentiment")
        mrow = mom[mom["candidate"] == cand].iloc[0]
        irow = inf[inf["candidate"] == cand].iloc[0]
        ui.kv_rows([
            ("Momentum index (7d)", f"{mrow['momentum']:.0f} / 100"),
            ("Influence index", f"{irow['influence']:.0f}  (rank {int(irow['rank'])}, {irow['change']:+.1f})"),
            ("Likes on mentions", ui.fmt_int(s["likes"])),
            ("Flagged comments", f"{ui.fmt_pct(s['flagged_share'], 1)}"),
        ])
        if s["n"] < MIN_N_FOR_RATE:
            ui.caption(f"Fewer than {MIN_N_FOR_RATE} mentions — shares are indicative only.")

# ------------------------------------------------------------------ trends
ui.section("Sentiment trajectory", "volume-weighted 7-day rolling net sentiment with 95% bands; shaded days are still accumulating comments")
if daily.empty:
    ui.empty_state()
else:
    st.plotly_chart(charts.trend_lines(daily, f.candidates, f.mature_until), width="stretch", config=theme.PLOTLY_CONFIG, key="ov_trend")
    st.plotly_chart(charts.volume_bars(daily, f.candidates, f.mature_until), width="stretch", config=theme.PLOTLY_CONFIG, key="ov_vol")
    tbl = daily[["candidate", "day", "n", "n_pos", "n_neu", "n_neg", "net", "rolling_net", "rolling_lo", "rolling_hi"]].copy()
    tbl["candidate"] = tbl["candidate"].map(lambda c: theme.candidate_label(c, "short"))
    tbl["day"] = tbl["day"].dt.date
    ui.data_table_expander(tbl.round(3), "View trajectory data", key="ov_trend_tbl")

# ---------------------------------------------------------- what's driving it
ui.section("What is driving the conversation", "issue prevalence and sentiment per candidate in the selected range")
if ft.empty:
    ui.empty_state("Topic tables are not available yet.")
else:
    c1, c2 = st.columns([1.35, 1])
    with c1:
        st.plotly_chart(charts.topic_candidate_heatmap(ft, f.start, f.end), width="stretch", config=theme.PLOTLY_CONFIG, key="ov_topic_heat")
        ui.caption(f"Cells with fewer than {MIN_N_FOR_RATE} comments are masked. Net sentiment = (positive − negative) / all comments on that issue.")
    with c2:
        tt = an.topic_table(ft, f.start, f.end)
        if not tt.empty:
            top = tt.head(10)
            st.plotly_chart(charts.ranked_bars(top, "share", "label", "Most-discussed issues (all comments)", value_fmt=".0%",
                                               hover_extra="%{x:.1%} of topic-tagged comments · n = %{customdata:,}", customdata=top["n"]),
                            width="stretch", config=theme.PLOTLY_CONFIG, key="ov_topic_rank")
    if not kw.empty:
        em = kw[kw["polarity"] == "emerging"]
        if not em.empty:
            st.markdown("**Emerging terms, last 7 days** — words appearing far more often than in the previous four weeks (weighted log-odds)")
            cols = st.columns(3)
            for col, cand in zip(cols, CANDIDATE_ORDER):
                terms = em[em["candidate"] == cand].sort_values("rank").head(8)
                with col:
                    st.markdown(ui.candidate_chip(cand) + " " + " ".join(ui.badge(t, "amber") for t in terms["term"]) if not terms.empty
                                else ui.candidate_chip(cand) + " " + ui.badge("no emerging terms", "neu"), unsafe_allow_html=True)

ui.footer()
