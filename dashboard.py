"""
Live dashboard for the Nigeria 2027 election sentiment pipeline.

Reads directly from election_sentiment.db (read-only) and re-queries on a
timer, so it stays current as run_pipeline.py keeps adding rows in the
background -- no restart needed as the dataset grows.

Run with:
    streamlit run dashboard.py

Does NOT import config.py on purpose: config.py requires YOUTUBE_API_KEY to
even be imported (it powers collection, which this dashboard doesn't do), and
viewing the data shouldn't be gated on having that key set.
"""

import os
import sqlite3
from datetime import datetime, timezone

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

DB_PATH = os.environ.get("DB_PATH", "election_sentiment.db")

st.set_page_config(
    page_title="Nigeria 2027 Election Sentiment",
    page_icon="\U0001F5F3",
    layout="wide",
)

# --- palette (see dataviz skill: fixed categorical order, diverging for sentiment) ---
CANDIDATE_ORDER = ["tinubu", "atiku", "obi"]
CANDIDATE_LABELS = {"tinubu": "Tinubu (APC)", "atiku": "Atiku (ADC)", "obi": "Peter Obi (NDC)"}
CANDIDATE_COLORS = {"tinubu": "#2a78d6", "atiku": "#eb6834", "obi": "#1baf7a"}

SENTIMENT_ORDER = ["negative", "neutral", "positive"]
SENTIMENT_COLORS = {"negative": "#e34948", "neutral": "#c3c2b7", "positive": "#2a78d6"}

GOOD, CRITICAL, MUTED_INK = "#0ca30c", "#d03b3b", "#898781"
INK, GRID = "#52514e", "#e1e0d9"

CHART_FONT = dict(family="system-ui, -apple-system, Segoe UI, sans-serif", color=INK)
BASE_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=CHART_FONT,
    margin=dict(l=10, r=10, t=30, b=10),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
)

REFRESH_OPTIONS = {"15 seconds": 15, "30 seconds": 30, "1 minute": 60, "5 minutes": 300}


@st.cache_data(ttl=15)
def load_data(db_path):
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        mentions = pd.read_sql_query(
            """
            SELECT ccm.candidate, c.sentiment_polarity, c.sentiment_label,
                   c.published_at, ch.category, ch.label AS channel_label
            FROM comment_candidate_mentions ccm
            JOIN comments c ON c.comment_id = ccm.comment_id
            JOIN videos v ON v.video_id = c.video_id
            JOIN channels ch ON ch.channel_id = v.channel_id
            WHERE c.sentiment_polarity IS NOT NULL
            """,
            conn,
            parse_dates=["published_at"],
        )
        videos = pd.read_sql_query(
            """
            SELECT v.video_id, v.title, ch.label AS channel_label, v.published_at,
                   COUNT(c.comment_id) AS n_comments,
                   AVG(c.sentiment_polarity) AS avg_polarity
            FROM videos v
            JOIN channels ch ON ch.channel_id = v.channel_id
            LEFT JOIN comments c ON c.video_id = v.video_id AND c.sentiment_polarity IS NOT NULL
            GROUP BY v.video_id
            HAVING n_comments > 0
            ORDER BY n_comments DESC
            """,
            conn,
        )
        runs = pd.read_sql_query(
            "SELECT * FROM pipeline_runs ORDER BY run_id DESC", conn
        )
        totals = pd.read_sql_query(
            """
            SELECT
                (SELECT COUNT(*) FROM channels) AS channels,
                (SELECT COUNT(*) FROM videos) AS videos,
                (SELECT COUNT(*) FROM comments) AS comments,
                (SELECT COUNT(*) FROM comments WHERE sentiment_polarity IS NOT NULL) AS scored
            """,
            conn,
        ).iloc[0]
    finally:
        conn.close()
    return mentions, videos, runs, totals


def sentiment_badge(avg_polarity):
    if avg_polarity is None or pd.isna(avg_polarity):
        return MUTED_INK, "no data yet"
    if avg_polarity > 0.1:
        return GOOD, "net positive"
    if avg_polarity < -0.1:
        return CRITICAL, "net negative"
    return MUTED_INK, "net neutral"


