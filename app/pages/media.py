"""Media intelligence: outlet tendency matrix, outlet influence, category comparison, most-discussed videos."""

import numpy as np
import pandas as pd
import streamlit as st

from app import analytics as an
from app import charts, components as ui, theme
from app.data import CATEGORY_ORDER, category_label, db_signature, load_channels, load_fact_daily, load_video_table, meta
from app.state import sidebar_controls
from pipeline.settings import CANDIDATE_ORDER, MIN_N_FOR_RATE

f = sidebar_controls()
m = meta()
sig = db_signature()
ui.page_header("Media intelligence", "Which outlets host the conversation, how their audiences react to each candidate, and which videos drive it. "
               "The tendency matrix describes the sentiment of a channel's commenters — not the editorial line of the outlet.")

fd_all = load_fact_daily(sig, f.model)
if fd_all.empty:
    ui.note("No enrichment data available. Run <code>python -m pipeline.enrich</code>.", "crit")
    st.stop()
fd = an.filter_facts(fd_all, f.start, f.end, f.categories, f.channels)
cands_fd = an.candidates_only(fd)
all_fd = an.all_comments(fd)
chans = load_channels(sig)
ui.caption(f"Selection: {f.describe()}")

# ---------------------------------------------------------- outlet influence
ui.section("Outlet influence", "where the discussion happens")
inf = all_fd.groupby(["channel", "category"], as_index=False).agg(comments=("n", "sum"), likes=("sum_likes", "sum"), videos=("n_videos", "max"),
                                                                 flagged=("n_flagged", "sum"))
vids = all_fd.groupby("channel")["n_videos"].sum()  # day-level distinct videos summed (approximation of active video-days)
cm = cands_fd.groupby("channel", as_index=False).agg(mentions=("n", "sum"))
inf = inf.merge(cm, on="channel", how="left").fillna({"mentions": 0})
inf["mentions"] = inf["mentions"].astype(int)
inf["category_label"] = inf["category"].map(category_label)
inf["share"] = inf["comments"] / inf["comments"].sum()
inf["likes_per_comment"] = inf["likes"] / inf["comments"].replace(0, np.nan)
inf = inf.sort_values("comments", ascending=False)

video_tbl = load_video_table(sig, f.model)
reach_available = bool(m.get("has_video_stats")) and "view_count" in video_tbl and video_tbl["view_count"].notna().any()

c1, c2 = st.columns([1.1, 1])
with c1:
    top = inf.head(15)
    st.plotly_chart(charts.ranked_bars(top, "comments", "channel", "Comments generated, top 15 channels", value_fmt=",.0f",
                                       hover_extra="%{x:,} comments · %{customdata[0]:,} candidate mentions · %{customdata[1]:.0%} of all comments",
                                       customdata=np.stack([top["mentions"], top["share"]], axis=-1)),
                    width="stretch", config=theme.PLOTLY_CONFIG, key="me_rank")
with c2:
    cat = all_fd.groupby("category", as_index=False).agg(comments=("n", "sum"), likes=("sum_likes", "sum"))
    cat["label"] = cat["category"].map(category_label)
    cat["share"] = cat["comments"] / cat["comments"].sum()
    st.plotly_chart(charts.ranked_bars(cat, "share", "label", "Share of comments by outlet category", value_fmt=".0%",
                                       hover_extra="%{x:.1%} · %{customdata:,} comments", customdata=cat["comments"]),
                    width="stretch", config=theme.PLOTLY_CONFIG, key="me_cat")
    conc = inf["share"].head(1).iloc[0] if not inf.empty else np.nan
    ui.note(f"<b>Concentration.</b> {ui.esc(inf['channel'].iloc[0]) if not inf.empty else '—'} alone accounts for {ui.fmt_pct(conc)} of all comments in this "
            f"selection. Any 'national' reading of sentiment is weighted toward that channel's audience; use the channel filter to test robustness.", "amber")

ui.section("Outlet influence table", "reach = YouTube view counts when available; otherwise comments and likes are the engagement proxies")
if not reach_available:
    ui.caption("YouTube view counts are not in this snapshot yet. They are collected by `pipeline/video_stats.py` (≈45 quota units for the whole corpus) "
               "on the next pipeline run with an API key; until then reach is estimated from comment activity only.")
tbl = inf[["channel", "category_label", "comments", "mentions", "likes", "likes_per_comment", "share", "flagged"]].copy()
if reach_available:
    views = video_tbl.groupby("channel")["view_count"].sum()
    tbl = tbl.merge(views.rename("views"), left_on="channel", right_index=True, how="left")
tbl["share"] = (tbl["share"] * 100).round(1)
tbl["likes_per_comment"] = tbl["likes_per_comment"].round(2)
tbl["flagged_share"] = (tbl["flagged"] / tbl["comments"].replace(0, np.nan) * 100).round(1)
st.dataframe(tbl.drop(columns=["flagged"]).rename(columns={"channel": "Channel", "category_label": "Category", "comments": "Comments", "mentions": "Candidate mentions",
                                                             "likes": "Likes on comments", "likes_per_comment": "Likes / comment", "share": "Share of comments %",
                                                             "views": "Video views (reach)", "flagged_share": "Flagged %"}),
             width="stretch", hide_index=True, height=min(520, 60 + 35 * len(tbl)))

