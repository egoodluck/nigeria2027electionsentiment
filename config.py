"""
Configuration for the Nigeria 2027 Election YouTube Sentiment Pipeline.

Edit CHANNELS, CANDIDATES, and the collection window here as the research
evolves -- e.g. once INEC publishes the final certified candidate list, or
if the PDP factional dispute (Jonathan vs Onor) resolves and you decide to
add a fourth candidate.
"""

import os

# --- API ---
# Get a free key at https://console.cloud.google.com/apis/credentials
# after enabling "YouTube Data API v3" on a project. See README.md.
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")
if not YOUTUBE_API_KEY:
    raise EnvironmentError(
        "Set the YOUTUBE_API_KEY environment variable before running. "
        "See README.md for how to get a free key from Google Cloud Console."
    )

# --- Collection window ---
# Election day: 16 January 2027 (INEC revised timetable, issued Feb 2026).
# Start date below is ~6 months out. If you start the pipeline later than
# COLLECTION_START, that's fine -- collect_videos.py always resumes from
# the last successful run, so you simply lose whatever window has already
# passed rather than losing anything going forward.
COLLECTION_START = "2026-07-16T00:00:00Z"
COLLECTION_END = "2027-01-16T00:00:00Z"

# --- Channels: 50-channel outlet-category roster ---
# 'category' replaces the earlier national/regional split -- with 50 channels
# spanning broadcast networks, investigative/digital outlets, print-backed
# digital, radio/talk shows, vernacular & regional-language broadcasts, and
# civil-society/advocacy channels, "category" (outlet type) is the more
# meaningful grouping for analysis. The 'vernacular_regional' category is
# the closest thing to the old geography proxy (see README's known
# limitations section).
#
# channel_id is pre-filled where verified during research; where it's None,
# resolve_channels.py will look it up from the handle. VERIFY every handle
# marked below before your first real run -- resolve_channels.py fails
# loudly (raises an error) on any handle it can't resolve, rather than
# silently dropping a channel, so a wrong handle will stop the pipeline
# immediately rather than corrupting your dataset.
CHANNELS = [
    # Major Broadcast Networks
    {"channel_id": None, "handle": "@channelstelevision", "label": "Channels Television", "category": "broadcast_network"},  # VERIFY
    {"channel_id": "UCyEJX-kSj0kOOCS7Qlq2G7g", "handle": "@arisenews", "label": "Arise News", "category": "broadcast_network"},  # verified
    {"channel_id": None, "handle": "@tvcnewsnigeria", "label": "TVC News Nigeria", "category": "broadcast_network"},  # VERIFY
    {"channel_id": None, "handle": "@NewsCentralAfrica", "label": "News Central TV", "category": "broadcast_network"},  # VERIFY
    {"channel_id": None, "handle": "@TrustTVNews", "label": "Trust TV News", "category": "broadcast_network"},  # VERIFY
    {"channel_id": None, "handle": "@PlusTVAfrica", "label": "Plus TV Africa", "category": "broadcast_network"},  # VERIFY
    {"channel_id": None, "handle": "@AfricaIndependentTv", "label": "AIT Online", "category": "broadcast_network"},  # VERIFY
    {"channel_id": "UCLLWAXn5F415g2kNAcE_T1g", "handle": "@ntanetworks", "label": "NTA News", "category": "broadcast_network"},  # verified
    {"channel_id": "UCfN4ImaiJIo0wFUHY5xx4MQ", "handle": "@coretvnewsng", "label": "Core TV News", "category": "broadcast_network"},  # verified
    {"channel_id": "UCQNkoYMlQEBgaFzamkeNoeg", "handle": "@silverbirdtelevision1", "label": "Silverbird Television", "category": "broadcast_network"},  # verified

    # Investigative & Digital Media
    {"channel_id": None, "handle": "@PremiumTimesng", "label": "Premium Times", "category": "investigative_digital"},  # VERIFY
    {"channel_id": None, "handle": "@icirnigeria", "label": "ICIR Nigeria", "category": "investigative_digital"},  # VERIFY
    {"channel_id": "UCVTfajerOQIrDzacPoPuUxg", "handle": "@fijnigeria9520", "label": "FIJ Nigeria", "category": "investigative_digital"},  # verified
    {"channel_id": None, "handle": "@thecableng", "label": "TheCable", "category": "investigative_digital"},  # VERIFY
    {"channel_id": None, "handle": "@HumAngle", "label": "HumAngle", "category": "investigative_digital"},  # VERIFY
    {"channel_id": None, "handle": "@dataphyte", "label": "Dataphyte", "category": "investigative_digital"},  # VERIFY
    {"channel_id": None, "handle": "@ORDERPAPER", "label": "OrderPaper Nigeria", "category": "investigative_digital"},  # VERIFY
    {"channel_id": "UCFniTQtBC3U7uQs4tfDROFA", "handle": "@dubawafacts", "label": "Dubawa", "category": "investigative_digital"},  # verified
    {"channel_id": None, "handle": "@AfricaCheck", "label": "Africa Check", "category": "investigative_digital"},  # VERIFY
    {"channel_id": "UCHFcmxRe9YbhlnSfzbe-_GQ", "handle": "@stearsnews4758", "label": "Stears", "category": "investigative_digital"},  # verified

    # Print-Backed Digital Channels
    {"channel_id": "UCKBMh5v6VrB0t75ryyiVsBg", "handle": "@mobilepunch234", "label": "The Punch Newspapers", "category": "print_backed_digital"},  # verified
    {"channel_id": "UCkRLkFEEJR3o7QYm1r8_5yg", "handle": "@vanguardngrTV", "label": "Vanguard Newspapers", "category": "print_backed_digital"},  # verified
    {"channel_id": None, "handle": "@DailyTrust", "label": "Daily Trust", "category": "print_backed_digital"},  # VERIFY
    {"channel_id": None, "handle": "@GuardianNigeriaOfficial", "label": "The Guardian Nigeria", "category": "print_backed_digital"},  # VERIFY
    {"channel_id": "UCsVZWCV-LutMa89JgR8-KGw", "handle": "@bdtv-ng", "label": "BusinessDay Nigeria", "category": "print_backed_digital"},  # verified
    {"channel_id": "UCRExbfG5-STw_uWF7BDNKdQ", "handle": "@ripplesnigeria2600", "label": "Ripples Nigeria", "category": "print_backed_digital"},  # verified
    {"channel_id": "UCKnyVIW5QvfnsXddsjFKx4A", "handle": "@Saharatv", "label": "Sahara Reporters", "category": "print_backed_digital"},  # verified

    # Radio & Talk Shows
    {"channel_id": None, "handle": "@NigeriaInfoFM", "label": "Nigeria Info FM", "category": "radio_talk_show"},  # VERIFY
    {"channel_id": "UCCKn6YDydzEW8e6RZwyrklg", "handle": "@breketefamily", "label": "Human Rights Radio (Berekete Family)", "category": "radio_talk_show"},  # verified
    {"channel_id": None, "handle": "@MicOnPodcast", "label": "Mic On Podcast", "category": "radio_talk_show"},  # VERIFY
    {"channel_id": "UC72CeEF4I3S2scNAp8v_Fog", "handle": "@wazobiafm", "label": "Wazobia FM", "category": "radio_talk_show"},  # verified
    {"channel_id": "UCD3GRKoWxCaJSaYB_KJZO7w", "handle": "@smooth981fmlagos", "label": "Smooth 98.1", "category": "radio_talk_show"},  # verified
    {"channel_id": None, "handle": "@VOP903FM", "label": "Voice of the People (VOP) 90.3 FM", "category": "radio_talk_show"},  # VERIFY
    {"channel_id": None, "handle": "@SplashFM1055", "label": "Splash FM 105.5 Ibadan", "category": "radio_talk_show"},  # VERIFY
    {"channel_id": None, "handle": "@NaijaFM1027", "label": "Naija FM 102.7", "category": "radio_talk_show"},  # VERIFY
    {"channel_id": "UCWrYzaIM_7HCIrWAAiLY-xA", "handle": "@ifm923lagos", "label": "Inspiration FM", "category": "radio_talk_show"},  # verified
    {"channel_id": "UCjzMxK80T1QVR7SbJ5iuC7Q", "handle": "@glitchafricastudios", "label": "The Honest Bunch Podcast", "category": "radio_talk_show"},  # verified
    {"channel_id": None, "handle": "@baobabmedia", "label": "Baobab Podcast", "category": "radio_talk_show"},  # VERIFY

    # Vernacular & Regional Broadcasts
    # BBC News Pidgin has no dedicated YouTube channel (confirmed via web + YouTube channel
    # search) -- substituted with BBC News Africa per user decision on 2026-07-13. This is a
    # broader pan-African English-language channel, not Pidgin-specific, so it's a weaker fit
    # for the vernacular/regional-language proxy than the other entries in this category --
    # note that in your methodology write-up.
    {"channel_id": "UCvhPRRiwI1_p4OBsY0yz6mg", "handle": "@bbcafrica", "label": "BBC News Africa", "category": "vernacular_regional"},  # verified
    {"channel_id": "UCZXbvNkOqOKGdaiV82_3zAQ", "handle": "@BBCHausaOfficial", "label": "BBC News Hausa", "category": "vernacular_regional"},  # verified
    {"channel_id": None, "handle": "@bbcnewsyoruba", "label": "BBC News Yoruba", "category": "vernacular_regional"},  # VERIFY
    {"channel_id": "UC9TfvgKOC4mM0tKhIgDcxyw", "handle": "@bbcigbonews", "label": "BBC News Igbo", "category": "vernacular_regional"},  # verified
    {"channel_id": None, "handle": "@AREWA24", "label": "Arewa24", "category": "vernacular_regional"},  # VERIFY
    {"channel_id": None, "handle": "@DWHausa", "label": "DW Hausa", "category": "vernacular_regional"},  # VERIFY
    {"channel_id": None, "handle": "@VOAHausa", "label": "VOA Hausa", "category": "vernacular_regional"},  # VERIFY

    # Civil Society & Democratic Advocacy
    {"channel_id": None, "handle": "@YiagaAfrica", "label": "YIAGA Africa", "category": "civil_society_advocacy"},  # VERIFY
    {"channel_id": "UCPmVqjz8fUBEyAf1H4F0rdA", "handle": "@BudgITNg", "label": "BudgIT Nigeria", "category": "civil_society_advocacy"},  # verified
    {"channel_id": None, "handle": "@CDDWestAfrica", "label": "CDD West Africa", "category": "civil_society_advocacy"},  # VERIFY
    {"channel_id": None, "handle": "@EiENigeria", "label": "EiE Nigeria", "category": "civil_society_advocacy"},  # VERIFY
    {"channel_id": "UCFki_bfKXqYSTy7v3ZKJSEw", "handle": "@CISLAC", "label": "CISLAC Nigeria", "category": "civil_society_advocacy"},  # verified
]

