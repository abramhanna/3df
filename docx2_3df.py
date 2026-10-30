#!/usr/bin/env python3
"""Convert a Word or Google Docs document (.docx) into a .3df document whose GIFs play.

  python docx2_3df.py report.docx [report.3df] [--gifs FOLDER] [--pdf report.pdf] [--dpi 150]

Google Docs: File > Download > Microsoft Word (.docx), then run this.

How it works
  1. LibreOffice lays out the document exactly as printed; each page becomes a
     full-page image, so fonts, tables, lists and spacing are kept as drawn.
  2. Every picture on each page is compared with the document's animated GIFs.
     Where one matches, the GIF is laid over the page at the same spot, so it plays.
     The page region underneath becomes the GIF's static fallback for printing.
  3. The page's words go on top as an invisible text layer, so the document can be
     searched, selected, copied and read by screen readers, like a scanned PDF with OCR.

If an exporter flattened your GIFs into still images, pass the original GIF files
with --gifs FOLDER and they are matched against the pictures in the document.

Requires: LibreOffice, and `pip install python-docx pymupdf pillow numpy`.
"""
import argparse
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

import numpy as np
import pymupdf
from docx import Document
from PIL import Image, ImageSequence

import threedf
from pptx2_3df import find_soffice, render_pdf

PT_PER_MM = 72 / 25.4
INVISIBLE = "#00000000"        # 8-digit CSS hex: fully transparent text
SIG = 24                       # signature thumbnail size for matching pictures
MATCH_LIMIT = 14.0             # mean grey-level difference (0-255) below which pictures match


# ---------- finding the animated GIFs ----------

def signature(img):
    """Small grey thumbnail used to recognise the same picture after re-encoding."""
    im = img.convert("RGBA")
    flat = Image.new("RGBA", im.size, (255, 255, 255, 255))
    flat.alpha_composite(im)
    return np.asarray(flat.convert("L").resize((SIG, SIG), Image.BILINEAR), dtype=np.float32)


def animated_gifs(docx, extra_dir=None):
    """Return [{name, blob, sig, aspect, frames}] for every animated GIF in the .docx (plus --gifs)."""
    found = []

    def add(name, blob):
        try:
            im = Image.open(__import__("io").BytesIO(blob))
            frames = getattr(im, "n_frames", 1)
        except Exception:
            return
        if im.format != "GIF" or frames < 2:
            return
        im.seek(0)
        found.append({"name": name, "blob": blob, "sig": signature(im),
                      "aspect": im.width / im.height, "frames": frames})

    with zipfile.ZipFile(docx) as z:
        for n in z.namelist():
            if n.startswith("word/media/") and n.lower().endswith(".gif"):
                add(Path(n).name, z.read(n))
    if extra_dir:
        for f in sorted(Path(extra_dir).glob("*")):
            if f.suffix.lower() == ".gif":
                add(f.name, f.read_bytes())
    return found


def alt_texts(docx):
    """Map media file name -> author-written alt text (Word/Docs 'Alt text' field)."""
    out = {}
    d = Document(docx)
    for shape in d.inline_shapes:
        inline = shape._inline
        descr = (inline.docPr.get("descr") or inline.docPr.get("title") or "").strip()
        blips = inline.xpath(".//a:blip/@r:embed")
        if descr and blips:
            part = d.part.related_parts.get(blips[0])
            if part is not None:
                out[Path(str(part.partname)).name] = descr
    return out


def best_match(pix_img, bbox, gifs):
    s = signature(pix_img)
    aspect = (bbox.width / bbox.height) if bbox.height else 0
    best, score = None, MATCH_LIMIT
    for g in gifs:
        if aspect and abs(g["aspect"] - aspect) / g["aspect"] > 0.04:
            continue
        diff = float(np.abs(g["sig"] - s).mean())
        if diff < score:
            best, score = g, diff
    return best


# ---------- text layer ----------

def text_lines(page):
    """One invisible text element per printed line, positioned in mm."""
    lines = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            spans = [s for s in line["spans"] if s["text"].strip()]
            if not spans or line["dir"] != (1.0, 0.0):
                continue
            text = "".join(s["text"] for s in line["spans"]).strip()
            x0, y0, x1, y1 = line["bbox"]
            size = max(s["size"] for s in spans)
            lines.append({"text": text, "x0": x0, "y0": y0, "x1": x1, "y1": y1, "size": size})
    return lines


def caption_below(lines, bbox):
    """The first short line just under a picture, used as alt text when none was written."""
    for ln in sorted(lines, key=lambda l: l["y0"]):
        if 0 <= ln["y0"] - bbox.y1 < 30 and ln["x0"] < bbox.x1 and ln["x1"] > bbox.x0:
            return ln["text"]
    return ""


# ---------- conversion ----------

def save_page_image(img, path_stem):
    """PNG keeps text crisp; switch to JPEG only for photo-heavy pages where PNG gets large."""
    png = path_stem.with_suffix(".png")
    img.save(png, optimize=True)
    if png.stat().st_size > 900_000:
        jpg = path_stem.with_suffix(".jpg")
        img.save(jpg, quality=88, optimize=True)
        png.unlink()
        return jpg
    return png


