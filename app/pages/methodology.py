"""Methodology & data: sources, collection health, attribution, models, taxonomy, indices, heuristics, limitations, downloads."""

import numpy as np
import pandas as pd
import streamlit as st

from app import analytics as an
from app import charts, components as ui, theme
from app.data import (CATEGORY_LABELS, category_label, db_signature, load_agreement, load_channels, load_enrichment_runs, load_fact_daily,
                      load_fact_topic, load_language_mix, meta, query_comments)
from app.state import sidebar_controls
from pipeline.settings import (
    ALL_KEY, AUTH_BURST_MIN_COMMENTS, AUTH_BURST_WINDOW_MIN, AUTH_HEAVY_AUTHOR_DAY, AUTH_RISK_FLAG, CANDIDATE_ORDER, CANDIDATES, LANG_LABELS,
    MANIPULATION_BANDS, MATURITY_DAYS, MIN_N_FOR_RATE, SENTIMENT_MODELS, TOPIC_LABELS, TOPIC_ORDER, TOPICS,
)

f = sidebar_controls()
m = meta()
sig = db_signature()
ui.page_header("Methodology & data", "Everything needed to understand, challenge and reproduce the numbers on this platform: where the data "
               "comes from, how comments are attributed and scored, how the indices are built, and what the data cannot tell you.")

try:
    import config as cfg
    ALIASES = {k: v["aliases"] for k, v in cfg.CANDIDATES.items()}
except Exception:
    ALIASES = {}

chans = load_channels(sig)
toc = st.container()

# ------------------------------------------------------------ 1. scope
ui.section("1 · What this platform measures")
st.markdown("""
This platform measures the **public conversation underneath Nigerian political news on YouTube** — not public opinion, not voting
intention. Every number is derived from top-level comments posted on videos published by a fixed roster of 50 Nigerian news, radio,
vernacular-language and civic channels during the run-up to the 16 January 2027 presidential election. The unit of analysis is a
*comment* (or a *candidate mention*: a comment that names one of the three leading contenders). All processing is done with free,
open-source software; no commercial API is involved at any stage.
""")

# ----------------------------------------------------------- 2. sources
ui.section("2 · Data sources and collection")
c1, c2 = st.columns([1.2, 1])
with c1:
    st.markdown(f"""
* **Platform.** YouTube Data API v3 (free quota, 10,000 units/day).
* **Roster.** {len(chans)} channels in six outlet categories, fixed before collection began. Categories are a proxy for the *kind of audience*
  a channel reaches, not a quality judgement.
* **Video discovery.** For each channel, videos matching four queries (*Tinubu APC*, *Atiku ADC*, *Peter Obi NDC*, *Nigeria 2027 election*)
  within the collection window. A cheaper uploads-playlist mode (every channel, every day, ~100 quota units) is implemented and can be
  switched on with `DISCOVERY_MODE=uploads`.
* **Comments.** Top-level comments only (no replies), newest first, published on or after 1 July 2026, up to the per-video cap.
  Authors are stored as the public display name only.
* **Window.** Comments from {ui.fmt_date(m['first_day'])} to {ui.fmt_date(m['last_day'])}; {ui.fmt_int(m['comments'])} comments on
  {ui.fmt_int(m['videos'])} videos from {ui.fmt_int(m['authors'])} distinct display names.
* **Maturity.** Comments keep arriving on a video for days. Days within {MATURITY_DAYS} days of the last collection run are marked
  *still accumulating* and excluded from index windows, trend fits and projections.
""")
with c2:
    roster = chans.groupby("category_label").agg(channels=("label", "count"), names=("label", lambda s: ", ".join(sorted(s)))).reset_index()
    st.dataframe(roster.rename(columns={"category_label": "Category", "channels": "Channels", "names": "Channels in category"}), width="stretch", hide_index=True,
                 column_config={"Channels in category": st.column_config.TextColumn(width="large")})

