#!/usr/bin/env python3
"""3DF-in-PDF: ship a .3df as an ordinary PDF that every device can open.

  python pdf3df.py wrap doc.3df out.pdf [--print print.pdf] [--viewer viewer.html]
  python pdf3df.py extract file.pdf [out.3df]
  python pdf3df.py check file.pdf

The result is a real PDF, not a disguised file. Plain readers show the pages,
with still frames where the document moves. 3DF-aware readers find the .3df
inside and play it in place. The structure uses only standard PDF features:

  * The .3df is an associated file (PDF 2.0 / PDF/A-3 /AF) with
    /AFRelationship /Alternative: "another representation of this content".
  * Each moving element gets an invisible Link annotation over its spot on the
    page, carrying /NM (3df:p<page>:e<element>) and alt text in /Contents,
    and pointing to the same associated file.
  * XMP metadata declares tdf:version, with the PDF/A extension schema that
    PDF/A requires for custom properties.

--print  use this PDF for the pages (e.g. the PDF/A-3 edition from docx2_3df.py
         --pdf). It must have the same page count and size as the .3df.
         Without it, pages are drawn from the .3df's own static content.
--viewer also attach an offline HTML viewer (from export_html.py) as a supplement.
"""
import argparse
import datetime
import hashlib
import io
import json
import re
import sys
import zipfile
from pathlib import Path

import pikepdf
from pikepdf import Array, Dictionary, Name, String

import safety
import threedf

MIME = threedf.MIMETYPE
NS = "https://github.com/mfogelson/3df/ns/0.1/"
PREFIX = "tdf"
PT_PER_MM = 72 / 25.4
ANIMATED_EXT = {".gif", ".webp"}


# ---------- reading the .3df ----------

def open_pdf(path):
    """pikepdf.open with a plain message instead of a traceback for missing or non-PDF files."""
    if not Path(path).is_file():
        raise threedf.ThreeDFError(f"{path} not found")
    try:
        return pikepdf.open(path)
    except pikepdf.PdfError as e:
        raise threedf.ThreeDFError(f"{Path(path).name} is not a readable PDF ({str(e).split(': ')[-1]})") from None


def load_3df(path):
    errs = threedf.validate(path)
    if errs:
        raise threedf.ThreeDFError(f"{path} is not a valid .3df:\n" + "\n".join(errs))
    try:
        safety.check_3df(path)
    except safety.UnsafePackage as e:
        raise threedf.ThreeDFError(str(e)) from None
    z = zipfile.ZipFile(path)
    return z, json.loads(z.read("document.json"))


def moving_elements(doc):
    """(page_index, element_index, element) for everything a plain PDF can only show as a still."""
    for pi, page in enumerate(doc["pages"]):
        for ei, el in enumerate(page.get("elements", [])):
            if el.get("type") == "model" or (el.get("type") == "image" and el.get("fallback")
                                             and Path(el.get("src", "")).suffix.lower() in ANIMATED_EXT):
                yield pi, ei, el


# ---------- drawing pages when no print PDF is given ----------

def draw_pages(z, doc):
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.pdfgen import canvas
    from PIL import Image

    W, H = doc["page"]["width_mm"] * PT_PER_MM, doc["page"]["height_mm"] * PT_PER_MM
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(W, H))
    c.setTitle(str(doc.get("title", ""))); c.setAuthor(str(doc.get("author", "")))
    for page in doc["pages"]:
        for el in sorted(page.get("elements", []), key=lambda e: e.get("z", 0)):
            x, y, w, h = (el[k] * PT_PER_MM for k in ("x", "y", "w", "h"))
            top = H - y
            if el["type"] in ("image", "model"):
                src = el.get("fallback") or el["src"]
                if Path(src).suffix.lower() == ".glb":
                    continue
                im = Image.open(io.BytesIO(z.read(src)))
                im.seek(0)
                im = im.convert("RGBA") if im.mode in ("RGBA", "LA", "P") else im.convert("RGB")
                # object-fit: contain, as the viewer draws it
                s = min(w / im.width, h / im.height)
                dw, dh = im.width * s, im.height * s
                c.drawImage(ImageReader(im), x + (w - dw) / 2, top - h + (h - dh) / 2, dw, dh, mask="auto")
            elif el["type"] == "text":
                size = float(el.get("font_size_pt", 11))
                bold = int(el.get("weight", 400)) >= 600
                font = "Times-Bold" if bold else "Times-Roman"
                color = str(el.get("color", "#1C232E"))
                invisible = len(color) == 9 and color.endswith("00")
                t = c.beginText()
                t.setFont(font, size, leading=size * 1.35)
                t.setTextRenderMode(3 if invisible else 0)      # 3 = invisible but searchable
                if not invisible:
                    t.setFillColor(color[:7])
                t.setTextOrigin(x, top - size)
                for para in str(el["text"]).split("\n"):
                    line = ""
                    for word in para.split():
                        test = (line + " " + word).strip()
                        if stringWidth(test, font, size) > w and line:
                            t.textLine(line); line = word
                        else:
                            line = test
                    t.textLine(line)
                c.drawText(t)
        c.showPage()
    c.save()
    return pikepdf.open(io.BytesIO(buf.getvalue()))


