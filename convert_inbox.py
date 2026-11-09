#!/usr/bin/env python3
"""Convert every Word file waiting in inbox/ into outbox/<name>/.

  python convert_inbox.py [inbox] [outbox]

For each .docx in the inbox this makes a folder in the outbox holding:
  <name>.3df    the master copy
  <name>.html   web page that opens on any device and moves (no JavaScript)
  <name>.pdf    PDF for printing and filing, with the .3df inside
  <name>.epub   ebook where GIFs play (Apple Books, Google Play Books)
  REPORT.md     what was converted, and any warnings
  <name>.docx   the original, moved out of the inbox so it isn't converted twice

A file that can't be converted gets a REPORT.md explaining why; the others still run.
The GitHub workflow in .github/workflows/convert.yml runs this whenever a file is uploaded
to inbox/.
"""
import datetime
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
IGNORE = {"README.md", ".gitkeep"}


def run(*args):
    r = subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True, cwd=HERE, timeout=900)
    return r.returncode == 0, (r.stdout + r.stderr).strip()


def tidy(text):
    """Keep tool output readable: drop folder paths and keep one line per message."""
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("wrote "):
            lines.append(line)
    return lines


def convert(docx, outbox):
    stem = docx.stem
    dest = outbox / stem
    if dest.exists():                                   # don't overwrite an earlier result
        dest = outbox / f"{stem} ({datetime.datetime.now():%Y-%m-%d %H%M%S})"
    dest.mkdir(parents=True)
    report = [f"# {stem}", "", f"Processed {datetime.datetime.now(datetime.timezone.utc):%Y-%m-%d %H:%M} UTC from `{docx.name}`.", ""]
    made, notes = [], []
    with tempfile.TemporaryDirectory() as tmp:
        master, printed = dest / f"{stem}.3df", Path(tmp, "print.pdf")
        ok, out = run("docx2_3df.py", docx, master, "--pdf", printed)
        notes += tidy(out.replace(str(master), master.name))
        if ok and master.exists():
            made.append((master.name, "master copy"))
            steps = [("3df2html.py", [master, dest / f"{stem}.html"], f"{stem}.html", "web page: opens anywhere, moves"),
                     ("pdf3df.py", ["wrap", master, dest / f"{stem}.pdf", "--print", printed], f"{stem}.pdf", "PDF: print and file"),
                     ("3df2epub.py", [master, dest / f"{stem}.epub"], f"{stem}.epub", "ebook: Apple Books, Google Play Books")]
            for tool, args, name, what in steps:
                ok2, out2 = run(tool, *args)
                if ok2 and (dest / name).exists():
                    made.append((name, what))
                else:
                    notes.append(f"{name} could not be made: {' '.join(tidy(out2))[:300]}")
    shutil.move(str(docx), str(dest / docx.name))
    if made:
        report += ["## Files", ""] + [f"- `{n}`: {w}" for n, w in made] + [""]
    else:
        report += ["## Not converted", "", "Nothing could be made from this file. The reason is below.", ""]
    if notes:
        report += ["## Notes", ""] + [f"- {n}" for n in notes] + [""]
    (dest / "REPORT.md").write_text("\n".join(report), encoding="utf-8")
    return dest, bool(made), made, notes


def main():
    inbox = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "inbox"
    outbox = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / "outbox"
    outbox.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in inbox.iterdir() if p.is_file() and p.name not in IGNORE) if inbox.is_dir() else []
    summary = ["## 3DF conversions", ""]
    if not files:
        summary.append("The inbox is empty; nothing to convert.")
    for f in files:
        if f.suffix.lower() != ".docx":
            summary.append(f"- **{f.name}**: skipped. Only Word files (.docx) are converted; in Google Docs use "
                           "File → Download → Microsoft Word (.docx).")
            continue
        dest, ok, made, notes = convert(f, outbox)
        mark = "converted" if ok else "**not converted**"
        summary.append(f"- **{f.name}**: {mark} → `outbox/{dest.name}/` ({len(made)} files)")
        summary += [f"  - {n}" for n in notes]
        print(f"{f.name}: {'converted' if ok else 'NOT converted'} -> {dest}")
    text = "\n".join(summary) + "\n"
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