ui.section("Collection health", "how much each run fetched; gaps and quota-limited runs show up as low bars")
runs = m["runs"]
if runs is not None and not runs.empty:
    st.plotly_chart(charts.runs_chart(runs), width="stretch", config=theme.PLOTLY_CONFIG, key="mt_runs")
    fd_all_any = an.all_comments(load_fact_daily(sig, f.model))
    arise_share = np.nan
    if not fd_all_any.empty:
        by_ch = fd_all_any.groupby("channel")["n"].sum().sort_values(ascending=False)
        arise_share = by_ch.iloc[0] / by_ch.sum()
        top_ch = by_ch.index[0]
    ui.note(f"<b>Known collection issues, now fixed in code.</b> Until November 2026 the comment collector visited every stored video, oldest first, "
            f"on every run. With {ui.fmt_int(m['videos'])} videos that exceeded the daily quota left after discovery, so runs stopped before reaching the "
            f"newest videos — recent weeks are under-collected in this snapshot and will back-fill on the next runs. The collector now visits newest "
            f"videos first, stops paging when it reaches comments it already holds, and ends cleanly on quota exhaustion. Separately, "
            f"<b>{ui.esc(top_ch) if not np.isnan(arise_share) else 'one channel'}</b> contributes {ui.fmt_pct(arise_share)} of all comments: the corpus is "
            f"dominated by one outlet's audience, which every aggregate inherits.", "amber")
    ui.data_table_expander(runs, "View pipeline runs", key="mt_runs_tbl")

# --------------------------------------------------------- 3. attribution
ui.section("3 · Candidate attribution")
st.markdown(f"""
A comment is attributed to a candidate when it contains one of the candidate's aliases **as a whole word** (case-insensitive). A comment may
mention several candidates and then counts once for each. Party acronyms are attributed only when they cannot be confused with other
meanings (*ADC* also means aide-de-camp; *NDC* is also Ghana's ruling party) — they must co-occur with “Nigeria” or a candidate alias.
""")
if ALIASES:
    st.dataframe(pd.DataFrame([{"Candidate": theme.candidate_label(k, "full"), "Aliases matched as whole words": ", ".join(ALIASES[k])} for k in CANDIDATE_ORDER]),
                 width="stretch", hide_index=True, column_config={"Aliases matched as whole words": st.column_config.TextColumn(width="large")})
ui.note("<b>Correction applied in this release.</b> The original pipeline matched aliases as plain substrings, so the alias <i>bat</i> matched inside "
        "<i>Abati</i> (a frequently discussed anchor), <i>debate</i> and <i>combat</i>: about 23% of Tinubu attributions (≈1,600 comments) were false "
        "positives, many of them negative comments about a journalist. The bare alias <i>Obi</i> was also missing, dropping ≈1,900 genuine Peter Obi "
        "mentions (~45% of his total). Both were corrected and every comment was re-attributed; share-of-voice figures before and after are therefore "
        "not comparable.", "brand")
st.markdown(f"**Chart colours** are assigned alphabetically by surname from a colour-blind-validated palette (Atiku orange, Obi violet, Tinubu teal) and "
            f"carry no party meaning. Sentiment uses a separate red–grey–blue diverging scale so the two encodings never collide.")

# ------------------------------------------------------------ 4. models
ui.section("4 · Sentiment models")
st.markdown("""
Three-class sentiment (negative / neutral / positive) toward whatever the comment is about. Note the subtlety: a comment attributed to
Tinubu that attacks a journalist for *defending* Tinubu is negative in tone, but not negative *about Tinubu*. Target-dependent (aspect-based)
sentiment is a roadmap item; today's scores are comment-level tone.
""")
mcols = st.columns(len(SENTIMENT_MODELS))
for col, (key, info) in zip(mcols, SENTIMENT_MODELS.items()):
    with col, st.container(border=True):
        st.markdown(f"**{info['short']}**" + (" · default" if key == "routed" else ""))
        st.markdown(f"<div class='nes-caption'>{info['description']}</div>", unsafe_allow_html=True)
        if info.get("hf_id"):
            st.markdown(f"<div class='nes-caption'><code>{info['hf_id']}</code></div>", unsafe_allow_html=True)
        if key not in (m.get("models") or []):
            st.markdown(ui.badge("not yet scored", "amber"), unsafe_allow_html=True)

