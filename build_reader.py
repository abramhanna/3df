#!/usr/bin/env python3
"""Build reader.html: an offline, single-file PDF reader that plays 3DF content.

  python build_reader.py [demo.pdf] [out.html]

Opens any PDF. If the PDF carries a .3df (see pdf3df.py), its animated figures
play in place over the page; otherwise it reads like any PDF viewer. Uses the
vendored PDF.js 3.11 and JSZip, so it needs no network. With demo.pdf, that file
opens automatically.
"""
import base64
import sys
from pathlib import Path

HERE = Path(__file__).parent
V = HERE / "vendor"


def inline(path):
    return "<script>\n" + path.read_text(encoding="utf-8").replace("</script", "<\\/script") + "\n</script>"


def build(demo=None, out=None):
    out = Path(out or HERE / "reader.html")
    html = (HERE / "reader_template.html").read_text(encoding="utf-8")
    worker = (V / "pdf.worker.min.js").read_text(encoding="utf-8").replace("</script", "<\\/script")
    html = html.replace("__PDF_WORKER__", worker, 1)
    html = html.replace("__PDFJS__", inline(V / "pdf.min.js"), 1)
    html = html.replace("__JSZIP__", inline(V / "jszip.min.js"), 1)
    if demo:
        if not Path(demo).is_file():
            raise SystemExit(f"{demo} not found")
        if not Path(demo).read_bytes()[:1024].lstrip().startswith(b"%PDF-"):
            raise SystemExit(f"{Path(demo).name} is not a PDF")
        data = base64.b64encode(Path(demo).read_bytes()).decode()
        data = "\n".join(data[i:i + 120] for i in range(0, len(data), 120))
        html = html.replace("__DEMO_B64__", data, 1).replace("__DEMO_NAME__", Path(demo).name.replace('"', ""), 1)
    else:
        html = html.replace("__DEMO_B64__", "", 1).replace("__DEMO_NAME__", "", 1)
    out.write_text(html, encoding="utf-8")
    return out


if __name__ == "__main__":
    o = build(*sys.argv[1:3])
    print(f"wrote {o} ({o.stat().st_size / 1e6:.2f} MB)")
