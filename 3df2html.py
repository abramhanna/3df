#!/usr/bin/env python3
"""Convert a .3df into one script-free .html page: a document, not a program.

  python 3df2html.py doc.3df [doc.html] [--embed]

The page has no JavaScript at all. It is positioned text and images, like a
printed page, and animated GIFs play because browsers animate images on their
own. That means it works where scripts are blocked: phone file previews, email
attachment previews and locked-down browsers. Every asset is inlined, so it
opens offline. Printing uses each animated element's still fallback.

Animated images marked "scrub": true (docx2_3df.py sets it when the alt text
starts with [drag]) become figures you drag through: swiping or scrolling sideways
across them steps through the frames, using CSS scroll-driven animations, still
with no script. Browsers without that feature play the GIF instead.

3D models become figures you turn and tilt: render_views.py pre-renders them
from 36 directions at 4 heights (needs Playwright), and dragging sideways turns
the model, dragging up or down tilts it, still with no script. Free rotation and
zoom need the live viewer (export_html.py). --no-views shows the still instead.

--embed  also carry the untouched .3df inside the page as a data block (not
         executed), so `export_html.py extract` can recover it. Adds about a third
         of the .3df's size again.
"""
import argparse
import base64
import html
import json
import zipfile
from pathlib import Path

import io

from PIL import Image, ImageSequence

import threedf
from export_html import TAG_OPEN

MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}
MM_PER_PT = 25.4 / 72
ANIMATED = {".gif", ".webp"}


def esc(s):
    return html.escape(str(s), quote=True)


SCRUB_REVS = 2          # turns available in one drag, since a scroller can't start in the middle without a script
MAX_FRAMES = 72


