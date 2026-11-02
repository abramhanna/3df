#!/usr/bin/env python3
"""Regression check: export_html.py refuses to build when viewer_template.html no longer
matches what it expects, instead of silently writing a broken page.

  python tests/check_export_guards.py
"""
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import export_html  # noqa: E402
import threedf  # noqa: E402

# Each string export_html.py rewrites; renaming any one of them must make export fail.
GUARDED = [
    "<title>3DF Viewer</title>",
    'const SAMPLE_B64 = "__SAMPLE_B64__";',
    'open3DF(b64ToBytes(SAMPLE_B64), "sample.3df")',
    "if(!window.JSZip || !window.THREE || !THREE.GLTFLoader)",   # only rewritten when there are no models
    "Check your connection and reload.",
    "https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js",
]


def main():
    template = (ROOT / "viewer_template.html").read_text(encoding="utf-8")
    failures = 0
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for f in ("vendor",):
            shutil.copytree(ROOT / f, tmp / f)
        fake_module_dir = tmp
        original_here = export_html.HERE
        export_html.HERE, export_html.VENDOR = fake_module_dir, fake_module_dir / "vendor"
        try:
            (tmp / "viewer_template.html").write_text(template, encoding="utf-8")
            export_html.export(ROOT / "test_report.3df", tmp / "ok.html")      # baseline must work
            print("PASS unmodified template exports")
            for s in GUARDED:
                assert s in template, f"test is stale: {s!r} not in template"
                (tmp / "viewer_template.html").write_text(template.replace(s, s[:4] + "X" + s[4:], 1), encoding="utf-8")
                try:
                    export_html.export(ROOT / "test_report.3df", tmp / "bad.html")
                    print(f"FAIL exported despite changed {s[:45]!r}"); failures += 1
                except threedf.ThreeDFError:
                    print(f"PASS refused when {s[:45]!r} changed")
        finally:
            export_html.HERE, export_html.VENDOR = original_here, original_here / "vendor"
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