def render_kpis(totals, runs, mentions_all):
    cols = st.columns(5)
    cols[0].metric("Channels tracked", int(totals["channels"]))
    cols[1].metric("Videos collected", int(totals["videos"]))

    comments_delta = None
    if len(runs) >= 2:
        comments_delta = int(runs.iloc[0]["comments_found"])
    cols[2].metric(
        "Comments collected", int(totals["comments"]),
        delta=(f"+{comments_delta} last run" if comments_delta else None),
    )
    cols[3].metric(
        "Scored for sentiment",
        int(totals["scored"]),
        help="Comments processed by attribute_and_score.py so far.",
    )

    overall_avg = mentions_all["sentiment_polarity"].mean() if not mentions_all.empty else None
    color, badge = sentiment_badge(overall_avg)
    with cols[4]:
        st.metric("Avg. sentiment (all candidates)", f"{overall_avg:.3f}" if overall_avg is not None else "—")
        st.markdown(
            f"<span style='color:{color}; font-weight:600'>&#9679; {badge}</span>",
            unsafe_allow_html=True,
        )

    if not runs.empty:
        last_run = runs.iloc[0]
        st.caption(
            f"Last pipeline run finished {last_run['finished_at']} • "
            f"{last_run['videos_found']} videos / {last_run['comments_found']} comments found • "
            f"{last_run['quota_units_used']} quota units used"
        )


def sentiment_mix_chart(mentions):
    """Diverging stacked bar: share of negative/neutral/positive per candidate,
    centered on zero (neutral split evenly across the midline)."""
    rows = []
    for cand in CANDIDATE_ORDER:
        sub = mentions[mentions["candidate"] == cand]
        if sub.empty:
            continue
        counts = sub["sentiment_label"].value_counts(normalize=True) * 100
        rows.append({
            "candidate": cand,
            "negative": counts.get("negative", 0.0),
            "neutral": counts.get("neutral", 0.0),
            "positive": counts.get("positive", 0.0),
            "n": len(sub),
        })
    if not rows:
        st.info("No candidate-attributed comments yet for this filter -- check back after the next pipeline run.")
        return
    df = pd.DataFrame(rows)

    fig = go.Figure()
    labels = [CANDIDATE_LABELS[c] for c in df["candidate"]]
    fig.add_trace(go.Bar(
        y=labels, x=-df["negative"], orientation="h", name="Negative",
        marker_color=SENTIMENT_COLORS["negative"],
        hovertemplate="Negative: %{customdata:.1f}%<extra></extra>", customdata=df["negative"],
    ))
    fig.add_trace(go.Bar(
        y=labels, x=-df["neutral"] / 2, orientation="h", name="Neutral",
        marker_color=SENTIMENT_COLORS["neutral"], showlegend=False,
        hovertemplate="Neutral: %{customdata:.1f}%<extra></extra>", customdata=df["neutral"],
    ))
    fig.add_trace(go.Bar(
        y=labels, x=df["neutral"] / 2, orientation="h", name="Neutral",
        marker_color=SENTIMENT_COLORS["neutral"],
        hovertemplate="Neutral: %{customdata:.1f}%<extra></extra>", customdata=df["neutral"],
    ))
    fig.add_trace(go.Bar(
        y=labels, x=df["positive"], orientation="h", name="Positive",
        marker_color=SENTIMENT_COLORS["positive"],
        hovertemplate="Positive: %{customdata:.1f}%<extra></extra>", customdata=df["positive"],
    ))
    fig.update_layout(
        **BASE_LAYOUT,
        barmode="relative",
        height=110 + 60 * len(df),
        xaxis=dict(title="Share of comments (%)", zeroline=True, zerolinecolor=INK, gridcolor=GRID, ticksuffix="%"),
        yaxis=dict(gridcolor=GRID),
        title="Sentiment mix by candidate",
    )
    st.plotly_chart(fig, width="stretch")