# -------------------------------------------------------- tendency matrix
ui.section("Outlet tendency matrix", f"net sentiment of each channel's commenters toward each candidate; cells with fewer than {MIN_N_FOR_RATE} mentions are masked")
min_total = st.slider("Minimum candidate mentions for a channel to appear", 20, 500, 60, 20, key="me_min")
g = cands_fd.groupby(["channel", "candidate"]).agg(n=("n", "sum"), n_pos=("n_pos", "sum"), n_neg=("n_neg", "sum"))
if g.empty:
    ui.empty_state()
else:
    g["net"] = (g["n_pos"] - g["n_neg"]) / g["n"]
    totals = g.groupby("channel")["n"].sum()
    keep = totals[totals >= min_total].sort_values(ascending=False).index.tolist()
    if not keep:
        ui.empty_state("No channel passes the minimum; lower the slider.")
    else:
        values = g["net"].unstack("candidate").reindex(index=keep, columns=CANDIDATE_ORDER)
        counts = g["n"].unstack("candidate").reindex(index=keep, columns=CANDIDATE_ORDER).fillna(0)
        st.plotly_chart(charts.heatmap(values, counts, "Net sentiment by channel × candidate",
                                       xlabels={c: theme.candidate_label(c, "short") for c in CANDIDATE_ORDER}, height=90 + 36 * len(keep)),
                        width="stretch", config=theme.PLOTLY_CONFIG, key="me_heat")
        # tendency summary: positive / negative / neutral leaning per channel (overall)
        tot = g.groupby("channel").agg(n=("n", "sum"), n_pos=("n_pos", "sum"), n_neg=("n_neg", "sum"))
        tot["pos_share"] = tot["n_pos"] / tot["n"]
        tot["neg_share"] = tot["n_neg"] / tot["n"]
        tot["neu_share"] = 1 - tot["pos_share"] - tot["neg_share"]
        tot = tot.loc[keep]
        overall_pos, overall_neg = cands_fd["n_pos"].sum() / cands_fd["n"].sum(), cands_fd["n_neg"].sum() / cands_fd["n"].sum()

        def tendency(r):
            if r["pos_share"] - overall_pos > 0.05:
                return "Positive-leaning audience"
            if r["neg_share"] - overall_neg > 0.05:
                return "Negative-leaning audience"
            return "In line with the corpus"
        tot["tendency"] = tot.apply(tendency, axis=1)
        out = tot.reset_index()[["channel", "n", "pos_share", "neu_share", "neg_share", "tendency"]]
        out[["pos_share", "neu_share", "neg_share"]] = (out[["pos_share", "neu_share", "neg_share"]] * 100).round(1)
        ui.data_table_expander(out.rename(columns={"channel": "Channel", "n": "Mentions", "pos_share": "Positive %", "neu_share": "Neutral %",
                                                   "neg_share": "Negative %", "tendency": "Audience tendency vs corpus"}),
                               "View channel tendency table", key="me_tend")
        ui.caption(f"Corpus baseline in this selection: {overall_pos:.0%} positive, {overall_neg:.0%} negative. A channel is 'leaning' when its share "
                   "differs from the baseline by more than 5 points. This characterises commenters, who self-select, not the outlet's journalism.")

# ------------------------------------------------------------------ videos
ui.section("Most-discussed videos", "the clips that generated the most comments in the selected range")
if video_tbl.empty:
    ui.empty_state()
else:
    v = video_tbl[(video_tbl["published_at"] >= pd.Timestamp(f.start, tz="UTC")) & (video_tbl["published_at"] <= pd.Timestamp(f.end, tz="UTC") + pd.Timedelta(days=1))]
    if f.categories:
        v = v[v["category"].isin(f.categories)]
    if f.channels:
        v = v[v["channel"].isin(f.channels)]
    v = v.head(40).copy()
    v["net"] = ((v["n_pos"] - v["n_neg"]) / v["comments"].replace(0, np.nan)).round(2)
    v["url"] = "https://www.youtube.com/watch?v=" + v["video_id"]
    v["candidates"] = v["candidates"].fillna("").map(lambda s: ", ".join(theme.candidate_label(c, "short") for c in sorted(set(s.split(","))) if c) if s else "—")
    v["published_at"] = v["published_at"].dt.strftime("%d %b %Y")
    cols = ["title", "channel", "published_at", "comments", "comment_likes", "net", "candidates", "url"]
    if reach_available:
        cols.insert(4, "view_count")
    st.dataframe(v[cols].rename(columns={"title": "Video", "channel": "Channel", "published_at": "Published", "comments": "Comments",
                                         "comment_likes": "Likes on comments", "net": "Net sentiment", "candidates": "Candidates discussed",
                                         "view_count": "Views", "url": "Link"}),
                 width="stretch", hide_index=True, height=min(620, 60 + 35 * len(v)),
                 column_config={"Link": st.column_config.LinkColumn(display_text="open"), "Video": st.column_config.TextColumn(width="large"),
                                "Net sentiment": st.column_config.NumberColumn(format="%+.2f")})

ui.footer()
