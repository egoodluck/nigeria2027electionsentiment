"""
Analytics layer: everything the pages compute from the fact tables.

Pure functions over pandas frames -- no Streamlit, no I/O -- so they can be
unit-tested and reused by the pipeline. Formulas are documented inline and
restated on the Methodology page; keep the two in sync.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from pipeline.settings import (
    ALL_KEY,
    CANDIDATE_ORDER,
    CANDIDATES,
    MANIPULATION_BANDS,
    MIN_N_FOR_RATE,
    TOPIC_LABELS,
)

Z95 = 1.959964


# ------------------------------------------------------------------ basics

def net_sentiment(n_pos, n_neg, n) -> float:
    return float((n_pos - n_neg) / n) if n else float("nan")


def net_ci(n_pos, n_neg, n, z=Z95) -> tuple[float, float]:
    """95% CI for the mean of a {-1, 0, +1} variable (net sentiment)."""
    if not n:
        return (float("nan"), float("nan"))
    net = (n_pos - n_neg) / n
    var = (n_pos + n_neg) / n - net ** 2
    se = math.sqrt(max(var, 0) / n)
    return (max(-1.0, net - z * se), min(1.0, net + z * se))


def summarize(df: pd.DataFrame) -> dict:
    """Totals for any slice of fact_daily."""
    if df is None or df.empty:
        return dict(n=0, n_pos=0, n_neu=0, n_neg=0, pos_share=np.nan, neu_share=np.nan, neg_share=np.nan,
                    net=np.nan, ci=(np.nan, np.nan), likes=0, flagged=0, flagged_share=np.nan, videos=0,
                    conf=np.nan, days=0)
    n = int(df["n"].sum())
    pos, neu, neg = int(df["n_pos"].sum()), int(df["n_neu"].sum()), int(df["n_neg"].sum())
    likes = int(df["sum_likes"].sum()) if "sum_likes" in df else 0
    flagged = int(df["n_flagged"].sum()) if "n_flagged" in df else 0
    conf = float(df["sum_conf"].sum() / n) if "sum_conf" in df and n else np.nan
    return dict(
        n=n, n_pos=pos, n_neu=neu, n_neg=neg,
        pos_share=pos / n if n else np.nan, neu_share=neu / n if n else np.nan, neg_share=neg / n if n else np.nan,
        net=net_sentiment(pos, neg, n), ci=net_ci(pos, neg, n), likes=likes, flagged=flagged,
        flagged_share=flagged / n if n else np.nan, videos=int(df["n_videos"].sum()) if "n_videos" in df else 0,
        conf=conf, days=int(df["day"].nunique()) if "day" in df else 0,
    )


def filter_facts(df: pd.DataFrame, start=None, end=None, categories=None, channels=None, candidates=None) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    m = pd.Series(True, index=df.index)
    if start is not None:
        m &= df["day"] >= pd.Timestamp(start)
    if end is not None:
        m &= df["day"] <= pd.Timestamp(end)
    if categories:
        m &= df["category"].isin(categories)
    if channels:
        m &= df["channel"].isin(channels)
    if candidates:
        m &= df["candidate"].isin(candidates)
    return df[m]


def candidates_only(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["candidate"].isin(CANDIDATE_ORDER)] if df is not None and not df.empty else df


def all_comments(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["candidate"] == ALL_KEY] if df is not None and not df.empty else df


# ----------------------------------------------------------- time series

def daily_series(df: pd.DataFrame, by: str = "candidate", window: int = 7, min_n: int = 1) -> pd.DataFrame:
    """Daily totals per `by` with a volume-weighted rolling net sentiment.

    rolling_net = sum(pos - neg over window) / sum(n over window); days with
    fewer than `min_n` mentions have NaN point estimates but still feed the
    rolling sums."""
    if df is None or df.empty:
        return pd.DataFrame(columns=[by, "day", "n", "n_pos", "n_neu", "n_neg", "net", "rolling_net", "rolling_n", "likes"])
    g = df.groupby([by, "day"], as_index=False).agg(
        n=("n", "sum"), n_pos=("n_pos", "sum"), n_neu=("n_neu", "sum"), n_neg=("n_neg", "sum"),
        likes=("sum_likes", "sum") if "sum_likes" in df else ("n", "size"),
        flagged=("n_flagged", "sum") if "n_flagged" in df else ("n", "size"),
    )
    out = []
    for key, sub in g.groupby(by):
        idx = pd.date_range(sub["day"].min(), sub["day"].max(), freq="D")
        s = sub.set_index("day").reindex(idx).fillna(0)
        s[by] = key
        s["net"] = np.where(s["n"] >= min_n, (s["n_pos"] - s["n_neg"]) / s["n"].replace(0, np.nan), np.nan)
        roll_pn = (s["n_pos"] - s["n_neg"]).rolling(window, min_periods=1).sum()
        roll_n = s["n"].rolling(window, min_periods=1).sum()
        s["rolling_net"] = roll_pn / roll_n.replace(0, np.nan)
        s["rolling_n"] = roll_n
        s["rolling_vol"] = s["n"].rolling(window, min_periods=1).mean()
        ci = [net_ci(p, q, n) if n else (np.nan, np.nan) for p, q, n in zip(
            s["n_pos"].rolling(window, min_periods=1).sum(), s["n_neg"].rolling(window, min_periods=1).sum(), roll_n)]
        s["rolling_lo"] = [c[0] for c in ci]
        s["rolling_hi"] = [c[1] for c in ci]
        s = s.reset_index().rename(columns={"index": "day"})
        out.append(s)
    return pd.concat(out, ignore_index=True)


def weekly_series(df: pd.DataFrame, by: str = "candidate") -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    w = df.copy()
    w["week"] = w["day"].dt.to_period("W-SUN").dt.start_time
    g = w.groupby([by, "week"], as_index=False).agg(n=("n", "sum"), n_pos=("n_pos", "sum"), n_neg=("n_neg", "sum"),
                                                   likes=("sum_likes", "sum"))
    g["net"] = (g["n_pos"] - g["n_neg"]) / g["n"].replace(0, np.nan)
    return g


# ------------------------------------------------------------ comparisons

@dataclass
class PeriodCompare:
    label: str
    cur_start: pd.Timestamp
    cur_end: pd.Timestamp
    prev_start: pd.Timestamp
    prev_end: pd.Timestamp
    current: dict = field(default_factory=dict)   # candidate -> summary
    previous: dict = field(default_factory=dict)


def period_windows(end: pd.Timestamp, days: int) -> tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]:
    end = pd.Timestamp(end).normalize()
    cur_start = end - pd.Timedelta(days=days - 1)
    prev_end = cur_start - pd.Timedelta(days=1)
    prev_start = prev_end - pd.Timedelta(days=days - 1)
    return cur_start, end, prev_start, prev_end


def compare_periods(df: pd.DataFrame, end: pd.Timestamp, days: int, label: str = "") -> PeriodCompare:
    cs, ce, ps, pe = period_windows(end, days)
    pc = PeriodCompare(label or f"{days}-day", cs, ce, ps, pe)
    for cand in CANDIDATE_ORDER + [ALL_KEY]:
        sub = df[df["candidate"] == cand] if df is not None and not df.empty else df
        pc.current[cand] = summarize(filter_facts(sub, cs, ce))
        pc.previous[cand] = summarize(filter_facts(sub, ps, pe))
    return pc


def pct_change(cur, prev) -> float:
    if prev in (0, None) or (isinstance(prev, float) and math.isnan(prev)):
        return float("nan")
    return (cur - prev) / abs(prev)


def share_of_voice(summaries: dict) -> dict:
    total = sum(summaries[c]["n"] for c in CANDIDATE_ORDER if c in summaries)
    return {c: (summaries[c]["n"] / total if total else np.nan) for c in CANDIDATE_ORDER if c in summaries}


def engagement_share(summaries: dict) -> dict:
    total = sum(summaries[c]["likes"] for c in CANDIDATE_ORDER if c in summaries)
    return {c: (summaries[c]["likes"] / total if total else np.nan) for c in CANDIDATE_ORDER if c in summaries}


# ------------------------------------------------------------------ indices

def _squash(x: float, scale: float) -> float:
    """Map a change onto (0, 1) with 0.5 = no change. tanh keeps outliers bounded."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return 0.5
    return 0.5 + 0.5 * math.tanh(x / scale)


