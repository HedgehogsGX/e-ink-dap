#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["mutagen>=1.47", "pillow>=10.0", "pypdfium2>=4.30", "mammoth>=1.8", "charset-normalizer>=3.3",
#                 "fonttools>=4.50"]
# ///
"""Prepares the microSD card for the player: the music library index, the books for
the reader, and the fonts. Formats: docs/formats.md.

    uv run tools/build_index.py /Volumes/MUSIC
    uv run tools/build_index.py --dump /Volumes/MUSIC/.dap/library.idx

Run it on the card's top folder after adding or removing music or books.
- Music: reads the tags of every FLAC, MP3 and WAV file and writes .dap/library.idx,
  plus one 4-gray cover per album in .dap/art/ (from the picture embedded in the files,
  or a cover.jpg/folder.jpg in the album folder). The Books folder is not searched.
- Books: converts what is in /Books (EPUB, PDF, TXT, Markdown, DOCX) with tools/books.py.
- Fonts: bitmap fonts with every character the library and the books use (tools/fonts.py).
Paths in the index start at the folder you give, so give the card itself, or a folder
whose contents you then copy to the card's top level.

uv installs the Python packages it needs on first use. Without uv: pip install mutagen
pillow pypdfium2 mammoth charset-normalizer fonttools, then run it with python3.
"""
import argparse
import os
import re
import struct
import sys
import time
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from mutagen.flac import FLAC
from mutagen.mp3 import MP3
from mutagen.wave import WAVE

import books
import cover_art
import fonts
from dap_common import INDEX_DIR, Strings, card_path, ident, skipped_name, sort_key, write_atomic

INDEX_FILE = "library.idx"
ART_DIR = "art"

MAGIC = b"DAPL"
VERSION = 1
# magic, version, header size, file size, CRC-32 of everything after the header,
# track/album/artist counts, offsets of tracks, albums, artists, artist albums, songs by
# title and strings, strings size, track/album/artist record sizes, build time.
HEADER = struct.Struct("<4sHH II III IIIIII I HBB I")
TRACK = struct.Struct("<IIIII HH BBBB H BB")
ALBUM = struct.Struct("<IIII HH")
ARTIST = struct.Struct("<II HH")
assert (HEADER.size, TRACK.size, ALBUM.size, ARTIST.size) == (64, 32, 20, 12)

CODECS = {".flac": 1, ".mp3": 2, ".wav": 3}
CODEC_NAMES = {1: "FLAC", 2: "MP3", 3: "WAV"}
OTHER_AUDIO = {".m4a", ".aac", ".alac", ".ogg", ".opus", ".wma", ".ape", ".aif", ".aiff", ".dsf", ".dff", ".wv"}
FLAG_LYRICS = 1
VARIOUS = "Various Artists"
DISC_FOLDER = re.compile(r"(cd|disc|disk)\s*\d+", re.IGNORECASE)

ID3_FRAMES = {"title": "TIT2", "artist": "TPE1", "album": "TALB", "albumartist": "TPE2",
              "tracknumber": "TRCK", "discnumber": "TPOS", "date": "TDRC", "titlesort": "TSOT",
              "artistsort": "TSOP", "albumsort": "TSOA", "albumartistsort": "TSO2"}
VORBIS_ALIASES = {"albumartist": ("albumartist", "album artist", "album_artist"), "date": ("date", "year")}


@dataclass
class Track:
    file: Path
    path: str  # on the card: "/Artist/Album/01 Song.flac"
    title: str
    artist: str
    album: str
    albumartist: str
    title_sort: str
    artist_sort: str
    album_sort: str
    albumartist_sort: str
    track_no: int
    disc_no: int
    year: int
    duration_ms: int
    sample_rate: int
    bits: int
    channels: int
    codec: int
    bitrate_kbps: int
    has_lyrics: bool
    album_index: int = 0
    index: int = 0  # position in the index's track table


@dataclass
class Album:
    title: str
    artist: str
    artist_sort: str
    title_sort: str
    year: int
    tracks: list
    art: str = ""


