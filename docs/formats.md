# Files on the microSD card

What the PC tools in `tools/` write to the card, and what the firmware reads. All numbers
are little-endian; all text is UTF-8.

```
/                         your music, in any folders (FLAC, MP3, WAV)
/Artist/Album/Song.flac
/Artist/Album/Song.lrc    synced lyrics: same name as the song, next to it
/Books/...                your books, in any folders (EPUB, PDF, TXT, Markdown, DOCX)
/.dap/library.idx         library index      (tools/build_index.py)
/.dap/art/00042.g4        album covers, one per album, named by album number
/.dap/books.idx           the reader's shelf (tools/books.py, run by build_index.py)
/.dap/books/1a2b3c4d.dbk  each book converted for the reader, named by book id
/.dap/books/1a2b3c4d.g4   its cover, 72 x 96
/.dap/fonts/*.dfn         bitmap fonts for the menus and the reader (tools/fonts.py)
/.dap/settings.ini        settings              (written by the player)
/.dap/reading.txt         where you are in each book, bookmarks (written by the player)
```

After adding or removing music or books, run the builder on the card (it also makes the
covers, converts the books and makes the fonts):

```bash
uv run tools/build_index.py /Volumes/MUSIC
```

`.dap` starts with a dot, so macOS Finder hides it. To try the tools without a card,
`tools/make_sample_library.sh` makes a small made-up library in `sample_music.nosync/`,
and `uv run tools/make_sample_books.py` made-up books in every format in
`sample_books.nosync/Books/`. Music files inside `/Books` are not indexed.

---

## Library index — `/.dap/library.idx`, version 1

Lets the player list and open thousands of songs without scanning the card at boot.
Reader: `lib/library_index/` (`LibraryIndex`). Writer and `--dump` viewer:
`tools/build_index.py`.

The firmware loads the whole file into PSRAM and reads it in place. It is about 150–200
bytes per track, mostly path text: 10,000 tracks ≈ 2 MB.

### Layout

| Section | Content |
|---|---|
| Header | 64 bytes, below |
| Tracks | `track_count` × 32-byte records, stored album by album in album order |
| Albums | `album_count` × 20-byte records, sorted by title |
| Artists | `artist_count` × 12-byte records, sorted by name, unknown artist last |
| Artist albums | `album_count` × u16 album numbers; each artist owns a range, albums by year; padded to 4 bytes |
| Songs by title | `track_count` × u32 track numbers, in title order |
| Strings | UTF-8, each ending in a NUL byte, each stored once. A string field is an offset into this section; offset 0 is the empty string |

### Header (64 bytes)

