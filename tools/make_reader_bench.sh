#!/bin/sh
# Makes the files the reader_bench firmware embeds: the made-up 450 KB novel from
# tools/make_sample_books.py, converted, and an 18 px font with its characters plus all
# 6,763 GB2312 hanzi, so glyph lookups take as long as with a real Chinese library.
#   tools/make_reader_bench.sh && pio run -e reader_bench -t upload
set -e
cd "$(dirname "$0")/.."
out=bench_reader.nosync
mkdir -p "$out"
uv run tools/make_sample_books.py --long --out "$out/Books"
uv run tools/books.py --convert "$out/Books/中文/长夜行.txt" -o "$out/book.dbk"
gb2312=$(python3 -c 'print("".join(bytes([a, b]).decode("gb2312") for a in range(0xB0, 0xF8) for b in range(0xA1, 0xFF) if (a, b) < (0xD7, 0xFA) or a > 0xD7))' 2>/dev/null)
uv run tools/fonts.py --text "$gb2312" --book "$out/book.dbk" --size 18 -o "$out/font.dfn"