@dataclass
class Artist:
    name: str
    albums: list = field(default_factory=list)  # album indexes


def first_int(text):
    m = re.match(r"\s*(\d+)", text)
    return int(m.group(1)) if m else 0


def year_of(text):
    m = re.search(r"\d{4}", text)
    return int(m.group(0)) if m else 0


def tag_reader(f):
    """Returns get(name) -> text ('' if missing) for Vorbis-style tag names."""
    tags = f.tags
    if tags is None:
        return lambda name: ""

    def join(values):
        return ", ".join(v for v in (str(x).replace("\0", "").strip() for x in values) if v)

    if isinstance(f, FLAC):
        return lambda name: next((join(tags[k]) for k in VORBIS_ALIASES.get(name, (name,)) if k in tags), "")

    def get_id3(name):
        frame = tags.get(ID3_FRAMES[name])
        return join(frame.text) if frame is not None else ""

    return get_id3


def read_track(file, root, warnings):
    ext = file.suffix.lower()
    f = {".flac": FLAC, ".mp3": MP3, ".wav": WAVE}[ext](file)
    info = f.info
    get = tag_reader(f)

    folder = file.parent
    if DISC_FOLDER.fullmatch(folder.name) and folder != root:
        folder = folder.parent
    lrc = lyrics_file(file)
    if lrc:
        try:
            lrc.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            warnings.append(f"not UTF-8, the player can't show it (re-save it as UTF-8): {lrc}")
    bitrate = getattr(info, "bitrate", 0) or 0
    return Track(
        file=file,
        path=card_path(file, root),
        title=get("title") or file.stem,
        artist=get("artist"),
        album=get("album") or (folder.name if folder != root else ""),
        albumartist=get("albumartist"),
        title_sort=get("titlesort"),
        artist_sort=get("artistsort"),
        album_sort=get("albumsort"),
        albumartist_sort=get("albumartistsort"),
        track_no=first_int(get("tracknumber")),
        disc_no=first_int(get("discnumber")),
        year=year_of(get("date")),
        duration_ms=round(info.length * 1000),
        sample_rate=info.sample_rate,
        bits=0 if ext == ".mp3" else getattr(info, "bits_per_sample", 0),
        channels=info.channels,
        codec=CODECS[ext],
        bitrate_kbps=round(bitrate / 1000),
        has_lyrics=lrc is not None,
    )


_dir_cache = {}


def lyrics_file(file):
    """The .lrc next to the audio file (same name, any case), or None."""
    names = _dir_cache.get(file.parent)
    if names is None:
        names = _dir_cache[file.parent] = {p.name.lower(): p for p in file.parent.iterdir()}
    return names.get((file.stem + ".lrc").lower())


def scan(root):
    """Audio files under root, skipping hidden folders/files (.dap, .Trashes, macOS ._ files)."""
    found, other = [], {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not skipped_name(d) and not (Path(dirpath) == root and d == "Books"))
        for name in sorted(filenames):
            ext = Path(name).suffix.lower()
            if name.startswith("."):
                continue
            if ext in CODECS:
                found.append(Path(dirpath, name))
            elif ext in OTHER_AUDIO:
                other[ext] = other.get(ext, 0) + 1
    return found, other


def group_albums(tracks, root):
    groups = {}
    for t in tracks:
        if t.albumartist:
            key = ("tag", ident(t.albumartist), ident(t.album))
        else:  # no album artist: one album per folder (CD1/CD2 folders count as one)
            folder = t.file.parent
            if DISC_FOLDER.fullmatch(folder.name) and folder != root:
                folder = folder.parent
            key = ("dir", str(folder), ident(t.album))
        groups.setdefault(key, []).append(t)

    albums = []
    for ts in groups.values():
        ts.sort(key=lambda t: (t.disc_no, t.track_no == 0, t.track_no, sort_key(t.file.name)))
        first = ts[0]
        if first.albumartist:
            artist = first.albumartist
        else:
            artist = first.artist if len({t.artist for t in ts}) == 1 else VARIOUS
        artist_sort = (next((t.albumartist_sort for t in ts if t.albumartist_sort), "")
                       or (first.artist_sort if artist == first.artist else "") or artist)
        albums.append(Album(title=first.album, artist=artist, artist_sort=artist_sort,
                            title_sort=first.album_sort or first.album,
                            year=min((t.year for t in ts if t.year), default=0), tracks=ts))
    albums.sort(key=lambda a: (sort_key(a.title_sort), sort_key(a.artist_sort), a.year))
    return albums