st.markdown(f"""
**Routing rule.** A lightweight lexicon of Pidgin, Hausa, Yoruba and Igbo function words tags each comment with a language hint. Comments tagged
as English (or untagged) are scored by CardiffNLP's Twitter-RoBERTa, which is strong on informal English; comments tagged as a Nigerian
language are scored by NaijaSenti's AfriBERTa, which was fine-tuned on human-annotated Nigerian tweets in those languages. Each comment gets
exactly one routed label. The hint is a routing heuristic, not a language identifier, and it is stored so you can audit it in the explorer.
""")
c1, c2 = st.columns([1, 1.4])
with c1:
    lang = load_language_mix(sig)
    if not lang.empty:
        lang["label"] = lang["lang_hint"].map(lambda k: LANG_LABELS.get(k, k))
        lang["share"] = lang["n"] / lang["n"].sum()
        st.plotly_chart(charts.ranked_bars(lang, "n", "label", "Detected language mix (routing hint)", value_fmt=",.0f",
                                           hover_extra="%{x:,} comments · %{customdata:.1%}", customdata=lang["share"], height=260),
                        width="stretch", config=theme.PLOTLY_CONFIG, key="mt_lang")
with c2:
    agr = load_agreement(sig)
    if not agr.empty:
        st.plotly_chart(charts.agreement_matrix(agr, {k: v["short"] for k, v in SENTIMENT_MODELS.items()}), width="stretch", config=theme.PLOTLY_CONFIG, key="mt_agree")
        ui.caption("Cohen's κ: 0.2–0.4 fair, 0.4–0.6 moderate, 0.6–0.8 substantial. Low agreement with TextBlob is expected and is the reason the "
                   "lexicon was retired as the default.")

st.markdown("""
**Known failure modes.** Sarcasm and irony (*“Tinubu, the best president ever 😂”*); praise of a journalist for attacking a candidate (positive
tone, negative stance); code-mixed sentences that flip language mid-way; very short comments (*“Sai Baba”*, *“PO 2027”*) where the model falls back
to neutral; and emoji-only comments. Confidence below 0.60 marks most of these; the explorer lets you exclude them.
""")

with st.expander("Validate the models yourself — download a stratified annotation sample"):
    st.markdown("""
No labelled Nigerian political-YouTube dataset exists to report an accuracy figure against. The methodologically sound step is a human-coded
sample: two or more coders label the comments below (positive / neutral / negative) blind to the model's output, then agreement (Cohen's κ)
between coders and between coders and each model is reported. 300–500 comments give κ a standard error of roughly ±0.05.
""")
    n_sample = st.slider("Sample size", 100, 600, 400, 50, key="mt_n")
    if st.button("Draw sample", key="mt_draw"):
        parts = []
        per = n_sample // 3
        for lab in ["negative", "neutral", "positive"]:
            d = query_comments(sig, f.model, sentiments=[lab], sort="newest", limit=4000)
            if not d.empty:
                parts.append(d.sample(min(per, len(d)), random_state=42))
        sample = pd.concat(parts) if parts else pd.DataFrame()
        if sample.empty:
            ui.empty_state("No comments available for sampling.")
        else:
            sample = sample.sample(frac=1, random_state=7)[["comment_id", "text", "label", "confidence", "baseline_label", "lang_hint", "candidates"]]
            sample["coder_1"] = ""
            sample["coder_2"] = ""
            st.download_button("Download annotation sample (CSV)", sample.to_csv(index=False).encode("utf-8"), "annotation_sample.csv", "text/csv", key="mt_dl")
            st.dataframe(sample.head(10), width="stretch", hide_index=True)

