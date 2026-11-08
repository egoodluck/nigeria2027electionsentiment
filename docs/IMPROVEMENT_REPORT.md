# Improvement report — Nigeria 2027 Election Intelligence Platform

**Scope.** Full audit, redesign and upgrade of the Nigeria 2027 Election Sentiment Dashboard (single-file Streamlit app +
YouTube collection pipeline) into a multi-page Election Intelligence Platform. Everything remains free and open source.
**Snapshot audited:** 40,388 comments · 2,204 videos · 50 channels · 16 Jul – 4 Nov 2026.

---

## 1. Audit findings

### 1.1 Data pipeline — two defects that changed the headline numbers

| # | Finding | Evidence | Impact |
|---|---|---|---|
| P1 | **Substring alias matching.** `"bat" in text` matched *Abati* (an Arise News anchor discussed in thousands of comments), *debate*, *combat*… | 1,642 of 7,175 Tinubu attributions (23%) contained **no** whole-word Tinubu alias | Tinubu's share of voice inflated from 47% to 64%; thousands of negative comments *about a journalist* counted as Tinubu sentiment |
| P2 | **Missing bare “Obi” alias** (only *peter obi*, *okwute*, *obidient*). | 1,927 comments contained the standalone word *Obi* and were unattributed; manual sample: virtually all refer to Peter Obi | Obi under-counted by ~45%; share of voice 21% instead of 38% |
| P3 | **Comment collector exhausted quota before reaching new videos.** Every stored video was visited, oldest first, every run (≥ 2,204 units); only ~3,000 units remained after discovery | Runs on 2 and 4 Nov used 9,043 / 9,235 units yet stored only 1,974 / 900 new comments; `comments_found` logged 39,202 *re-fetched* rows | Recent weeks systematically under-collected; week-on-week volume comparisons unreliable |
| P4 | HTML entities and `<br>` tags stored raw (`&#39;`, `&amp;`) | 24 comments, hundreds of video titles | Cosmetic in UI, harmful for tokenisation |
| P5 | No indexes beyond primary keys; no run-level accounting of *new* rows | — | Explorer-style queries would not scale |
| P6 | `config.py` raised at import without the API key | — | Dashboard could not share any constant with the pipeline; duplication |

### 1.2 Sentiment methodology — the baseline inverted the picture

TextBlob (English lexicon, no Nigerian English, no Pidgin, no sarcasm) labelled the corpus **29% positive / 17% negative**.
Two transformer models trained on social-media text agree the corpus is overwhelmingly critical:

| Model | Positive | Negative | Net, Atiku | Net, Obi | Net, Tinubu |
|---|---|---|---|---|---|
| TextBlob (old default) | 29% | 17% | +0.10 | +0.15 | +0.10 |
| CardiffNLP Twitter-RoBERTa | 16% | 55% | −0.56 | −0.42 | −0.57 |
| NaijaSenti AfriBERTa | 29% | 58% | −0.48 | −0.42 | −0.52 |
| **Routed ensemble (new default)** | **16%** | **56%** | **−0.55** | **−0.42** | **−0.57** |

Agreement with TextBlob is κ ≈ 0.19 (slight); between the two transformers κ = 0.37 (fair) — model choice matters, which is
why the model is now a visible, switchable control and the agreement matrix is published. Sample sentences from the old
output: *“APC is a government of lies and propaganda”* → **positive** (+0.13); *“Obi won't win any election 😂”* → **positive** (+0.80).

### 1.3 Dashboard

* Single page, default Streamlit styling, 30-second auto-refresh against a static committed database.
* Heat-map colour range fixed at −1…+1 while values spanned 0.03–0.07 → every cell the same grey.
* Trend chart plotted the last, half-collected days as data → spurious −0.4 plunge at the right edge.
* Candidate colours (blue / orange / green) not validated; no dark mode; no methodology, confidence, topics, explainability.
* `n=` counts shown but no uncertainty, no minimum-sample masking, no statement of what “net” means.

---

## 2. What was changed and why

### 2.1 Pipeline (collection layer, backward compatible)