def group_artists(albums):
    by_name = {}
    for i, a in enumerate(albums):
        by_name.setdefault(ident(a.artist), Artist(a.artist)).albums.append(i)
    artists = sorted(by_name.values(), key=lambda ar: sort_key(albums[ar.albums[0]].artist_sort))
    for ar in artists:
        ar.albums.sort(key=lambda i: (albums[i].year == 0, albums[i].year, sort_key(albums[i].title_sort)))
    return artists


def album_picture(album, root):
    """PIL image of the album's cover, or None."""
    from PIL import Image
    import io

    for t in album.tracks:
        data = cover_art.embedded_picture(t.file)
        if data:
            return Image.open(io.BytesIO(data))
    folder = album.tracks[0].file.parent
    for d in (folder, folder.parent) if DISC_FOLDER.fullmatch(folder.name) and folder != root else (folder,):
        p = cover_art.folder_picture(d)
        if p:
            return Image.open(p)
    return None


def make_art(albums, root, size, warnings):
    art_dir = root / INDEX_DIR / ART_DIR
    art_dir.mkdir(parents=True, exist_ok=True)
    for old in art_dir.glob("*.g4"):
        old.unlink()
    made = 0
    for i, a in enumerate(albums):
        try:
            img = album_picture(a, root)
            if img is None:
                continue
            data, _ = cover_art.convert(img, (size, size))
        except Exception as e:  # a broken picture shouldn't stop the whole index
            warnings.append(f"cover of '{a.title}' skipped: {e}")
            continue
        name = f"{i:05d}.g4"
        (art_dir / name).write_bytes(data)
        a.art = f"/{INDEX_DIR}/{ART_DIR}/{name}"
        made += 1
    return made


def encode_index(tracks, albums, artists, built):
    strings = Strings()
    sec_tracks = bytearray()
    for t in tracks:
        sec_tracks += TRACK.pack(
            strings.add(t.path), strings.add(t.title), strings.add(t.artist),
            min(t.duration_ms, 0xFFFFFFFF), t.sample_rate, t.album_index, min(t.track_no, 0xFFFF),
            min(t.disc_no, 0xFF), min(t.bits, 0xFF), min(t.channels, 0xFF), t.codec,
            min(t.bitrate_kbps, 0xFFFF), FLAG_LYRICS if t.has_lyrics else 0, 0)
    sec_albums = bytearray()
    for a in albums:
        sec_albums += ALBUM.pack(strings.add(a.title), strings.add(a.artist), strings.add(a.art),
                                 a.tracks[0].index, len(a.tracks), min(a.year, 0xFFFF))
    sec_artists = bytearray()
    artist_albums = []
    for ar in artists:
        n_tracks = sum(len(albums[i].tracks) for i in ar.albums)
        sec_artists += ARTIST.pack(strings.add(ar.name), len(artist_albums), len(ar.albums), min(n_tracks, 0xFFFF))
        artist_albums += ar.albums
    sec_artist_albums = struct.pack(f"<{len(artist_albums)}H", *artist_albums)
    sec_artist_albums += b"\0" * (-len(sec_artist_albums) % 4)
    songs = sorted(range(len(tracks)), key=lambda i: (
        sort_key(tracks[i].title_sort or tracks[i].title), sort_key(tracks[i].artist), i))
    sec_songs = struct.pack(f"<{len(songs)}I", *songs)

    body = bytearray()
    offsets = []
    for sec in (sec_tracks, sec_albums, sec_artists, sec_artist_albums, sec_songs, strings.data):
        offsets.append(HEADER.size + len(body))
        body += sec
    header = HEADER.pack(MAGIC, VERSION, HEADER.size, HEADER.size + len(body), zlib.crc32(body),
                         len(tracks), len(albums), len(artists), *offsets, len(strings.data),
                         TRACK.size, ALBUM.size, ARTIST.size, built)
    return header + body


