"""
Constants shared by the enrichment pipeline and the Streamlit app.

This module deliberately has NO dependency on the YouTube API key, so the
dashboard and the offline enrichment steps can import it freely. Collection
settings that need the key live in config.py.
"""

import os

DB_PATH = os.environ.get("DB_PATH", "election_sentiment.db")

ELECTION_DAY = "2027-01-16"

# --- Candidates --------------------------------------------------------------
# Display order is alphabetical by surname; chart colours are assigned in this
# order from a colour-blind-validated palette and carry NO party meaning.
CANDIDATE_ORDER = ["atiku", "obi", "tinubu"]
CANDIDATES = {
    "atiku": {"short": "Atiku", "full_name": "Atiku Abubakar", "party": "ADC",
              "party_full": "African Democratic Congress"},
    "obi": {"short": "Obi", "full_name": "Peter Obi", "party": "NDC",
            "party_full": "Nigeria Democratic Congress"},
    "tinubu": {"short": "Tinubu", "full_name": "Bola Ahmed Tinubu", "party": "APC",
               "party_full": "All Progressives Congress"},
}
ALL_KEY = "_any"  # fact-table pseudo-candidate: every comment, attributed or not

# --- Sentiment models --------------------------------------------------------
SENTIMENT_MODELS = {
    "routed": {
        "label": "Language-routed ensemble (default)",
        "short": "Routed ensemble",
        "description": (
            "CardiffNLP Twitter-RoBERTa scores comments whose detected language is "
            "English; NaijaSenti AfriBERTa scores comments detected as Nigerian Pidgin, "
            "Hausa, Yoruba or Igbo. Each comment is scored by exactly one of the two."
        ),
    },
    "cardiffnlp": {
        "label": "CardiffNLP Twitter-RoBERTa (English)",
        "short": "CardiffNLP RoBERTa",
        "hf_id": "cardiffnlp/twitter-roberta-base-sentiment-latest",
        "description": "RoBERTa-base fine-tuned on ~124M tweets (TweetEval 2022). English.",
    },
    "naijasenti": {
        "label": "NaijaSenti AfriBERTa (Pidgin / Hausa / Yoruba / Igbo)",
        "short": "NaijaSenti AfriBERTa",
        "hf_id": "Davlan/naija-twitter-sentiment-afriberta-large",
        "description": (
            "AfriBERTa-large fine-tuned on the NaijaSenti corpus of ~30k human-annotated "
            "Nigerian tweets in Hausa, Igbo, Yoruba and Nigerian Pidgin."
        ),
    },
    "textblob": {
        "label": "TextBlob lexicon (legacy baseline)",
        "short": "TextBlob",
        "description": "Pattern-library lexicon polarity, thresholded at ±0.1. Kept for comparison only.",
    },
}
DEFAULT_MODEL = "routed"
TRANSFORMER_MODELS = ["cardiffnlp", "naijasenti"]
TRANSFORMER_MAX_LENGTH = 160
TRANSFORMER_BATCH_SIZE = 64

