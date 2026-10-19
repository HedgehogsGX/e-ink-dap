#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["pillow>=10.0", "mutagen>=1.47"]
# ///
"""Converts album art into the player's 4-gray screen format (.g4, see docs/formats.md).

    uv run tools/cover_art.py cover.jpg             -> cover.g4, plus cover.g4.png to look at
    uv run tools/cover_art.py song.flac -o art.g4   (takes the cover embedded in the file)
    uv run tools/cover_art.py art.g4                -> art.g4.png (view an existing .g4)

uv installs Pillow and mutagen on first use. Without uv: pip install pillow mutagen,
then run it with python3. tools/build_index.py uses this to make art for every album.

The picture is cropped to a square (--fit pad keeps all of it), resized, given a little
contrast and sharpening (--no-enhance turns that off), then dithered to the 4 grays.
--levels says how bright the panel's 4 grays look (sRGB 0-255, black to white); the
default assumes even steps. Once you can see real art on the panel, adjust them.
"""
import argparse
import io
import struct
import sys
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps

MAGIC = b"G4BM"
HEADER = struct.Struct("<4sHH")  # magic, width, height
DEFAULT_SIZE = (200, 200)  # the now-playing screen's art box
DEFAULT_LEVELS = (0, 85, 170, 255)  # black, dark gray, light gray, white
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".bmp", ".webp")
COVER_NAMES = ("cover", "folder", "front", "album", "albumart")


def _srgb_to_linear(v):
    v /= 255
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


_LINEAR = [_srgb_to_linear(i) for i in range(256)]


# ---- Finding a cover ----

def embedded_picture(audio_path):
    """Bytes of the picture embedded in a FLAC/MP3/WAV file (front cover first), or None."""
    import mutagen
    from mutagen.flac import FLAC

    try:
        f = mutagen.File(audio_path)
    except Exception:
        return None
    if f is None:
        return None
    if isinstance(f, FLAC):
        pics = [(p.type, p.data) for p in f.pictures]
    else:
        tags = getattr(f, "tags", None)
        pics = [(fr.type, fr.data) for fr in tags.getall("APIC")] if hasattr(tags, "getall") else []
    pics.sort(key=lambda p: p[0] != 3)  # type 3 = front cover
    return pics[0][1] if pics else None


def folder_picture(folder):
    """Path of a cover image file in the folder (cover.jpg, folder.jpg, ...), or None."""
    try:
        images = sorted(p for p in Path(folder).iterdir()
                        if p.suffix.lower() in IMAGE_SUFFIXES and not p.name.startswith("."))
    except OSError:
        return None
    for name in COVER_NAMES:
        for p in images:
            if p.stem.lower() == name:
                return p
    return images[0] if images else None


def open_picture(path):
    """Opens an image file, or the cover embedded in an audio file."""
    path = Path(path)
    if path.suffix.lower() in IMAGE_SUFFIXES:
        return Image.open(path)
    data = embedded_picture(path)
    if data is None:
        sys.exit(f"{path}: no picture embedded in this file")
    return Image.open(io.BytesIO(data))


# ---- Converting ----

def prepare(img, size=DEFAULT_SIZE, fit="crop", enhance=True):
    """Grayscale image of exactly `size`."""
    img.load()
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(bg, img)
    img = img.convert("L")
    if fit == "pad":
        img = ImageOps.pad(img, size, Image.Resampling.LANCZOS, color=255)
    else:
        img = ImageOps.fit(img, size, Image.Resampling.LANCZOS)
    if enhance:
        img = ImageOps.autocontrast(img, cutoff=0.5)
        img = img.filter(ImageFilter.UnsharpMask(radius=1.0, percent=60, threshold=2))
    return img


def dither(img, levels=DEFAULT_LEVELS, method="fs"):
    """Gray levels 0-3 (row by row) for an 'L' image. Error diffusion runs in linear light,
    so areas keep their brightness. fs = Floyd-Steinberg (serpentine), atkinson, or none."""
    w, h = img.size
    pal = [_LINEAR[v] for v in levels]
    cuts = [(pal[i] + pal[i + 1]) / 2 for i in range(3)]
    px = [_LINEAR[v] for v in img.tobytes()]
    out = bytearray(w * h)

    if method == "atkinson":
        spread = [(1, 0, 1 / 8), (2, 0, 1 / 8), (-1, 1, 1 / 8), (0, 1, 1 / 8), (1, 1, 1 / 8), (0, 2, 1 / 8)]
    elif method == "fs":
        spread = [(1, 0, 7 / 16), (-1, 1, 3 / 16), (0, 1, 5 / 16), (1, 1, 1 / 16)]
    else:
        spread = []

    for y in range(h):
        backward = method == "fs" and y % 2 == 1
        for x in (range(w - 1, -1, -1) if backward else range(w)):
            i = y * w + x
            v = px[i]
            q = 0 if v < cuts[0] else 1 if v < cuts[1] else 2 if v < cuts[2] else 3
            out[i] = q
            err = v - pal[q]
            for dx, dy, k in spread:
                nx, ny = (x - dx if backward else x + dx), y + dy
                if 0 <= nx < w and ny < h:
                    px[ny * w + nx] += err * k
    return out