# --- Candidates: top 3, per current research scope ---
CANDIDATES = {
    "tinubu": {
        "full_name": "Bola Tinubu",
        "aliases": ["tinubu", "bola tinubu", "bola ahmed tinubu", "bat", "asiwaju", "jagaban", "president tinubu"],
        "party": "apc",
    },
    "atiku": {
        "full_name": "Atiku Abubakar",
        "aliases": ["atiku", "atiku abubakar", "waziri adamawa"],
        "party": "adc",
    },
    "obi": {
        "full_name": "Peter Obi",
        "aliases": ["peter obi", "okwute", "obidient", "obidients"],
        "party": "ndc",
    },
}

# --- Parties ---
# Full names are preferred as search/match terms. Acronyms are only counted
# as a match when disambiguation_required is False, OR when the comment also
# contains a disambiguator (see DISAMBIGUATORS below). This exists because:
#   ADC (bare acronym) collides constantly with "Aide-de-Camp" in Nigerian
#     political news -- a completely unrelated military/protocol term.
#   NDC (bare acronym) collides with Ghana's ruling party (also "NDC").
PARTIES = {
    "apc": {"full_name": "All Progressives Congress", "acronym": "apc", "disambiguation_required": False},
    "adc": {"full_name": "African Democratic Congress", "acronym": "adc", "disambiguation_required": True},
    "ndc": {"full_name": "Nigeria Democratic Congress", "acronym": "ndc", "disambiguation_required": True},
}
DISAMBIGUATORS = ["nigeria"] + [alias for c in CANDIDATES.values() for alias in c["aliases"]]

