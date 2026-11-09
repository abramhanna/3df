#!/usr/bin/env python3
"""Robustness checks from the stress tests: messy real-world documents and hostile inputs.

  python tests/check_robustness.py        (needs LibreOffice)

1. A report with a logo in the page header, a transparent GIF, a reused GIF, a GIF in a
   table, a landscape page and hostile alt text converts with every GIF placed, alt text
   and [drag] kept, the landscape page undistorted, and no hostile text left unescaped in
   any export.
2. Corrupt, fake, missing and zip-bomb inputs make every tool stop with a short message,
   never a Python traceback, and never produce oversized output.
Tools that aren't in this checkout are skipped.
"""
import io
import json
import math
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.shared import Mm
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
FAILS = []
HOSTILE = '"><img src=x onerror=alert(2)><script>alert(3)</script>'


def check(ok, label):
    print(("PASS " if ok else "FAIL ") + label)
    if not ok:
        FAILS.append(label)


def gif(frames, **kw):
    b = io.BytesIO()
    frames[0].save(b, "GIF", save_all=True, append_images=frames[1:], duration=80, loop=0, **kw)
    return b.getvalue()


def bars(n):
    out = []
    for k in range(1, 7):
        im = Image.new("RGB", (480, 270), "white"); d = ImageDraw.Draw(im)
        for j in range(5):
            h = (j + 1) * k * (n + 2) % 230 + 10
            d.rectangle([30 + j * 90, 260 - h, 90 + j * 90, 260], fill=(40 + n * 30 % 200, 90, 160))
        out.append(im)
    return gif(out)


def spinner():
    out = []
    for i in range(10):
        im = Image.new("P", (200, 200), 0); im.putpalette([255, 255, 255] + [40, 90, 200] * 255)
        a = i / 10 * math.pi
        ImageDraw.Draw(im).line([100 - 80 * math.cos(a), 100 - 80 * math.sin(a),
                                 100 + 80 * math.cos(a), 100 + 80 * math.sin(a)], fill=1, width=14)
        out.append(im)
    return gif(out, transparency=0, disposal=2)


def build_messy(path):
    d = Document()
    s = d.sections[0]
    s.page_width, s.page_height = Mm(215.9), Mm(279.4)
    logo = io.BytesIO(); Image.new("RGB", (300, 80), (30, 60, 120)).save(logo, "PNG")
    s.header.paragraphs[0].add_run().add_picture(io.BytesIO(logo.getvalue()), width=Mm(30))
    d.add_paragraph('Body text with <script>alert("body")</script> in it.')
    figs = [("[drag] Transparent spinner", spinner()), ("Chart A", bars(1)), (HOSTILE, bars(2)),
            ("Chart A again", None)]
    blob_a = None
    for alt, blob in figs:
        if blob is None:
            blob = blob_a
        if alt == "Chart A":
            blob_a = blob
        for _ in range(6):
            d.add_paragraph("Filler paragraph to spread figures across pages. " * 4)
        d.add_picture(io.BytesIO(blob), width=Mm(90))._inline.docPr.set("descr", alt)
    t = d.add_table(rows=1, cols=2)
    t.cell(0, 1).paragraphs[0].add_run().add_picture(io.BytesIO(bars(3)), width=Mm(50))._inline.docPr.set("descr", "In a table")
    ns = d.add_section(); ns.orientation = WD_ORIENT.LANDSCAPE
    ns.page_width, ns.page_height = Mm(279.4), Mm(215.9)
    d.add_picture(io.BytesIO(bars(4)), width=Mm(200))._inline.docPr.set("descr", "Wide chart")
    d.save(path)