def momentum_index(df: pd.DataFrame, end: pd.Timestamp, days: int = 7) -> pd.DataFrame:
    """Candidate Momentum Index (0-100).

      40%  sentiment trend     : change in net sentiment vs the previous window,
                                 squashed with tanh(d / 0.15)
      30%  engagement growth   : relative change in likes on mentions, tanh(g / 1.0)
      20%  discussion growth   : relative change in mention count, tanh(g / 1.0)
      10%  consistency         : 1 - min(1, sd(daily net) / 0.5) over days with >= 5 mentions
    50 means "no change"; > 50 gaining, < 50 losing.
    """
    pc = compare_periods(df, end, days)
    daily = daily_series(candidates_only(df), window=1, min_n=5)
    rows = []
    for cand in CANDIDATE_ORDER:
        cur, prev = pc.current[cand], pc.previous[cand]
        d_net = (cur["net"] - prev["net"]) if not (np.isnan(cur["net"]) or np.isnan(prev["net"])) else np.nan
        g_eng = pct_change(cur["likes"], prev["likes"]) if prev["likes"] else (1.0 if cur["likes"] else np.nan)
        g_vol = pct_change(cur["n"], prev["n"]) if prev["n"] else (1.0 if cur["n"] else np.nan)
        dsub = daily[(daily["candidate"] == cand) & (daily["day"] >= pc.cur_start) & (daily["day"] <= pc.cur_end)]
        valid = dsub["net"].dropna()
        consistency = 1 - min(1.0, float(valid.std(ddof=0)) / 0.5) if len(valid) >= 3 else 0.5
        comp = dict(sentiment=_squash(d_net, 0.15), engagement=_squash(g_eng, 1.0),
                    discussion=_squash(g_vol, 1.0), consistency=consistency)
        score = 100 * (0.4 * comp["sentiment"] + 0.3 * comp["engagement"] + 0.2 * comp["discussion"] + 0.1 * comp["consistency"])
        rows.append(dict(candidate=cand, momentum=round(score, 1), d_net=d_net, g_eng=g_eng, g_vol=g_vol,
                         consistency=consistency, n_cur=cur["n"], n_prev=prev["n"], net_cur=cur["net"], net_prev=prev["net"],
                         likes_cur=cur["likes"], likes_prev=prev["likes"], **{f"c_{k}": v for k, v in comp.items()}))
    return pd.DataFrame(rows)


