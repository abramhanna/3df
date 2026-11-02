#!/usr/bin/env python3
"""Regression check for 3df2html.py output, with JavaScript disabled in the browser:
no scripts or network use, drag figures (GIF scrub and 3D orbit) hold still until
dragged, respond to sideways and vertical drags, return when dragged back, and
print as stills.

  python tests/check_static_html.py      (needs Playwright and LibreOffice)
"""
import io
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parent.parent
FAILS = []


def check(ok, label):
    print(("PASS " if ok else "FAIL ") + label)
    if not ok:
        FAILS.append(label)


def frame(pg, clip):
    return Image.open(io.BytesIO(pg.screenshot(clip=clip))).convert("RGB")


def same(a, b):
    return ImageChops.difference(a, b).getbbox() is None


def drag_test(pg, selector, label, moves, vertical=False):
    fig = pg.locator(selector).first
    fig.scroll_into_view_if_needed(); pg.wait_for_timeout(300)
    box = fig.bounding_box(); clip = {k: box[k] for k in ("x", "y", "width", "height")}
    start = frame(pg, clip); pg.wait_for_timeout(700)
    check(same(start, frame(pg, clip)), f"{label}: holds still until dragged")
    pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    prev, changed = start, 0
    for _ in range(moves):
        pg.mouse.wheel(0 if vertical else 80, 120 if vertical else 0); pg.wait_for_timeout(250)
        cur = frame(pg, clip); changed += not same(prev, cur); prev = cur
    check(changed >= moves - 1, f"{label}: {'vertical' if vertical else 'sideways'} drag changed the view {changed}/{moves}")
    pg.mouse.wheel(0 if vertical else -80 * moves, -120 * moves if vertical else 0); pg.wait_for_timeout(400)
    check(same(start, frame(pg, clip)), f"{label}: dragging back returns to the start")


def main():
    from playwright.sync_api import sync_playwright
    with tempfile.TemporaryDirectory() as tmp:
        pages = {}
        report = Path(tmp, "test_report.3df")        # converted fresh from the committed .docx
        subprocess.run([sys.executable, str(ROOT / "docx2_3df.py"), str(ROOT / "test_report.docx"), str(report)],
                       check=True, capture_output=True)
        sources = {"sample": ROOT / "sample.3df", "test_report": report}
        for name in ("sample", "test_report"):
            out = Path(tmp, name + ".html")
            subprocess.run([sys.executable, str(ROOT / "3df2html.py"), str(sources[name]), str(out)],
                           check=True, capture_output=True)
            html = out.read_text(encoding="utf-8")
            check(not re.search(r"<script|\son\w+=|(src|href)=\"https?:", html), f"{name}: no scripts, handlers or web links")
            pages[name] = out
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            ctx = browser.new_context(viewport={"width": 900, "height": 900}, java_script_enabled=False, offline=True)
            pg = ctx.new_page(); net = []
            pg.on("request", lambda r: net.append(r.url) if not r.url.startswith(("file:", "data:")) else None)
            pg.goto(pages["sample"].as_uri()); pg.wait_for_timeout(500)
            drag_test(pg, ".orbit", "3D model", 4)
            drag_test(pg, ".orbit", "3D model", 3, vertical=True)
            pg.goto(pages["test_report"].as_uri()); pg.wait_for_timeout(500)
            drag_test(pg, ".scrub >> nth=1", "GIF scrub", 4)
            check(not net, "no network requests")
            ctx2 = browser.new_context(); p2 = ctx2.new_page()
            p2.goto(pages["sample"].as_uri()); pdf = Path(tmp, "print.pdf"); p2.pdf(path=str(pdf), prefer_css_page_size=True)
            import pymupdf
            d = pymupdf.open(pdf)
            check(len(d) == 2, f"sample prints as 2 pages (got {len(d)})")
            browser.close()
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
