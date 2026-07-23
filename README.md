# Nigeria 2027 Election — YouTube Sentiment Collection Pipeline

Collects YouTube comments mentioning Tinubu (APC), Atiku (ADC), and Peter Obi
(NDC) from a fixed roster of 50 channels spanning major broadcast networks,
investigative/digital outlets, print-backed digital channels, radio/talk
shows, vernacular & regional-language broadcasts, and civil-society/advocacy
channels. Each comment is tagged by candidate/party and each channel by
outlet category, and comments are scored for sentiment — built for the six
months leading up to Nigeria's January 16, 2027 presidential election.

## Before you run anything

**1. Verify the channel handles.** Several entries in `config.CHANNELS` are
marked `# VERIFY` — I identified these channels by name during research but
could not always confirm the exact `@handle` YouTube currently uses. Visit
`youtube.com/<handle>` for each marked channel and correct it in `config.py`
if it doesn't resolve to the right page. `resolve_channels.py` will raise a
clear error (not fail silently) on any handle it can't find, so a wrong
handle stops the pipeline immediately rather than quietly missing a channel.

**2. Get a free YouTube Data API v3 key:**
1. Go to [console.cloud.google.com](https://console.cloud.google.com/)
2. Create a project (or use an existing one)
3. Enable "YouTube Data API v3" under APIs & Services
4. Create credentials → API key
5. Copy `.env.example` to `.env`, or just export it: `export YOUTUBE_API_KEY=your_key_here`

Default free quota is 10,000 units/day — see the quota math below. With 50
channels, a full discovery pass is rationed across multiple daily runs to
stay inside that quota rather than completing in one run.

**3. Install dependencies:**
```bash
pip install -r requirements.txt
```

## Running it

```bash
python resolve_channels.py   # once, and again any time CHANNELS changes
python run_pipeline.py       # first collection run
```

For daily incremental collection over the six-month window, schedule
`run_pipeline.py` via cron (adjust paths):

```cron
30 23 * * * cd /path/to/nigeria_election_sentiment && /path/to/venv/bin/python run_pipeline.py >> pipeline.log 2>&1
```

If you are migrating the pipeline to a cloud VM or container, make sure the
host is always on and use the same cron schedule (`23:30` local server time)
so the daily run happens at 11:30 PM.

With 50 channels, one run is no longer enough to search every channel x
query pair in a day's quota (see "Quota math" below) — `collect_videos.py`
rations search calls across runs automatically via the `discovery_state`
table, picking up up where the previous run left off. You don't need to do
anything differently; just keep running `run_pipeline.py` daily and it
converges.

## Azure migration guidance

The best Azure option for this pipeline is a small Linux VM, because the
pipeline uses a local SQLite database (`election_sentiment.db`) and needs a
persistent host to keep state between runs.

### Why Azure VM is the best fit

- SQLite is easiest to keep on a VM disk.
- The app is lightweight and only runs once per day.
- A Linux VM lets you keep the database file persisted without extra
  storage plumbing.
- You can use the included `azure-setup.sh` to configure the VM and install
  a daily cron job at 23:30.

### What to do on Azure

1. Create a small Linux VM in Azure.
   - A B1s/B1ms or similar low-cost Ubuntu VM is usually enough.
   - Choose a region that is supported by Azure free-tier VMs if you want to
     minimize cost.
2. Clone this repository on the VM.
3. Copy `.env.example` to `.env` and set `YOUTUBE_API_KEY`.
4. Run:
   ```bash
   chmod +x azure-setup.sh run_daily_pipeline.sh
   ./azure-setup.sh
   ```
   The setup script now creates `.env` from `.env.example` if needed and
   reminds you to replace the placeholder `YOUTUBE_API_KEY` before the first
   run.
5. Confirm the cron job is installed by running:
   ```bash
   crontab -l
   ```

If you want to persist the SQLite database on a mounted Azure disk or volume,
set `DB_PATH` in the VM environment or in `.env` to point to that mounted
location, for example `/mnt/azure-data/election_sentiment.db`.

### Azure CLI provisioning commands

If you want to provision the VM from your own machine with Azure CLI, run:

```bash
az login
az account set --subscription "<YOUR_SUBSCRIPTION_NAME_OR_ID>"

az group create \
  --name NigeriaElectionSentimentRG \
  --location southafricanorth

az vm create \
  --resource-group NigeriaElectionSentimentRG \
  --name NigeriaElectionSentimentVM \
  --image UbuntuLTS \
  --size Standard_B1s \
  --admin-username azureuser \
  --generate-ssh-keys

az vm open-port \
  --resource-group NigeriaElectionSentimentRG \
  --name NigeriaElectionSentimentVM \
  --port 22
```

Then connect to the VM with:

```bash
ssh azureuser@$(az vm show --resource-group NigeriaElectionSentimentRG --name NigeriaElectionSentimentVM --show-details --query publicIps -o tsv)
```

On the VM, clone this repo or copy the files, then run the setup script:

```bash
chmod +x azure-setup.sh run_daily_pipeline.sh
./azure-setup.sh
```

If your repo is not on GitHub, upload the repo files to the VM using `scp`
from your local machine or create a GitHub repo and clone it on the Azure VM.

### If you want to use containers instead

A container-based deployment is also possible, but it requires an Azure
persistent volume for `election_sentiment.db`.
- Build the included `Dockerfile`.
- Mount an Azure Files share or managed volume to persist `election_sentiment.db`.
- Schedule the container to run daily at 23:30 using Azure Logic Apps, Azure
  Container Instances with a scheduler, or another Azure scheduling service.

### Important reminder

A GitHub repo alone will not keep the app running daily. The Azure VM must be
powered on and reachable. The included `azure-setup.sh` and `run_daily_pipeline.sh`
make Azure VM deployment simple and reliable.

## What it does, step by step

1. **`resolve_channels.py`** — resolves the 50 configured channels (across
   6 outlet categories — broadcast networks, investigative/digital,
   print-backed digital, radio/talk shows, vernacular & regional
   broadcasts, and civil-society/advocacy) to YouTube channel IDs and
   stores them.
2. **`collect_videos.py`** — for each channel, searches for 4 fixed queries
   ("Tinubu APC", "Atiku ADC", "Peter Obi NDC", "Nigeria 2027 election"),
   restricted to the collection window, and stores matching videos. With 50
   channels this no longer fits in a single day's quota, so it's rationed
   into multiple runs — see "Quota math" below.
3. **`collect_comments.py`** — pulls up to `MAX_COMMENTS_PER_VIDEO` (default
   300) top-level comments per stored video. By default it only stores comments
   published on or after `config.COMMENT_COLLECTION_START`; use `python
   collect_comments.py --since 2026-07-01T00:00:00Z` to override the start date.
4. **`attribute_and_score.py`** — cleans each comment's text, tags it with
   the candidate(s)/party(ies) it mentions, and scores sentiment.
5. **`run_pipeline.py`** — runs all of the above in order and logs the run.

Everything lands in `election_sentiment.db` (SQLite).

## Quota math

| Call | Cost |
|---|---|
| `search.list` | 100 units |
| `commentThreads.list` | 1 unit |
| `channels.list` | 1 unit |

A full video-discovery **pass** (one search.list call per channel x query
pair) = 50 channels × 4 queries = 200 calls = **20,000 units** — double the
free daily quota (10,000 units/day). A single run can no longer complete a
full pass, so `collect_videos.py` rations search calls via
`config.MAX_SEARCH_CALLS_PER_RUN` (default 70 calls = 7,000 units/run,
leaving ~3,000 units/day headroom for comment pulls) and persists its
progress in the `discovery_state` table between runs. At the default
rationing, one full pass takes **3 daily runs** (70 + 70 + 60 calls) to
sweep every channel x query pair; only once a pass fully completes does its
`publishedBefore` become the next pass's `publishedAfter`, so nothing is
skipped or double-counted — a pass just takes a few days instead of
finishing in one run.

If that latency is a problem (e.g. you want same-day coverage), your
options are:
- Request a quota increase from Google Cloud Console (the "Get a free
  YouTube Data API v3 key" section above links to the console), then raise
  `MAX_SEARCH_CALLS_PER_RUN` to match — quota resets once per day regardless
  of how many times you run the pipeline, so this is the only way to
  actually finish a pass in fewer runs.
- Reduce `DISCOVERY_QUERIES` or the channel roster in `config.py`.

## Known limitations to carry into your methodology section

- **Sentiment model.** `attribute_and_score.py` uses TextBlob as a baseline
  — it's lexicon-based and not tuned for Nigerian English or Pidgin.
  Validate it against a human-coded sample (see the docstring in
  `score_sentiment()`) before treating scores as final, and report the
  agreement statistic. Swapping in a stronger model later only requires
  editing that one function.
- **Outlet category, not geolocation or outlet quality.** `channels.category`
  groups the roster by outlet type (broadcast network, investigative/
  digital, print-backed digital, radio/talk show, vernacular & regional,
  civil-society/advocacy) — it is a proxy for the kind of audience a
  channel reaches, not a measured attribute of the audience itself. Within
  that, the `vernacular_regional` category (BBC Hausa/Yoruba/Igbo, DW Hausa,
  VOA Hausa, Arewa24) works as a soft regional-language proxy the way the
  original 4-channel set did: commenting on a Hausa-language video suggests
  engagement with Hausa-language news, not confirmed residence in the
  North. The exception is **BBC News Africa**, standing in for BBC News
  Pidgin (which has no dedicated YouTube channel as of this writing) —
  it's pan-African and English-language, so it doesn't carry the same
  regional-language signal as the rest of this category. State all of this
  as a limitation, not a resolved design choice.
- **Party acronym disambiguation.** ADC and NDC acronyms are only counted
  as party mentions when they co-occur with "Nigeria" or a candidate name,
  to filter out "Aide-de-Camp" (ADC) and Ghana's NDC. This will still miss
  some genuine mentions and let through some false positives — worth a
  manual spot-check on a sample before final analysis.
- **Candidate list is not final.** PDP is currently split between two
  factions (Jonathan vs. Onor); INEC's certified candidate list isn't out
  yet. Re-check `config.CANDIDATES` against the final list before your
  main collection window opens in earnest.

## Getting from here to your correlation analysis

Once you've been collecting for a while, a first-pass query for
average sentiment per candidate per outlet category looks like this:

```sql
SELECT
    ccm.candidate,
    ch.category,
    AVG(c.sentiment_polarity) AS avg_polarity,
    COUNT(*) AS n_comments
FROM comments c
JOIN comment_candidate_mentions ccm ON ccm.comment_id = c.comment_id
JOIN videos v ON v.video_id = c.video_id
JOIN channels ch ON ch.channel_id = v.channel_id
GROUP BY ccm.candidate, ch.category
ORDER BY ccm.candidate, ch.category;
```

If you specifically want the regional-language proxy from the original
4-channel design, filter to `WHERE ch.category = 'vernacular_regional'`
and group by `ch.label` instead (each channel there maps to one
language/region) — that's your input table for the Spearman correlation
against internet-penetration-by-region discussed earlier, not built into
this pipeline yet since it depends on which penetration dataset you pair
it with.