| Offset | Type | Field |
|---|---|---|
| 0 | 4 bytes | magic `DAPL` |
| 4 | u16 | version = 1. Readers reject other versions |
| 6 | u16 | header size = 64 |
| 8 | u32 | file size. A mismatch means the copy was cut short |
| 12 | u32 | CRC-32 (zlib's) of everything after the header |
| 16 | u32 | track count |
| 20 | u32 | album count (at most 65,535) |
| 24 | u32 | artist count |
| 28 | u32 | offset of tracks |
| 32 | u32 | offset of albums |
| 36 | u32 | offset of artists |
| 40 | u32 | offset of artist albums |
| 44 | u32 | offset of songs by title |
| 48 | u32 | offset of strings |
| 52 | u32 | size of strings (the last byte is NUL) |
| 56 | u16 | track record size (32) |
| 58 | u8 | album record size (20) |
| 59 | u8 | artist record size (12) |
| 60 | u32 | build time, Unix seconds |

The record sizes let a later version add fields at the end of a record without breaking
older readers: readers step through records by the size given here.

### Track record (32 bytes)

| Offset | Type | Field |
|---|---|---|
| 0 | u32 | path (string). From the card root: `/Artist/Album/01 Song.flac` |
| 4 | u32 | title (string). The file name without extension if there is no tag |
| 8 | u32 | artist (string), may be empty |
| 12 | u32 | duration, ms |
| 16 | u32 | sample rate, Hz |
| 20 | u16 | album number |
| 22 | u16 | track number, 0 = unknown |
| 24 | u8 | disc number, 0 = unknown |
| 25 | u8 | bits per sample, 0 for MP3 |
| 26 | u8 | channels |
| 27 | u8 | codec: 1 FLAC, 2 MP3, 3 WAV |
| 28 | u16 | bitrate, kbps (average for FLAC and VBR MP3) |
| 30 | u8 | flags: bit 0 = a `.lrc` with the same name is next to the file |
| 31 | u8 | reserved, 0 |

### Album record (20 bytes)

| Offset | Type | Field |
|---|---|---|
| 0 | u32 | title (string) |
| 4 | u32 | album artist (string): the album-artist tag, else the one artist of all tracks, else `Various Artists`; empty if unknown |
| 8 | u32 | cover (string): path of its `.g4` file, empty if none |
| 12 | u32 | first track; the album's tracks follow in disc/track order |
| 16 | u16 | track count |
| 18 | u16 | year, 0 = unknown |

### Artist record (12 bytes)

| Offset | Type | Field |
|---|---|---|
| 0 | u32 | name (string), empty = unknown artist |
| 4 | u32 | first entry in "artist albums" |
| 8 | u16 | album count |
| 10 | u16 | track count (stops at 65,535) |

### How the builder decides things

- **Files**: `.flac`, `.mp3`, `.wav`. Skipped: anything in a folder or file starting with
  `.` (`.dap`, `.Trashes`, the `._Song.flac` files macOS leaves on FAT32 cards) and
  `System Volume Information`. Other audio formats are counted and reported.
- **Albums**: tracks with an album-artist tag group by (album artist, album). Without
  one, by (folder, album), and `CD1`/`Disc 2` folders count as their parent folder, so
  compilations and multi-disc albums stay together. A missing album tag becomes the
  folder name.
- **Sorting**: case and full/half width are ignored, and so is leading punctuation
  (`「青」` sorts under 青). Without sort tags, Latin comes first, then kana, then
  kanji/hanzi by code point, which is not reading order. For correct Japanese or
  Chinese order, add sort tags (`TITLESORT`/`ALBUMSORT`/`ARTISTSORT`/`ALBUMARTISTSORT`
  in FLAC, `TSOT`/`TSOA`/`TSOP`/`TSO2` in MP3), e.g. a kana reading. The builder uses
  them for ordering only.
- **Paths** are stored in Unicode NFC form. macOS hands FAT32 file names to programs
  decomposed (が as か + ゛), but stores them composed on the card, which is what the
  ESP32 compares against when opening a file (checked 2026-10-16 on a FAT32 disk image).
  Copying from macOS also leaves `._` files, which is why those are skipped.
- The file is written to `library.idx.tmp` and then renamed, so an interrupted run
  leaves the old index in place.

---

## Album art — `.g4` (4-gray bitmap)

Made by `tools/cover_art.py` (and by `build_index.py` for every album). Reader:
`lib/g4image/g4image.h` (`G4Image`).

| Offset | Type | Field |
|---|---|---|
| 0 | 4 bytes | magic `G4BM` |
| 4 | u16 | width, pixels |
| 6 | u16 | height, pixels |
| 8 | … | pixels: `height` rows of `ceil(width / 4)` bytes |

Each byte holds 4 pixels, the leftmost in the top two bits (bits 7–6). Values: 0 black,
1 dark gray, 2 light gray, 3 white. Padding pixels at the end of a row are white. The
default 200 × 200 cover is 10,008 bytes.

To draw it, read the file into memory and plot each pixel with the matching gray; to
draw in black and white only, `G4Image::blackInBw()` turns the grays into a 2 × 2 dot
pattern.

How the tool makes it: crop to a square (`--fit pad` keeps the whole picture instead),
resize, stretch the contrast a little and sharpen (`--no-enhance` turns this off), then
Floyd–Steinberg dithering (`--dither atkinson|none`) computed in linear light, so dithered
areas keep their brightness. `--levels` says how bright the panel's 4 grays look (sRGB
0–255, default even steps 0,85,170,255); adjust it once real art is visible on the panel.
`cover_art.py file.g4` turns a `.g4` back into a PNG to check it.