# --- Language hint lexicons ----------------------------------------------------
# Heuristic function-word lexicons used ONLY to route comments to a sentiment
# model and to describe the language mix of the corpus. Not a language ID model.
# "strong" markers are distinctive enough to count on their own; "weak" ones
# are short function words that only count once a strong marker is present.
LANG_MARKERS = {
    "pcm": {
        "label": "Nigerian Pidgin",
        "strong": ["dey", "wetin", "una", "abeg", "sabi", "wahala", "no be", "e go", "wey", "na so",
                   "oga", "sef", "shey", "abi", "comot", "chop", "waka", "jare", "mumu", "sapa",
                   "shebi", "nawa", "na wa", "e don", "make una", "no go", "go dey", "wetin dey",
                   "nothing dey", "dem", "dis", "dat", "bros", "e be like", "na im", "na him",
                   "e no", "no dey", "dey go", "don dey", "pikin", "wayo", "kolo", "yeye", "gbege",
                   "japa", "wahala dey", "how far", "no wahala", "abeg o", "chai", "oya", "omo"],
        "weak": ["wan", "don", "nah", "sha", "yarn", "na", "say", "make"],
    },
    "ha": {
        "label": "Hausa",
        "strong": ["allah", "wannan", "kuma", "mutane", "shugaba", "gwamnati", "zabe", "zaben",
                   "yana", "suna", "masu", "wanda", "amma", "domin", "sosai", "kasar", "arewa",
                   "jama'a", "gaskiya", "lafiya", "nasara", "siyasa", "dan takara", "yan siyasa",
                   "allah ya", "ya yi", "yayi", "shi ne", "ita ce", "hakan", "haka", "musulmi",
                   "kudi", "talakawa", "mulki", "zamu", "zasu", "muna", "kuna", "babu", "akwai",
                   "yanzu", "gobe", "kowa", "wani", "wata", "wasu", "ina ganin", "yan arewa",
                   "sarki", "tsaro", "rashin", "matsala", "kasa", "alhamdulillah", "insha allah",
                   "ubangiji", "yan nigeria", "najeriya", "tinubu ne", "atiku ne", "shugaban kasa"],
        "weak": ["ne", "ce", "ba", "bai", "dai", "dan", "yan", "duk", "ina", "mun", "kun", "ku",
                 "mu", "su", "ta", "za", "sai", "da", "ya", "ga", "ma", "na"],
    },
    "yo": {
        "label": "Yoruba",
        "strong": ["awon", "àwọn", "oloun", "olorun", "ọlọrun", "ijoba", "ìjọba", "eniyan", "ènìyàn",
                   "nitori", "gbogbo", "alaga", "idibo", "oselu", "òṣèlú", "ohun", "nkan", "ṣe",
                   "ṣugbọn", "sugbon", "pelu", "pẹlu", "lori", "tabi", "pupo", "pupọ", "daadaa",
                   "kaabo", "oluwa", "olodumare", "aṣiwaju", "asiwaju", "ko si", "ko ni", "o ni",
                   "won ni", "wọn ni", "ki lo", "kini", "bawo", "e ku", "ẹ kú", "oko", "aye", "ayé",
                   "ilu", "ìlú", "ise", "iṣẹ", "owo", "owó", "oro", "ọrọ", "omo wa",
                   "ọmọ", "gbe", "lo", "wa ni", "ni won", "ati", "ìbò", "ibo wa"],
        "weak": ["ni", "ti", "wa", "yi", "ko", "ori", "ibo", "si", "baba", "iya", "won"],
    },
    "ig": {
        "label": "Igbo",
        "strong": ["ndi", "ndị", "anyi", "anyị", "biko", "nke", "ozo", "ọzọ", "oge", "ochichi",
                   "onye", "ihe", "maka", "unu", "chineke", "chukwu", "obodo", "nwa", "nna", "nne",
                   "mmadu", "mmadụ", "ugbua", "ugbu a", "ndi igbo", "ndị igbo", "ntuli aka", "oyibo",
                   "daalu", "dalu", "kedu", "nwanne", "nwanna", "umu", "ụmụ", "ọ bụ", "o bu", "bụ",
                   "nwere", "mana", "ala igbo", "igbo kwenu", "ezigbo", "ajọ", "ajo", "mmiri", "nri",
                   "ụlọ", "ulo", "ọchịchị", "ihe a", "gịnị", "gini", "onyeisi", "ndi ala", "ala anyi",
                   "chukwu gozie", "ikuku", "egwu"],
        "weak": ["ka", "gi", "gị", "ya", "aka", "na-", "ma", "kwa", "gwa", "na"],
    },
}
LANG_LABELS = {"en": "English", **{k: v["label"] for k, v in LANG_MARKERS.items()}}
# A comment is tagged with a vernacular language when it has at least this many
# strong marker hits, OR one strong hit plus enough weak hits to cross the density.
LANG_MIN_STRONG = 2
LANG_MIN_DENSITY = 0.15

