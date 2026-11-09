"""Checks run before a tool trusts a package it was handed (a .3df or a .docx).

threedf.validate() checks the document's structure. This adds what an exporter also needs
before it inflates and copies every asset: sane sizes (a few-hundred-KB "zip bomb" must not
turn into a gigabyte page) and pictures that really are pictures.
"""
import io
import json
import zipfile
from pathlib import Path

from PIL import Image

MAX_TOTAL = 400_000_000           # all entries, uncompressed (bytes)
MAX_ENTRY = 200_000_000           # any one entry, uncompressed (bytes)
MAX_RATIO = 100                      # uncompressed : compressed, for entries over 1 MB
MAX_PIXELS = 80_000_000              # per image (e.g. 10000 x 8000)
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


class UnsafePackage(Exception):
    pass


def check_archive(path, kind):
    """Refuse archives whose contents would expand to an unreasonable size."""
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as e:
        raise UnsafePackage(f"{Path(path).name} is not a valid {kind} file ({e})") from None
    total = 0
    for info in z.infolist():
        total += info.file_size
        if info.file_size > MAX_ENTRY:
            raise UnsafePackage(f"{info.filename} would expand to {info.file_size / 1e6:.0f} MB; "
                                f"the limit is {MAX_ENTRY / 1e6:.0f} MB per file")
        if info.file_size > 1_000_000 and info.compress_size and info.file_size / info.compress_size > MAX_RATIO:
            raise UnsafePackage(f"{info.filename} is compressed {info.file_size / info.compress_size:.0f}:1, "
                                "which looks like a zip bomb")
    if total > MAX_TOTAL:
        raise UnsafePackage(f"{Path(path).name} would expand to {total / 1e6:.0f} MB; the limit is {MAX_TOTAL / 1e6:.0f} MB")
    return z


def check_3df(path):
    """Run after threedf.validate(): every picture an element uses must open as that image type."""
    z = check_archive(path, ".3df")
    doc = json.loads(z.read("document.json"))
    seen = set()
    for pi, page in enumerate(doc.get("pages", []), 1):
        for ei, el in enumerate(page.get("elements", []), 1):
            for key in ("src", "fallback"):
                name = el.get(key)
                if not name or name in seen or Path(name).suffix.lower() not in IMAGE_EXT:
                    continue
                seen.add(name)
                try:
                    with Image.open(io.BytesIO(z.read(name))) as im:
                        if im.width * im.height > MAX_PIXELS:
                            raise UnsafePackage(f"page {pi}, element {ei}: {name} is {im.width}x{im.height} pixels, too large")
                        im.verify()
                except UnsafePackage:
                    raise
                except Exception:
                    raise UnsafePackage(f"page {pi}, element {ei}: {name} is not a readable image") from None