# --- Search queries used for VIDEO DISCOVERY ---
# Kept small and high-precision on purpose. Full alias/nickname matching
# (Jagaban, Okwute, Waziri, etc.) happens later at the comment-attribution
# stage in attribute_and_score.py, not here -- video titles from
# professional news channels reliably use full names, so there's no need
# to burn search quota on every nickname variant.
DISCOVERY_QUERIES = [
    "Tinubu APC",
    "Atiku ADC",
    "Peter Obi NDC",
    "Nigeria 2027 election",
]

# --- Storage ---
# Allow Azure storage mounts / containers to override the default SQLite path
# without changing the repository layout.
DB_PATH = os.environ.get("DB_PATH", "election_sentiment.db")

# --- Comment collection window ---
# Collect only comments published on or after this RFC 3339 timestamp.
# This is useful for retrospective runs that should not retain older comments.
COMMENT_COLLECTION_START = "2026-07-01T00:00:00Z"

# --- Quota management ---
# search.list        = 100 units/call
# commentThreads.list = 1 unit/call
# channels.list       = 1 unit/call
# Free daily quota    = 10,000 units (default; can request an increase from
#                        Google if needed, see README.md)
#
# A full discovery pass = 50 channels x 4 queries = 200 calls = 20,000
# units -- double the free daily quota. A single run can no longer complete
# a full pass, so collect_videos.py rations search calls across runs:
# MAX_SEARCH_CALLS_PER_RUN caps how many (channel, query) pairs are searched
# per invocation of run_pipeline.py, and progress is persisted in the
# discovery_state table so the next run picks up where this one left off.
# Only once every pair has been searched does the pass "close" and its
# publishedAfter/publishedBefore window get handed off to the next pass --
# see README.md for the full explanation and the day-count math.
MAX_RESULTS_PER_SEARCH = 25
MAX_COMMENTS_PER_VIDEO = 300
MAX_SEARCH_CALLS_PER_RUN = 70  # 7,000 units/run, leaving 3,000 units/day for comment pulls
