#!/usr/bin/env python3
"""Build test_report.docx: a short engineering report with two animated GIFs,
a static image, a table and bullet lists, shaped like a Google Doc exported as .docx.

  python make_test_report.py [turntable_frames_dir]

The optional folder holds pre-rendered truss angles (p1_y00.jpg ... p1_y35.jpg);
without it the second GIF is a simple animated load chart.
"""
import io
import math
import sys
from pathlib import Path

from docx import Document
from docx.shared import Mm, Pt, RGBColor
from PIL import Image, ImageDraw

HERE = Path(__file__).parent


def turntable_gif(frames_dir):
    frames = [Image.open(Path(frames_dir) / f"p1_y{i:02d}.jpg").convert("RGB").resize((600, 400), Image.LANCZOS)
              for i in range(36)]
    frames = [f.quantize(colors=64, method=Image.Quantize.MEDIANCUT) for f in frames]
    buf = io.BytesIO()
    frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:], duration=70, loop=0, optimize=True)
    return buf.getvalue()


def load_chart_gif():
    W, H, frames = 600, 300, []
    pts = [(t, 1 - math.exp(-t / 9) + 0.06 * math.sin(t / 2)) for t in range(0, 41)]
    for n in range(2, len(pts) + 1, 2):
        im = Image.new("RGB", (W, H), "white")
        d = ImageDraw.Draw(im)
        d.line([(50, 260), (580, 260)], fill="#9aa3b0", width=2)
        d.line([(50, 20), (50, 260)], fill="#9aa3b0", width=2)
        xy = [(50 + t * 13, 260 - v * 210) for t, v in pts[:n]]
        d.line(xy, fill="#2f5bd3", width=4)
        d.ellipse([xy[-1][0] - 6, xy[-1][1] - 6, xy[-1][0] + 6, xy[-1][1] + 6], fill="#2f5bd3")
        frames.append(im)
    buf = io.BytesIO()
    frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:], duration=90, loop=0)
    return buf.getvalue()


def photo_png():
    im = Image.new("RGB", (800, 360), "#d9dee5")
    d = ImageDraw.Draw(im)
    for i in range(9):
        d.rectangle([40 + i * 82, 60, 100 + i * 82, 300], fill="#6c7a8c", outline="#3c4655", width=3)
    d.text((40, 20), "Stowed panel stack (static photo placeholder)", fill="#1c232e")
    buf = io.BytesIO(); im.save(buf, "PNG"); return buf.getvalue()


def main(frames_dir=None):
    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Mm(215.9), Mm(279.4)        # US Letter, the Google Docs default
    for side in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(sec, side, Mm(25.4))
    doc.core_properties.title = "Deployment Test Report: Four-Bay Truss"
    doc.core_properties.author = "3DF test fixtures"

    doc.add_heading("Deployment Test Report: Four-Bay Truss", 0)
    p = doc.add_paragraph("Test campaign DT-07 · Prepared for internal review")
    p.runs[0].font.color.rgb = RGBColor(0x5A, 0x62, 0x70)

    doc.add_heading("1. Summary", 1)
    doc.add_paragraph(
        "The four-bay truss deployed fully in all six ground tests. Deployment took 11.8 s on average, "
        "within the 15 s requirement. Peak latch load stayed under 40% of the allowable. One test showed a "
        "brief hinge bind at bay 3, cleared by the spring margin without intervention.")

    doc.add_heading("2. Deployment sequence", 1)
    doc.add_paragraph("Figure 1 shows the panel stack unfolding from its stowed state. The motion is the same "
                      "sequence the flight unit will perform after separation.")
    doc.add_picture(io.BytesIO((HERE / "sample/assets/deploy.gif").read_bytes()), width=Mm(150))
    cap = doc.add_paragraph("Figure 1. Panel deployment sequence (animated).")
    cap.runs[0].font.size = Pt(9); cap.runs[0].italic = True

    doc.add_paragraph("For comparison, the stowed configuration before release:")
    doc.add_picture(io.BytesIO(photo_png()), width=Mm(140))
    cap = doc.add_paragraph("Figure 2. Stowed configuration (still image).")
    cap.runs[0].font.size = Pt(9); cap.runs[0].italic = True

    doc.add_heading("3. Results", 1)
    t = doc.add_table(rows=1, cols=4)
    t.style = "Light Grid Accent 1"
    for c, h in zip(t.rows[0].cells, ["Test", "Deploy time (s)", "Peak latch load (N)", "Result"]):
        c.text = h
    for row in [("DT-07-1", "11.2", "182", "Pass"), ("DT-07-2", "12.1", "190", "Pass"),
                ("DT-07-3", "13.4", "204", "Pass, hinge bind"), ("DT-07-4", "11.0", "176", "Pass"),
                ("DT-07-5", "11.6", "185", "Pass"), ("DT-07-6", "11.5", "181", "Pass")]:
        for c, v in zip(t.add_row().cells, row):
            c.text = v

    doc.add_heading("4. As-built geometry", 1)
    doc.add_paragraph("Figure 3 turns the as-built truss through a full revolution so reviewers can check "
                      "bay alignment from every side without opening CAD.")
    gif2 = turntable_gif(frames_dir) if frames_dir else load_chart_gif()
    doc.add_picture(io.BytesIO(gif2), width=Mm(150))
    cap = doc.add_paragraph("Figure 3. As-built truss, full revolution (animated).")
    cap.runs[0].font.size = Pt(9); cap.runs[0].italic = True

    doc.add_heading("5. Open items", 1)
    for item in ["Root-cause the bay 3 hinge bind (suspected burr on pin, inspect before DT-08).",
                 "Repeat DT-07-3 with the replacement pin.",
                 "Add thermal soak at -40 °C before the next deployment series."]:
        doc.add_paragraph(item, style="List Bullet")

    doc.add_heading("6. Conclusion", 1)
    doc.add_paragraph("The design meets its deployment requirements on the ground. The team recommends proceeding "
                      "to thermal vacuum testing once the hinge bind is closed out.")
    out = HERE / "test_report.docx"
    doc.save(out)
    print(f"wrote {out}")


if __name__ == "__main__":
    main(*sys.argv[1:2])