def read_index(data):
    """Parses an index (the same checks the player does). Returns a dict of lists."""
    if len(data) < HEADER.size:
        raise ValueError("file too small")
    (magic, version, header_size, file_size, crc, n_tracks, n_albums, n_artists, o_tracks, o_albums,
     o_artists, o_artist_albums, o_songs, o_strings, strings_size, track_size, album_size, artist_size,
     built) = HEADER.unpack_from(data)
    if magic != MAGIC or version != VERSION:
        raise ValueError(f"not a version {VERSION} library index")
    if file_size != len(data):
        raise ValueError(f"size is {len(data)}, header says {file_size} (file cut short?)")
    if zlib.crc32(data[header_size:]) != crc:
        raise ValueError("checksum mismatch (file damaged?)")

    def s(off):
        start = o_strings + off
        return data[start:data.index(b"\0", start)].decode("utf-8")

    tracks = []
    for i in range(n_tracks):
        (path, title, artist, dur, rate, album, track_no, disc_no, bits, channels, codec, kbps, flags,
         _) = TRACK.unpack_from(data, o_tracks + i * track_size)
        tracks.append(dict(path=s(path), title=s(title), artist=s(artist), duration_ms=dur, sample_rate=rate,
                           album=album, track_no=track_no, disc_no=disc_no, bits=bits, channels=channels,
                           codec=codec, bitrate_kbps=kbps, has_lyrics=bool(flags & FLAG_LYRICS)))
    albums = []
    for i in range(n_albums):
        title, artist, art, first, count, year = ALBUM.unpack_from(data, o_albums + i * album_size)
        albums.append(dict(title=s(title), artist=s(artist), art=s(art), first=first, count=count, year=year))
    artist_albums = struct.unpack_from(f"<{n_albums}H", data, o_artist_albums)
    artists = []
    for i in range(n_artists):
        name, first, n_alb, n_trk = ARTIST.unpack_from(data, o_artists + i * artist_size)
        artists.append(dict(name=s(name), albums=list(artist_albums[first:first + n_alb]), tracks=n_trk))
    songs = list(struct.unpack_from(f"<{n_tracks}I", data, o_songs))
    return dict(tracks=tracks, albums=albums, artists=artists, songs=songs, built=built)


def fmt_format(t):
    rate = t["sample_rate"] / 1000
    rate = f"{rate:g}"
    name = CODEC_NAMES.get(t["codec"], "?")
    return f"{name} {t['bitrate_kbps']}k" if t["codec"] == 2 else f"{name} {rate}/{t['bits']}"


def fmt_time(ms):
    s = round(ms / 1000)
    return f"{s // 60}:{s % 60:02d}"


def dump(path):
    data = Path(path).read_bytes()
    lib = read_index(data)
    built = time.strftime("%Y-%m-%d %H:%M", time.localtime(lib["built"]))
    print(f"{path}: {len(lib['tracks'])} tracks, {len(lib['albums'])} albums, "
          f"{len(lib['artists'])} artists, {len(data):,} bytes, built {built}")
    print("\nAlbums")
    for i, a in enumerate(lib["albums"]):
        year = f" ({a['year']})" if a["year"] else ""
        print(f"  [{i}] {a['title']} - {a['artist'] or 'Unknown artist'}{year}  art: {a['art'] or '-'}")
        for t in lib["tracks"][a["first"]:a["first"] + a["count"]]:
            no = f"{t['disc_no']}-{t['track_no']}" if t["disc_no"] else f"{t['track_no'] or '-'}"
            print(f"      {no:>4}. {t['title']} - {t['artist'] or '?'}  {fmt_time(t['duration_ms'])}  "
                  f"{fmt_format(t)}{'  [lrc]' if t['has_lyrics'] else ''}  {t['path']}")
    print("\nArtists")
    for ar in lib["artists"]:
        names = ", ".join(lib["albums"][i]["title"] for i in ar["albums"])
        print(f"  {ar['name'] or 'Unknown artist'} ({ar['tracks']} songs): {names}")
    print("\nSongs by title")
    print("  " + " | ".join(lib["tracks"][i]["title"] for i in lib["songs"]))