# ---------- structure ----------

def page_rect(mediabox, W_mm, H_mm, el):
    """Where a .3df element lands on a PDF page. A page whose size differs from the .3df's is
    shown on the .3df page scaled uniformly to fit and centred (as docx2_3df.py lays it out),
    so map back through that; for same-size pages this is a plain mm-to-points conversion."""
    x0, y0, x1, y1 = (float(v) for v in mediabox)
    pw, ph = (x1 - x0) / PT_PER_MM, (y1 - y0) / PT_PER_MM
    s = min(W_mm / pw, H_mm / ph)
    ox, oy = (W_mm - pw * s) / 2, (H_mm - ph * s) / 2
    k = PT_PER_MM / s
    return [x0 + (el["x"] - ox) * k, y1 - (el["y"] + el["h"] - oy) * k,
            x0 + (el["x"] + el["w"] - ox) * k, y1 - (el["y"] - oy) * k]


def _pdf_date(dt):
    return dt.strftime("D:%Y%m%d%H%M%S+00'00'")


def _filespec(pdf, data, filename, mime, desc, relationship):
    now = _pdf_date(datetime.datetime.now(datetime.timezone.utc))
    ef = pikepdf.Stream(pdf, data)
    ef.Type = Name.EmbeddedFile
    ef.Subtype = Name("/" + mime)
    ef.Params = Dictionary(Size=len(data), ModDate=String(now), CheckSum=String(hashlib.md5(data).digest()))
    return pdf.make_indirect(Dictionary(Type=Name.Filespec, F=String(filename), UF=String(filename),
                                        Desc=String(desc), AFRelationship=relationship,
                                        EF=Dictionary(F=ef, UF=ef)))


def _add_to_names(pdf, name, spec):
    if "/Names" not in pdf.Root:
        pdf.Root.Names = Dictionary()
    names = pdf.Root.Names
    if "/EmbeddedFiles" not in names:
        names.EmbeddedFiles = pdf.make_indirect(Dictionary(Names=Array()))
    arr = names.EmbeddedFiles.Names
    arr.append(String(name)); arr.append(spec)


def _xmp_add(pdf, version, attachment):
    """Add tdf:version/tdf:attachment plus the PDF/A extension schema that describes them."""
    if "/Metadata" in pdf.Root:
        xmp = pdf.Root.Metadata.read_bytes().decode("utf-8")
    else:
        xmp = ('<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?><x:xmpmeta xmlns:x="adobe:ns:meta/">'
               '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"></rdf:RDF></x:xmpmeta>'
               '<?xpacket end="w"?>')
    xmp = re.sub(r'<rdf:Description[^>]*xmlns:(pdfaExtension|tdf)=.*?</rdf:Description>\s*', "", xmp, flags=re.S)
    prop = lambda n, d: (f'<rdf:li rdf:parseType="Resource"><pdfaProperty:name>{n}</pdfaProperty:name>'
                         f'<pdfaProperty:valueType>Text</pdfaProperty:valueType>'
                         f'<pdfaProperty:category>external</pdfaProperty:category>'
                         f'<pdfaProperty:description>{d}</pdfaProperty:description></rdf:li>')
    block = (
        '<rdf:Description rdf:about="" xmlns:pdfaExtension="http://www.aiim.org/pdfa/ns/extension/" '
        'xmlns:pdfaSchema="http://www.aiim.org/pdfa/ns/schema#" xmlns:pdfaProperty="http://www.aiim.org/pdfa/ns/property#">'
        '<pdfaExtension:schemas><rdf:Bag><rdf:li rdf:parseType="Resource">'
        '<pdfaSchema:schema>3DF document</pdfaSchema:schema>'
        f'<pdfaSchema:namespaceURI>{NS}</pdfaSchema:namespaceURI><pdfaSchema:prefix>{PREFIX}</pdfaSchema:prefix>'
        '<pdfaSchema:property><rdf:Seq>'
        + prop("version", "3DF specification version of the attached document")
        + prop("attachment", "File name of the attached .3df that this PDF is a still rendering of")
        + '</rdf:Seq></pdfaSchema:property></rdf:li></rdf:Bag></pdfaExtension:schemas></rdf:Description>'
        f'<rdf:Description rdf:about="" xmlns:{PREFIX}="{NS}">'
        f'<{PREFIX}:version>{version}</{PREFIX}:version><{PREFIX}:attachment>{_xml(attachment)}</{PREFIX}:attachment>'
        '</rdf:Description>')
    xmp = xmp.replace("</rdf:RDF>", block + "</rdf:RDF>", 1)
    stream = pikepdf.Stream(pdf, xmp.encode("utf-8"))
    stream.Type, stream.Subtype = Name.Metadata, Name.XML
    pdf.Root.Metadata = pdf.make_indirect(stream)