# ------------------------------------------------------------ 5. topics
ui.section("5 · Issue taxonomy and keywords")
ft = load_fact_topic(sig, f.model)
coverage = np.nan
if not ft.empty:
    allt = ft[ft["candidate"] == ALL_KEY].groupby("topic")["n"].sum()
    coverage = 1 - allt.get("other", 0) / max(m["comments"], 1)
st.markdown(f"""
* **Seeded lexicon (primary).** {len(TOPIC_ORDER)} issue areas with {sum(len(v['terms']) for v in TOPICS.values())} Nigerian-context terms (e.g. *sapa*, *japa*,
  *bandits*, *BVAS*, *subsidy*, *zoning*), matched as whole words. Multi-label. About {ui.fmt_pct(coverage)} of comments carry at least one issue;
  the rest are *other / general* — mostly reactions to people rather than policy. The full lexicon is listed on the Issues page so every tag can be audited.
* **Discovery layer.** TF-IDF (1–2-grams, candidate names and function words removed) + non-negative matrix factorisation with 12 components and a
  fixed seed, to surface themes the lexicon misses. Clusters are reported with their top terms and sizes, never renamed by hand.
* **Keywords.** Weighted log-odds ratio with an informative Dirichlet prior (Monroe, Colaresi & Quinn 2008) between positive and negative comments
  per candidate, with the whole candidate corpus as prior. Emerging terms compare the last 7 days with the previous 4 weeks. Terms need ≥ 5 occurrences.
""")

# ------------------------------------------------------------ 6. indices
ui.section("6 · Composite indices")
st.markdown("""
| Index | Components | Transform |
|---|---|---|
| **Candidate Momentum Index** (0–100, 50 = no change) | 40% change in net sentiment vs previous window · 30% growth in likes on mentions · 20% growth in mention count · 10% consistency (1 − min(1, sd of daily net / 0.5)) | each change squashed with tanh (scale 0.15 for sentiment, 1.0 for growth rates) so one viral day cannot dominate |
| **Election Influence Index** (0–100) | 35% (net sentiment + 1)/2 · 25% share of voice among the three candidates · 20% share of likes among the three · 20% momentum / 100 | reported with the change vs the previous window and the rank |

Windows default to the last 7 mature days; the comparison window is the 7 days before. Both indices describe the online conversation only.
""")

# ------------------------------------------------------- 7. authenticity
ui.section("7 · Authenticity heuristics")
st.markdown(f"""
Per-comment risk score = 0.50 × *cross-author copies* + 0.25 × *same-author repeats* + 0.15 × *burst posting* + 0.10 × *heavy daily posting*, each
component in [0, 1]. Copies are detected on text normalised for case, punctuation, emoji and accents (texts shorter than 20 characters are ignored).
A burst is ≥ {AUTH_BURST_MIN_COMMENTS} comments by one display name within {AUTH_BURST_WINDOW_MIN} minutes; heavy posting is ≥ {AUTH_HEAVY_AUTHOR_DAY}
comments in one UTC day. A comment is *flagged* at risk ≥ {AUTH_RISK_FLAG}. The candidate-level **manipulation risk indicator** bands the share of flagged
mentions: {" · ".join(f"{lab} &lt; {thr:.0%}" if thr <= 1 else f"{lab} ≥ {MANIPULATION_BANDS[i-1][0]:.0%}" for i, (thr, lab) in enumerate(MANIPULATION_BANDS))}.
These thresholds are judgement calls and are deliberately conservative; the signals are observational and cannot distinguish organised
campaigns from enthusiastic fans.
""", unsafe_allow_html=True)

# ---------------------------------------------------------- 8. projections
ui.section("8 · Projections")
st.markdown("""
Exponential smoothing (ETS, additive error, additive damped trend; 7-day additive season for volume) fitted with `statsmodels` on mature daily series;
80% and 95% prediction intervals from the state-space model; ARIMA(1,0,0) and a naive band as fallbacks. Labelled *projection, not prediction*
throughout: the model extrapolates the recent pattern and is blind to events.
""")

