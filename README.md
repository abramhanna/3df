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
| `pdf3df.py` | Ship a `.3df` inside an ordinary PDF that opens everywhere; extract it back; check files. See [docs/PDF-PROFILE.md](docs/PDF-PROFILE.md) |
| `3df2epub.py` | Convert a `.3df` to a fixed-layout EPUB 3, so readers people already have play its GIFs: Apple Books (iPhone, iPad, Mac), Google Play Books (Android). Passes EPUBCheck |
| `reader_template.html`, `build_reader.py` | Offline PDF reader (PDF.js) that plays 3DF content inside any PDF |
| `viewer_template.html` | Browser viewer; `build_viewer.py` embeds a sample document into it |
| `vendor/` | Viewer libraries inlined by the HTML tools: JSZip and three.js r128 (MIT), PDF.js 3.11 (Apache 2.0), with their licenses |
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
python docx2_3df.py report.docx report.3df --pdf report.print.pdf
python pdf3df.py wrap report.3df report.pdf --print report.print.pdf   # a real PDF/A-3 with the .3df inside
python build_reader.py report.pdf        # reader.html plays it; any other PDF reader shows stills
python 3df2epub.py report.3df            # report.epub: GIFs play in Apple Books and Google Play Books
```

## Sending a .3df to someone

No phone or browser opens `.3df` files yet, so `export_html.py export` wraps the document and a viewer into one `.html` file. It makes no network requests, and three.js is only included when the document has 3D models. The original `.3df` sits untouched inside a `<script type="application/vnd.3df+zip" id="threedf-document">` block, so `export_html.py extract` gets back the identical file.
 
Open `viewer.html` in a browser and use **Open .3df** to view any document.
 
## License
 
MIT. See [LICENSE](LICENSE). The specification in `SPEC.md` is covered by the same license, so anyone may implement readers and writers for 3DF.