**Panel notes (not yet tested on hardware):**
- GxEPD2 1.6.9's `GxEPD2_370_GDEY037T03` driver is black and white only. Grays need a
  grayscale waveform: GxEPD2_4G, or the 4-gray mode in Good Display's demo code. Whether
  either supports this panel is still to check.
- Partial refreshes are black and white. So the plan is: draw the cover during the full
  refresh on a track change, and update progress and lyrics with partial refreshes. That
  only works if a partial refresh leaves grays outside its window alone, which also
  needs checking on the panel.

---

## Synced lyrics — `.lrc`

Same file name as the song, in the same folder (`01 Song.flac` → `01 Song.lrc`, any
case). Parser: `lib/lyrics/` (`Lyrics`).

- **Encoding**: UTF-8, with or without a BOM. Lyrics downloaded from Chinese or
  Japanese sites are often GBK or Shift-JIS; `build_index.py` lists them so they can be
  re-saved as UTF-8 (the player can't convert them).
- **Time tags**: `[mm:ss]`, `[mm:ss.x]`, `[mm:ss.xx]`, `[mm:ss.xxx]`, `[mm:ss:xx]`, and
  several in front of one line (`[00:12.00][01:30.00]chorus`).
- **Info tags**: `[ti:]`, `[ar:]`, `[al:]`, and `[offset:+/-ms]`, where a positive offset
  makes the lyrics appear earlier.
- An empty timed line clears the lyrics, e.g. during a solo.
- Lines sharing a time stay in file order, so a translation written right after the
  original line stays under it. The lyrics screen shows them as one group.
- Enhanced-LRC word times (`<00:12.30>`) are removed; lines without a time tag are
  ignored.

---

## Books

What `tools/books.py` does with each format (the player itself never parses them):

| Format | What the reader gets |
|---|---|
| EPUB 2 and 3 | The spine's chapters, each starting a new page; headings, bold, quotes, lists, line breaks (`<br>`); the contents from the EPUB 3 nav document or the EPUB 2 NCX; the declared cover. Ruby readings (`<rt>`), images, scripts and styles are dropped. |
| PDF | The text layer, joined back into paragraphs (a line ends one when it is clearly shorter than the page's usual line and ends a sentence). Page numbers and running headers are dropped; the outline becomes the contents; the first page is the cover. Scanned PDFs have no text layer and are skipped with a warning. At most 5,000 pages. |
| TXT | UTF-8 or UTF-16 with a BOM; otherwise the encoding is guessed (GB18030, Shift-JIS, Big5, …) and reported. One line is one paragraph, unless the text is wrapped at a fixed width with blank lines between paragraphs (Project Gutenberg style), then the lines are joined. Chapter lines (`第七章 灯塔`, `第一卷`, `Chapter 3`, `序章`, `Prologue` …) become headings and the contents; `作者：`/`书名：` lines near the top set the author and title. |
| Markdown | `#` and underlined headings, lists, quotes, code blocks, rules, `**bold**`; links keep their text, images are dropped; `title:`/`author:` front matter. |
| DOCX | Through mammoth: Heading 1/2 styles become headings and the contents, bold stays; the document's thumbnail or first picture is the cover. |

A book without a cover gets a lettered one: its title and author in a frame, black and
white. Books keep their id (and so their reading position) as long as the file keeps its
path on the card. Unchanged books are not converted again; a newer tool converts all of
them again by itself (the shelf records the converter version).

### Book — `/.dap/books/<id>.dbk`, version 1

Reader: `lib/book/` (`Book`). Writer and `--dump` viewer: `tools/books.py`.

The text comes last, so the player reads the front of the file (header, sections,
contents, strings: a few KB) to open a book, and then one section of text at a time.

| Section | Content |
|---|---|
| Header | 64 bytes, below |
| Sections | `section count` × u32: text offsets where a section starts, rising, the first 0 |
| Contents | `toc count` × 12-byte entries, in text order |
| Strings | UTF-8, NUL-terminated, as in the library index (offset 0 = empty) |
| Text | the book text, below |

| Offset | Type | Field |
|---|---|---|
| 0 | 4 bytes | magic `DAPB` |
| 4 | u16 | version = 1 |
| 6 | u16 | header size = 64 |
| 8 | u32 | file size |
| 12 | u32 | CRC-32 of everything after the header |
| 16 | u32 | offset of the text (= the size of the front part) |
| 20 | u32 | text size, bytes |
| 24 | u32 | offset of sections |
| 28 | u32 | section count (at least 1) |
| 32 | u32 | offset of contents |
| 36 | u32 | contents entry count |
| 40 | u32 | offset of strings |
| 44 | u32 | size of strings |
| 48 | u32 | title (string) |
| 52 | u32 | author (string), may be empty |
| 56 | u32 | language (string), e.g. `zh`, `en`; may be empty |
| 60 | u8 | source format: 1 EPUB, 2 PDF, 3 TXT, 4 Markdown, 5 DOCX |
| 61 | u8 | flags: bit 0 = mostly CJK text (the reader indents paragraphs by 2 em) |
| 62 | u16 | reserved, 0 |

Contents entry: u32 text offset of the chapter's first paragraph (always a section
start), u32 title (string), u8 level (1 = top), 3 reserved bytes.

**Sections.** The reader lays out one section at a time and starts every section on a
new page, so a page can always be laid out from its own first byte. A section starts at
every chapter in the contents and at every EPUB chapter file, and a section never grows
past 64 KiB: longer chapters are split at a paragraph, which leaves one short page there.
Measured on the board (2026-10-19, `reader_bench`): 64 KiB takes 112 ms to lay out.

### Book text

UTF-8. Every paragraph ends with `\n`. Its first byte may give it a style; without one it
is body text:

| Byte | Paragraph |
|---|---|
| 0x01, 0x02, 0x03 | heading level 1, 2, 3 |
| 0x04 | quote (indented both sides) |
| 0x05 | list item; the text starts with its bullet or number (`• `, `3. `) |
| 0x06 | preformatted: spaces kept, breaks anywhere |
| 0x07 | centred (scene breaks like `* * *`) |
| 0x08 | separator: no text, the reader draws a short line |
| 0x0B | continues the paragraph before it on a new line (`<br>`, or a split paragraph) |

Inside a paragraph, 0x0E turns bold on and 0x0F off; bold ends with the paragraph. No
other control characters occur, there are no blank paragraphs, and a paragraph is at most
8 KiB (longer ones are split at a sentence end). A position in a book (reading position,
bookmark) is a byte offset in this text.

### Shelf — `/.dap/books.idx`, version 1

Reader: `lib/book/` (`Shelf`). Header (48 bytes): magic `DAPS`, u16 version 1, u16 header
size 48, u32 file size, u32 CRC-32 of everything after the header, u32 book count, u32
offset of books, u32 offset of "by author", u32 offset of strings, u32 strings size, u16
book record size (32), u16 reserved, u32 build time (Unix seconds), u32 converter version.

Books are sorted by title (sorted like albums, see above); "by author" is `count` × u32
book numbers in author order, unknown authors last. Book record (32 bytes):

| Offset | Type | Field |
|---|---|---|
| 0 | u32 | id: CRC-32 of the source path; names `/.dap/books/<id as 8 hex digits>.dbk` and `.g4` |
| 4 | u32 | title (string) |
| 8 | u32 | author (string) |
| 12 | u32 | source path on the card (string), `/Books/…` |
| 16 | u32 | source file size |
| 20 | u32 | source modification time (Unix seconds); with the size, tells the tool the book is unchanged |
| 24 | u32 | text size, bytes (progress on the shelf = reading position / text size) |
| 28 | u8 | source format, as in the book header |
| 29 | u8 | flags: bit 0 = the cover is the book's own (else lettered) |
| 30 | u16 | contents entry count |

The cover is a `.g4` image (above), 72 × 96, next to the book.

---

## Fonts — `/.dap/fonts/*.dfn`, version 1

Made by `tools/fonts.py` (run by `build_index.py`). Reader: `lib/bitmap_font/`
(`BitmapFont`). One file per size: `reader-14.dfn` … `reader-32.dfn` for book text (the
font size setting: 14, 16, 18, 20, 22, 24, 28, 32 px) and `ui-12.dfn` … `ui-20b.dfn`
(`b` = bold) for the menus. Each holds only the characters the card needs: every
character of the books, every title and name in the library and on the shelf, and the
usual Latin, CJK and full-width punctuation. A character a font lacks is drawn as its
U+FFFD box. `fonts.txt` next to them records what they were made from, so an unchanged
card isn't baked again.

Glyphs are rendered black and white (no anti-aliasing), because text changes through
partial refreshes. Bold book text is drawn twice, 1 px apart.

| Offset | Type | Field |
|---|---|---|
| 0 | 4 bytes | magic `DAPF` |
| 4 | u16 | version = 1 |
| 6 | u16 | header size = 32 |
| 8 | u32 | file size |
| 12 | u32 | glyph count |
| 16 | u16 | size, px (one em) |
| 18 | u16 | line height (ascent + descent) |
| 20 | i16 | ascent, px above the baseline |
| 22 | i16 | descent, px below it |
| 24 | u32 | offset of glyphs: `glyph count` × 16 bytes, sorted by code point |
| 28 | u32 | offset of bitmaps |

Glyph (16 bytes): u32 code point, u32 bitmap offset (from the bitmaps' start), u8
advance, u8 width, u8 height, i8 left (bitmap's left edge from the pen), i8 top (its top
row, pixels above the baseline), 3 reserved bytes. A bitmap is `height` rows of
`ceil(width / 8)` bytes, leftmost pixel in bit 7, 1 = ink.

---

## Settings — `/.dap/settings.ini`

Written by the player, readable and editable on a computer. Reader: `lib/settings/`
(`Settings`). Unknown keys and bad values are ignored (keys in any case); values out of
range are pulled into range, and the start volume never exceeds the volume limit. With
no file, the defaults below apply.

```ini
[music]
start_volume = 10          ; 0-40, steps of 1.5 dB (40 = 0 dB)
volume_limit = 40          ; 0-40
resume = on                ; reopen the last song, paused
repeat = off               ; off / all / one
shuffle = off
lyric_translations = on

[reader]
font_size = 18             ; 14 16 18 20 22 24 28 32
line_spacing = 150         ; percent, 120-200
margins = medium           ; small / medium / large = 6 / 14 / 22 px
indent = auto              ; auto (2 em for CJK books, 1 em otherwise) / on / off
justify = on
volume_keys_turn_pages = off

[display]
full_refresh_every = 10    ; page turns between full refreshes, 1-50
invert = off               ; white on black
rotate_180 = off

[system]
auto_lock_minutes = 2      ; 0 = never
sleep_minutes = 15         ; idle and not playing; 0 = never
language = en              ; en / zh / ja
```

## Reading state — `/.dap/reading.txt`

Written by the player. Reader: `lib/reader/` (`ReadingState`). The first line must be
`# E-ink DAP reading state 1`; then one line per book:

```
652fee49 964 17 0 100 964
```

book id (hex), reading position (text offset of the page's first character), last opened
(a counter, the board has no clock), finished (0/1), then up to 100 bookmarks (page
starts). A bookmark belongs to the page it falls on, so it survives font changes. Lines
that can't be read are skipped.
