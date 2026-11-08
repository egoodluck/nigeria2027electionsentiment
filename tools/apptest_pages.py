import sys, time
ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from streamlit.testing.v1 import AppTest
model = sys.argv[1] if len(sys.argv) > 1 else "textblob"
pages = ["overview","sentiment","momentum","topics","media","geography","authenticity","projections","explorer","methodology"]
for p in pages:
    t0 = time.time()
    try:
        at = AppTest.from_file(str(ROOT / f"app/pages/{p}.py"), default_timeout=180)
        at.run()
        if at.selectbox(key="g_model").value != model:
            at.selectbox(key="g_model").select(model).run()
        dt = time.time() - t0
        exc = [e.message for e in at.exception]
        errs = [x.value[:200] for x in at.error]
        print(f"{p:12s} {dt:5.1f}s  exceptions={len(exc)} errors={len(errs)} md={len(at.markdown)}")
        for e in at.exception:
            print("   EXC:", e.message[:400]); print("   ", e.stack_trace[-1500:].replace("\n","\n    "))
        for e in errs: print("   ERR:", e)
    except Exception as ex:
        print(f"{p:12s} FAILED to run: {type(ex).__name__}: {ex}")
