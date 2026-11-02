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

Start a GIF's alt text with [drag] (Word and Google Docs both have an "Alt text"
box) to mark it "scrub": readers that support it let the viewer drag through its
frames instead of playing it on a loop. Readers that don't simply play it.

If an exporter flattened your GIFs into still images, pass the original GIF files
with --gifs FOLDER and they are matched against the pictures in the document.

Requires: LibreOffice, and `pip install python-docx pymupdf pillow numpy`.
"""
import argparse
import hashlib
import io
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

import subprocess

import threedf
from pptx2_3df import find_soffice

# PDF/A-3b: archival PDF that allows attached files (needed by pdf3df.py), tagged for accessibility
PDFA3_FILTER = 'pdf:writer_pdf_Export:{"SelectPdfVersion":{"type":"long","value":"3"},"UseTaggedPDF":{"type":"boolean","value":"true"}}'


def render_pdf(docx, workdir, soffice):
    profile = Path(workdir, "lo_profile").resolve().as_uri()
    subprocess.run([soffice, f"-env:UserInstallation={profile}", "--headless",
                    "--convert-to", PDFA3_FILTER, "--outdir", str(workdir), str(docx)],
                   check=True, capture_output=True, timeout=600)
    pdf = Path(workdir, Path(docx).stem + ".pdf")
    if not pdf.exists():
        sys.exit("LibreOffice ran but produced no PDF. Check the document opens in LibreOffice Writer.")
    return pdf

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


def pictures(docx):
    """Every picture in the body, in document order: media file name, alt text, and crop
    as fractions (left, top, right, bottom) from <a:srcRect>, which Word and Google Docs write."""
    d = Document(docx)
    out = []
    A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
    for pic in d.element.body.iter("{http://schemas.openxmlformats.org/drawingml/2006/picture}pic"):
        blip = pic.find(f".//{A}blip")
        part = d.part.related_parts.get(blip.get(f"{R}embed")) if blip is not None else None
        holder = pic
        while holder is not None and holder.tag not in (f"{WP}inline", f"{WP}anchor"):
            holder = holder.getparent()
        docpr = holder.find(f"{WP}docPr") if holder is not None else None
        alt = ((docpr.get("descr") or docpr.get("title") or "") if docpr is not None else "").strip()
        src = pic.find(f".//{A}srcRect")
        crop = tuple(max(0.0, int(src.get(k, 0)) / 100000) if src is not None else 0.0 for k in ("l", "t", "r", "b"))
        out.append({"media": Path(str(part.partname)).name if part is not None else "", "alt": alt, "crop": crop})
    return out


def fit_gif(blob, crop, display_aspect):
    """Crop a GIF and stretch it to the shape it is shown at, keeping its timing.
    Returns the original bytes when nothing needs changing."""
    im = Image.open(io.BytesIO(blob))
    W, H = im.size
    l, t, r, b = crop
    box = (round(l * W), round(t * H), round(W - r * W), round(H - b * H))
    cw, ch = box[2] - box[0], box[3] - box[1]
    if cw < 2 or ch < 2:
        return blob
    nw, nh = cw, ch
    if display_aspect and abs(cw / ch - display_aspect) / display_aspect > 0.02:
        nh = max(1, round(cw / display_aspect))
    if box == (0, 0, W, H) and (nw, nh) == (W, H):
        return blob
    frames, durations = [], []
    for f in ImageSequence.Iterator(im):
        durations.append(f.info.get("duration", im.info.get("duration", 100)))
        fr = f.convert("RGBA").crop(box)
        frames.append(fr.resize((nw, nh), Image.LANCZOS) if (nw, nh) != (cw, ch) else fr)
    out = io.BytesIO()
    frames[0].save(out, "GIF", save_all=True, append_images=frames[1:], duration=durations,
                   loop=im.info.get("loop", 0), disposal=2)
    return out.getvalue()


def best_match(pix_img, gifs):
    """Compare against the embedded picture itself. Its pixel shape is the GIF's, however the
    document crops or stretches it on the page, so cropping and resizing don't break matching."""
    s = signature(pix_img)
    aspect = pix_img.width / pix_img.height if pix_img.height else 0
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
    pics = pictures(docx)
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
        # LibreOffice draws pictures in document order, so the n-th image in the PDF is the
        # n-th picture in the .docx. Only trust that when the counts agree.
        n_drawn = sum(1 for pg in pdoc for info in pg.get_image_info(xrefs=True) if info.get("xref"))
        geometry = n_drawn == len(pics)
        if not geometry and pics:
            warnings.append(f"The PDF draws {n_drawn} pictures but the document has {len(pics)}; "
                            "crops and alt text may not be applied.")
        pic_index = -1

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
                pic_index += 1
                pic = pics[pic_index] if geometry else {"media": "", "alt": "", "crop": (0.0, 0.0, 0.0, 0.0)}
                # info["bbox"] is where the whole picture is placed; a crop clips it to a smaller window
                full = pymupdf.Rect(info["bbox"])
                l, t, r, b = pic["crop"]
                bbox = pymupdf.Rect(full.x0 + l * full.width, full.y0 + t * full.height,
                                    full.x1 - r * full.width, full.y1 - b * full.height) & page.rect
                if bbox.is_empty or bbox.width < 4 or bbox.height < 4:
                    continue
                try:
                    p = pymupdf.Pixmap(pdoc, info["xref"])
                    if p.n - p.alpha >= 4:
                        p = pymupdf.Pixmap(pymupdf.csRGB, p)
                    shown = Image.frombytes("RGBA" if p.alpha else "RGB", (p.width, p.height), p.samples)
                except Exception:
                    continue
                g = best_match(shown, gifs)
                if g is None:
                    continue
                blob = fit_gif(g["blob"], pic["crop"], bbox.width / bbox.height)
                key = (g["name"], hashlib.md5(blob).hexdigest())
                src = used.get(key)
                if src is None:                      # store each distinct GIF once, however often it appears
                    src = f"assets/anim{len(used) + 1}.gif"
                    (root / src).write_bytes(blob)
                    used[key] = src
                scale = bg.width / page.rect.width
                crop = bg.crop((round(bbox.x0 * scale), round(bbox.y0 * scale),
                                round(bbox.x1 * scale), round(bbox.y1 * scale)))
                fb = f"assets/page{i}_anim{k}_fallback.png"
                crop.save(root / fb, optimize=True)
                elements.append({"type": "image", "x": round(bbox.x0 * sx, 2), "y": round(bbox.y0 * sy, 2),
                                 "w": round(bbox.width * sx, 2), "h": round(bbox.height * sy, 2),
                                 "src": src, "fallback": fb, "z": 1,
                                 "alt": pic["alt"] or caption_below(lines, bbox) or "Animated figure"})
                alt_text = elements[-1]["alt"]
                if alt_text.lower().startswith("[drag]"):        # author asked for hand control
                    elements[-1]["alt"] = alt_text[6:].strip() or "Animated figure"
                    elements[-1]["scrub"] = True

            for ln in lines:
                h_pt = (ln["y1"] - ln["y0"]) * 1.25
                elements.append({"type": "text", "text": ln["text"],
                                 "x": round(ln["x0"] * sx, 2), "y": round(ln["y0"] * sy, 2),
                                 # extra width so a wider fallback font never wraps the invisible line
                                 "w": round(max(W_mm - ln["x0"] * sx, (ln["x1"] - ln["x0"]) * sx), 2),
                                 "h": round(h_pt * sy, 2),
                                 "font_size_pt": round(ln["size"], 1), "color": INVISIBLE, "z": 2})
            pages.append({"elements": elements})

        placed = {name for name, _ in used}
        missing = [g["name"] for g in gifs if g["name"] not in placed]
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