def influence_index(df: pd.DataFrame, end: pd.Timestamp, days: int = 7, momentum: pd.DataFrame | None = None) -> pd.DataFrame:
    """Election Influence Index (0-100).

      35%  sentiment      : (net + 1) / 2 over the window
      25%  mention share  : share of voice among the three candidates
      20%  engagement     : share of likes received among the three candidates
      20%  momentum       : Candidate Momentum Index / 100
    Reported with the change from the previous window and a rank.
    """
    if momentum is None:
        momentum = momentum_index(df, end, days)
    pc = compare_periods(df, end, days)
    prev_end = pc.prev_end
    mom_prev = momentum_index(df, prev_end, days)
    sov, eng = share_of_voice(pc.current), engagement_share(pc.current)
    sov_p, eng_p = share_of_voice(pc.previous), engagement_share(pc.previous)

    def score(summ, sov_c, eng_c, mom_c):
        sent = (summ["net"] + 1) / 2 if not np.isnan(summ["net"]) else 0.5
        return 100 * (0.35 * sent + 0.25 * (0 if np.isnan(sov_c) else sov_c) + 0.20 * (0 if np.isnan(eng_c) else eng_c) + 0.20 * mom_c / 100)

    rows = []
    for cand in CANDIDATE_ORDER:
        m_c = float(momentum.loc[momentum["candidate"] == cand, "momentum"].iloc[0])
        m_p = float(mom_prev.loc[mom_prev["candidate"] == cand, "momentum"].iloc[0])
        cur = score(pc.current[cand], sov[cand], eng[cand], m_c)
        prev = score(pc.previous[cand], sov_p[cand], eng_p[cand], m_p)
        rows.append(dict(candidate=cand, influence=round(cur, 1), influence_prev=round(prev, 1), change=round(cur - prev, 1),
                         sentiment=pc.current[cand]["net"], sov=sov[cand], engagement=eng[cand], momentum=m_c, n=pc.current[cand]["n"]))
    out = pd.DataFrame(rows).sort_values("influence", ascending=False).reset_index(drop=True)
    out["rank"] = np.arange(1, len(out) + 1)
    prev_rank = out.sort_values("influence_prev", ascending=False)["candidate"].tolist()
    out["rank_prev"] = out["candidate"].map({c: i + 1 for i, c in enumerate(prev_rank)})
    return out