def _xml(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def wrap(src, out, print_pdf=None, viewer=None):
    src, out = Path(src), Path(out)
    z, doc = load_3df(src)
    W_mm, H_mm = doc["page"]["width_mm"], doc["page"]["height_mm"]
    pdf = open_pdf(print_pdf) if print_pdf else draw_pages(z, doc)
    if len(pdf.pages) != len(doc["pages"]):
        raise threedf.ThreeDFError(f"print PDF has {len(pdf.pages)} pages but the .3df has {len(doc['pages'])}")
    mb = [float(v) for v in pdf.pages[0].mediabox]
    if abs((mb[2] - mb[0]) / PT_PER_MM - W_mm) > 1 or abs((mb[3] - mb[1]) / PT_PER_MM - H_mm) > 1:
        raise threedf.ThreeDFError(f"print PDF page 1 is not {W_mm} x {H_mm} mm like the .3df")
    if "/AF" in pdf.Root or "/Names" in pdf.Root and "/EmbeddedFiles" in pdf.Root.Names:
        raise threedf.ThreeDFError("this PDF already carries attachments; wrap a clean print edition")

    name = src.name if src.suffix == ".3df" else src.stem + ".3df"
    spec = _filespec(pdf, src.read_bytes(), name, MIME,
                     "3DF document: the moving version of this PDF", Name.Alternative)
    af = Array([spec])
    _add_to_names(pdf, name, spec)
    if viewer:
        v = Path(viewer)
        vspec = _filespec(pdf, v.read_bytes(), v.name, "text/html",
                          "Offline viewer: open in any browser to see this document move", Name.Supplement)
        af.append(vspec)
        _add_to_names(pdf, v.name, vspec)
    pdf.Root.AF = af

    n = 0
    for pi, ei, el in moving_elements(doc):
        pg = pdf.pages[pi]
        rect = page_rect(pg.mediabox, W_mm, H_mm, el)
        kind = "3D model" if el["type"] == "model" else "Animated figure"
        annot = pdf.make_indirect(Dictionary(
            Type=Name.Annot, Subtype=Name.Link, Rect=Array([round(v, 3) for v in rect]),
            Border=Array([0, 0, 0]), F=4,                         # Print flag, as PDF/A requires
            NM=String(f"3df:p{pi + 1}:e{ei + 1}"), Contents=String(f"{kind}: {el.get('alt', '')}"),
            AF=Array([spec])))
        if "/Annots" not in pg.obj:
            pg.obj.Annots = Array()
        pg.obj.Annots.append(annot)
        n += 1

    _xmp_add(pdf, doc.get("3df", threedf.SPEC_VERSION), name)
    pdf.save(out)
    return out, n


def _find_3df(pdf):
    for spec in pdf.Root.get("/AF", Array()):
        ef = spec.get("/EF", {}).get("/F")
        if ef is None:
            continue
        mime = str(ef.get("/Subtype", "")).lstrip("/").replace("#2F", "/")
        if mime == MIME or str(spec.get("/UF", spec.get("/F", ""))).endswith(".3df"):
            return spec, ef.read_bytes()
    return None, None


def extract(path, out=None):
    pdf = open_pdf(path)
    spec, data = _find_3df(pdf)
    if data is None:
        raise threedf.ThreeDFError("no 3DF document attached to this PDF")
    out = Path(out or Path(path).with_suffix(".3df"))
    out.write_bytes(data)
    errs = threedf.validate(out)
    if errs:
        raise threedf.ThreeDFError("attached file is not a valid .3df:\n" + "\n".join(errs))
    return out


def check(path):
    """Human-readable report; returns (ok, lines)."""
    lines, ok = [], True
    pdf = open_pdf(path)
    xmp = pdf.Root.Metadata.read_bytes().decode("utf-8", "replace") if "/Metadata" in pdf.Root else ""
    part = re.search(r"pdfaid:part(?:>|=\")(\d)", xmp)
    conf = re.search(r"pdfaid:conformance(?:>|=\")(\w)", xmp)
    lines.append(f"PDF {pdf.pdf_version}, {len(pdf.pages)} pages"
                 + (f", declares PDF/A-{part.group(1)}{conf.group(1).lower() if conf else ''}" if part else ", not PDF/A"))
    ver = re.search(rf"<{PREFIX}:version>([^<]+)<", xmp)
    lines.append(f"3DF marker in metadata: {ver.group(1) if ver else 'none'}")
    spec, data = _find_3df(pdf)
    if data is None:
        if ver:      # metadata promises a 3DF document that isn't there
            dangling = [str(s.get("/UF", s.get("/F", "?"))) for s in pdf.Root.get("/AF", Array())
                        if str(s.get("/UF", s.get("/F", ""))).endswith(".3df")]
            lines.append("The metadata declares 3DF " + ver.group(1) + ", but "
                         + (f"the associated file {dangling[0]} has no embedded data." if dangling
                            else "no 3DF document is attached as an associated file (/AF)."))
            lines.append("PROBLEMS FOUND")
            return False, lines
        lines.append("No 3DF document attached: this is a plain PDF.")
        return True, lines
    rel = str(spec.get("/AFRelationship", ""))
    lines.append(f"Attached {spec.get('/UF', spec.get('/F'))} ({len(data) / 1e6:.2f} MB), relationship {rel}")
    if rel != "/Alternative":
        ok = False; lines.append("  expected /AFRelationship /Alternative")
    zb = io.BytesIO(data)
    try:
        z = zipfile.ZipFile(zb)
        doc = json.loads(z.read("document.json"))
        tmp = Path(path).with_suffix(".check.3df"); tmp.write_bytes(data)
        errs = threedf.validate(tmp); tmp.unlink()
    except Exception as e:
        doc, errs = None, [str(e)]
    if errs:
        ok = False; lines += ["  attached .3df is invalid:"] + ["    " + e for e in errs]
        return ok, lines
    lines.append("  attached .3df validates against spec " + doc.get("3df", "?"))
    want = {f"3df:p{pi + 1}:e{ei + 1}": (pi, el) for pi, ei, el in moving_elements(doc)}
    seen = {}
    for pi, pg in enumerate(pdf.pages):
        for a in pg.obj.get("/Annots", Array()):
            nm = str(a.get("/NM", ""))
            if nm.startswith("3df:"):
                seen[nm] = (pi, [float(v) for v in a.Rect])
    lines.append(f"Moving elements: {len(want)} in the .3df, {len(seen)} marked on the pages")
    W_mm, H_mm = doc["page"]["width_mm"], doc["page"]["height_mm"]
    for nm, (pi, el) in want.items():
        if nm not in seen:
            ok = False; lines.append(f"  {nm} has no annotation"); continue
        spi, r = seen[nm]
        exp = page_rect(pdf.pages[spi].mediabox, W_mm, H_mm, el)
        if spi != pi or max(abs(a - b) for a, b in zip(r, exp)) > 0.5:
            ok = False; lines.append(f"  {nm} is not where the .3df puts it")
    others = [str(s.get("/UF", s.get("/F"))) for s in pdf.Root.get("/AF", Array()) if s.objgen != spec.objgen]
    if others:
        lines.append("Other associated files: " + ", ".join(others))
    lines.append("OK" if ok else "PROBLEMS FOUND")
    return ok, lines


def main(argv=None):
    ap = argparse.ArgumentParser(description="Ship a .3df inside an ordinary PDF.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("wrap"); w.add_argument("src"); w.add_argument("out")
    w.add_argument("--print", dest="print_pdf"); w.add_argument("--viewer")
    e = sub.add_parser("extract"); e.add_argument("pdf"); e.add_argument("out", nargs="?")
    c = sub.add_parser("check"); c.add_argument("pdf")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "wrap":
            out, n = wrap(a.src, a.out, a.print_pdf, a.viewer)
            print(f"wrote {out} ({out.stat().st_size / 1e6:.2f} MB), {n} moving element{'s' if n != 1 else ''} marked")
        elif a.cmd == "extract":
            print(f"wrote {extract(a.pdf, a.out)}")
        else:
            ok, lines = check(a.pdf)
            print("\n".join(lines))
            return 0 if ok else 1
    except threedf.ThreeDFError as err:
        print(err)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