def candidate_bar_chart(mentions):
    rows = []
    for cand in CANDIDATE_ORDER:
        sub = mentions[mentions["candidate"] == cand]
        if sub.empty:
            continue
        rows.append({"candidate": cand, "avg_polarity": sub["sentiment_polarity"].mean(), "n": len(sub)})
    if not rows:
        st.info("No candidate-attributed comments yet for this filter.")
        return
    df = pd.DataFrame(rows)

    fig = go.Figure(go.Bar(
        x=[CANDIDATE_LABELS[c] for c in df["candidate"]],
        y=df["avg_polarity"],
        marker_color=[CANDIDATE_COLORS[c] for c in df["candidate"]],
        text=[f"n={n}" for n in df["n"]],
        textposition="outside",
        hovertemplate="%{x}<br>Avg. polarity: %{y:.3f}<extra></extra>",
    ))
    fig.update_layout(
        **BASE_LAYOUT,
        showlegend=False,
        height=340,
        yaxis=dict(title="Average sentiment polarity (-1 to 1)", zeroline=True, zerolinecolor=INK, gridcolor=GRID),
        title="Average sentiment by candidate",
    )
    st.plotly_chart(fig, width="stretch")


def trend_chart(mentions):
    if mentions.empty:
        st.info("No data yet for this filter.")
        return
    df = mentions.copy()
    df["day"] = df["published_at"].dt.floor("D")
    span_days = (df["day"].max() - df["day"].min()).days
    freq = "W" if span_days > 45 else "D"

    fig = go.Figure()
    any_series = False
    for cand in CANDIDATE_ORDER:
        sub = df[df["candidate"] == cand]
        if sub.empty:
            continue
        grouped = sub.set_index("published_at").resample(freq)["sentiment_polarity"].mean().dropna()
        if grouped.empty:
            continue
        any_series = True
        fig.add_trace(go.Scatter(
            x=grouped.index, y=grouped.values, mode="lines+markers", name=CANDIDATE_LABELS[cand],
            line=dict(color=CANDIDATE_COLORS[cand], width=2), marker=dict(size=8),
            hovertemplate="%{x|%b %d}<br>" + CANDIDATE_LABELS[cand] + ": %{y:.3f}<extra></extra>",
        ))
    if not any_series:
        st.info("Not enough data yet to plot a trend.")
        return
    fig.update_layout(
        **BASE_LAYOUT,
        height=360,
        yaxis=dict(title="Average sentiment polarity", zeroline=True, zerolinecolor=INK, gridcolor=GRID),
        xaxis=dict(gridcolor=GRID),
        title=f"Sentiment trend over time ({'weekly' if freq == 'W' else 'daily'} average)",
    )
    st.plotly_chart(fig, width="stretch")


def category_heatmap(mentions):
    if mentions.empty or mentions["category"].nunique() == 0:
        st.info("No data yet for this filter.")
        return
    pivot = mentions.pivot_table(
        index="category", columns="candidate", values="sentiment_polarity", aggfunc="mean"
    )
    pivot = pivot.reindex(columns=[c for c in CANDIDATE_ORDER if c in pivot.columns])
    if pivot.empty:
        st.info("No data yet for this filter.")
        return
    counts = mentions.pivot_table(
        index="category", columns="candidate", values="sentiment_polarity", aggfunc="count"
    ).reindex(columns=pivot.columns)

    fig = go.Figure(go.Heatmap(
        z=pivot.values,
        x=[CANDIDATE_LABELS[c] for c in pivot.columns],
        y=[c.replace("_", " ").title() for c in pivot.index],
        colorscale=[[0, "#e34948"], [0.5, "#f0efec"], [1, "#2a78d6"]],
        zmid=0, zmin=-1, zmax=1,
        customdata=counts.values,
        hovertemplate="%{y} × %{x}<br>Avg. polarity: %{z:.3f}<br>n=%{customdata}<extra></extra>",
        colorbar=dict(title="Polarity"),
    ))
    fig.update_layout(
        **BASE_LAYOUT,
        height=90 + 50 * len(pivot),
        title="Average sentiment by outlet category × candidate",
    )
    st.plotly_chart(fig, width="stretch")


