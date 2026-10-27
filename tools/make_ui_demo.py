#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Makes the books and fonts the ui_demo firmware carries in flash, so the home screen,
the reader and the settings can be tried with only the screen and touch wired:

    uv run tools/make_ui_demo.py               the made-up sample books
    uv run tools/make_ui_demo.py ~/Books       your own (EPUB, PDF, TXT, MD, DOCX)
    pio run -e ui_demo -t upload

Builds a stand-in card in ui_demo.nosync/card/ with build_index.py (books converted to
/.dap/books/, fonts baked into /.dap/fonts/, exactly as for the real card), then packs
those /.dap files into ui_demo.nosync/card.pack, which the firmware embeds and reads in
place (lib/ui/card_pack.h).

Pack format, little-endian: "DPAK", u32 version 1, u32 file count, u32 0; then one
64-byte record per file: path from the card root (UTF-8, NUL-padded to 48 bytes), u32
offset from the pack start, u32 size, 8 zero bytes; then the files, each at a 4-byte
aligned offset.
"""
import argparse
import shutil
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "ui_demo.nosync"
BOOK_TYPES = {".epub", ".pdf", ".txt", ".md", ".markdown", ".docx"}
# The app partition is 6.5 MB (default_16MB.csv); the firmware itself takes about 0.6 MB.
MAX_PACK = 5_700_000
RECORD = struct.Struct("<48sII8x")


def run(*args):
    subprocess.run(["uv", "run", *map(str, args)], cwd=ROOT, check=True)


def pack(card, out):
    dap = card / ".dap"
    files = [dap / "books.idx"] + sorted((dap / "books").glob("*.dbk")) + sorted((dap / "books").glob("*.g4"))
    files += sorted((dap / "fonts").glob("*.dfn"))
    names = ["/" + f.relative_to(card).as_posix() for f in files]
    offset = 16 + RECORD.size * len(files)
    records, blobs = bytearray(), bytearray()
    for name, f in zip(names, files):
        data = f.read_bytes()
        records += RECORD.pack(name.encode(), offset + len(blobs), len(data))
        blobs += data + b"\0" * (-len(data) % 4)
    out.write_bytes(struct.pack("<4sIII", b"DPAK", 1, len(files), 0) + records + blobs)
    return len(files), out.stat().st_size


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("books", type=Path, nargs="?", help="a folder of your own books (default: made-up samples)")
    args = ap.parse_args()
    card = OUT / "card"
    books = card / "Books"
    shutil.rmtree(books, ignore_errors=True)
    if args.books:
        found = [p for p in args.books.expanduser().rglob("*")
                 if p.suffix.lower() in BOOK_TYPES and not p.name.startswith(".")]
        if not found:
            sys.exit(f"no books (EPUB, PDF, TXT, MD, DOCX) in {args.books}")
        for p in found:
            dest = books / p.relative_to(args.books.expanduser())
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dest)
    else:
        run("tools/make_sample_books.py", "--long", "--out", books)
    run("tools/build_index.py", card)
    count, size = pack(card, OUT / "card.pack")
    print(f"{OUT / 'card.pack'}: {count} files, {size / 1e6:.2f} MB")
    if size > MAX_PACK:
        sys.exit(f"too big for the firmware's flash space ({MAX_PACK / 1e6:.1f} MB at most): use fewer books")
    print("next: pio run -e ui_demo -t upload")


if __name__ == "__main__":
    main()
