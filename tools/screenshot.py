"""Screenshot the running Streamlit app with the system Chrome via Playwright.

    python tools_screenshot.py <out_dir> [width] [height] [dark] [pages...]

Pages are the URL slugs produced by st.navigation (title lower-cased, spaces
-> underscores). Writes full-page PNGs; used for the visual QA iterations.
"""

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

out = Path(sys.argv[1] if len(sys.argv) > 1 else "/home/claude/shots")
width = int(sys.argv[2]) if len(sys.argv) > 2 else 1440
height = int(sys.argv[3]) if len(sys.argv) > 3 else 900
dark = (sys.argv[4] if len(sys.argv) > 4 else "light") == "dark"
pages = sys.argv[5:] or ["", "sentiment", "momentum", "issues", "media", "geography", "authenticity", "projections",
                         "explorer", "methodology"]
out.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path="/usr/bin/google-chrome", headless=True,
                                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"])
    ctx = browser.new_context(viewport={"width": width, "height": height}, device_scale_factor=1,
                              color_scheme="dark" if dark else "light")
    page = ctx.new_page()
    page.goto("http://localhost:8501/", wait_until="networkidle", timeout=120000)
    page.wait_for_timeout(3000)
    for slug in pages:
        url = f"http://localhost:8501/{slug}"
        page.goto(url, wait_until="networkidle", timeout=120000)
        # wait for streamlit to finish running (status widget disappears)
        for _ in range(60):
            time.sleep(1)
            running = page.locator("[data-testid='stStatusWidget']").count()
            if running == 0:
                break
        time.sleep(2.5)
        # let plotly charts finish rendering
        page.wait_for_timeout(1500)
        name = (slug or "brief").replace("&", "and")
        # Streamlit's main area scrolls internally, so full_page=False + a tall viewport
        # sized to the content is what captures the whole page.
        total = page.evaluate("() => { const m = document.querySelector('[data-testid=stMain]') || document.scrollingElement; return m.scrollHeight; }")
        page.set_viewport_size({"width": width, "height": min(max(int(total) + 40, height), 12000)})
        page.wait_for_timeout(1200)
        page.screenshot(path=str(out / f"{name}_{width}{'_dark' if dark else ''}.png"), full_page=False)
        page.set_viewport_size({"width": width, "height": height})
        print("saved", name)
    browser.close()
