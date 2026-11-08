# Roadmap

Prioritised by impact on analytical credibility and effort to deliver on the free/open-source stack.
Effort: **S** < 1 day · **M** 1–3 days · **L** > 3 days.

## High impact · low effort

| # | Item | Why | Effort |
|---|---|---|---|
| 1 | **Switch discovery to `DISCOVERY_MODE=uploads`** after one validation run against a live key | Covers all 50 channels every day for ~100 quota units instead of a 3–4 run rationed pass at 20,000; frees quota for comments and statistics | S |
| 2 | **Human-coded validation sample** (400 comments, 2 coders) using the export on the Methodology page; report κ per model, per language | Turns "model agreement" into an accuracy statement; required before any publication | S (coding time aside) |
| 3 | **Back-fill recent weeks** by letting the fixed collector run daily for a week | Restores the under-collected late-October window; recomputes everything automatically | S |
| 4 | **Automate the snapshot push** (GitHub Action or cron: run pipeline → commit `election_sentiment.db` → push) | Removes the manual "data update" commits; keeps the hosted app within a day of the data | S |
| 5 | **Reply threads** (`commentThreads.list(part=replies)` or `comments.list`) for high-traffic videos | Replies carry much of the heated discussion; same 1-unit cost class | M |
| 6 | **Alerting**: email/Slack digest of the daily brief + any High manipulation band or burst day | Makes the platform proactive for observers and newsrooms; pure local computation + SMTP | S |

## High impact · high effort

| # | Item | Why | Effort |
|---|---|---|---|
| 7 | **Target-dependent (stance) sentiment** — fine-tune a small transformer on the human-coded sample to classify sentiment *toward the named candidate*, not tone | Fixes the "attack on a journalist counted as negative for Tinubu" class of errors; the single biggest methodological upgrade | L |
| 8 | **Nigerian-English/Pidgin domain adaptation** — continued pre-training or LoRA of the RoBERTa on the unlabeled corpus, then fine-tune on the coded sample | Improves recall on sarcasm, slang (*sapa*, *japa*, *gbola*) and code-mixing | L |
| 9 | **Author-level network signals** — co-commenting graphs, time-zone of activity, account age proxies | Stronger coordinated-behaviour detection than text duplication alone; must stay privacy-preserving (aggregate only) | L |
| 10 | **Event annotation layer** — manually curated timeline (debates, defections, INEC announcements) overlaid on trends and used as regressors in projections | Explains spikes; lets projections become conditional "what-if" scenarios | M |
| 11 | **Cross-platform ingestion** (X/Twitter via free tiers is now limited; Facebook public pages; Nairaland forum) | Reduces single-platform and single-channel bias; requires per-source collectors | L |
| 12 | **Aspect-based topic sentiment** — sentiment computed per (candidate, issue) pair inside a comment | Today a two-issue comment contributes its overall tone to both issues | M |

## Nice to have

| # | Item | Effort |
|---|---|---|
| 13 | Weekly PDF/PNG "brief" export for newsroom use (Plotly static export via kaleido) | M |
| 14 | Hausa/Yoruba/Igbo UI translation of the methodology page | M |
| 15 | Embedding-based topic fallback (sentence-transformers MiniLM) for comments the lexicon misses | M |
| 16 | Per-video drill-down page (comments, sentiment over the video's life, anchors mentioned) | S |
| 17 | Public read-only API (FastAPI) over the fact tables for researchers | M |
| 18 | Streamlit `@st.fragment` partial reruns for the explorer filters | S |
| 19 | Accessibility audit with axe-core; texture fills for CVD/print mode in charts | M |
| 20 | Nigeria LGA-level conversation geography (geoBoundaries ADM2; needs an LGA alias list) | M |

## Explicitly out of scope

* Vote-share or turnout prediction of any kind.
* Inferring commenter demographics or location from names, language or writing style.
* Any paid API, proprietary analytics service or closed model.
