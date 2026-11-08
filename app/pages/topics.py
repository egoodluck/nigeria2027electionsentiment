"""Issues & keywords: topic prevalence, trends, candidate-topic relationships, keyword intelligence, discovered themes."""

import numpy as np
import pandas as pd
import streamlit as st

from app import analytics as an
from app import charts, components as ui, theme
from app.data import db_signature, load_fact_topic, load_keywords, load_themes, meta
from app.state import sidebar_controls
from pipeline.settings import ALL_KEY, CANDIDATE_ORDER, MIN_N_FOR_RATE, TOPIC_LABELS, TOPIC_ORDER, TOPICS

f = sidebar_controls()
m = meta()
sig = db_signature()
ui.page_header("Issues & keywords", "Sentiment alone says how people feel; this page shows what they are talking about. Thirteen election issues "
               "are tagged from a Nigerian-context lexicon (a comment can carry several), and distinctive vocabulary is surfaced per candidate.")

ft = load_fact_topic(sig, f.model)
kw = load_keywords(sig, f.model)
if ft.empty:
    ui.note("Topic tables are empty. Run <code>python -m pipeline.enrich --only topics aggregates</code>.", "crit")
    st.stop()
if f.categories or f.channels:
    ui.note("Issue tables are aggregated across all outlets; the outlet-category and channel filters do not apply on this page.", "amber")

cand_options = {ALL_KEY: "All comments", **{c: theme.candidate_label(c, "party") for c in CANDIDATE_ORDER}}
focus = st.segmented_control("Focus", list(cand_options.keys()), format_func=lambda k: cand_options[k], default=ALL_KEY, key="tp_focus") or ALL_KEY

# ----------------------------------------------------------- prevalence
ui.section("Issue prevalence", f"{f.start:%d %b} – {f.end:%d %b %Y} · {cand_options[focus].lower()}")
tt = an.topic_table(ft, f.start, f.end, None if focus == ALL_KEY else focus)
tc = an.topic_change(ft, f.analysis_end, f.period_days, None if focus == ALL_KEY else focus)
if tt.empty:
    ui.empty_state()
else:
    c1, c2 = st.columns([1.2, 1])
    with c1:
        st.plotly_chart(charts.ranked_bars(tt, "share", "label", "Share of topic-tagged comments", value_fmt=".0%",
                                           hover_extra="%{x:.1%} of topic-tagged comments · n = %{customdata:,}", customdata=tt["n"]),
                        width="stretch", config=theme.PLOTLY_CONFIG, key="tp_rank")
    with c2:
        t = theme.tokens()
        d = tt[tt["n"] >= MIN_N_FOR_RATE].sort_values("net")
        colors = [t["neg"] if v < 0 else t["pos"] for v in d["net"]]
        fig = charts.ranked_bars(d, "net", "label", "Net sentiment by issue", colors=colors, value_fmt="+.2f",
                                 hover_extra="net %{x:+.2f} · n = %{customdata:,}", customdata=d["n"], xaxis_title="Net sentiment",
                                 text_inside=True)
        fig.add_vline(x=0, line=dict(color=t["axis"], width=1))
        st.plotly_chart(fig, width="stretch", config=theme.PLOTLY_CONFIG, key="tp_net")
    if not tc.empty:
        ui.caption(f"Change vs the previous {f.period_days} days (share of topic-tagged comments, percentage points):")
        chips = []
        for _, r in tc.sort_values("share_change_pp", ascending=False).iterrows():
            if r["n"] < MIN_N_FOR_RATE:
                continue
            kind = "pos" if r["share_change_pp"] > 1 else "neg" if r["share_change_pp"] < -1 else "neu"
            chips.append(ui.badge(f"{r['label']} {r['share_change_pp']:+.1f} pp", kind))
        st.markdown(" ".join(chips), unsafe_allow_html=True)
    tbl = tt[["label", "n", "share", "n_pos", "n_neu", "n_neg", "net"]].copy()
    tbl["share"] = (tbl["share"] * 100).round(1)
    ui.data_table_expander(tbl.round(3).rename(columns={"label": "Issue", "share": "Share %"}), "View issue table", key="tp_tbl")