def convert(docx, out, dpi=150, soffice=None, gif_dir=None, pdf_out=None):
    docx = Path(docx)
    if not docx.is_file():
        sys.exit(f"{docx} not found")
    if docx.suffix.lower() != ".docx":
        sys.exit("Only .docx is supported. In Google Docs use File > Download > Microsoft Word (.docx).")
    gifs = animated_gifs(docx, gif_dir)
    alts = alt_texts(docx)
    props = Document(docx).core_properties
    warnings = []
    if not gifs:
        warnings.append("No animated GIFs found. If your exporter flattened them, pass the originals with --gifs FOLDER.")

    with tempfile.TemporaryDirectory() as tmp:
        pdf = render_pdf(docx, tmp, find_soffice(soffice))
        if pdf_out:
            shutil.copyfile(pdf, pdf_out)
        pdoc = pymupdf.open(pdf)
        W_mm, H_mm = pdoc[0].rect.width / PT_PER_MM, pdoc[0].rect.height / PT_PER_MM
        root = Path(tmp, "doc")
        (root / "assets").mkdir(parents=True)
        used, pages = {}, []

        for i, page in enumerate(pdoc, 1):
            if abs(page.rect.width / PT_PER_MM - W_mm) > 0.5 or abs(page.rect.height / PT_PER_MM - H_mm) > 0.5:
                warnings.append(f"Page {i}: size differs from page 1; 3DF v0.1 uses one page size, so it is scaled.")
            sx, sy = W_mm / page.rect.width, H_mm / page.rect.height
            pix = page.get_pixmap(dpi=dpi)
            bg = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            bg_file = save_page_image(bg, root / f"assets/page{i}")
            lines = text_lines(page)
            elements = [{"type": "image", "x": 0, "y": 0, "w": round(W_mm, 2), "h": round(H_mm, 2),
                         "src": f"assets/{bg_file.name}", "alt": f"Page {i}", "z": 0}]

            for k, info in enumerate(page.get_image_info(xrefs=True), 1):
                if not info.get("xref"):
                    continue
                bbox = pymupdf.Rect(info["bbox"]) & page.rect
                if bbox.is_empty or bbox.width < 4 or bbox.height < 4:
                    continue
                try:
                    p = pymupdf.Pixmap(pdoc, info["xref"])
                    if p.n - p.alpha >= 4:
                        p = pymupdf.Pixmap(pymupdf.csRGB, p)
                    shown = Image.frombytes("RGBA" if p.alpha else "RGB", (p.width, p.height), p.samples)
                except Exception:
                    continue
                g = best_match(shown, bbox, gifs)
                if g is None:
                    continue
                src = used.get(g["name"])
                if src is None:                      # store each GIF once, however often it appears
                    src = f"assets/anim{len(used) + 1}.gif"
                    (root / src).write_bytes(g["blob"])
                    used[g["name"]] = src
                scale = bg.width / page.rect.width
                crop = bg.crop((round(bbox.x0 * scale), round(bbox.y0 * scale),
                                round(bbox.x1 * scale), round(bbox.y1 * scale)))
                fb = f"assets/page{i}_anim{k}_fallback.png"
                crop.save(root / fb, optimize=True)
                elements.append({"type": "image", "x": round(bbox.x0 * sx, 2), "y": round(bbox.y0 * sy, 2),
                                 "w": round(bbox.width * sx, 2), "h": round(bbox.height * sy, 2),
                                 "src": src, "fallback": fb, "z": 1,
                                 "alt": alts.get(g["name"]) or caption_below(lines, bbox) or "Animated figure"})

            for ln in lines:
                h_pt = (ln["y1"] - ln["y0"]) * 1.25
                elements.append({"type": "text", "text": ln["text"],
                                 "x": round(ln["x0"] * sx, 2), "y": round(ln["y0"] * sy, 2),
                                 # extra width so a wider fallback font never wraps the invisible line
                                 "w": round(max(W_mm - ln["x0"] * sx, (ln["x1"] - ln["x0"]) * sx), 2),
                                 "h": round(h_pt * sy, 2),
                                 "font_size_pt": round(ln["size"], 1), "color": INVISIBLE, "z": 2})
            pages.append({"elements": elements})

        missing = [g["name"] for g in gifs if g["name"] not in used]
        if missing:
            warnings.append("Could not place: " + ", ".join(missing) + " (not found on any page)")
        doc = {"3df": threedf.SPEC_VERSION,
               "title": props.title or docx.stem,
               "author": props.author or "",
               "page": {"width_mm": round(W_mm, 2), "height_mm": round(H_mm, 2)},
               "pages": pages}
        (root / "document.json").write_text(json.dumps(doc, indent=1))
        threedf.pack(root, out)
    return len(pages), len(used), warnings


def main():
    ap = argparse.ArgumentParser(description="Convert a .docx (Word or Google Docs) into a .3df with playing GIFs.")
    ap.add_argument("docx")
    ap.add_argument("out", nargs="?", help="output .3df (default: next to the input)")
    ap.add_argument("--gifs", help="folder of original GIFs, for exports that flattened them")
    ap.add_argument("--pdf", help="also save the print edition as this PDF")
    ap.add_argument("--dpi", type=int, default=150, help="page render resolution (default 150)")
    ap.add_argument("--soffice", help="path to the LibreOffice soffice executable")
    a = ap.parse_args()
    out = a.out or str(Path(a.docx).with_suffix(".3df"))
    n, g, warnings = convert(a.docx, out, a.dpi, a.soffice, a.gifs, a.pdf)
    for w in warnings:
        print("warning:", w)
    print(f"wrote {out}: {n} pages, {g} animated GIF{'s' if g != 1 else ''}")


if __name__ == "__main__":
    main()
