#!/usr/bin/env python3
"""Render a glTF model from a grid of orbit angles, for script-free "turn and tilt" figures.

  python render_views.py model.glb outdir [--yaw-steps 36] [--pitches 20,40,60,80] [--size 960x640]

Uses the same three.js build, camera and lighting as the 3DF viewer, in headless
Chromium (Playwright), so the stills match what the live viewer shows.
Writes outdir/p<row>_y<col>.webp. As a library: render_views(glb_bytes, ...) returns
a list of rows, each a list of WebP bytes.

Requires: pip install playwright (Chromium is installed with `playwright install chromium`).
"""
import argparse
import base64
import io
import json
from pathlib import Path

from PIL import Image

HERE = Path(__file__).parent
VENDOR = HERE / "vendor"

PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8"></head>
<body style="margin:0;background:#fff"><script>%(three)s</script><script>%(gltf)s</script>
<script>
window.renderViews = async (b64, opts) => {
  const bin = Uint8Array.from(atob(b64), c => c.charCodeAt(0)).buffer;
  const renderer = new THREE.WebGLRenderer({antialias: true, preserveDrawingBuffer: true});
  renderer.setPixelRatio(1); renderer.setSize(opts.w, opts.h, false);
  renderer.outputEncoding = THREE.sRGBEncoding;
  document.body.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(opts.background);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x8a93a3, 0.9));
  const sun = new THREE.DirectionalLight(0xffffff, 0.9); sun.position.set(3, 5, 4); scene.add(sun);
  const camera = new THREE.PerspectiveCamera(40, opts.w / opts.h, 0.01, 1000);
  const gltf = await new Promise((ok, bad) => new THREE.GLTFLoader().parse(bin, "", ok, bad));
  scene.add(gltf.scene);
  const bb = new THREE.Box3().setFromObject(gltf.scene), center = bb.getCenter(new THREE.Vector3());
  const radius = bb.getSize(new THREE.Vector3()).length() / 2 || 1;
  // Keep the whole model in frame at every angle: never closer than the distance at which its
  // bounding sphere fits the narrower field of view (an author's camera.distance can be closer).
  const vfov = THREE.MathUtils.degToRad(40), hfov = 2 * Math.atan(Math.tan(vfov / 2) * opts.w / opts.h);
  const fit = radius / Math.sin(Math.min(vfov, hfov) / 2) * 1.04;
  const dist = Math.max(opts.distance ?? radius * 2.6, fit);
  const rows = [];
  for (const pitchDeg of opts.pitches) {
    const row = [];
    for (let i = 0; i < opts.yawSteps; i++) {
      const yaw = THREE.MathUtils.degToRad(opts.yaw0 + i * 360 / opts.yawSteps);
      const pitch = THREE.MathUtils.degToRad(pitchDeg);
      camera.position.set(center.x + dist * Math.cos(pitch) * Math.sin(yaw), center.y + dist * Math.sin(pitch),
                          center.z + dist * Math.cos(pitch) * Math.cos(yaw));
      camera.lookAt(center);
      renderer.render(scene, camera);
      row.push(renderer.domElement.toDataURL("image/png"));
    }
    rows.push(row);
  }
  return rows;
};
</script></body></html>"""


def render_views(glb, yaw_steps=36, pitches=(20, 40, 60, 80), size=(960, 640), yaw0=35.0,
                 distance=None, background="#eef1f4", quality=78):
    """Return rows (one per pitch) of WebP frames (bytes), turning yaw0, yaw0+step, ..."""
    from playwright.sync_api import sync_playwright
    html = PAGE % {"three": (VENDOR / "three.min.js").read_text(encoding="utf-8"),
                   "gltf": (VENDOR / "GLTFLoader.js").read_text(encoding="utf-8")}
    opts = {"w": size[0], "h": size[1], "yawSteps": yaw_steps, "pitches": list(pitches), "yaw0": yaw0,
            "distance": distance, "background": background}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--use-gl=swiftshader", "--enable-unsafe-swiftshader"])
        try:
            page = browser.new_page()
            page.set_content(html)
            rows = page.evaluate("([b, o]) => renderViews(b, o)", [base64.b64encode(glb).decode(), opts])
        finally:
            browser.close()
    out = []
    for row in rows:
        frames = []
        for url in row:
            im = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).convert("RGB")
            buf = io.BytesIO(); im.save(buf, "WEBP", quality=quality, method=5)
            frames.append(buf.getvalue())
        out.append(frames)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("glb"); ap.add_argument("outdir")
    ap.add_argument("--yaw-steps", type=int, default=36)
    ap.add_argument("--pitches", default="20,40,60,80", help="camera heights in degrees, comma separated")
    ap.add_argument("--size", default="960x640")
    a = ap.parse_args()
    w, h = (int(v) for v in a.size.lower().split("x"))
    rows = render_views(Path(a.glb).read_bytes(), a.yaw_steps, [float(p) for p in a.pitches.split(",")], (w, h))
    out = Path(a.outdir); out.mkdir(parents=True, exist_ok=True)
    total = 0
    for r, row in enumerate(rows):
        for c, data in enumerate(row):
            (out / f"p{r}_y{c:02d}.webp").write_bytes(data); total += len(data)
    print(f"wrote {sum(len(r) for r in rows)} views to {out} ({total / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
