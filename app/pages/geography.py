"""Geography: conversation geography (state mentions) with explicit limitations, zone view, vernacular-language proxy."""

import numpy as np
import pandas as pd
import streamlit as st

from app import analytics as an
from app import charts, components as ui, theme
from app.data import db_signature, load_fact_daily, load_fact_location, load_geojson, meta
from app.state import sidebar_controls
from pipeline.settings import ALL_KEY, CANDIDATE_ORDER, MIN_N_FOR_RATE, STATE_TO_ZONE, ZONES

f = sidebar_controls()
m = meta()
sig = db_signature()
ui.page_header("Geography", "YouTube does not expose where commenters are, so audience geography cannot be measured from this data. What can be "
               "measured honestly is <b>conversation geography</b> — which states and zones the comments talk about — and a soft "
               "language proxy from vernacular channels.")

ui.note("<b>Read this first.</b> The map shows where the conversation points, not where commenters live. A comment such as "
        "<i>“no roads in Benue”</i> counts for Benue regardless of who wrote it or where. Video, channel and comment metadata from the "
        "YouTube Data API carry no location fields, and inferring commenter location from names or language would be unreliable and "
        "ethically questionable, so it is not attempted. Nothing on this page is fabricated or imputed.", "amber")

fl = load_fact_location(sig, f.model)
if fl.empty:
    ui.empty_state("State-mention tables are not available yet. Run `python -m pipeline.enrich --only locations aggregates`.")
    st.stop()
if f.categories or f.channels:
    ui.caption("State-mention tables are aggregated across all outlets; the outlet filters do not apply here.")

fl = fl[(fl["day"] >= f.start) & (fl["day"] <= f.end)]
cand_options = {ALL_KEY: "All comments", **{c: theme.candidate_label(c, "party") for c in CANDIDATE_ORDER}}
focus = st.segmented_control("Focus", list(cand_options.keys()), format_func=lambda k: cand_options[k], default=ALL_KEY, key="ge_focus") or ALL_KEY
metric = st.segmented_control("Colour by", ["Mentions", "Net sentiment"], default="Mentions", key="ge_metric") or "Mentions"

sub = fl[fl["candidate"] == focus].groupby("state", as_index=False).agg(n=("n", "sum"), n_pos=("n_pos", "sum"), n_neg=("n_neg", "sum"))
all_states = pd.DataFrame({"state": sorted(STATE_TO_ZONE.keys())})
sub = all_states.merge(sub, on="state", how="left").fillna(0)
sub["net"] = np.where(sub["n"] > 0, (sub["n_pos"] - sub["n_neg"]) / sub["n"].replace(0, np.nan), np.nan)
sub["zone"] = sub["state"].map(STATE_TO_ZONE)

geo = load_geojson()
c1, c2 = st.columns([1.5, 1])
with c1:
    if geo is None:
        ui.empty_state("Map boundaries not found (app/assets/nigeria_states.geojson).")
    elif metric == "Mentions":
        st.plotly_chart(charts.choropleth(sub, geo, "n", f"Comments mentioning each state — {cand_options[focus].lower()}", "Mentions",
                                          diverging=False, min_n=1), width="stretch", config=theme.PLOTLY_CONFIG, key="ge_map_n")
    else:
        st.plotly_chart(charts.choropleth(sub, geo, "net", f"Net sentiment of comments mentioning each state — {cand_options[focus].lower()}",
                                          "Net sentiment", diverging=True, min_n=MIN_N_FOR_RATE), width="stretch", config=theme.PLOTLY_CONFIG, key="ge_map_net")
        ui.caption(f"States with fewer than {MIN_N_FOR_RATE} mentions are outlined only.")
    ui.caption("Boundaries: geoBoundaries (gbOpen) ADM1, CC BY 4.0, simplified for the web.")