def run(tool, *args):
    r = subprocess.run([sys.executable, str(ROOT / tool), *map(str, args)], capture_output=True, text=True, timeout=600)
    return r.returncode, r.stdout + r.stderr


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        # --- 1. messy real-world document ---
        build_messy(tmp / "messy.docx")
        code, text = run("docx2_3df.py", tmp / "messy.docx", tmp / "messy.3df")
        check(code == 0 and "Traceback" not in text, "messy report converts")
        z = zipfile.ZipFile(tmp / "messy.3df")
        doc = json.loads(z.read("document.json"))
        gifs = [e for p in doc["pages"] for e in p["elements"] if e["type"] == "image" and e["src"].endswith(".gif")]
        alts = [e["alt"] for e in gifs]
        check(len(gifs) == 6, f"all 6 GIFs placed despite a header logo on every page (got {len(gifs)})")
        check("Could not place" not in text, "transparent GIF placed")
        check(alts.count("Chart A") == 1 and "Chart A again" in alts and "In a table" in alts and HOSTILE in alts,
              "alt text paired with the right pictures, including a reused GIF")
        spin = [e for e in gifs if e["alt"] == "Transparent spinner"]
        check(bool(spin) and spin[0].get("scrub") is True, "[drag] alt text sets scrub")
        last_bg = doc["pages"][-1]["elements"][0]
        check(abs(last_bg["w"] / last_bg["h"] - 279.4 / 215.9) < 0.01, "landscape page keeps its shape")
        wide = [e for e in gifs if e["alt"] == "Wide chart"][0]
        gw, gh = Image.open(io.BytesIO(z.read(wide["src"]))).size
        check(abs(wide["w"] / wide["h"] - gw / gh) < 0.02, "GIF on the landscape page keeps its shape")
        raw = ['<img src=x onerror=alert(2)>', '<script>alert(3)</script>', '<script>alert("body")</script>']
        exports = [("3df2html.py", "messy.html"), ("3df2epub.py", "messy.epub")]
        for tool, out in exports:
            if not (ROOT / tool).exists():
                continue
            code, text = run(tool, tmp / "messy.3df", tmp / out)
            body = (tmp / out).read_bytes()
            if out.endswith(".epub"):
                zz = zipfile.ZipFile(tmp / out); body = b"".join(zz.read(n) for n in zz.namelist() if n.endswith(".xhtml"))
            body = body.decode("utf-8", "replace")
            check(code == 0 and not any(r in body for r in raw), f"{tool}: hostile text escaped")

        # --- 2. broken and hostile inputs ---
        (tmp / "corrupt.docx").write_bytes(b"\x00\x01garbage" * 500)
        (tmp / "notes.txt").write_text("plain text")
        page = {"width_mm": 100, "height_mm": 100}
        with zipfile.ZipFile(tmp / "bomb.3df", "w", compression=zipfile.ZIP_DEFLATED) as zb:
            zb.writestr(zipfile.ZipInfo("mimetype"), "application/vnd.3df+zip", compress_type=zipfile.ZIP_STORED)
            zb.writestr("document.json", json.dumps({"3df": "0.1", "page": page, "pages": [{"elements": [
                {"type": "image", "x": 0, "y": 0, "w": 10, "h": 10, "src": "assets/big.png", "alt": "x"}]}]}))
            zb.writestr("assets/big.png", b"\0" * 300_000_000)
        cases = [("docx2_3df.py", [tmp / "corrupt.docx", tmp / "o.3df"]),
                 ("docx2_3df.py", [tmp / "missing.docx", tmp / "o.3df"]),
                 ("3df2html.py", [tmp / "bomb.3df", tmp / "bomb.html"]),
                 ("3df2epub.py", [tmp / "bomb.3df", tmp / "bomb.epub"]),
                 ("export_html.py", ["export", tmp / "bomb.3df", tmp / "bomb.v.html"]),
                 ("pdf3df.py", ["wrap", tmp / "bomb.3df", tmp / "bomb.pdf"]),
                 ("pdf3df.py", ["check", tmp / "notes.txt"]),
                 ("pdf3df.py", ["extract", tmp / "missing.pdf", tmp / "x.3df"]),
                 ("build_reader.py", [tmp / "notes.txt", tmp / "r.html"])]
        for tool, args in cases:
            if not (ROOT / tool).exists():
                continue
            code, text = run(tool, *args)
            label = f"{tool} {' '.join(Path(str(a)).name for a in args[:-1] or args)}"
            check(code != 0 and "Traceback" not in text, f"{label}: refused with a message, no crash")
        big = [p for p in tmp.glob("bomb.*") if p.suffix != ".3df" and p.stat().st_size > 50_000_000]
        check(not big, "zip bomb produced no oversized output")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