# ------------------------------------------------------------ 9. limits
ui.section("9 · Limitations — read before quoting any number")
st.markdown(f"""
1. **Who comments.** YouTube commenters on Nigerian news channels are a self-selected, disproportionately urban, male, younger and diaspora audience.
   Nothing here generalises to the electorate.
2. **Outlet concentration.** One channel's audience supplies the majority of comments. Filter by channel to check whether a finding survives.
3. **Collection gaps.** Runs were irregular and quota-limited (see *Collection health*); recent weeks are under-collected until the fixed collector catches up.
   The per-video cap means the busiest videos are truncated to their newest comments.
4. **Replies are not collected.** Only top-level comments; the often more heated reply threads are absent.
5. **Language.** Pidgin, Hausa, Yoruba and Igbo are a minority of comments and are handled by routing, not by a model trained on this exact mix; the
   language hint is heuristic.
6. **Sarcasm, irony and stance.** Tone ≠ stance. Classifiers read tone; a sarcastic compliment or an attack on a candidate's critic will be mis-scored.
7. **Attribution ambiguity.** Whole-word aliases are precise but incomplete; nicknames and misspellings (*Turubu*, *Gbola*) are missed; *PO* and *Bola* are
   included because in this corpus they overwhelmingly refer to the candidates, which is a corpus-specific judgement.
8. **Small cells.** Any share based on fewer than {MIN_N_FOR_RATE} comments is masked or marked; confidence intervals are shown wherever a net score is.
9. **No geography.** The API exposes no commenter location; the Geography page shows what places the conversation is *about*.
10. **Models drift.** The same text may be scored differently if a model is updated; model identifiers and versions are stored with every score.
""")

# --------------------------------------------------- 10. reproducibility
ui.section("10 · Reproducibility and downloads")
st.markdown("""
* Code: `github.com/egoodluck/nigeria2027electionsentiment` — collection (`run_pipeline.py`), enrichment (`python -m pipeline.enrich`), app (`dashboard.py`).
* Stack: Python, SQLite, pandas, scikit-learn, statsmodels, Hugging Face `transformers` (PyTorch CPU), Streamlit, Plotly. No paid service anywhere.
* Every enrichment step logs its run, row counts and parameters to `enrichment_runs`; every sentiment row carries the model id and timestamp.
* Map boundaries: geoBoundaries gbOpen ADM1 (CC BY 4.0).
""")
runs_e = load_enrichment_runs(sig)
if not runs_e.empty:
    ui.data_table_expander(runs_e, "View enrichment runs", key="mt_enrich")
fd_dl = load_fact_daily(sig, f.model)
if not fd_dl.empty:
    out = fd_dl.copy()
    out["day"] = out["day"].dt.date
    st.download_button("Download daily fact table (CSV)", out.to_csv(index=False).encode("utf-8"), f"fact_daily_{f.model}.csv", "text/csv", key="mt_dl_fact")
if not ft.empty:
    out = ft.copy()
    out["day"] = out["day"].dt.date
    st.download_button("Download daily issue table (CSV)", out.to_csv(index=False).encode("utf-8"), f"fact_daily_topic_{f.model}.csv", "text/csv", key="mt_dl_topic")

with st.expander("Glossary"):
    st.markdown("""
* **Mention** — a comment that names a candidate (whole-word alias). One comment can be a mention for several candidates.
* **Net sentiment** — (positive − negative) ÷ all mentions, from −1 to +1. 0 means positive and negative balance, *not* that comments are neutral.
* **Share of voice** — a candidate's mentions as a share of all three candidates' mentions.
* **Confidence** — the probability the classifier assigns to its chosen label.
* **Mature day** — a day old enough that its comment count is no longer growing materially.
* **Flagged** — a comment whose authenticity risk score is at or above the threshold.
""")
ui.footer()