def index_trajectory(df: pd.DataFrame, end: pd.Timestamp, days: int = 7, weeks: int = 12) -> pd.DataFrame:
    """Momentum and influence recomputed at each weekly anchor for the trajectory chart."""
    rows = []
    end = pd.Timestamp(end).normalize()
    start_floor = df["day"].min() + pd.Timedelta(days=2 * days) if df is not None and not df.empty else end
    for k in range(weeks):
        anchor = end - pd.Timedelta(days=7 * k)
        if anchor < start_floor:
            break
        mom = momentum_index(df, anchor, days)
        inf = influence_index(df, anchor, days, mom)
        for _, r in inf.iterrows():
            rows.append(dict(anchor=anchor, candidate=r["candidate"], influence=r["influence"], momentum=r["momentum"],
                             sov=r["sov"], sentiment=r["sentiment"]))
    return pd.DataFrame(rows).sort_values(["candidate", "anchor"]) if rows else pd.DataFrame()


# ------------------------------------------------------------- topics

def topic_table(ft: pd.DataFrame, start=None, end=None, candidate: str | None = None, include_other=False) -> pd.DataFrame:
    if ft is None or ft.empty:
        return pd.DataFrame()
    sub = ft.copy()
    if start is not None:
        sub = sub[sub["day"] >= pd.Timestamp(start)]
    if end is not None:
        sub = sub[sub["day"] <= pd.Timestamp(end)]
    sub = sub[sub["candidate"] == (candidate or ALL_KEY)]
    if not include_other:
        sub = sub[sub["topic"] != "other"]
    g = sub.groupby("topic", as_index=False).agg(n=("n", "sum"), n_pos=("n_pos", "sum"), n_neg=("n_neg", "sum"), n_neu=("n_neu", "sum"))
    total = g["n"].sum()
    g["share"] = g["n"] / total if total else np.nan
    g["net"] = (g["n_pos"] - g["n_neg"]) / g["n"].replace(0, np.nan)
    g["label"] = g["topic"].map(lambda t: TOPIC_LABELS.get(t, t))
    return g.sort_values("n", ascending=False).reset_index(drop=True)