# --- Topic taxonomy ----------------------------------------------------------
# Seeded lexicon, Nigerian political context. Multi-label: a comment may carry
# several topics. Matching is word-boundary, case-insensitive, on text_clean.
TOPICS = {
    "economy": {
        "label": "Economy & cost of living",
        "terms": ["economy", "economic", "inflation", "hardship", "hunger", "hungry", "poverty",
                  "poor masses", "naira", "dollar", "exchange rate", "forex", "fx", "devaluation",
                  "fuel", "petrol", "pms", "diesel", "subsidy", "pump price", "price", "prices",
                  "cost of living", "food", "rice", "garri", "bread", "expensive", "salary",
                  "salaries", "minimum wage", "wage", "tax", "taxes", "taxation", "debt", "debts",
                  "borrow", "borrowing", "loan", "loans", "imf", "world bank", "cbn", "interest rate",
                  "sapa", "suffering", "suffer", "starvation", "starving", "refinery", "dangote",
                  "gdp", "investment", "investors", "business", "businesses", "market", "cost",
                  "palliative", "palliatives", "cash transfer", "stomach infrastructure"],
    },
    "security": {
        "label": "Security",
        "terms": ["security", "insecurity", "insecure", "bandit", "bandits", "banditry", "kidnap",
                  "kidnapped", "kidnapping", "kidnappers", "terrorist", "terrorists", "terrorism",
                  "boko haram", "iswap", "herdsmen", "herders", "fulani herdsmen", "killing",
                  "killings", "killed", "massacre", "attack", "attacks", "attacked", "army",
                  "military", "soldiers", "police", "dss", "unknown gunmen", "gunmen", "ransom",
                  "abducted", "abduction", "benue killings", "plateau killings", "ipob", "esn",
                  "lakurawa", "jihadist", "jihadists", "genocide", "violence", "thugs", "thuggery"],
    },
    "corruption": {
        "label": "Corruption & accountability",
        "terms": ["corrupt", "corruption", "loot", "looted", "looting", "looters", "stole", "stolen",
                  "steal", "stealing", "thief", "thieves", "ole", "embezzle", "embezzled",
                  "embezzlement", "efcc", "icpc", "bribe", "bribery", "bribes", "fraud", "fraudulent",
                  "419", "money laundering", "laundering", "padding", "budget padding", "kickback",
                  "kickbacks", "misappropriation", "accountability", "transparency", "probe",
                  "audit", "scam", "scammer", "scammers", "swindle"],
    },
    "elections": {
        "label": "Elections & INEC",
        "terms": ["inec", "electoral", "election", "elections", "rig", "rigging", "rigged", "bvas",
                  "irev", "ballot", "ballots", "vote", "votes", "voting", "voter", "voters", "pvc",
                  "pvcs", "tribunal", "polling", "polling unit", "result", "results", "free and fair",
                  "electoral act", "collation", "manipulation", "manipulate", "2027", "poll", "polls",
                  "turnout", "register", "registration", "amendment"],
    },
    "politics": {
        "label": "Party politics & coalitions",
        "terms": ["coalition", "defection", "defect", "defected", "defectors", "decamp", "decamped",
                  "primaries", "primary", "ticket", "running mate", "flagbearer", "flag bearer",
                  "candidate", "candidates", "aspirant", "aspirants", "campaign", "campaigns", "rally",
                  "rallies", "merger", "alliance", "party", "parties", "pdp", "lp", "labour party",
                  "nnpp", "kwankwaso", "wike", "el-rufai", "el rufai", "obasanjo", "jonathan",
                  "amaechi", "atikulated", "obidient", "obidients", "bat", "renewed hope", "g5",
                  "structure", "godfather", "godfatherism", "endorsement", "endorse", "endorsed",
                  "opposition", "ruling party", "apc", "adc", "ndc", "sdp", "nomination",
                  "consensus", "delegates", "supporters", "loyalists"],
    },
    "identity": {
        "label": "Ethnicity, religion & zoning",
        "terms": ["igbo", "igbos", "yoruba", "yorubas", "hausa", "fulani", "tribe", "tribal",
                  "tribalism", "tribalist", "tribalistic", "ethnic", "ethnicity", "christian",
                  "christians", "muslim", "muslims", "islam", "islamic", "religion", "religious",
                  "church", "mosque", "pastor", "imam", "north", "south", "northerner", "northerners",
                  "southerner", "southerners", "biafra", "biafran", "oduduwa", "arewa", "zoning",
                  "rotation", "rotational", "southeast", "south east", "south-east", "southwest",
                  "south west", "south-west", "middle belt", "nepotism", "nepotistic", "muslim-muslim",
                  "same faith", "indigene", "indigenes", "settler", "settlers", "ethnic cleansing",
                  "sharia", "christianity", "cabal", "nyesom"],
    },
    "education": {
        "label": "Education",
        "terms": ["education", "educational", "school", "schools", "university", "universities",
                  "asuu", "strike", "student", "students", "teacher", "teachers", "lecturer",
                  "lecturers", "jamb", "waec", "neco", "scholarship", "scholarships", "out-of-school",
                  "out of school", "tuition", "school fees", "fees", "almajiri", "illiteracy",
                  "illiterate", "literacy", "curriculum", "polytechnic", "graduate", "graduates",
                  "certificate", "certificates", "degree"],
    },
    "employment": {
        "label": "Jobs, youth & japa",
        "terms": ["job", "jobs", "employment", "unemployment", "unemployed", "jobless", "youth",
                  "youths", "young people", "japa", "migrate", "migration", "emigration", "abroad",
                  "visa", "visas", "npower", "n-power", "skills", "entrepreneur", "entrepreneurs",
                  "sme", "smes", "startup", "startups", "gen z", "genz", "labour market", "hire",
                  "hiring", "employ", "employed", "brain drain", "diaspora"],
    },
    "infrastructure": {
        "label": "Infrastructure & power",
        "terms": ["infrastructure", "road", "roads", "bridge", "bridges", "rail", "railway", "train",
                  "trains", "airport", "airports", "power", "electricity", "nepa", "phcn", "grid",
                  "national grid", "generator", "generators", "transformer", "transformers",
                  "power supply", "coastal highway", "lagos-calabar", "highway", "highways", "housing",
                  "water", "pipe borne", "borehole", "seaport", "port", "ports", "metro", "projects",
                  "project", "construction", "contract", "contracts", "umahi", "flyover", "flyovers"],
    },
    "health": {
        "label": "Health",
        "terms": ["health", "healthcare", "health care", "hospital", "hospitals", "doctor", "doctors",
                  "nurse", "nurses", "medical", "medicine", "medicines", "malaria", "nhis", "health insurance",
                  "maternal", "mortality", "clinic", "clinics", "drug prices", "pharmacy", "epidemic",
                  "cholera", "lassa", "mpox", "vaccine", "vaccines", "mental health", "sick", "illness"],
    },
    "leadership": {
        "label": "Leadership, competence & integrity",
        "terms": ["competent", "incompetent", "incompetence", "competence", "capable", "capacity",
                  "visionary", "vision", "leadership", "leader", "leaders", "failure", "failed",
                  "failing", "performance", "performing", "performed", "delivered", "deliver",
                  "promise", "promises", "promised", "liar", "liars", "lie", "lies", "lying",
                  "propaganda", "integrity", "character", "honest", "honesty", "dishonest", "trust",
                  "trustworthy", "credible", "credibility", "experience", "experienced", "track record",
                  "age", "old", "too old", "senile", "health status", "unfit", "fit", "frail",
                  "drug", "drugs", "drug lord", "chicago", "forgery", "forged", "fake certificate",
                  "bullion van", "greedy", "greed", "wicked", "wickedness", "arrogant", "arrogance",
                  "humble", "humility", "frugal", "prudent", "stingy", "selfish", "sincere",
                  "sincerity", "dictator", "dictatorship", "tyrant", "tyranny", "accountable",
                  "clueless", "visionless", "weak", "strong", "bold", "courage", "courageous",
                  "statesman", "messiah", "saint", "saviour", "savior", "debate", "debates",
                  "interview", "interviews", "manifesto"],
    },
    "media": {
        "label": "Media & press",
        "terms": ["journalist", "journalists", "press", "media", "anchor", "anchors", "presenter",
                  "presenters", "arise", "arise news", "arise tv", "channels tv", "channels television",
                  "tvc", "biased", "bias", "unbiased", "fake news", "misinformation", "disinformation",
                  "rufai", "abati", "seun", "okinbaloye", "ojy", "dr reuben", "reuben", "ayo mairo",
                  "interviewer", "reporter", "reporters", "news", "newspaper", "newspapers", "headline",
                  "headlines", "narrative", "narratives", "agenda", "sponsored", "paid media",
                  "influencer", "influencers", "podcast", "broadcast", "station", "stations"],
    },
    "international": {
        "label": "International affairs",
        "terms": ["america", "american", "americans", "usa", "u.s", "united states", "trump", "biden",
                  "china", "chinese", "france", "french", "uk", "britain", "british", "london",
                  "foreign", "international", "ecowas", "niger republic", "sahel", "russia", "russian",
                  "united nations", "un", "au", "african union", "ghana", "south africa", "kenya",
                  "europe", "european", "west", "western", "colonial", "colonialism", "neo-colonial",
                  "imperialist", "imperialism", "cnn", "bbc", "al jazeera", "the economist",
                  "economist", "washington", "white house", "sanction", "sanctions", "cpc", "religious freedom"],
    },
}
TOPIC_ORDER = list(TOPICS.keys())
TOPIC_LABELS = {k: v["label"] for k, v in TOPICS.items()}
OTHER_TOPIC = "other"
TOPIC_LABELS[OTHER_TOPIC] = "Other / general"

