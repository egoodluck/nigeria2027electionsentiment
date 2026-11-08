"""Measure cold and warm page render times via the Streamlit AppTest harness and
the size of the SQLite file / payloads. Used for the performance section of the report."""
import sys, time, os
ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import streamlit as st
from streamlit.testing.v1 import AppTest
pages = ["overview","sentiment","momentum","topics","media","geography","authenticity","projections","explorer","methodology"]
print(f"DB size: {os.path.getsize(ROOT / 'election_sentiment.db')/1e6:.1f} MB")
st.cache_data.clear()
for p in pages:
    at = AppTest.from_file(str(ROOT / f"app/pages/{p}.py"), default_timeout=180)
    t0=time.time(); at.run(); cold=time.time()-t0
    t0=time.time(); at.run(); warm=time.time()-t0
    print(f"{p:12s} cold {cold:5.2f}s  warm {warm:5.2f}s  exceptions={len(at.exception)}")
