# 3DF in PDF (draft profile)

**Status:** proposal for discussion, not part of SPEC v0.1.

## Why

Nobody can open a bare `.3df` today. Everybody can open a PDF. So a 3DF document can travel as an ordinary PDF. Plain readers show it with still frames. Readers that understand 3DF play it in place. The file never fails to open; at worst it looks like the PDF it is.

E-invoices already use this pattern: Factur-X and ZUGFeRD invoices are PDF/A-3 files that carry their machine-readable data as an attached file.

## Rules

A **3DF-enabled PDF** is a valid PDF that also meets these rules:

1. **Pages.** Each page of the PDF shows the matching page of the `.3df`. Animated images and models appear as their `fallback` stills. Text should be real or invisible PDF text, so the file stays searchable.
2. **Attached document.** The complete `.3df` is attached as an associated file:
   - it is listed in the document catalog's `/AF` array, and in `/Names /EmbeddedFiles`;
   - its file specification has `/AFRelationship /Alternative`;
   - the embedded file stream has `/Subtype /application#2Fvnd.3df+zip` and `/Params` with `/Size` and `/ModDate`.
3. **Marked elements.** Every animated image and every model gets a Link annotation covering its box on its page, with:
   - `/NM (3df:p<page>:e<element>)`, both counted from 1;
   - `/Contents` with its alt text;
   - `/F 4` (print flag), no action, and no visible border;
   - `/AF` pointing to the attached `.3df`.
4. **Metadata.** XMP metadata includes `tdf:version` (the 3DF spec version) and `tdf:attachment` (the attached file name) in the namespace `https://github.com/mfogelson/3df/ns/0.1/`. Files that declare PDF/A must also include the PDF/A extension schema describing these two properties.
5. **Other attachments.** An offline HTML viewer may be attached with `/AFRelationship /Supplement`.

PDF/A-3 is recommended (it allows associated files and suits archives), but the profile works on any PDF 1.7 file.

## Reader behaviour

- **Detecting.** A reader finds the `/AF` entry whose embedded file has the 3DF MIME type, or checks the `tdf:version` metadata first as a quick test.
- **Playing.** The reader draws the PDF page as usual, then lays each live element from the attached `document.json` over its box. The Link annotations give the same boxes in PDF coordinates, for tools that never open the `.3df`.
- **Falling back.** If the attached `.3df` is missing or invalid, the reader shows the PDF as is.

## Tools in this repo

| Command | What it does |
|---|---|
| `python pdf3df.py wrap doc.3df out.pdf [--print print.pdf] [--viewer viewer.html]` | Builds a 3DF-enabled PDF. `--print` uses an existing PDF for the pages, such as the PDF/A-3 edition from `docx2_3df.py --pdf`. Without it, pages are drawn from the `.3df`. |
| `python pdf3df.py extract file.pdf [out.3df]` | Gets the attached `.3df` back, byte for byte. |
| `python pdf3df.py check file.pdf` | Reports PDF/A status, the 3DF marker, the attachment and whether each marked element matches the `.3df`. |
| `python build_reader.py [demo.pdf] [reader.html]` | Builds an offline, single-file PDF reader (PDF.js) that plays 3DF content in any PDF it opens. |

## Open questions

- **Size.** The PDF carries the page images twice: once as PDF pages and again inside the `.3df`. A later version could let a `.3df` inside a PDF use the PDF's own pages as its backgrounds.
- **Native 3D.** Models could also be given ISO/TS 32007 glTF annotations, so readers with PDF 3D support show them without a 3DF reader.
- **Validation.** Check files with veraPDF before claiming PDF/A-3 conformance; the tools here only check structure.
