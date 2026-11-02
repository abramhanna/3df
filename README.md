# 3DF
 
3DF (`.3df`) is a fixed-layout document format, like PDF, that also supports animated images and interactive 3D models (glTF). See [SPEC.md](SPEC.md).
 
![The two pages of sample.3df: an animated deployment GIF and a rotating truss model](docs/sample.gif)
 
*`sample.3df` in the viewer. The GIF plays on its own; the truss turns here for the demo, and in the viewer you drag to rotate it.*
 
## Contents
 
| File | Purpose |
|---|---|
| `SPEC.md` | Format specification, v0.1 |
| `threedf.py` | Pack, unpack and validate `.3df` files |
| `pptx2_3df.py` | Convert PowerPoint (`.pptx`) decks to `.3df`. For Google Slides, download as `.pptx` first |
| `docx2_3df.py` | Convert Word or Google Docs (`.docx`) reports to `.3df`; GIFs keep playing and the text stays searchable |
| `3df2html.py` | Turn any `.3df` into one `.html` page with no JavaScript that opens offline in any browser or file preview |
| `render_views.py` | Pre-render a glTF model from 36 directions at 4 heights, with the viewer's own three.js camera and lighting |
| `viewer_template.html` | Browser viewer; `build_viewer.py` embeds a sample document into it |
| `make_sample.py`, `make_test_deck.py`, `make_test_report.py` | Generate the sample document and converter test files |
| `tests/` | `check_docx_geometry.py` (cropped and resized GIFs) and `check_static_html.py` (the no-JavaScript page, in a browser with JavaScript off) |
| `vendor/` | three.js r128 and its GLTFLoader (MIT), used by `render_views.py` |
| `make_readme_gif.py` | Render `docs/sample.gif`, the animated preview above |
 
## Quick start
 
```
pip install -r requirements.txt
python make_sample.py                     # builds sample.3df
python threedf.py validate sample.3df
python pptx2_3df.py deck.pptx             # needs LibreOffice installed
python build_viewer.py                    # writes viewer.html with sample.3df embedded
python docx2_3df.py report.docx           # Google Docs: File > Download > Microsoft Word (.docx); needs LibreOffice
python 3df2html.py report.3df             # report.html: send it, it opens anywhere
```

`render_views.py` and the tests need Playwright's Chromium: `python -m playwright install chromium`.

## Google Docs reports

In Google Docs, choose **File → Download → Microsoft Word (.docx)**, then run `docx2_3df.py`. LibreOffice lays the pages out as printed, and each GIF is laid back over its spot so it plays. The page's words stay searchable as an invisible text layer. Cropped or resized GIFs are cropped and stretched to match the page. If an exporter ever flattens your GIFs into stills, pass the originals with `--gifs FOLDER`.

## A page anyone can open, with no program inside

`3df2html.py` writes one `.html` file with no JavaScript at all: text and pictures placed on pages, with every asset inside the file. GIFs play because browsers animate images on their own, so it works offline and in file previews that block scripts, such as iPhone Files and Mail. It prints with each animation's still fallback.

- **Drag through a GIF.** Start a GIF's alt text with `[drag]` in Google Docs or Word, and `docx2_3df.py` marks it `"scrub": true`. Swiping sideways across it then steps through its frames instead of looping. This is a proposed optional field, not yet in SPEC v0.1; readers that don't know it just play the GIF.
- **Turn and tilt 3D models.** Each model is pre-rendered with `render_views.py` (about 1 MB for the sample truss). Drag sideways to turn it, or up and down to tilt it. Free rotation and zoom still need the live viewer.

Dragging uses CSS scroll-driven animations (Safari 26 and later, recent Chrome and Edge). Browsers without them play the GIF and show models as their still. `--no-views` skips 3D rendering.
 
Open `viewer.html` in a browser and use **Open .3df** to view any document.
 
## License
 
MIT. See [LICENSE](LICENSE). The specification in `SPEC.md` is covered by the same license, so anyone may implement readers and writers for 3DF.