def top_videos_table(videos):
    if videos.empty:
        st.info("No videos with scored comments yet.")
        return
    df = videos.head(15).copy()
    df["avg_polarity"] = df["avg_polarity"].round(3)
    st.dataframe(
        df[["title", "channel_label", "n_comments", "avg_polarity"]].rename(columns={
            "title": "Video", "channel_label": "Channel", "n_comments": "Comments", "avg_polarity": "Avg. polarity",
        }),
        width="stretch", hide_index=True,
    )


def render_body(mentions_all, videos, runs, totals, candidates_sel, categories_sel, date_range):
    render_kpis(totals, runs, mentions_all)
    st.caption(f"Live view • refreshed {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")
    st.divider()

    mentions = mentions_all[mentions_all["candidate"].isin(candidates_sel)]
    if categories_sel:
        mentions = mentions[mentions["category"].isin(categories_sel)]
    if date_range and len(date_range) == 2:
        start, end = pd.Timestamp(date_range[0], tz="UTC"), pd.Timestamp(date_range[1], tz="UTC") + pd.Timedelta(days=1)
        mentions = mentions[(mentions["published_at"] >= start) & (mentions["published_at"] < end)]

    left, right = st.columns(2)
    with left:
        sentiment_mix_chart(mentions)
    with right:
        candidate_bar_chart(mentions)

    trend_chart(mentions)
    category_heatmap(mentions)

    st.subheader("Most-discussed videos")
    top_videos_table(videos)

    with st.expander("View filtered comment-level data (table view)"):
        st.dataframe(
            mentions[["published_at", "candidate", "channel_label", "category", "sentiment_label", "sentiment_polarity"]]
            .sort_values("published_at", ascending=False),
            width="stretch", hide_index=True,
        )

    with st.expander("Pipeline run history"):
        st.dataframe(runs, width="stretch", hide_index=True)


def main():
    st.title("\U0001F5F3 Nigeria 2027 Election Sentiment — Live Dashboard")
    st.caption(
        "YouTube comment sentiment for Tinubu (APC), Atiku (ADC), and Peter Obi (NDC), "
        "collected daily. This page keeps itself current as new data is scraped -- no need to reload."
    )

    if not os.path.exists(DB_PATH):
        st.error(f"Database not found at `{DB_PATH}`. Run `python run_pipeline.py` at least once first.")
        return

    with st.sidebar:
        st.header("Filters")
        candidates_sel = st.multiselect(
            "Candidates", options=CANDIDATE_ORDER, default=CANDIDATE_ORDER,
            format_func=lambda c: CANDIDATE_LABELS[c],
        )
        mentions_probe, _, _, _ = load_data(DB_PATH)
        category_options = sorted(mentions_probe["category"].dropna().unique().tolist()) if not mentions_probe.empty else []
        categories_sel = st.multiselect("Outlet category", options=category_options, default=[])

        date_range = None
        if not mentions_probe.empty:
            min_d = mentions_probe["published_at"].min().date()
            max_d = mentions_probe["published_at"].max().date()
            if min_d < max_d:
                date_range = st.date_input("Date range", value=(min_d, max_d), min_value=min_d, max_value=max_d)

        st.divider()
        st.header("Live updates")
        auto_refresh = st.toggle("Auto-refresh", value=True)
        interval_label = st.selectbox("Refresh every", options=list(REFRESH_OPTIONS.keys()), index=1, disabled=not auto_refresh)
        if st.button("Refresh now"):
            load_data.clear()
            st.rerun()

    if not candidates_sel:
        candidates_sel = CANDIDATE_ORDER

    if auto_refresh:
        interval = REFRESH_OPTIONS[interval_label]

        @st.fragment(run_every=f"{interval}s")
        def live_body():
            mentions_all, videos, runs, totals = load_data(DB_PATH)
            render_body(mentions_all, videos, runs, totals, candidates_sel, categories_sel, date_range)

        live_body()
    else:
        mentions_all, videos, runs, totals = load_data(DB_PATH)
        render_body(mentions_all, videos, runs, totals, candidates_sel, categories_sel, date_range)


if __name__ == "__main__":
    main()
