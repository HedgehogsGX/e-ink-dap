#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["pillow>=10.0", "fonttools>=4.50"]
# ///
"""Makes the player's bitmap fonts (.dfn, see docs/formats.md) from TrueType/OpenType fonts.

    uv run tools/fonts.py /Volumes/MUSIC    (build_index.py does this for you, after the books)
    uv run tools/fonts.py --text "雾港 Aa" --size 18 -o test.dfn
    uv run tools/fonts.py --preview test.dfn "雾港来信 The fog"     -> test.dfn.png

Text on the e-paper is pure black and white, so every glyph is rendered without
anti-aliasing at each size the player uses, ahead of time. A font holds only the
characters the card needs (the books' text, every title and name, and the usual
punctuation), which keeps Chinese and Japanese fonts small.

The default faces are macOS system fonts: Hiragino Sans GB, then Hiragino Sans for the
Japanese-only kanji, then Arial Unicode. They are rendered for your own card only. Other
fonts: --ui-font / --ui-bold-font / --reader-font, each PATH or PATH:INDEX (the face in a
.ttc), repeatable to give fallbacks for missing characters. Free fonts that cover Chinese
and Japanese: Noto Sans/Serif CJK, Source Han Sans/Serif, LXGW WenKai.
"""
import argparse
import hashlib
import struct
import sys
from pathlib import Path

from dap_common import INDEX_DIR, write_atomic

FONT_DIR = "fonts"
MANIFEST = "fonts.txt"
MAGIC = b"DAPF"
VERSION = 1
# magic, version, header size, file size, glyph count, pixel size, line height, ascent,
# descent, offset of glyphs, offset of bitmaps
HEADER = struct.Struct("<4sHH II HHhh II")
# code point, bitmap offset, advance, width, height, left, top
GLYPH = struct.Struct("<IIBBBbb3x")
assert (HEADER.size, GLYPH.size) == (32, 16)

DEFAULT_UI = ["/System/Library/Fonts/Hiragino Sans GB.ttc:0", "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc:0",
              "/Library/Fonts/Arial Unicode.ttf", "/System/Library/Fonts/Apple Symbols.ttf"]
DEFAULT_UI_BOLD = ["/System/Library/Fonts/Hiragino Sans GB.ttc:2", "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc:0",
                   "/Library/Fonts/Arial Unicode.ttf"]
DEFAULT_READER = DEFAULT_UI
# Reader text sizes (the font size setting), and the UI's sizes: (px, bold).
READER_SIZES = (14, 16, 18, 20, 22, 24, 28, 32)
UI_FONTS = ((12, False), (13, False), (14, False), (15, False),
            (13, True), (14, True), (15, True), (17, True), (18, True), (20, True))
REPLACEMENT = 0xFFFD  # drawn for characters a font doesn't have
BASE_CHARS = (
    "".join(chr(c) for c in range(0x20, 0x7F)) + "".join(chr(c) for c in range(0xA0, 0x100))
    + "‐–—‘’‚“”„†‡•…‰′″‹›€™←↑→↓√∞≈≠≤≥♪"
    + "　、。〃々〆〇〈〉《》「」『』【】〒〔〕〖〗〜〝〞・ー"
    + "中文日本語"  # the language setting's choices
    + "".join(chr(c) for c in range(0xFF01, 0xFF5F)) + chr(REPLACEMENT))


# ---- Faces ----

PILLOW = Path("pillow")  # Pillow's built-in Latin font (Aileron, public domain), for tests


def parse_face(spec):
    path, _, index = spec.rpartition(":") if spec.rpartition(":")[2].isdigit() else (spec, "", "0")
    return Path(path), int(index or 0)


class FaceChain:
    """A list of font faces; each character comes from the first face that has it."""

    def __init__(self, specs):
        self.faces = [parse_face(s) for s in specs]
        self.faces = [(p, i) for p, i in self.faces if p == PILLOW or p.exists()]
        if not self.faces:
            sys.exit("none of these fonts exist: " + ", ".join(specs) + " (give one with --ui-font/--reader-font)")
        self._cmaps = {}
        self._fonts = {}

    def key(self):
        return ";".join(f"{p}:{i}:{0 if p == PILLOW else p.stat().st_size}" for p, i in self.faces)

    def cmap(self, face):
        if face not in self._cmaps:
            from fontTools.ttLib import TTFont

            try:
                if face[0] == PILLOW:
                    import io

                    tt = TTFont(io.BytesIO(self.pil(face, 12).font_bytes))
                else:
                    tt = TTFont(str(face[0]), fontNumber=face[1], lazy=True)
                self._cmaps[face] = set(tt.getBestCmap())
            except Exception:
                self._cmaps[face] = set()
        return self._cmaps[face]

    def face_for(self, ch):
        for face in self.faces:
            if ord(ch) in self.cmap(face):
                return face
        return None

    def pil(self, face, size):
        from PIL import ImageFont

        k = (face, size)
        if k not in self._fonts:
            self._fonts[k] = (ImageFont.load_default(size) if face[0] == PILLOW
                              else ImageFont.truetype(str(face[0]), size, index=face[1]))
        return self._fonts[k]


