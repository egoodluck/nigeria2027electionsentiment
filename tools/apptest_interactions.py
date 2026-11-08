import sys, time
ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from streamlit.testing.v1 import AppTest
pages = sys.argv[1:] or ["overview","sentiment","momentum","topics","media","geography","authenticity","projections","explorer","methodology"]
scenarios = [
    ("last7", lambda at: at.radio(key="g_range").set_value("Last 7 days")),
    ("last30+vernacular", lambda at: (at.radio(key="g_range").set_value("Last 30 days"), at.multiselect(key="g_cats").set_value(["vernacular_regional"]))),
    ("civil_society_only", lambda at: at.multiselect(key="g_cats").set_value(["civil_society_advocacy"])),
    ("one_candidate", lambda at: at.multiselect(key="g_cands").set_value(["atiku"])),
    ("textblob_model", lambda at: at.selectbox(key="g_model").select("textblob")),
]
for p in pages:
    for name, fn in scenarios:
        t0=time.time()
        at = AppTest.from_file(str(ROOT / f"app/pages/{p}.py"), default_timeout=180); at.run()
        fn(at); at.run()
        exc = [e.message[:200] for e in at.exception]
        status = "OK " if not exc else "EXC"
        print(f"{status} {p:12s} {name:22s} {time.time()-t0:5.1f}s {exc[:1]}")
        if exc:
            for e in at.exception: print("    ", str(e.stack_trace)[-900:])