def build(root, out, art_size, args):
    root = root.resolve()
    if not root.is_dir():
        sys.exit(f"{root}: not a folder")
    t0 = time.time()
    files, other = scan(root)
    warnings, tracks = [], []
    for n, file in enumerate(files, 1):
        if n % 200 == 0:
            print(f"  reading tags: {n}/{len(files)}", file=sys.stderr)
        try:
            tracks.append(read_track(file, root, warnings))
        except Exception as e:
            warnings.append(f"skipped, can't read it ({type(e).__name__}: {e}): {file}")
    if len(tracks) > 0xFFFFFFFF:
        sys.exit("too many tracks")
    albums = group_albums(tracks, root)
    if len(albums) > 0xFFFF:
        sys.exit(f"{len(albums)} albums: the index format allows 65535")
    ordered = []
    for i, a in enumerate(albums):
        for t in a.tracks:
            t.album_index, t.index = i, len(ordered)
            ordered.append(t)
    artists = group_artists(albums)
    art_made = make_art(albums, root, art_size, warnings) if art_size else 0

    built = int(os.environ.get("SOURCE_DATE_EPOCH", time.time()))
    data = encode_index(ordered, albums, artists, built)
    read_index(data)  # self-check
    out = out or root / INDEX_DIR / INDEX_FILE
    write_atomic(out, data)

    print(f"{out}: {len(ordered)} tracks, {len(albums)} albums, {len(artists)} artists, "
          f"{len(data):,} bytes ({len(data) // max(len(ordered), 1)} per track), "
          f"{art_made} covers, {time.time() - t0:.1f} s")
    if other:
        print("Not indexed (the player can't play these yet): "
              + ", ".join(f"{n} {ext}" for ext, n in sorted(other.items())))
    if not args.no_books:
        face = fonts.pil_face(args.ui_font or fonts.DEFAULT_UI, args.ui_bold_font or fonts.DEFAULT_UI_BOLD)
        _, text_chars, title_chars = books.build(root, face, warnings, args.force_books)
        if not args.no_fonts:
            ui_chars = set(title_chars)
            for t in ordered:
                ui_chars.update(t.title + t.artist)
            for a in albums:
                ui_chars.update(a.title + a.artist)
            fonts.build(root, ui_chars, text_chars | title_chars,
                        {"ui": args.ui_font or fonts.DEFAULT_UI, "ui_bold": args.ui_bold_font or fonts.DEFAULT_UI_BOLD,
                         "reader": args.reader_font or fonts.DEFAULT_READER})
    for w in warnings:
        print("warning: " + w)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", type=Path, nargs="?", help="the card (or the folder that will be its top level)")
    ap.add_argument("--out", type=Path, help=f"index file to write (default: FOLDER/{INDEX_DIR}/{INDEX_FILE})")
    ap.add_argument("--art-size", type=int, default=cover_art.DEFAULT_SIZE[0],
                    help="cover size in pixels (default %(default)s); 0 = no covers")
    ap.add_argument("--dump", type=Path, metavar="INDEX", help="print the contents of an index file instead")
    ap.add_argument("--no-books", action="store_true", help="music only: skip the books and the fonts")
    ap.add_argument("--no-fonts", action="store_true", help="skip making the fonts")
    ap.add_argument("--force-books", action="store_true", help="convert every book again, even unchanged ones")
    ap.add_argument("--ui-font", action="append", metavar="PATH[:INDEX]", help="font for menus (see tools/fonts.py)")
    ap.add_argument("--ui-bold-font", action="append", metavar="PATH[:INDEX]")
    ap.add_argument("--reader-font", action="append", metavar="PATH[:INDEX]", help="font for book text")
    args = ap.parse_args()
    if args.dump:
        dump(args.dump)
    elif args.folder:
        build(args.folder, args.out, args.art_size, args)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