def pil_face(regular_specs, bold_specs):
    """face(size, bold) -> a PIL font (the first face of each chain), for drawing covers."""
    chains = {False: FaceChain(regular_specs), True: FaceChain(bold_specs)}
    return lambda size, bold=False: chains[bold].pil(chains[bold].faces[0], size)


# ---- Baking ----

def bake(chain, size, chars, missing=None):
    """.dfn bytes with the given characters at `size` px."""
    from PIL import Image, ImageDraw

    primary = chain.pil(chain.faces[0], size)
    ascent, descent = primary.getmetrics()
    pad = size * 2
    canvas = Image.new("1", (size * 5, size * 5), 0)
    d = ImageDraw.Draw(canvas)
    d.fontmode = "1"
    glyphs = []
    for ch in sorted(set(chars) | {chr(REPLACEMENT)}):
        cp = ord(ch)
        if cp < 0x20 or 0x7F <= cp < 0xA0:
            continue
        face = chain.face_for(ch)
        d.rectangle([0, 0, canvas.width, canvas.height], fill=0)
        if face is None:
            if cp != REPLACEMENT:
                if missing is not None:
                    missing.add(ch)
                continue
            w, h = max(4, size * 6 // 10), max(5, size * 7 // 10)  # an empty box
            d.rectangle([pad + 1, pad - h, pad + w, pad - 1], outline=1)
            advance = w + 2
        else:
            f = chain.pil(face, size)
            d.text((pad, pad), ch, font=f, fill=1, anchor="ls")
            advance = round(f.getlength(ch))
        box = canvas.getbbox()
        if box is None:
            glyphs.append((cp, min(advance, 255), 0, 0, 0, 0, b""))
            continue
        x0, y0, x1, y1 = box
        bitmap = canvas.crop(box).tobytes()  # rows of whole bytes, leftmost pixel in the top bit
        glyphs.append((cp, min(advance, 255), min(x1 - x0, 255), min(y1 - y0, 255),
                       max(-128, min(127, x0 - pad)), max(-128, min(127, pad - y0)), bitmap))

    table, bitmaps = bytearray(), bytearray()
    for cp, adv, w, h, left, top, bits in glyphs:
        table += GLYPH.pack(cp, len(bitmaps), adv, w, h, left, top)
        bitmaps += bits
    glyph_at = HEADER.size
    bitmap_at = glyph_at + len(table)
    header = HEADER.pack(MAGIC, VERSION, HEADER.size, bitmap_at + len(bitmaps), len(glyphs), size,
                         ascent + descent, ascent, descent, glyph_at, bitmap_at)
    return header + bytes(table) + bytes(bitmaps)


def read_font(data):
    """Parses a .dfn the way the player does. Returns a dict with the glyphs by code point."""
    if len(data) < HEADER.size:
        raise ValueError("file too small")
    magic, version, hsize, fsize, count, size, line_h, ascent, descent, glyph_at, bitmap_at = HEADER.unpack_from(data)
    if magic != MAGIC or version != VERSION:
        raise ValueError(f"not a version {VERSION} font")
    if fsize != len(data):
        raise ValueError(f"size is {len(data)}, header says {fsize}")
    glyphs = {}
    for i in range(count):
        cp, off, adv, w, h, left, top = GLYPH.unpack_from(data, glyph_at + i * GLYPH.size)
        stride = (w + 7) // 8
        glyphs[cp] = (adv, w, h, left, top, data[bitmap_at + off:bitmap_at + off + stride * h])
    return dict(size=size, line_height=line_h, ascent=ascent, descent=descent, glyphs=glyphs)


def preview(font, text, scale=3):
    """Draws text with a parsed .dfn, the way the player would, into a PIL image."""
    from PIL import Image

    g = font["glyphs"]
    width = sum(g.get(ord(c), g[REPLACEMENT])[0] for c in text) + 8
    img = Image.new("L", (width, font["line_height"] + 8), 255)
    x, base = 4, 4 + font["ascent"]
    for c in text:
        adv, w, h, left, top, bits = g.get(ord(c), g[REPLACEMENT])
        stride = (w + 7) // 8
        for yy in range(h):
            for xx in range(w):
                if bits[yy * stride + xx // 8] & (0x80 >> (xx % 8)):
                    img.putpixel((x + left + xx, base - top + yy), 0)
        x += adv
    return img.resize((img.width * scale, img.height * scale), Image.Resampling.NEAREST)


# ---- The fonts on the card ----

def font_set(ui_chars, reader_chars):
    """(file name, chain name, size, characters) for every font the player uses."""
    ui = set(BASE_CHARS) | ui_chars
    reader = set(BASE_CHARS) | reader_chars | ui_chars
    out = [(f"reader-{s}.dfn", "reader", s, reader) for s in READER_SIZES]
    out += [(f"ui-{s}{'b' if b else ''}.dfn", "ui_bold" if b else "ui", s, ui) for s, b in UI_FONTS]
    return out


def build(root, ui_chars, reader_chars, specs, force=False):
    """Writes the fonts into .dap/fonts on the card, unless nothing changed since last time."""
    chains = {name: FaceChain(s) for name, s in specs.items()}
    fonts = font_set(ui_chars, reader_chars)
    h = hashlib.sha256()
    for name, chain_name, size, chars in fonts:
        h.update(f"{VERSION}|{name}|{chains[chain_name].key()}|{size}|".encode())
        h.update("".join(sorted(chars)).encode("utf-8"))
    digest = h.hexdigest()
    out_dir = root / INDEX_DIR / FONT_DIR
    manifest = out_dir / MANIFEST
    if (not force and manifest.exists() and manifest.read_text().split("\n", 1)[0] == digest
            and all((out_dir / name).exists() for name, *_ in fonts)):
        print(f"{out_dir}: fonts unchanged")
        return
    missing, total, lines = set(), 0, []
    for name, chain_name, size, chars in fonts:
        data = bake(chains[chain_name], size, chars, missing)
        write_atomic(out_dir / name, data)
        total += len(data)
        lines.append(f"{name}  {len(chars)} characters  {len(data):,} bytes")
    keep = {name for name, *_ in fonts}
    for p in out_dir.glob("*.dfn"):
        if p.name not in keep:
            p.unlink()
    faces = "\n".join(f"{n}: " + ", ".join(f"{p.name}:{i}" for p, i in c.faces) for n, c in chains.items())
    write_atomic(manifest, (digest + "\n" + faces + "\n" + "\n".join(lines) + "\n").encode())
    print(f"{out_dir}: {len(fonts)} fonts, {len(fonts[0][3]):,} characters for the reader, {total / 1e6:.1f} MB")
    if missing:
        sample = "".join(sorted(missing)[:40])
        print(f"warning: {len(missing)} characters are in none of the fonts and show as a box: {sample}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", type=Path, nargs="?", help="the card: fonts for its books and library")
    ap.add_argument("--text", help="make one font with these characters (plus the basic set)")
    ap.add_argument("--book", type=Path, action="append", help="with --text: also every character of this .dbk")
    ap.add_argument("--size", type=int, default=18)
    ap.add_argument("--bold", action="store_true", help="with --text: the bold UI face")
    ap.add_argument("-o", "--output", type=Path)
    ap.add_argument("--preview", nargs=2, metavar=("FONT", "TEXT"), help="draw TEXT with a .dfn into FONT.png")
    ap.add_argument("--ui-font", action="append", help="UI face, PATH[:INDEX] (repeat for fallbacks)")
    ap.add_argument("--ui-bold-font", action="append")
    ap.add_argument("--reader-font", action="append")
    ap.add_argument("--force", action="store_true", help="make the fonts even if nothing changed")
    args = ap.parse_args()
    specs = {"ui": args.ui_font or DEFAULT_UI, "ui_bold": args.ui_bold_font or DEFAULT_UI_BOLD,
             "reader": args.reader_font or DEFAULT_READER}
    if args.preview:
        path = Path(args.preview[0])
        out = path.with_name(path.name + ".png")
        preview(read_font(path.read_bytes()), args.preview[1]).save(out)
        print(out)
    elif args.text is not None:
        chain = FaceChain(specs["ui_bold"] if args.bold else specs["reader"])
        chars = set(BASE_CHARS) | set(args.text)
        for path in args.book or []:
            import books

            book = books.read_book(path.read_bytes())
            chars |= set(book["text"].decode("utf-8")) | set(book["title"] + book["author"])
        data = bake(chain, args.size, chars)
        out = args.output or Path(f"font-{args.size}.dfn")
        out.write_bytes(data)
        print(f"{out}: {len(read_font(data)['glyphs'])} glyphs, {len(data):,} bytes")
    elif args.folder:
        import books

        root = args.folder.resolve()
        chars = set()
        shelf = root / INDEX_DIR / books.SHELF_FILE
        if shelf.exists():
            for b in books.read_shelf(shelf.read_bytes())["books"]:
                book = books.read_book((root / INDEX_DIR / books.BOOK_DIR / f"{b['id']:08x}.dbk").read_bytes())
                chars |= set(book["text"].decode("utf-8")) | set(b["title"] + b["author"])
        build(root, chars, chars, specs, args.force)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