def topic_change(ft: pd.DataFrame, end: pd.Timestamp, days: int, candidate: str | None = None) -> pd.DataFrame:
    cs, ce, ps, pe = period_windows(end, days)
    cur = topic_table(ft, cs, ce, candidate).set_index("topic")
    prev = topic_table(ft, ps, pe, candidate).set_index("topic")
    out = cur.join(prev[["share", "n", "net"]], rsuffix="_prev", how="left").fillna({"share_prev": 0, "n_prev": 0})
    out["share_change_pp"] = (out["share"] - out["share_prev"]) * 100
    out["net_change"] = out["net"] - out["net_prev"]
    return out.reset_index()


# -------------------------------------------------------- manipulation

def manipulation_band(share: float) -> str:
    if share is None or (isinstance(share, float) and math.isnan(share)):
        return "n/a"
    for threshold, label in MANIPULATION_BANDS:
        if share < threshold:
            return label
    return MANIPULATION_BANDS[-1][1]


# ---------------------------------------------------------------- brief

def _fmt_pct(x, digits=0, signed=False):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "n/a"
    s = f"{x * 100:+.{digits}f}%" if signed else f"{x * 100:.{digits}f}%"
    return s


def _fmt_net(x, signed=True):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "n/a"
    return f"{x:+.2f}" if signed else f"{x:.2f}"


def _name(c):
    return CANDIDATES[c]["short"] if c in CANDIDATES else "all candidates"