def encode(levels, w, h):
    """.g4 bytes: header, then rows of 4 pixels per byte, leftmost pixel in the top bits."""
    stride = (w + 3) // 4
    data = bytearray(HEADER.pack(MAGIC, w, h))
    for y in range(h):
        row = bytearray([0xFF] * stride)  # padding pixels are white
        for x in range(w):
            shift = 6 - 2 * (x % 4)
            row[x // 4] = (row[x // 4] & ~(3 << shift)) | (levels[y * w + x] << shift)
        data += row
    return bytes(data)


def decode(data):
    """(width, height, levels) from .g4 bytes."""
    if len(data) < HEADER.size:
        raise ValueError("too short for a .g4 image")
    magic, w, h = HEADER.unpack_from(data)
    stride = (w + 3) // 4
    if magic != MAGIC or len(data) < HEADER.size + stride * h:
        raise ValueError("not a .g4 image, or truncated")
    levels = bytearray(w * h)
    for y in range(h):
        row = data[HEADER.size + y * stride:]
        for x in range(w):
            levels[y * w + x] = (row[x // 4] >> (6 - 2 * (x % 4))) & 3
    return w, h, levels


def to_image(levels, w, h, gray=DEFAULT_LEVELS):
    """What the panel shows, as an 'L' image (each level drawn as its --levels gray)."""
    return Image.frombytes("L", (w, h), bytes(gray[v] for v in levels))


def convert(img, size=DEFAULT_SIZE, fit="crop", enhance=True, levels=DEFAULT_LEVELS, method="fs"):
    """Returns (.g4 bytes, preview image)."""
    gray = prepare(img, size, fit, enhance)
    q = dither(gray, levels, method)
    return encode(q, *size), to_image(q, *size, gray=levels)


# ---- Command line ----

def parse_size(text):
    w, _, h = text.lower().partition("x")
    return int(w), int(h or w)


def parse_levels(text):
    levels = tuple(int(v) for v in text.split(","))
    if len(levels) != 4 or list(levels) != sorted(levels) or not all(0 <= v <= 255 for v in levels):
        raise argparse.ArgumentTypeError("need 4 rising values 0-255, e.g. 0,85,170,255")
    return levels


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", type=Path, help="image, audio file with embedded art, or a .g4 to view")
    ap.add_argument("-o", "--output", type=Path, help="output .g4 (default: next to the input)")
    ap.add_argument("--size", type=parse_size, default=DEFAULT_SIZE, help="WxH or one number (default 200)")
    ap.add_argument("--fit", choices=("crop", "pad"), default="crop", help="crop to fill, or pad with white")
    ap.add_argument("--dither", choices=("fs", "atkinson", "none"), default="fs")
    ap.add_argument("--no-enhance", action="store_true", help="skip auto-contrast and sharpening")
    ap.add_argument("--levels", type=parse_levels, default=DEFAULT_LEVELS,
                    help="the panel's 4 grays as sRGB 0-255 (default 0,85,170,255)")
    ap.add_argument("--no-preview", action="store_true", help="don't write the .png preview")
    args = ap.parse_args()

    if args.input.suffix.lower() == ".g4":
        w, h, q = decode(args.input.read_bytes())
        out = args.output or args.input.with_name(args.input.name + ".png")
        to_image(q, w, h, gray=args.levels).save(out)
        print(f"{args.input}: {w}x{h} -> {out}")
        return

    out = args.output or args.input.with_suffix(".g4")
    data, preview = convert(open_picture(args.input), args.size, args.fit, not args.no_enhance,
                            args.levels, args.dither)
    out.write_bytes(data)
    print(f"{out}: {args.size[0]}x{args.size[1]}, {len(data)} bytes")
    if not args.no_preview:
        preview.save(out.with_name(out.name + ".png"))
        print(f"{out}.png: preview")


if __name__ == "__main__":
    main()