# --- Nigerian states and geopolitical zones ------------------------------------
ZONES = {
    "North Central": ["Benue", "Kogi", "Kwara", "Nasarawa", "Niger", "Plateau", "FCT"],
    "North East": ["Adamawa", "Bauchi", "Borno", "Gombe", "Taraba", "Yobe"],
    "North West": ["Jigawa", "Kaduna", "Kano", "Katsina", "Kebbi", "Sokoto", "Zamfara"],
    "South East": ["Abia", "Anambra", "Ebonyi", "Enugu", "Imo"],
    "South South": ["Akwa Ibom", "Bayelsa", "Cross River", "Delta", "Edo", "Rivers"],
    "South West": ["Ekiti", "Lagos", "Ogun", "Ondo", "Osun", "Oyo"],
}
STATE_TO_ZONE = {s: z for z, states in ZONES.items() for s in states}
STATE_ORDER = sorted(STATE_TO_ZONE.keys())

# Surface forms that identify a state. Includes capitals / major cities. All
# matching is word-boundary and case-insensitive. Ambiguous short names are
# listed with the qualifiers that make them safe.
STATE_ALIASES = {
    "Abia": ["abia", "umuahia", "aba"],
    "Adamawa": ["adamawa", "yola"],
    "Akwa Ibom": ["akwa ibom", "akwa-ibom", "uyo"],
    "Anambra": ["anambra", "awka", "onitsha", "nnewi"],
    "Bauchi": ["bauchi"],
    "Bayelsa": ["bayelsa", "yenagoa"],
    "Benue": ["benue", "makurdi", "otukpo", "gboko"],
    "Borno": ["borno", "maiduguri"],
    "Cross River": ["cross river", "cross-river", "calabar"],
    "Delta": ["delta state", "asaba", "warri", "sapele", "ughelli"],
    "Ebonyi": ["ebonyi", "abakaliki"],
    "Edo": ["edo state", "benin city", "edo"],
    "Ekiti": ["ekiti", "ado ekiti", "ado-ekiti"],
    "Enugu": ["enugu", "nsukka"],
    "FCT": ["abuja", "fct", "federal capital territory", "gwagwalada", "kuje"],
    "Gombe": ["gombe"],
    "Imo": ["imo state", "owerri", "orlu", "imo"],
    "Jigawa": ["jigawa", "dutse"],
    "Kaduna": ["kaduna", "zaria", "kafanchan"],
    "Kano": ["kano"],
    "Katsina": ["katsina", "daura", "funtua"],
    "Kebbi": ["kebbi", "birnin kebbi"],
    "Kogi": ["kogi", "lokoja", "okene"],
    "Kwara": ["kwara", "ilorin", "offa"],
    "Lagos": ["lagos", "ikeja", "lekki", "ikorodu", "eko"],
    "Nasarawa": ["nasarawa", "nassarawa", "lafia", "keffi"],
    "Niger": ["niger state", "minna", "suleja", "bida", "kontagora"],
    "Ogun": ["ogun", "abeokuta", "ijebu", "sagamu"],
    "Ondo": ["ondo", "akure", "owo"],
    "Osun": ["osun", "osogbo", "oshogbo", "ile-ife", "ife", "ilesa"],
    "Oyo": ["oyo", "ibadan", "ogbomoso"],
    "Plateau": ["plateau", "jos", "bokkos", "mangu"],
    "Rivers": ["rivers state", "port harcourt", "portharcourt", "ph city", "bonny", "rivers"],
    "Sokoto": ["sokoto"],
    "Taraba": ["taraba", "jalingo"],
    "Yobe": ["yobe", "damaturu"],
    "Zamfara": ["zamfara", "gusau"],
}
# Phrases that must NOT be read as a state even though they contain one.
STATE_EXCLUSIONS = ["niger republic", "niger delta", "river niger", "republic of niger",
                    "oyo empire", "benin republic", "niger coup"]