with c2:
    zone = sub.groupby("zone", as_index=False).agg(n=("n", "sum"), n_pos=("n_pos", "sum"), n_neg=("n_neg", "sum"))
    zone["net"] = (zone["n_pos"] - zone["n_neg"]) / zone["n"].replace(0, np.nan)
    zone["share"] = zone["n"] / zone["n"].sum() if zone["n"].sum() else np.nan
    st.plotly_chart(charts.ranked_bars(zone, "n", "zone", "Mentions by geopolitical zone", value_fmt=",.0f",
                                       hover_extra="%{x:,} mentions · %{customdata[0]:.0%} of state mentions · net %{customdata[1]:+.2f}",
                                       customdata=np.stack([zone["share"], zone["net"]], axis=-1), height=300),
                    width="stretch", config=theme.PLOTLY_CONFIG, key="ge_zone")
    top = sub[sub["n"] > 0].sort_values("n", ascending=False).head(12)
    st.plotly_chart(charts.ranked_bars(top, "n", "state", "Most-mentioned states", value_fmt=",.0f",
                                       hover_extra="%{x:,} mentions · net %{customdata:+.2f}", customdata=top["net"], height=360),
                    width="stretch", config=theme.PLOTLY_CONFIG, key="ge_states")

# ------------------------------------------------------- candidate x zone
ui.section("Candidate × zone", "net sentiment of comments that mention a state in the zone AND the candidate")
cz = fl[fl["candidate"].isin(CANDIDATE_ORDER)].copy()
cz["zone"] = cz["state"].map(STATE_TO_ZONE)
g = cz.groupby(["zone", "candidate"]).agg(n=("n", "sum"), n_pos=("n_pos", "sum"), n_neg=("n_neg", "sum"))
if g.empty:
    ui.empty_state()
else:
    g["net"] = (g["n_pos"] - g["n_neg"]) / g["n"]
    order = list(ZONES.keys())
    values = g["net"].unstack("candidate").reindex(index=order, columns=CANDIDATE_ORDER)
    counts = g["n"].unstack("candidate").reindex(index=order, columns=CANDIDATE_ORDER).fillna(0)
    st.plotly_chart(charts.heatmap(values, counts, "Net sentiment by zone mentioned × candidate",
                                   xlabels={c: theme.candidate_label(c, "short") for c in CANDIDATE_ORDER}), width="stretch", config=theme.PLOTLY_CONFIG, key="ge_heat")
    tbl = sub[sub["n"] > 0][["state", "zone", "n", "n_pos", "n_neg", "net"]].sort_values("n", ascending=False)
    ui.data_table_expander(tbl.round(3).rename(columns={"state": "State", "zone": "Zone", "n": "Mentions", "n_pos": "Positive", "n_neg": "Negative", "net": "Net"}),
                           "View state table", key="ge_tbl")

# ----------------------------------------------------- language proxy
ui.section("Vernacular-channel proxy", "sentiment on Hausa-, Yoruba- and Igbo-language channels (a language-audience proxy, not a location)")
fd_all = load_fact_daily(sig, f.model)
vern = an.filter_facts(fd_all, f.start, f.end, ["vernacular_regional"], None)
vern = an.candidates_only(vern)
if vern.empty:
    ui.empty_state("No candidate mentions on vernacular channels in this range.")
else:
    g2 = vern.groupby(["channel", "candidate"]).agg(n=("n", "sum"), n_pos=("n_pos", "sum"), n_neg=("n_neg", "sum"))
    g2["net"] = (g2["n_pos"] - g2["n_neg"]) / g2["n"]
    order = g2.groupby("channel")["n"].sum().sort_values(ascending=False).index.tolist()
    values = g2["net"].unstack("candidate").reindex(index=order, columns=CANDIDATE_ORDER)
    counts = g2["n"].unstack("candidate").reindex(index=order, columns=CANDIDATE_ORDER).fillna(0)
    st.plotly_chart(charts.heatmap(values, counts, "Net sentiment on vernacular & regional channels × candidate",
                                   xlabels={c: theme.candidate_label(c, "short") for c in CANDIDATE_ORDER}, min_n=10), width="stretch", config=theme.PLOTLY_CONFIG, key="ge_vern")
    ui.caption("Commenting on a Hausa-language video suggests engagement with Hausa-language news, not residence in the North. BBC News Africa is "
               "pan-African and English-language and carries no such signal. Volumes on these channels are small; cells with fewer than 10 "
               "mentions are masked and the rest should be read as indicative.")

ui.footer()
