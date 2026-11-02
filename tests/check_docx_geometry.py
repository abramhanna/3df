#!/usr/bin/env python3
"""Regression check: GIFs that a document crops or stretches are placed at the size
the page shows them, and the GIF itself is cropped or stretched to match.

  python tests/check_docx_geometry.py        (needs LibreOffice and test_report.docx)
"""
import io
import json
import sys
import tempfile
import zipfile
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from lxml import etree
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import docx2_3df  # noqa: E402


def variant(src, out, crop_right=0.0, squash=1.0):
    d = Document(src)
    inl = d.inline_shapes[0]._inline              # Figure 1, the deployment GIF
    if crop_right:
        fill = inl.find(".//" + qn("pic:blipFill"))
        rect = etree.Element(qn("a:srcRect")); rect.set("r", str(int(crop_right * 100000)))
        fill.insert(1, rect)
    inl.extent.cx = int(inl.extent.cx * squash)
    for ext in inl.iter(qn("a:ext")):
        ext.set("cx", str(int(int(ext.get("cx")) * squash)))
    d.save(out)


def first_gif(path):
    z = zipfile.ZipFile(path)
    doc = json.loads(z.read("document.json"))
    el = next(e for e in doc["pages"][0]["elements"] if e.get("src", "").endswith(".gif"))
    return el, Image.open(io.BytesIO(z.read(el["src"])))


def main():
    src = ROOT / "test_report.docx"
    failures = 0
    with tempfile.TemporaryDirectory() as tmp:
        cases = {"cropped 40% right": dict(crop_right=0.4, squash=0.6),
                 "squashed to 60% width": dict(squash=0.6)}
        for name, kw in cases.items():
            docx = Path(tmp, "v.docx"); out = Path(tmp, "v.3df")
            variant(src, docx, **kw)
            n, placed, warnings = docx2_3df.convert(docx, out)
            el, gif = first_gif(out)
            box_aspect, gif_aspect = el["w"] / el["h"], gif.width / gif.height
            ok = (placed == 2 and abs(el["w"] - 90) < 1 and abs(box_aspect - gif_aspect) / box_aspect < 0.03
                  and gif.n_frames == 26 and not warnings)
            failures += not ok
            print(f"{'PASS' if ok else 'FAIL'} {name}: {placed} GIFs placed, box {el['w']:.1f} x {el['h']:.1f} mm, "
                  f"GIF {gif.width}x{gif.height}, {gif.n_frames} frames, warnings {warnings}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