| Change | Why | Expected impact |
|---|---|---|
| Whole-word alias matching; new aliases (*obi*, *PO*, *pbat*, *bola*, *emilokan*, possessives); `--reattribute` mode, auto-detected by the enrichment orchestrator | P1, P2 | Correct share of voice (Tinubu 47 / Obi 38 / Atiku 14) |
| HTML unescape + tag stripping on ingest and retroactively | P4 | Clean text for models and UI |
| Collector: newest videos first; skip stale videos; stop paging at known comment ids; clean stop on `quotaExceeded`; per-video fetch state; count only inserted rows | P3 | Full daily coverage of new comments within quota; honest run accounting |
| `MAX_SEARCH_CALLS_PER_RUN` 70 → 50; `DISCOVERY_MODE=uploads` implemented (playlistItems.list, ~100 units/day for all 50 channels) | quota | 5,000 units/day freed for comments; path to same-day discovery |
| `require_api_key()` instead of import-time raise; `db.py` busy timeout | P6, concurrency | Shared constants; collector and dashboard can run concurrently |
| Indexes on `comments(video_id, published_at, author)`, `videos(channel_id)`, mentions | P5 | Explorer queries < 300 ms at 40k; scales to 1M |

### 2.2 Enrichment layer (new, offline, no API key)

| Module | What it adds |
|---|---|
| `features` | language hint (en/pcm/ha/yo/ig) from strong/weak function-word lexicons; normalised text hash; duplicate counts across/within authors; posting bursts; heavy-day posting; risk score and flag |
| `sentiment_models` | CardiffNLP Twitter-RoBERTa and NaijaSenti AfriBERTa over every comment (resumable, batch-committed); `routed` view (English → CardiffNLP, vernacular → NaijaSenti); TextBlob mirrored for comparison |
| `topics` | 13-issue Nigerian-context lexicon, multi-label (62% coverage) + TF-IDF/NMF discovery layer with top terms per theme |
| `locations` | 36 states + FCT and six geopolitical zones from text (conversation geography, explicitly not commenter location) |
| `video_stats` | views / likes / duration per video for reach (needs key; 1 unit per 50 videos) |
| `aggregates` | `fact_daily` (day × candidate × channel × model), topic and location facts, weighted log-odds keywords (positive / negative / emerging), pairwise model agreement with Cohen's κ |
| `forecast` | ETS (damped trend; weekly season for volume) 30-day projections with 80/95% intervals; ARIMA / naive fallbacks; mature-days only |
| `enrich` | idempotent orchestrator with per-step run log; called by `run_pipeline.py` |

### 2.3 Dashboard (rebuilt)

**Architecture.** `dashboard.py` + `st.navigation` → ten pages; `app/data.py` cached loaders keyed on the database file's
mtime; `app/analytics.py` pure functions; `app/charts.py` Plotly builders; `app/theme.py` design tokens + CSS + Plotly template;
`.streamlit/config.toml` light and dark themes.

**Design system.** Deep Nigeria Green brand on neutral slate; Inter typography with tabular figures in tables; candidate
colours assigned alphabetically (orange / violet / teal) from a palette validated with the colour-vision-deficiency checker
(all-pairs ΔE ≥ 9.2 light / 9.4 dark; normal-vision ΔE ≥ 24); sentiment on a red–grey–blue diverging scale that never collides with
candidate hues; status colours reserved; one axis per chart; legend + endpoint labels; a table twin and CSV behind every chart;
cells with n < 20 masked; dark mode as a designed palette.

**Pages.**

| Page | Content |
|---|---|
| Intelligence brief | daily / weekly / monthly narrative generated locally (volume with collection-lag guard, movers with n, visibility, outlets, dominant and rising issues, emerging terms, authenticity, maturity caveat); six headline tiles; candidate scorecards with CI, mix bar, sparkline, indices; 7-day rolling trend with 95% bands and “still accumulating” zone; issue × candidate heat-map; emerging terms |
| Sentiment | diverging mix bar; net ± CI dots; per-candidate cards with trend direction; daily/weekly trend; category heat-map; channel table; classifier confidence histogram and low-confidence shares |
| Momentum & influence | Candidate Momentum Index (40/30/20/10) and Election Influence Index (35/25/20/20) with components, ranking, change, 16-week trajectories, low-sample warnings |
| Issues & keywords | prevalence, net sentiment by issue, period change chips, weekly trend, candidate × issue (net or share), positive / negative / emerging keywords per candidate, discovered NMF themes, full lexicon |
| Media intelligence | outlet influence (comments, mentions, likes, reach when available), concentration warning, outlet tendency matrix with minimum-n slider, audience tendency vs corpus baseline, most-discussed videos with links |
| Geography | explicit limitations; state-mention choropleth (geoBoundaries ADM1) by mentions or net; zones; candidate × zone; vernacular-channel language proxy |
| Authenticity signals | corpus signals; manipulation risk indicator per candidate (Low / Medium / High, documented bands); risk distribution; burst days (robust z); repeated-text campaigns; most active authors (masked) |
| Projections | 7/14/30-day ETS projections for net sentiment and volume with 80/95% bands; “projection, not prediction” banner; method notes |
| Comment explorer | search + nine filters; cards with model probabilities, confidence, baseline agreement, candidate and issue cue highlighting, authenticity notes; table view; CSV export without authors |
| Methodology & data | sources and roster; collection health with new-rows-per-run; attribution rules and the correction notice; model cards, routing rule, language mix, agreement matrix, failure modes; stratified annotation-sample export; taxonomy; index formulas; heuristics; projections; ten limitations; downloads and run logs |

