"""
Nigeria 2027 Election Intelligence Platform -- Streamlit entry point.

    streamlit run dashboard.py

Reads election_sentiment.db read-only. All heavy lifting (transformer
sentiment, topics, authenticity signals, aggregates, projections) happens
offline in `python -m pipeline.enrich`; this app only renders the results,
which keeps it fast on Streamlit Community Cloud.

Kept at the repository root so existing deployments (main file = dashboard.py)
keep working. Page code lives in app/pages/.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

st.set_page_config(
    page_title="Nigeria 2027 Election Intelligence",
    page_icon=":material/how_to_vote:",
    layout="wide",
    initial_sidebar_state="auto",
    menu_items={
        "Get help": "https://github.com/egoodluck/nigeria2027electionsentiment",
        "Report a bug": "https://github.com/egoodluck/nigeria2027electionsentiment/issues",
        "About": "Nigeria 2027 Election Intelligence Platform — YouTube comment sentiment, topics and authenticity signals for the "
                 "2027 presidential race. Open-source, free-tier stack. See the Methodology page for model details and limitations.",
    },
)

from app import theme  # noqa: E402
from app.data import db_path  # noqa: E402

theme.inject_css()

if not os.path.exists(db_path()):
    st.error(f"Database not found at `{db_path()}`. Run `python run_pipeline.py` (collection) and `python -m pipeline.enrich` "
             "(enrichment) first, or set DB_PATH.", icon=":material/database_off:")
    st.stop()

PAGES_DIR = ROOT / "app" / "pages"
pages = {
    "Overview": [
        st.Page(str(PAGES_DIR / "overview.py"), title="Intelligence brief", icon=":material/dashboard:", default=True),
    ],
    "Analysis": [
        st.Page(str(PAGES_DIR / "sentiment.py"), title="Sentiment", icon=":material/mood:", url_path="sentiment"),
        st.Page(str(PAGES_DIR / "momentum.py"), title="Momentum & influence", icon=":material/trending_up:", url_path="momentum"),
        st.Page(str(PAGES_DIR / "topics.py"), title="Issues & keywords", icon=":material/topic:", url_path="issues"),
        st.Page(str(PAGES_DIR / "media.py"), title="Media intelligence", icon=":material/newspaper:", url_path="media"),
        st.Page(str(PAGES_DIR / "geography.py"), title="Geography", icon=":material/map:", url_path="geography"),
        st.Page(str(PAGES_DIR / "authenticity.py"), title="Authenticity signals", icon=":material/verified_user:", url_path="authenticity"),
        st.Page(str(PAGES_DIR / "projections.py"), title="Projections", icon=":material/query_stats:", url_path="projections"),
    ],
    "Explore": [
        st.Page(str(PAGES_DIR / "explorer.py"), title="Comment explorer", icon=":material/search:", url_path="explorer"),
    ],
    "About": [
        st.Page(str(PAGES_DIR / "methodology.py"), title="Methodology & data", icon=":material/science:", url_path="methodology"),
    ],
}

nav = st.navigation(pages, position="sidebar", expanded=True)
nav.run()