def intelligence_brief(fd: pd.DataFrame, ft: pd.DataFrame, keywords: pd.DataFrame, end: pd.Timestamp, days: int,
                       period_word: str, mature_until: str | None, min_n: int = MIN_N_FOR_RATE,
                       last_day: str | None = None) -> dict:
    """Deterministic, template-based narrative from the fact tables. Returns
    {'paragraphs': [...], 'facts': [...], 'window': (start, end)}."""
    pc = compare_periods(fd, end, days)
    cur_all, prev_all = pc.current[ALL_KEY], pc.previous[ALL_KEY]
    cands = {c: pc.current[c] for c in CANDIDATE_ORDER}
    prevs = {c: pc.previous[c] for c in CANDIDATE_ORDER}
    paragraphs, facts = [], []
    span = f"{pc.cur_start:%d %b} – {pc.cur_end:%d %b %Y}"

    if cur_all["n"] == 0:
        return {"paragraphs": [f"No comments were collected for the {period_word} ending {pc.cur_end:%d %b %Y}."],
                "facts": [], "window": (pc.cur_start, pc.cur_end), "compare": pc, "lagging": False}

    # 1. Volume
    total_mentions = sum(s["n"] for s in cands.values())
    prev_mentions = sum(s["n"] for s in prevs.values())
    chg = pct_change(total_mentions, prev_mentions)
    # A sharp recorded drop inside the last ~10 days of data is usually collection
    # lag (comments still arriving, or a run that did not reach every video), not
    # a real fall in discussion. Say so instead of asserting a decline.
    lagging = (not np.isnan(chg) and chg < -0.4 and last_day is not None
               and (pd.Timestamp(last_day) - pc.cur_end).days <= 10)
    if np.isnan(chg):
        lead = f"{total_mentions:,} candidate mentions were recorded across {cur_all['n']:,} comments ({span})."
    elif lagging:
        lead = (f"Recorded discussion volume was {_fmt_pct(abs(chg))} lower than the previous {period_word} "
                f"({total_mentions:,} candidate mentions across {cur_all['n']:,} comments, {span}); much of that gap is "
                f"collection lag — comments on recent videos are still being gathered — so treat the decline as provisional.")
    else:
        verb = "rose" if chg > 0.02 else "fell" if chg < -0.02 else "was flat"
        amount = f" {_fmt_pct(abs(chg))}" if abs(chg) > 0.02 else ""
        lead = (f"Discussion volume {verb}{amount} {period_word}-on-{period_word} to {total_mentions:,} candidate mentions "
                f"across {cur_all['n']:,} comments ({span}).")
    paragraphs.append(lead)
    facts.append(("Volume", f"{total_mentions:,} mentions" + (" (provisional)" if lagging else ""),
                  "neu" if lagging or np.isnan(chg) or abs(chg) <= 0.02 else ("pos" if chg > 0 else "neg")))

    # 2. Sentiment movers
    movers = []
    for c in CANDIDATE_ORDER:
        s, p = cands[c], prevs[c]
        if s["n"] >= min_n and p["n"] >= min_n:
            movers.append((c, s["net"] - p["net"], s["net"]))
    sent_sentence = ""
    if movers:
        best = max(movers, key=lambda x: x[1])
        worst = min(movers, key=lambda x: x[1])
        if best[1] > 0.02:
            sent_sentence = (f"{_name(best[0])} recorded the strongest sentiment gain ({best[1] * 100:+.0f} pts to a net score of "
                             f"{_fmt_net(best[2])}, n = {cands[best[0]]['n']:,})")
            facts.append(("Sentiment gain", f"{_name(best[0])} {best[1] * 100:+.0f} pts", "pos"))
        else:
            steadiest = max(movers, key=lambda x: x[2])
            sent_sentence = f"No candidate improved materially; {_name(steadiest[0])} held the highest net sentiment ({_fmt_net(steadiest[2])})"
        if worst[0] != best[0] and worst[1] < -0.02:
            sent_sentence += f", while {_name(worst[0])} slipped {abs(worst[1]) * 100:.0f} pts to {_fmt_net(worst[2])} (n = {cands[worst[0]]['n']:,})"
            facts.append(("Sentiment loss", f"{_name(worst[0])} {worst[1] * 100:+.0f} pts", "neg"))
        sent_sentence += "."
    else:
        ranked = sorted(((c, s["net"]) for c, s in cands.items() if s["n"] >= min_n), key=lambda x: -x[1])
        if ranked:
            sent_sentence = (f"Net sentiment this {period_word}: " +
                             ", ".join(f"{_name(c)} {_fmt_net(v)}" for c, v in ranked) + " (too little prior data for a comparison).")

    # 3. Visibility
    sov = share_of_voice(cands)
    sov_prev = share_of_voice(prevs)
    top = max(sov, key=lambda c: (sov[c] if not np.isnan(sov[c]) else -1))
    vis_sentence = f"{_name(top)} maintained the highest visibility with {_fmt_pct(sov[top])} share of voice"
    others = [c for c in CANDIDATE_ORDER if c != top]
    gains = [(c, sov[c] - sov_prev[c]) for c in others if not np.isnan(sov_prev.get(c, np.nan))]
    if gains:
        g = max(gains, key=lambda x: x[1])
        if g[1] > 0.01:
            vis_sentence += f"; {_name(g[0])} gained the most share ({g[1] * 100:+.0f} pts to {_fmt_pct(sov[g[0]])})"
    vis_sentence += "."
    facts.append(("Share of voice", f"{_name(top)} {_fmt_pct(sov[top])}", "brand"))
    paragraphs.append(" ".join(x for x in (sent_sentence, vis_sentence) if x))

    # 4. Outlets
    cur_slice = filter_facts(candidates_only(fd), pc.cur_start, pc.cur_end)
    if cur_slice is not None and not cur_slice.empty:
        by_cat = cur_slice.groupby("category")["n"].sum().sort_values(ascending=False)
        from app.data import category_phrase  # local import keeps analytics UI-agnostic elsewhere
        top_cat = by_cat.index[0]
        cat_share = by_cat.iloc[0] / by_cat.sum()
        cat_slice = cur_slice[cur_slice["category"] == top_cat]
        cat_summ = {c: summarize(cat_slice[cat_slice["candidate"] == c]) for c in CANDIDATE_ORDER}
        eligible = {c: s for c, s in cat_summ.items() if s["n"] >= min_n}
        outlet_sentence = f"{category_phrase(top_cat)} generated {_fmt_pct(cat_share)} of candidate mentions"
        if len(eligible) >= 2:
            best_c = max(eligible, key=lambda c: eligible[c]["net"])
            worst_c = min(eligible, key=lambda c: eligible[c]["net"])
            gap = eligible[best_c]["net"] - eligible[worst_c]["net"]
            if gap >= 0.05:
                outlet_sentence += (f", where {_name(best_c)} drew the most favourable reaction ({_fmt_net(eligible[best_c]['net'])}) "
                                    f"and {_name(worst_c)} the least ({_fmt_net(eligible[worst_c]['net'])})")
            else:
                outlet_sentence += ", with little difference in how the three candidates were received there"
        outlet_sentence += "."
        if len(by_cat) > 1:
            second = by_cat.index[1]
            s2 = cur_slice[cur_slice["category"] == second]
            s2_summ = {c: summarize(s2[s2["candidate"] == c]) for c in CANDIDATE_ORDER}
            s2_el = {c: s for c, s in s2_summ.items() if s["n"] >= min_n}
            if s2_el:
                lead2 = max(s2_el, key=lambda c: s2_el[c]["n"])
                outlet_sentence += f" Across {category_phrase(second).lower()}, {_name(lead2)} was the most discussed candidate."
        paragraphs.append(outlet_sentence)

    # 5. Topics
    if ft is not None and not ft.empty:
        tc = topic_change(ft, end, days)
        tc = tc[tc["n"] >= min_n]
        if not tc.empty:
            top_t = tc.sort_values("n", ascending=False).iloc[0]
            rising = tc.sort_values("share_change_pp", ascending=False).iloc[0]
            topic_sentence = f"The dominant issue was {top_t['label'].lower()} ({_fmt_pct(top_t['share'])} of topic-tagged comments"
            if not np.isnan(top_t["net"]):
                topic_sentence += f", net sentiment {_fmt_net(top_t['net'])}"
            topic_sentence += ")"
            if rising["topic"] != top_t["topic"] and rising["share_change_pp"] > 1:
                topic_sentence += f"; {rising['label'].lower()} rose fastest ({rising['share_change_pp']:+.0f} pts)"
            topic_sentence += "."
            facts.append(("Top issue", top_t["label"], "amber"))
            paragraphs.append(topic_sentence)

    # 6. Keywords (emerging)
    if keywords is not None and not keywords.empty:
        em = keywords[(keywords["polarity"] == "emerging") & (keywords["rank"] <= 3)]
        if not em.empty:
            bits = []
            for c in CANDIDATE_ORDER:
                terms = em[em["candidate"] == c]["term"].tolist()
                if terms:
                    bits.append(f"{_name(c)}: {', '.join(terms)}")
            if bits:
                paragraphs.append("Newly trending terms in the latest seven days — " + "; ".join(bits) + ".")

    # 7. Authenticity
    flagged_share = cur_all["flagged_share"]
    band = manipulation_band(flagged_share)
    if not np.isnan(flagged_share):
        paragraphs.append(
            f"Authenticity signals were {band.lower()}: {_fmt_pct(flagged_share, 1)} of comments this {period_word} matched "
            f"duplicate-text or burst-posting patterns. Indicators are observational, not proof of coordination.")
        facts.append(("Manipulation risk", band, "neg" if band == "High" else "amber" if band == "Medium" else "pos"))

    # 8. Maturity caveat
    if mature_until and pd.Timestamp(mature_until) < pc.cur_end:
        paragraphs.append(
            f"Figures after {pd.Timestamp(mature_until):%d %b} are still accumulating: YouTube comments keep arriving on recent "
            f"videos for several days, so the most recent counts will rise at the next collection run.")

    return {"paragraphs": paragraphs, "facts": facts, "window": (pc.cur_start, pc.cur_end), "compare": pc, "lagging": lagging}
