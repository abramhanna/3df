#!/usr/bin/env python3
"""Package a .3df as one self-contained .html that opens in any browser, offline.

  python export_html.py export report.3df [report.3df.html]
  python export_html.py extract report.3df.html [report.3df]

The .html is the viewer plus the untouched .3df, stored in
  <script type="application/vnd.3df+zip" id="threedf-document" data-encoding="base64">
so any tool can pull the original back out byte for byte. Nothing loads from the
network: the viewer's libraries come from vendor/, and three.js is only included
when the document contains 3D models.
"""
import base64
import json
import re
import sys
import zipfile
from pathlib import Path

import threedf

HERE = Path(__file__).parent
VENDOR = HERE / "vendor"
TAG_OPEN = '<script type="application/vnd.3df+zip" id="threedf-document" data-encoding="base64">'
CDN = {
    "jszip": ("https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js", "jszip.min.js"),
    "three": ("https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js", "three.min.js"),
    "gltf": ("https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/loaders/GLTFLoader.js", "GLTFLoader.js"),
    "orbit": ("https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js", "OrbitControls.js"),
}


def _inline(code):
    return "<script>\n" + code.replace("</script", "<\\/script") + "\n</script>"


def export(src, out=None):
    src = Path(src)
    errs = threedf.validate(src)
    if errs:
        raise threedf.ThreeDFError("not a valid .3df:\n" + "\n".join(errs))
    out = Path(out or src.with_name(src.name + ".html"))
    with zipfile.ZipFile(src) as z:
        doc = json.loads(z.read("document.json"))
    has_models = any(el.get("type") == "model" for p in doc["pages"] for el in p.get("elements", []))
    title = str(doc.get("title") or src.stem)

    html = (HERE / "viewer_template.html").read_text(encoding="utf-8")
    html = re.sub(r'<link rel="preconnect"[^>]*>\n?', "", html)              # no web fonts: system fonts only
    html = re.sub(r'<link href="https://fonts\.googleapis\.com[^>]*>\n?', "", html)
    html = html.replace("<title>3DF Viewer</title>", f"<title>{_esc(title)}</title>")
    for key, (url, file) in CDN.items():
        tag = f'<script src="{url}"></script>'
        if tag not in html:
            raise threedf.ThreeDFError(f"viewer_template.html no longer loads {url}; update export_html.py")
        keep = key == "jszip" or has_models
        html = html.replace(tag, _inline((VENDOR / file).read_text(encoding="utf-8")) if keep else "")

    payload = base64.b64encode(src.read_bytes()).decode()
    payload = "\n".join(payload[i:i + 120] for i in range(0, len(payload), 120))
    html = html.replace('<script>\nconst SAMPLE_B64 = "__SAMPLE_B64__";',
                        f"{TAG_OPEN}\n{payload}\n</script>\n<script>\n"
                        'const SAMPLE_B64 = document.getElementById("threedf-document").textContent.replace(/\\s+/g, "");', 1)
    html = html.replace('open3DF(b64ToBytes(SAMPLE_B64), "sample.3df")',
                        f"open3DF(b64ToBytes(SAMPLE_B64), {json.dumps(src.name)})")
    if not has_models:
        html = html.replace("if(!window.JSZip || !window.THREE || !THREE.GLTFLoader)", "if(!window.JSZip)")
    html = html.replace("Check your connection and reload.", "Try opening this file in Safari, Chrome or Edge.")

    if "__SAMPLE_B64__" in html or TAG_OPEN not in html:
        raise threedf.ThreeDFError("viewer_template.html changed shape; update export_html.py")
    outside_scripts = re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.S)
    if re.search(r'(src|href)="https?://', outside_scripts):
        raise threedf.ThreeDFError("exported page still references the network")
    out.write_text(html, encoding="utf-8")
    return out


def extract(html_path, out=None):
    html_path = Path(html_path)
    html = html_path.read_text(encoding="utf-8")
    m = re.search(re.escape(TAG_OPEN) + r"(.*?)</script>", html, flags=re.S)
    if not m:
        raise threedf.ThreeDFError("no embedded .3df found in this page")
    name = html_path.name[:-5] if html_path.name.endswith(".3df.html") else html_path.stem + ".3df"
    out = Path(out or html_path.with_name(name))
    out.write_bytes(base64.b64decode(re.sub(r"\s+", "", m.group(1))))
    errs = threedf.validate(out)
    if errs:
        raise threedf.ThreeDFError("extracted file is not a valid .3df:\n" + "\n".join(errs))
    return out


def _esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def main(argv):
    if len(argv) < 3 or argv[1] not in ("export", "extract"):
        print(__doc__)
        return 2
    try:
        out = (export if argv[1] == "export" else extract)(argv[2], argv[3] if len(argv) > 3 else None)
    except threedf.ThreeDFError as e:
        print(e)
        return 1
    print(f"wrote {out} ({out.stat().st_size / 1e6:.2f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
