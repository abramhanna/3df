#!/usr/bin/env python3
"""Convert a .3df into an EPUB 3 fixed-layout book, so readers people already
have play its GIFs: Apple Books (iPhone, iPad, Mac), Google Play Books (Android),
and EPUB readers on Windows such as Thorium.

  python 3df2epub.py doc.3df [doc.epub]

Each 3DF page becomes one fixed-size XHTML page with every element at the same
position. Animated GIFs stay animated. 3D models appear as their still fallback,
since ebook readers have no 3D. Invisible text layers stay invisible but searchable.
"""
import datetime
import html
import json
import sys
import uuid
import zipfile
from pathlib import Path

import safety
import threedf

PX_PER_MM = 96 / 25.4
MEDIA = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}


def esc(s):
    return html.escape(str(s), quote=True)


def css_color(c):
    c = str(c or "")
    if len(c) == 9 and c.startswith("#"):        # #RRGGBBAA -> rgba(), widest reader support
        r, g, b, a = (int(c[i:i + 2], 16) for i in (1, 3, 5, 7))
        return f"rgba({r},{g},{b},{a / 255:.3f})"
    return c if c.startswith("#") and len(c) in (4, 7) else "#1C232E"


def page_xhtml(i, page, Wpx, Hpx, lang, title, asset_name):
    parts = []
    for el in sorted(page.get("elements", []), key=lambda e: e.get("z", 0)):
        box = (f"left:{el['x'] * PX_PER_MM:.2f}px;top:{el['y'] * PX_PER_MM:.2f}px;"
               f"width:{el['w'] * PX_PER_MM:.2f}px;height:{el['h'] * PX_PER_MM:.2f}px;z-index:{int(el.get('z', 0))}")
        if el["type"] in ("image", "model"):
            src = el["src"] if el["type"] == "image" else el.get("fallback")
            if not src or Path(src).suffix.lower() not in MEDIA:
                continue
            parts.append(f'<img class="el" style="{box}" src="{esc(asset_name(src))}" alt="{esc(el.get("alt", ""))}"/>')
        elif el["type"] == "text":
            size = float(el.get("font_size_pt", 11)) * 96 / 72
            style = (f"{box};font-size:{size:.2f}px;font-weight:{int(el.get('weight', 400))};"
                     f"color:{css_color(el.get('color'))};text-align:{el.get('align', 'left')}")
            if el.get("font_family"):
                style += f";font-family:{el['font_family']}, Georgia, serif"
            parts.append(f'<div class="el t" style="{esc(style)}">{esc(el["text"])}</div>')
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="{esc(lang)}" xml:lang="{esc(lang)}">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width={Wpx}, height={Hpx}"/>
<title>{esc(title)} – page {i}</title>
<link rel="stylesheet" type="text/css" href="page.css"/>
</head>
<body style="width:{Wpx}px;height:{Hpx}px">
<section class="page" epub:type="bodymatter" aria-label="Page {i}">
{chr(10).join(parts)}
</section>
</body>
</html>
"""


CSS = """@page { margin: 0; }
html, body { margin: 0; padding: 0; overflow: hidden; background: #fff; }
.page { position: relative; width: 100%; height: 100%; }
.el { position: absolute; display: block; margin: 0; }
img.el { object-fit: contain; }
.t { font-family: Georgia, "Times New Roman", serif; line-height: 1.35; overflow: hidden; white-space: pre-wrap; }
"""


def convert(src, out=None):
    src = Path(src)
    errs = threedf.validate(src)
    if errs:
        raise threedf.ThreeDFError(f"{src} is not a valid .3df:\n" + "\n".join(errs))
    try:
        safety.check_3df(src)
    except safety.UnsafePackage as e:
        raise threedf.ThreeDFError(str(e)) from None
    out = Path(out or src.with_suffix(".epub"))
    z = zipfile.ZipFile(src)
    doc = json.loads(z.read("document.json"))
    title = str(doc.get("title") or src.stem)
    author = str(doc.get("author") or "")
    lang = str(doc.get("lang") or "en")
    Wpx = round(doc["page"]["width_mm"] * PX_PER_MM)
    Hpx = round(doc["page"]["height_mm"] * PX_PER_MM)

    used, names = {}, {}

    def asset_name(path):           # 3DF asset path -> file name inside the EPUB
        if path not in names:
            ext = Path(path).suffix.lower()
            names[path] = f"img/a{len(names) + 1}{ext}"
            used[names[path]] = (path, MEDIA[ext])
        return names[path]

    pages = [page_xhtml(i, p, Wpx, Hpx, lang, title, asset_name) for i, p in enumerate(doc["pages"], 1)]
    book_id = "urn:uuid:" + str(uuid.uuid5(uuid.NAMESPACE_URL, "3df:" + src.name + ":" + str(len(z.read("document.json")))))
    modified = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Library thumbnail: the first full-page image if there is one
    cover = None
    first = doc["pages"][0].get("elements", [])
    for el in first:
        if el["type"] == "image" and el["x"] <= 0.5 and el["y"] <= 0.5 and el["w"] >= doc["page"]["width_mm"] - 1:
            cover = asset_name(el["src"])
            break

    manifest = ['<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
                '<item id="css" href="page.css" media-type="text/css"/>']
    manifest += [f'<item id="p{i}" href="page{i}.xhtml" media-type="application/xhtml+xml"/>'
                 for i in range(1, len(pages) + 1)]
    for k, (name, (_, mime)) in enumerate(sorted(used.items()), 1):
        props = ' properties="cover-image"' if name == cover else ""
        manifest.append(f'<item id="img{k}" href="{name}" media-type="{mime}"{props}/>')
    spine = "\n    ".join(f'<itemref idref="p{i}"/>' for i in range(1, len(pages) + 1))
    opf = f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid" xml:lang="{esc(lang)}">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">{book_id}</dc:identifier>
    <dc:title>{esc(title)}</dc:title>
    {f'<dc:creator>{esc(author)}</dc:creator>' if author else ''}
    <dc:language>{esc(lang)}</dc:language>
    <meta property="dcterms:modified">{modified}</meta>
    <meta property="rendition:layout">pre-paginated</meta>
    <meta property="rendition:spread">none</meta>
    <meta property="rendition:orientation">auto</meta>
    <meta property="schema:accessMode">textual</meta>
    <meta property="schema:accessMode">visual</meta>
    <meta property="schema:accessibilityFeature">alternativeText</meta>
    <meta property="schema:accessibilityHazard">none</meta>
    <meta property="schema:accessibilitySummary">Fixed-layout pages converted from a 3DF document. Animated figures have text alternatives.</meta>
    <meta name="generator" content="3df2epub.py (3DF {esc(doc.get('3df', ''))})"/>
  </metadata>
  <manifest>
    {chr(10).join('    ' + m for m in manifest).strip()}
  </manifest>
  <spine>
    {spine}
  </spine>
</package>
"""
    toc = "\n".join(f'<li><a href="page{i}.xhtml">Page {i}</a></li>' for i in range(1, len(pages) + 1))
    nav = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="{esc(lang)}" xml:lang="{esc(lang)}">
<head><meta charset="UTF-8"/><title>{esc(title)}</title></head>
<body>
<nav epub:type="toc" id="toc"><h1>{esc(title)}</h1><ol>
{toc}
</ol></nav>
<nav epub:type="page-list" hidden=""><ol>
{chr(10).join(f'<li><a href="page{i}.xhtml">{i}</a></li>' for i in range(1, len(pages) + 1))}
</ol></nav>
</body>
</html>
"""
    container = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>
"""
    with zipfile.ZipFile(out, "w") as e:
        e.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        e.writestr("META-INF/container.xml", container, compress_type=zipfile.ZIP_DEFLATED)
        e.writestr("OEBPS/content.opf", opf, compress_type=zipfile.ZIP_DEFLATED)
        e.writestr("OEBPS/nav.xhtml", nav, compress_type=zipfile.ZIP_DEFLATED)
        e.writestr("OEBPS/page.css", CSS, compress_type=zipfile.ZIP_DEFLATED)
        for i, x in enumerate(pages, 1):
            e.writestr(f"OEBPS/page{i}.xhtml", x, compress_type=zipfile.ZIP_DEFLATED)
        for name, (path, _) in used.items():
            e.writestr(f"OEBPS/{name}", z.read(path), compress_type=zipfile.ZIP_STORED)
    return out


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(2)
    try:
        o = convert(*sys.argv[1:3])
    except threedf.ThreeDFError as err:
        print(err); sys.exit(1)
    print(f"wrote {o} ({o.stat().st_size / 1e6:.2f} MB)")