# ------------------------------------------------------------------ trend
ui.section("Issue trend", "weekly share of topic-tagged comments")
default_topics = tt["topic"].head(5).tolist() if not tt.empty else TOPIC_ORDER[:5]
sel = st.multiselect("Issues to plot", [t for t in TOPIC_ORDER], default=default_topics, format_func=lambda k: TOPIC_LABELS[k], key="tp_sel", max_selections=8)
if sel:
    st.plotly_chart(charts.topic_trend(ft[(ft["day"] >= f.start) & (ft["day"] <= f.end)], sel, focus, f.mature_until), width="stretch",
                    config=theme.PLOTLY_CONFIG, key="tp_trend")

# ------------------------------------------------------- candidate x topic
ui.section("Candidate × issue", "how each candidate's conversation is distributed across issues, and how it is received")
view = st.segmented_control("Metric", ["Net sentiment", "Share of candidate's mentions"], default="Net sentiment", key="tp_heat") or "Net sentiment"
st.plotly_chart(charts.topic_candidate_heatmap(ft, f.start, f.end, metric="net" if view == "Net sentiment" else "share"), width="stretch",
                config=theme.PLOTLY_CONFIG, key="tp_heatmap")
ui.caption("Share cells read down a column: e.g. 18% of all Obi mentions touch the economy. A comment that mentions two issues counts once in each row.")

# --------------------------------------------------------------- keywords
ui.section("Keyword intelligence", "terms most distinctive of positive vs negative comments about each candidate, and newly trending terms")
if kw.empty:
    ui.empty_state("Keyword statistics are not available for this model yet.")
else:
    ui.caption("Weighted log-odds with an informative Dirichlet prior (Monroe, Colaresi & Quinn 2008). The z-score says how much more a term "
               "appears in one corpus than the other after accounting for how common it is overall; |z| > 2 is a strong association. "
               "Candidate names, parties and function words are excluded. Emerging = last 7 days vs the previous 4 weeks.")
    tabs = st.tabs([theme.candidate_label(c, "party") for c in CANDIDATE_ORDER])
    for tab, c in zip(tabs, CANDIDATE_ORDER):
        sub = kw[kw["candidate"] == c]
        with tab:
            if sub.empty:
                ui.empty_state("No keyword data for this candidate.")
                continue
            k1, k2, k3 = st.columns(3)
            with k1:
                st.plotly_chart(charts.keyword_bars(sub, "positive", "Positive keywords"), width="stretch", config=theme.PLOTLY_CONFIG, key=f"kw_pos_{c}")
            with k2:
                st.plotly_chart(charts.keyword_bars(sub, "negative", "Negative keywords"), width="stretch", config=theme.PLOTLY_CONFIG, key=f"kw_neg_{c}")
            with k3:
                if (sub["polarity"] == "emerging").any():
                    st.plotly_chart(charts.keyword_bars(sub, "emerging", "Emerging keywords (7d)"), width="stretch", config=theme.PLOTLY_CONFIG, key=f"kw_em_{c}")
                else:
                    ui.empty_state("No term rose significantly in the last seven days.")
            ui.data_table_expander(sub.drop(columns=["candidate"]).rename(columns={"count_a": "count (focal corpus)", "count_b": "count (comparison)"}),
                                   "View keyword table", key=f"kw_tbl_{c}")

# ------------------------------------------------------- discovered themes
ui.section("Discovered themes (unsupervised)", "TF-IDF + non-negative matrix factorisation, 12 components, fixed seed")
themes = load_themes(sig)
if themes.empty:
    ui.empty_state("No discovered themes yet.")
else:
    ui.caption("These are statistical word clusters, not editorial categories: they show what the lexicon may be missing. A large catch-all "
               "cluster is expected. Clusters built around journalists' names show how much of the conversation is about the media itself.")
    rows = []
    for tid, g in themes.groupby("theme_id"):
        g = g.sort_values("rank")
        rows.append({"Theme": f"theme {tid}", "Comments": int(g["n_comments"].iloc[0]), "Top terms": ", ".join(g["term"].head(10))})
    st.dataframe(pd.DataFrame(rows).sort_values("Comments", ascending=False), width="stretch", hide_index=True,
                 column_config={"Top terms": st.column_config.TextColumn(width="large")})

with st.expander("Issue taxonomy — the full lexicon behind each issue"):
    for k in TOPIC_ORDER:
        st.markdown(f"**{TOPIC_LABELS[k]}** · {len(TOPICS[k]['terms'])} terms  \n<span class='nes-caption'>{', '.join(sorted(TOPICS[k]['terms']))}</span>",
                    unsafe_allow_html=True)

ui.footer()