**Statistical rigour added.** 95% confidence intervals on every net score (exact variance of a {−1,0,+1} mean); minimum-n
masking everywhere; maturity window excluding right-censored days from trends, indices and projections; collection-lag guard in
the narrative; tanh-squashed index components so one viral day cannot dominate; weighted log-odds with informative prior for
keywords; Cohen's κ between models; prediction intervals on projections.

### 2.4 Performance

| Page | Cold | Warm | | Page | Cold | Warm |
|---|---|---|---|---|---|---|
| Brief | 1.7 s | 0.40 s | | Geography | 0.6 s | 0.19 s |
| Sentiment | 0.5 s | 0.29 s | | Authenticity | 0.7 s | 0.08 s |
| Momentum | 2.2 s | 0.17 s | | Projections | 0.6 s | 0.19 s |
| Issues | 0.7 s | 0.28 s | | Explorer | 0.6 s | 0.07 s |
| Media | 0.6 s | 0.13 s | | Methodology | 0.4 s | 0.09 s |

Measured with Streamlit's `AppTest` on two CPU cores. Explorer SQL with filters: 30–290 ms. Nothing in the app scales with
comment volume except the explorer's indexed `COUNT(*)`; fact tables grow with calendar × roster, not with comments.
Enrichment: 40k-comment backfill ≈ 55 min on two cores (one-off); daily increments take minutes.

### 2.5 Mobile and accessibility

Sidebar auto-collapses below 760 px; header, section titles and tiles restack; charts are responsive Plotly with ≥ 24 px hit
areas and unified hover; every chart has a table twin; colours validated for CVD; text never carries meaning by colour alone
(badges carry labels). Tested at 390, 1024 and 1440 px in both colour schemes with headless Chrome.

---

## 3. Three self-review iterations

1. **Correctness pass.** Found and fixed: CSS block rendering as text (Markdown HTML-block rule), choropleth filling the whole
   map (ring winding after simplification), `%`-format collision with Plotly placeholders, NaN handling for unattributed
   comments in the explorer, default-page URL path, mobile sidebar overlay, title/legend collisions on narrow screens.
2. **Statistical pass.** Added the collection-lag guard after the brief asserted a 67% volume drop that was an artefact of P3;
   added sample sizes to mover sentences; added low-sample badges to index cards; made heat-map colour ranges asymmetric so an
   all-negative corpus still shows gradation; excluded immature days from projections.
3. **Design pass.** Replaced party-coded candidate colours with the validated alphabetical palette; moved labels off
   too-narrow bar segments; shortened heat-map axis labels for phones; fixed legend ordering on stacked bars; unified margins so
   headers never overlap; verified dark mode as a designed palette rather than an inversion.

---

## 4. Expected impact

* **Credibility.** Numbers now come with uncertainty, sample sizes, model provenance and an explicit limitations list; the
  methodology page is written for a newsroom fact-checker or an academic reviewer.
* **Correctness.** Share of voice and sentiment headlines change materially (see §1) — the previous dashboard's two central
  claims (Tinubu ≈ two-thirds of the conversation; a mildly positive corpus) were artefacts of P1/P2 and the lexicon.
* **Insight.** Analysts can now answer *why* (issues, keywords, outlets, states), *how reliable* (confidence, agreement,
  authenticity) and *where it is heading* (indices, projections) rather than only *how much*.
* **Operations.** Daily runs now collect what they should within quota and refresh everything automatically; hosting stays on
  the free tier; the working database can be slimmed with `pipeline/publish.py` to stay under GitHub's 100 MB file limit.

## 5. Known gaps carried into the roadmap

Target-dependent (stance) sentiment; a human-coded validation sample for an accuracy figure; reply threads; live-key
validation of the uploads-playlist discovery mode; automation of the snapshot push. See `docs/ROADMAP.md`.