# --- Authenticity heuristics ---------------------------------------------------
AUTH_DUP_MIN_LEN = 20          # ignore very short texts for duplicate detection
AUTH_BURST_WINDOW_MIN = 10     # minutes
AUTH_BURST_MIN_COMMENTS = 5    # >= this many comments by one author inside the window
AUTH_HEAVY_AUTHOR_DAY = 20     # >= this many comments by one author in one UTC day
AUTH_RISK_FLAG = 0.5           # comment risk score >= this is "flagged"
MANIPULATION_BANDS = [(0.05, "Low"), (0.15, "Medium"), (1.01, "High")]  # share of flagged mentions

# --- Forecasting --------------------------------------------------------------
FORECAST_HORIZON_DAYS = 30
FORECAST_MIN_HISTORY_DAYS = 21
FORECAST_MIN_DAILY_N = 5       # days with fewer mentions are treated as missing

# --- Statistical guard rails ----------------------------------------------------
MIN_N_FOR_RATE = 20            # below this a sentiment share is shown as "insufficient data"
# Comments keep arriving on a video for days after it is published, so the most
# recent days are right-censored at every collection run. Days within this many
# days of the last comment fetch are marked "still accumulating" and excluded
# from trend fits, momentum windows and projections.
MATURITY_DAYS = 3