def gif_frames(blob):
    """Data URLs for each frame of an animated image (JPEG, or PNG where there is transparency)."""
    im = Image.open(io.BytesIO(blob))
    frames = [f.convert("RGBA") for f in ImageSequence.Iterator(im)]
    step = max(1, -(-len(frames) // MAX_FRAMES))
    out = []
    for f in frames[::step]:
        buf = io.BytesIO()
        if f.getextrema()[3][0] < 255:
            f.save(buf, "PNG", optimize=True); mime = "image/png"
        else:
            f.convert("RGB").save(buf, "JPEG", quality=82, optimize=True); mime = "image/jpeg"
        out.append(f"data:{mime};base64," + base64.b64encode(buf.getvalue()).decode())
    return out


def scrub_html(k, box, gif_url, still_url, alt, frames):
    """A figure you drag through: an invisible horizontal scroller drives a CSS scroll
    timeline, and each frame is visible only in its slice of that scroll. No script."""
    n = len(frames)
    total = n * SCRUB_REVS
    imgs = []
    for i, url in enumerate(frames):
        ranges = ", ".join(f"{(r * n + i) / total * 100:.4f}% {(r * n + i + 1) / total * 100:.4f}%"
                           for r in range(SCRUB_REVS))
        fills = ", ".join("forwards" if (r == SCRUB_REVS - 1 and i == n - 1) else "none" for r in range(SCRUB_REVS))
        names = ", ".join(["on"] * SCRUB_REVS)
        tl = ", ".join([f"--s{k}"] * SCRUB_REVS)
        imgs.append(f'<img class="f" src="{url}" alt="" style="animation-name:{names};animation-timeline:{tl};'
                    f'animation-range:{ranges};animation-fill-mode:{fills}">')
    return (f'<div class="el scrub" style="{box};timeline-scope:--s{k}">'
            f'<img class="gifplay" src="{gif_url}" alt="{alt}">'
            f'<div class="frames" aria-hidden="true">{"".join(imgs)}</div>'
            f'<div class="scroller" style="scroll-timeline:--s{k} x" tabindex="0" role="slider" '
            f'aria-label="Drag sideways to turn: {alt}" aria-valuemin="0" aria-valuemax="100"><div class="track"></div></div>'
            f'<span class="hint" aria-hidden="true">&#8644; drag</span>'
            f'<img class="still" src="{still_url}" alt="" aria-hidden="true"></div>')


def orbit_html(k, box, still_url, alt, rows):
    """A 3D model you turn and tilt with no script. One scroller moves on both axes and drives
    two CSS scroll timelines: rows of views fade in by vertical scroll (tilt), and within a row
    each view is shown only in its slice of the horizontal scroll (turn, two turns per drag)."""
    n_rows, n = len(rows), len(rows[0])
    total = n * SCRUB_REVS
    html_rows = []
    for r, row in enumerate(rows):
        fill = "forwards" if r == n_rows - 1 else "none"
        imgs = []
        for i, url in enumerate(row):
            ranges = ", ".join(f"{(v * n + i) / total * 100:.4f}% {(v * n + i + 1) / total * 100:.4f}%"
                               for v in range(SCRUB_REVS))
            fills = ", ".join("forwards" if (v == SCRUB_REVS - 1 and i == n - 1) else "none" for v in range(SCRUB_REVS))
            imgs.append(f'<img class="f" src="{url}" alt="" style="animation-name:{", ".join(["on"] * SCRUB_REVS)};'
                        f'animation-timeline:{", ".join([f"--ox{k}"] * SCRUB_REVS)};'
                        f'animation-range:{ranges};animation-fill-mode:{fills}">')
        html_rows.append(f'<div class="orow" style="animation-name:on;animation-timeline:--oy{k};'
                         f'animation-range:{r / n_rows * 100:.4f}% {(r + 1) / n_rows * 100:.4f}%;'
                         f'animation-fill-mode:{fill}">{"".join(imgs)}</div>')
    return (f'<div class="el orbit" style="{box};timeline-scope:--ox{k}, --oy{k}">'
            f'<img class="ostill" src="{still_url}" alt="{alt}">'
            f'<div class="oframes" aria-hidden="true">{"".join(html_rows)}</div>'
            f'<div class="oscroller" style="scroll-timeline-name:--ox{k}, --oy{k};scroll-timeline-axis:x, y" '
            f'tabindex="0" role="img" aria-label="{alt}. Drag sideways to turn, up or down to tilt.">'
            f'<div class="otrack" style="height:{100 + n_rows * 25}%"></div></div>'
            f'<span class="hint" aria-hidden="true">&#8644; turn &#8645; tilt</span></div>')


def model_views(z, el, warnings):
    """Pre-render a model as rows of WebP data URLs, or None if rendering isn't available."""
    try:
        from render_views import render_views
    except Exception as e:        # pragma: no cover
        warnings.append(f"3D views skipped ({e}); the model shows as its still image")
        return None
    cam = el.get("camera") or {}
    p0 = float(cam.get("pitch_deg", 20))
    pitches = [p0 + 20 * i for i in range(4) if p0 + 20 * i <= 85]
    w = min(960, max(320, round(el["w"] * 96 / 25.4 * 1.5)))
    h = max(1, round(w * el["h"] / el["w"]))
    try:
        rows = render_views(z.read(el["src"]), 36, pitches, (w, h), float(cam.get("yaw_deg", 35)),
                            cam.get("distance"), el.get("background") or "#eef1f4")
    except Exception as e:
        warnings.append(f"3D views for {el.get('alt', el['src'])!r} failed ({type(e).__name__}: {e}); using the still")
        return None
    return [["data:image/webp;base64," + base64.b64encode(f).decode() for f in row] for row in rows]


def css_color(c):
    c = str(c or "")
    if len(c) == 9 and c.startswith("#"):
        r, g, b, a = (int(c[i:i + 2], 16) for i in (1, 3, 5, 7))
        return f"rgba({r},{g},{b},{a / 255:.3f})"
    return c if c.startswith("#") and len(c) in (4, 7) else "#1C232E"


def convert(src, out=None, embed=False, views=True, warnings=None):
    src = Path(src)
    errs = threedf.validate(src)
    if errs:
        raise threedf.ThreeDFError(f"{src} is not a valid .3df:\n" + "\n".join(errs))
    out = Path(out or src.with_suffix(".html"))
    z = zipfile.ZipFile(src)
    doc = json.loads(z.read("document.json"))
    W, H = doc["page"]["width_mm"], doc["page"]["height_mm"]
    title = str(doc.get("title") or src.stem)
    warnings = [] if warnings is None else warnings

    # Each asset is written once as a CSS class with a data: URL? No: <img> needs src.
    # Repeated assets are rare, so inline each use directly.
    cache = {}

    def data_url(path):
        if path not in cache:
            cache[path] = f"data:{MIME[Path(path).suffix.lower()]};base64," + base64.b64encode(z.read(path)).decode()
        return cache[path]

    def pct(v, total):
        return f"{v / total * 100:.4f}%"

    pages = []
    for i, page in enumerate(doc["pages"], 1):
        parts = []
        for el in sorted(page.get("elements", []), key=lambda e: e.get("z", 0)):
            box = (f"left:{pct(el['x'], W)};top:{pct(el['y'], H)};width:{pct(el['w'], W)};"
                   f"height:{pct(el['h'], H)};z-index:{int(el.get('z', 0))}")
            alt = esc(el.get("alt", ""))
            if el["type"] == "image":
                animated = Path(el["src"]).suffix.lower() in ANIMATED and el.get("fallback")
                frames = gif_frames(z.read(el["src"])) if animated and el.get("scrub") else []
                if len(frames) > 1:
                    parts.append(scrub_html(len(parts), box, data_url(el["src"]), data_url(el["fallback"]), alt, frames))
                elif animated:
                    parts.append(f'<img class="el live" style="{box}" src="{data_url(el["src"])}" alt="{alt}">'
                                 f'<img class="el still" style="{box}" src="{data_url(el["fallback"])}" alt="" aria-hidden="true">')
                else:
                    parts.append(f'<img class="el" style="{box}" src="{data_url(el["src"])}" alt="{alt}">')
            elif el["type"] == "model":
                rows = model_views(z, el, warnings) if views and el.get("fallback") else None
                if rows:
                    parts.append(orbit_html(len(parts), box, data_url(el["fallback"]), alt, rows))
                elif el.get("fallback"):
                    parts.append(f'<img class="el" style="{box}" src="{data_url(el["fallback"])}" alt="{alt}">')
            elif el["type"] == "text":
                # font size in cqw (1% of the page's width), so text scales with the page, no script needed
                size = float(el.get("font_size_pt", 11)) * MM_PER_PT / W * 100
                style = (f"{box};font-size:{size:.4f}cqw;font-weight:{int(el.get('weight', 400))};"
                         f"color:{css_color(el.get('color'))};text-align:{el.get('align', 'left')}")
                if el.get("font_family"):
                    style += f";font-family:{el['font_family']}, Georgia, serif"
                parts.append(f'<div class="el t" style="{esc(style)}">{esc(el["text"])}</div>')
        pages.append(f'<section class="page" aria-label="Page {i}">\n' + "\n".join(parts) + "\n</section>")

    embedded = ""
    if embed:
        payload = base64.b64encode(src.read_bytes()).decode()
        payload = "\n".join(payload[i:i + 120] for i in range(0, len(payload), 120))
        embedded = f"\n{TAG_OPEN}\n{payload}\n</script>"

    page_px = round(W * 96 / 25.4)
    out.write_text(f"""<!DOCTYPE html>
<html lang="{esc(doc.get('lang', 'en'))}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="generator" content="3df2html.py (3DF {esc(doc.get('3df', ''))}, no scripts)">
<title>{esc(title)}</title>
<style>
:root{{--desk:#D3D8DE;--shadow:0 1px 2px rgba(20,30,45,.18),0 6px 24px rgba(20,30,45,.12);color-scheme:light}}
@media (prefers-color-scheme:dark){{:root{{--desk:#1B2029;--shadow:0 1px 2px rgba(0,0,0,.5),0 8px 28px rgba(0,0,0,.45)}}}}
html{{background:var(--desk)}}
body{{margin:0;padding:16px;background:var(--desk)}}
.page{{position:relative;width:100%;max-width:{page_px}px;aspect-ratio:{W} / {H};margin:0 auto 16px;
  background:#fff;box-shadow:var(--shadow);overflow:hidden;container-type:inline-size}}
.el{{position:absolute;display:block;margin:0}}
img.el{{object-fit:contain}}
.t{{font-family:Georgia,"Times New Roman",serif;line-height:1.35;overflow:hidden;white-space:pre-wrap}}
.still{{display:none}}
.scrub{{overflow:hidden}}
.scrub>img,.scrub .f{{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;display:block}}
.scrub>img.still{{display:none}}
.scrub .frames,.scrub .scroller,.scrub .hint{{display:none}}
.orbit{{overflow:hidden}}
.orbit>img,.orbit .f{{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;display:block}}
.orbit .oframes,.orbit .oscroller,.orbit .hint{{display:none}}
@keyframes on{{from,to{{opacity:1}}}}
@supports (animation-timeline: scroll()) {{
  .scrub .gifplay{{display:none}}
  .scrub .frames{{display:block;position:absolute;inset:0}}
  .scrub .f{{opacity:0;animation-duration:auto;animation-timing-function:linear}}
  .scrub .scroller{{display:block;position:absolute;inset:0;overflow-x:scroll;overflow-y:hidden;
    scrollbar-width:thin;overscroll-behavior-x:contain;touch-action:pan-x;cursor:ew-resize;z-index:1}}
  .scrub .track{{width:500%;height:1px}}
  .orbit .ostill{{display:none}}
  .orbit .oframes{{display:block;position:absolute;inset:0}}
  .orbit .orow{{position:absolute;inset:0;opacity:0;animation-duration:auto;animation-timing-function:linear}}
  .orbit .f{{opacity:0;animation-duration:auto;animation-timing-function:linear}}
  .orbit .oscroller{{display:block;position:absolute;inset:0;overflow:scroll;scrollbar-width:thin;
    overscroll-behavior-x:contain;overscroll-behavior-y:auto;touch-action:pan-x pan-y;cursor:grab;z-index:1}}
  .orbit .otrack{{width:500%}}
  .orbit .hint,.scrub .hint{{display:block;position:absolute;right:2%;bottom:3%;z-index:2;pointer-events:none;
    font:600 2.2cqw/1 system-ui,sans-serif;color:#1C232E;background:rgba(255,255,255,.82);
    border-radius:99px;padding:.6cqw 1.2cqw}}
}}
@page{{size:{W}mm {H}mm;margin:0}}
@media print{{
  html,body{{background:#fff;padding:0}}
  .page{{width:{W}mm;max-width:none;margin:0;box-shadow:none;break-after:page}}
  .live,.scrub .gifplay,.scrub .frames,.scrub .scroller,.hint,.orbit .oframes,.orbit .oscroller{{display:none!important}}
  .orbit .ostill{{display:block!important}} .still,.scrub>img.still{{display:block}}
}}
</style>
</head>
<body>
{chr(10).join(pages)}{embedded}
</body>
</html>
""", encoding="utf-8")
    return out


def main():
    ap = argparse.ArgumentParser(description="Convert a .3df into one script-free .html page.")
    ap.add_argument("src"); ap.add_argument("out", nargs="?")
    ap.add_argument("--embed", action="store_true", help="carry the .3df inside as a data block")
    ap.add_argument("--no-views", action="store_true", help="show 3D models as their still instead of turnable views")
    a = ap.parse_args()
    try:
        warnings = []
        o = convert(a.src, a.out, a.embed, not a.no_views, warnings)
        for w in warnings:
            print("warning:", w)
    except threedf.ThreeDFError as err:
        print(err); return 1
    print(f"wrote {o} ({o.stat().st_size / 1e6:.2f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
