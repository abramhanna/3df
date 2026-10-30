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
| `export_html.py` | Package any `.3df` as one `.html` that opens offline in any browser, and extract the `.3df` back out |
| `viewer_template.html` | Browser viewer; `build_viewer.py` embeds a sample document into it |
| `vendor/` | Viewer libraries (JSZip, three.js r128) inlined by `export_html.py`, with their MIT licenses |
| `make_sample.py`, `make_test_deck.py`, `make_test_report.py` | Generate the sample document and converter test files |
| `make_readme_gif.py` | Render `docs/sample.gif`, the animated preview above |
 
## Quick start
 
```
pip install -r requirements.txt
python make_sample.py                     # builds sample.3df
python threedf.py validate sample.3df
python pptx2_3df.py deck.pptx             # needs LibreOffice installed
python build_viewer.py                    # writes viewer.html with sample.3df embedded
python docx2_3df.py report.docx           # Google Docs: File > Download > .docx; needs LibreOffice
python export_html.py export report.3df   # report.3df.html: send it, it opens offline anywhere
```

## Sending a .3df to someone

No phone or browser opens `.3df` files yet, so `export_html.py export` wraps the document and a viewer into one `.html` file. It makes no network requests, and three.js is only included when the document has 3D models. The original `.3df` sits untouched inside a `<script type="application/vnd.3df+zip" id="threedf-document">` block, so `export_html.py extract` gets back the identical file.
 
Open `viewer.html` in a browser and use **Open .3df** to view any document.
 
## License
 
MIT. See [LICENSE](LICENSE). The specification in `SPEC.md` is covered by the same license, so anyone may implement readers and writers for 3DF.

