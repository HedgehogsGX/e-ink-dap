#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["pillow>=10.0", "mutagen>=1.47"]
# ///
"""Draws mockups of the player's screens at the panel's real resolution in its 4 grays,
in both orientations, into docs/previews/:

    uv run tools/render_previews.py

- now_playing.png, lyrics.png, library.png: landscape, 416 x 240
- now_playing_portrait.png, lyrics_portrait.png, library_portrait.png: portrait, 240 x 416
- overview_x2.png, overview_portrait_x2.png: the exact pixels, enlarged, to review
- eink_look.jpg, eink_look_portrait.jpg: the screens toned like e-paper (warm gray paper,
  soft black, a little ink spread) in a device frame
- orientations.jpg: each screen in landscape next to portrait, e-paper toned
- home.png, shelf.png, reader_page.png, reader_menu.png, reader_contents.png, settings.png,
  settings_reader.png: the home screen and the other apps (portrait only), with
  overview_apps_x2.png (exact pixels, captioned with how you get to each screen) and
  eink_look_apps.jpg
The e-paper look is an impression, not a measurement: real tones depend on the panel's
grayscale waveform and the light. The device frames are not to scale.

Layout rules the mockups follow, because of how the e-paper refreshes:
- Text and lines are pure black/white, no anti-aliasing: they change through fast
  partial refreshes, which are black/white only.
- Grays appear only in the album art, drawn during a full refresh on a track change.
- Touch targets (list rows, tabs) are at least 26 px (about 5 mm) tall, list rows 38 px.
Fonts are a stand-in (macOS Hiragino Sans GB); the firmware's bitmap font isn't chosen
yet. All titles, names and lyrics are made up.
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

import cover_art

LANDSCAPE, PORTRAIT = (416, 240), (240, 416)
BLACK, DARK, LIGHT, WHITE = 0, 85, 170, 255
OUT = Path(__file__).resolve().parent.parent / "docs" / "previews"
FONT_FILE = "/System/Library/Fonts/Hiragino Sans GB.ttc"  # index 0 = W3, 2 = W6
STATUS_H = 20
ART = 200
BOOK_COVER = (72, 96)  # book covers on the shelf
POS, LENGTH = 91, 242  # playback position and song length, seconds


def font(size, bold=False):
    return ImageFont.truetype(FONT_FILE, size, index=2 if bold else 0)


def new_screen(size):
    img = Image.new("L", size, WHITE)
    d = ImageDraw.Draw(img)
    d.fontmode = "1"  # no anti-aliasing
    return img, d


def text_w(d, text, f):
    return d.textlength(text, font=f)


def fit(d, text, f, width):
    """Text cut with an ellipsis to fit width."""
    if text_w(d, text, f) <= width:
        return text
    while text and text_w(d, text + "…", f) > width:
        text = text[:-1]
    return text.rstrip() + "…"


def wrap(d, text, f, width, max_lines):
    """Wraps at spaces for Latin text and between any two CJK characters."""
    tokens, word = [], ""
    for ch in text:
        if ord(ch) > 0x2E7F:  # CJK and kana: each character can start a line
            if word:
                tokens.append(word)
                word = ""
            tokens.append(ch)
        elif ch == " ":
            tokens.append(word + " ")
            word = ""
        else:
            word += ch
    if word:
        tokens.append(word)
    lines, line = [], ""
    for tok in tokens:
        if line and text_w(d, (line + tok).rstrip(), f) > width:
            lines.append(line.rstrip())
            line = tok.lstrip()
        else:
            line += tok
    lines.append(line.rstrip())
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = fit(d, lines[-1] + "…", f, width)
    return lines


def centered(d, width, y, text, f, fill=BLACK, margin=12):
    text = fit(d, text, f, width - 2 * margin)
    d.text(((width - text_w(d, text, f)) / 2, y), text, font=f, fill=fill)


def time_text(s):
    return f"{s // 60}:{s % 60:02d}"


# ---- Icons (drawn, so they look the same in any font) ----

def icon_play(d, x, y, fill=BLACK):
    d.polygon([(x, y), (x, y + 10), (x + 8, y + 5)], fill=fill)


def icon_pause(d, x, y, fill=BLACK):
    d.rectangle([x, y, x + 2, y + 10], fill=fill)
    d.rectangle([x + 5, y, x + 7, y + 10], fill=fill)


def icon_battery(d, x, y, level):
    d.rectangle([x, y, x + 21, y + 10], outline=BLACK)
    d.rectangle([x + 22, y + 3, x + 23, y + 7], fill=BLACK)
    d.rectangle([x + 2, y + 2, x + 2 + round(17 * level), y + 8], fill=BLACK)


def icon_lock(d, x, y):
    d.arc([x + 1, y, x + 8, y + 9], 180, 360, fill=BLACK, width=2)
    d.rectangle([x + 1, y + 4, x + 2, y + 6], fill=BLACK)
    d.rectangle([x + 7, y + 4, x + 8, y + 6], fill=BLACK)
    d.rectangle([x, y + 6, x + 9, y + 13], fill=BLACK)


def icon_speaker(d, x, y):
    d.rectangle([x, y + 3, x + 2, y + 7], fill=BLACK)
    d.polygon([(x + 3, y + 3), (x + 7, y), (x + 7, y + 10), (x + 3, y + 7)], fill=BLACK)


def icon_note(d, x, y):
    d.ellipse([x, y + 8, x + 5, y + 12], fill=BLACK)
    d.line([(x + 5, y + 10), (x + 5, y)], fill=BLACK)
    d.line([(x + 5, y), (x + 9, y + 2)], fill=BLACK, width=2)


def meta_w(d, parts, f):
    return sum(text_w(d, p, f) for p in parts) + 12 * (len(parts) - 1)


def meta_line(d, x, y, parts, f, fill, width):
    """Parts separated by small drawn dots (the font's middle dot is full width)."""
    end = x + width
    for i, part in enumerate(parts):
        if i:
            d.rectangle([x + 5, y + 7, x + 6, y + 8], fill=fill)
            x += 12
        part = fit(d, part, f, end - x)
        d.text((x, y), part, font=f, fill=fill)
        x += text_w(d, part, f)
        if x >= end - 10:
            break


def dotted_hline(d, x0, x1, y):
    for x in range(x0, x1, 2):
        d.point((x, y), fill=BLACK)


def icon_home(d, x, y):
    d.polygon([(x, y + 5), (x + 6, y), (x + 12, y + 5)], fill=BLACK)
    d.rectangle([x + 2, y + 5, x + 10, y + 11], fill=BLACK)
    d.rectangle([x + 5, y + 7, x + 7, y + 11], fill=WHITE)


def status_bar(d, width, fmt, playing=True, locked=False, volume=18, battery=0.82, home=False):
    """home: the screen belongs to an app, so the bar starts with the home icon (tapping
    the bar goes to the home screen)."""
    f = font(12)
    x0 = 6
    if home:
        icon_home(d, 5, 4)
        d.line([(23, 4), (23, 15)], fill=BLACK)
        x0 = 29
    (icon_play if playing else icon_pause)(d, x0, 5)
    d.text((x0 + 14, 3), fmt, font=f, fill=BLACK)
    x = width - 6 - 24
    icon_battery(d, x, 5, battery)
    pct = f"{round(battery * 100)}%"
    x -= 4 + text_w(d, pct, f)
    d.text((x, 3), pct, font=f, fill=BLACK)
    vol = str(volume)
    x -= 12 + text_w(d, vol, f)
    d.text((x, 3), vol, font=f, fill=BLACK)
    icon_speaker(d, x - 11, 5)
    if locked:
        icon_lock(d, x - 30, 3)
    d.line([(0, STATUS_H), (width, STATUS_H)], fill=BLACK)


def progress(d, x, y, w, h, frac):
    d.rectangle([x, y, x + w - 1, y + h - 1], outline=BLACK)
    d.rectangle([x, y, x + round((w - 1) * frac), y + h - 1], fill=BLACK)


def progress_with_times(d, x, y, w):
    progress(d, x, y, w, 7, POS / LENGTH)
    small = font(12)
    d.text((x, y + 11), time_text(POS), font=small, fill=BLACK)
    end = time_text(LENGTH)
    d.text((x + w - text_w(d, end, small), y + 11), end, font=small, fill=BLACK)
    track = "3 / 11"
    d.text((x + (w - text_w(d, track, small)) / 2, y + 11), track, font=small, fill=BLACK)


# ---- Sample content (all made up) ----

TITLE, ARTIST, ALBUM, YEAR = "群青の午後 (Blue Afternoon)", "Mizuiro Tape", "Paper Weather", "2024"
NOW_LYRIC = "紙の空に 青を塗った"

LYRICS = [  # (original, translation)
    ("灰色の街に 朝が来て", "灰色的街道迎来清晨"),
    ("窓の外は まだ雨のまま", "窗外依旧下着雨"),
    ("紙の空に 青を塗った", "在纸做的天空涂上蓝色"),
    ("傘はいらない 午後になれば", "不需要伞 到了午后"),
    ("きっと晴れるから", "天一定会放晴"),
    ("君の声が 聞こえた気がした", "仿佛听见了你的声音"),
]
CURRENT = 2

ALBUMS = [  # title, artist, year, songs, format. Sorted the way the index sorts them.
    ("Paper Weather", "Mizuiro Tape", 2024, "11 songs", "96/24"),
    ("Quiet Hours, Vol. 2", "The Quiet Hours", 2022, "9 songs", "44.1/16"),
    ("Sunday Dials", "Kiko & The Dials", 2020, "10 songs", "MP3"),
    ("北国の灯", "遠野ゆき", 2018, "13 songs", "48/24"),
    ("城市夜航", "林夕舟", 2019, "2 discs, 21 songs", "44.1/16"),
    ("夏の終わりのラジオ", "青木そら", 2023, "12 songs", "48/24"),
    ("海边的图书馆", "小川灯", 2021, "10 songs", "44.1/16"),
    ("白い港", "白石湾", 2017, "8 songs", "MP3"),
    ("雨上がりのバス", "Mizuiro Tape", 2022, "9 songs", "96/24"),
]
FIRST_ROW, TOTAL = 201, 248


def sample_cover(size=600):
    img = Image.new("L", (size, size))
    d = ImageDraw.Draw(img)
    for y in range(size):  # evening sky: dark at the top, bright near the horizon
        d.line([(0, y), (size, y)], fill=round(35 + 190 * (y / size) ** 1.4))
    cx, cy, r = size * 0.62, size * 0.55, size * 0.2
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=245)
    for i in range(6):  # stripes across the lower half of the sun
        y = cy + r * (0.15 + i * 0.15)
        d.rectangle([cx - r, y, cx + r, y + 3 + i * 2], fill=150)
    for k, (base, amp, shade) in enumerate([(0.70, 0.06, 95), (0.80, 0.05, 60), (0.90, 0.04, 25)]):
        pts = [(x, size * base + size * amp * math.sin(x / size * (5 + 2 * k) + k)) for x in range(0, size + 10, 10)]
        d.polygon(pts + [(size, size), (0, size)], fill=shade)
    title = ImageFont.truetype("/System/Library/Fonts/Avenir Next.ttc", 54, index=0)
    d.text((size * 0.07, size * 0.08), "PAPER\nWEATHER", font=title, fill=235, spacing=4)
    return img


# ---- Landscape screens (416 x 240) ----

def now_playing(cover):
    img, d = new_screen(LANDSCAPE)
    W, H = LANDSCAPE
    status_bar(d, W, "FLAC  96 kHz / 24 bit")
    top = STATUS_H + 1 + (H - STATUS_H - 1 - ART) // 2
    img.paste(cover, (8, top))
    x, w = 8 + ART + 14, W - (8 + ART + 14) - 8
    y = top + 2
    for line in wrap(d, TITLE, font(20, True), w, 2):
        d.text((x, y), line, font=font(20, True), fill=BLACK)
        y += 26
    y += 4
    d.text((x, y), fit(d, ARTIST, font(15), w), font=font(15), fill=BLACK)
    y += 22
    meta_line(d, x, y, [ALBUM, YEAR], font(13), BLACK, w)
    y += 30
    dotted_hline(d, x, x + w, y)
    y += 10
    icon_note(d, x, y + 2)
    for line in wrap(d, NOW_LYRIC, font(14), w - 16, 2):
        d.text((x + 16, y), line, font=font(14), fill=BLACK)
        y += 20
    progress_with_times(d, x, top + ART - 30, w)
    return img


def lyrics_header(d, width):
    head = font(13, True)
    t = f"{time_text(POS)} / {time_text(LENGTH)}"
    tw = text_w(d, t, font(12))
    title = TITLE.split(" (")[0]
    left = f"{title} — {ARTIST}" if width > 300 else title
    d.text((10, STATUS_H + 6), fit(d, left, head, width - 30 - tw), font=head, fill=BLACK)
    d.text((width - 10 - tw, STATUS_H + 7), t, font=font(12), fill=BLACK)
    dotted_hline(d, 10, width - 10, STATUS_H + 26)


def current_bars(d, width, y, h):
    d.rectangle([6, y, 9, y + h], fill=BLACK)
    d.rectangle([width - 10, y, width - 7, y + h], fill=BLACK)


def lyrics_screen():
    img, d = new_screen(LANDSCAPE)
    W, H = LANDSCAPE
    status_bar(d, W, "FLAC  96 kHz / 24 bit")
    lyrics_header(d, W)
    small, mid, big = font(13), font(14), font(21, True)
    y = STATUS_H + 36
    centered(d, W, y, LYRICS[CURRENT - 1][0], small)  # previous line
    y += 30
    # current line: bold, with its translation under it, between two bars
    current_bars(d, W, y, 52)
    centered(d, W, y + 2, LYRICS[CURRENT][0], big)
    centered(d, W, y + 32, LYRICS[CURRENT][1], mid)
    y += 66
    centered(d, W, y, LYRICS[CURRENT + 1][0], mid)  # next lines
    centered(d, W, y + 21, LYRICS[CURRENT + 1][1], small)
    centered(d, W, y + 46, LYRICS[CURRENT + 2][0], small)
    progress(d, 10, H - 9, W - 20, 4, POS / LENGTH)
    return img


def album_rows(d, albums, top, right, selected):
    """List rows, 38 px each. Returns the y below the last row."""
    row_h = 38
    title_f, sub_f, badge_f = font(14, True), font(12), font(11)
    for i, (title, artist, year, songs, fmt) in enumerate(albums):
        y = top + i * row_h
        sel = i == selected
        fg = WHITE if sel else BLACK
        if sel:
            d.rectangle([0, y, right, y + row_h - 2], fill=BLACK)
        bw = text_w(d, fmt, badge_f) + 8
        d.text((10, y + 2), fit(d, title, title_f, right - 10 - bw - 18), font=title_f, fill=fg)
        meta_line(d, 10, y + 21, [artist, str(year), songs], sub_f, fg, right - 20)
        bx = right - 6 - bw
        d.rectangle([bx, y + 5, bx + bw, y + 18], outline=fg)
        d.text((bx + 4, y + 6), fmt, font=badge_f, fill=fg)
        if not sel and i + 1 != selected and i + 1 < len(albums):
            dotted_hline(d, 10, right, y + row_h - 1)
    return top + len(albums) * row_h


def scroll_bar(d, x, top, bottom, shown):
    """Dotted track with a thumb showing where the visible rows sit in the whole list."""
    for yy in range(top, bottom, 3):
        d.point((x + 2, yy), fill=BLACK)
    span = bottom - top
    t0 = top + span * (FIRST_ROW - 1) / TOTAL
    d.rectangle([x, t0, x + 3, t0 + max(12, span * shown / TOTAL)], fill=BLACK)


def library_screen(selected=0):
    img, d = new_screen(LANDSCAPE)
    W, H = LANDSCAPE
    status_bar(d, W, "FLAC  96 kHz / 24 bit")
    tab_f = font(14, True)
    x, tab_y, tab_h = 0, STATUS_H + 1, 24
    for i, name in enumerate(["Albums", "Artists", "Songs"]):
        tw = text_w(d, name, tab_f) + 24
        if i == 0:
            d.rectangle([x, tab_y, x + tw, tab_y + tab_h - 1], fill=BLACK)
        d.text((x + 12, tab_y + 3), name, font=tab_f, fill=WHITE if i == 0 else BLACK)
        x += tw
        d.line([(x, tab_y), (x, tab_y + tab_h - 1)], fill=BLACK)
    pos = f"{FIRST_ROW + selected} / {TOTAL}"
    d.text((W - 10 - text_w(d, pos, font(12)), tab_y + 5), pos, font=font(12), fill=BLACK)
    d.line([(0, tab_y + tab_h), (W, tab_y + tab_h)], fill=BLACK)
    top = tab_y + tab_h + 1
    album_rows(d, ALBUMS[:5], top, W - 10, selected)
    scroll_bar(d, W - 6, top + 2, H - 3, 5)
    return img


# ---- Portrait screens (240 x 416) ----

def now_playing_portrait(cover):
    img, d = new_screen(PORTRAIT)
    W, H = PORTRAIT
    status_bar(d, W, "FLAC 96/24", home=True)
    art_y = STATUS_H + 10
    img.paste(cover, ((W - ART) // 2, art_y))
    y = art_y + ART + 12
    for line in wrap(d, TITLE, font(19, True), W - 24, 2):
        centered(d, W, y, line, font(19, True))
        y += 25
    y += 2
    centered(d, W, y, ARTIST, font(15))
    y += 22
    mf = font(13)
    meta_line(d, (W - meta_w(d, [ALBUM, YEAR], mf)) / 2, y, [ALBUM, YEAR], mf, BLACK, W - 24)
    y += 28
    lf = font(14)
    lyric = fit(d, NOW_LYRIC, lf, W - 40)
    x = (W - 16 - text_w(d, lyric, lf)) / 2
    icon_note(d, x, y + 2)
    d.text((x + 16, y), lyric, font=lf, fill=BLACK)
    progress_with_times(d, 12, H - 36, W - 24)
    return img


def lyrics_portrait():
    img, d = new_screen(PORTRAIT)
    W, H = PORTRAIT
    status_bar(d, W, "FLAC 96/24", home=True)
    lyrics_header(d, W)
    small, tiny, mid, big = font(13), font(12), font(14), font(20, True)
    inner = W - 36
    y = STATUS_H + 38
    bottom = H - 22  # keep clear of the progress bar
    for gi, (orig, trans) in enumerate(LYRICS):
        if gi == CURRENT:
            lo, lt = wrap(d, orig, big, inner, 2), wrap(d, trans, mid, inner, 2)
            h = len(lo) * 27 + len(lt) * 19 + 6
            if y + h > bottom:
                break
            current_bars(d, W, y, h)
            yy = y + 3
            for line in lo:
                centered(d, W, yy, line, big)
                yy += 27
            for line in lt:
                centered(d, W, yy, line, mid)
                yy += 19
        else:
            lo, lt = wrap(d, orig, small, inner, 2), wrap(d, trans, tiny, inner, 2)
            h = len(lo) * 19 + len(lt) * 17
            if y + h > bottom:
                break
            yy = y
            for line in lo:
                centered(d, W, yy, line, small)
                yy += 19
            for line in lt:
                centered(d, W, yy, line, tiny)
                yy += 17
        y += h + 14
    progress(d, 10, H - 9, W - 20, 4, POS / LENGTH)
    return img


def library_portrait(selected=0):
    img, d = new_screen(PORTRAIT)
    W, H = PORTRAIT
    status_bar(d, W, "FLAC 96/24", home=True)
    tab_f = font(14, True)
    tab_y, tab_h = STATUS_H + 1, 26
    for i, name in enumerate(["Albums", "Artists", "Songs"]):
        x0, x1 = round(i * W / 3), round((i + 1) * W / 3)
        if i == 0:
            d.rectangle([x0, tab_y, x1 - 1, tab_y + tab_h - 1], fill=BLACK)
        else:
            d.line([(x0, tab_y), (x0, tab_y + tab_h - 1)], fill=BLACK)
        d.text(((x0 + x1 - text_w(d, name, tab_f)) / 2, tab_y + 4), name, font=tab_f,
               fill=WHITE if i == 0 else BLACK)
    d.line([(0, tab_y + tab_h), (W, tab_y + tab_h)], fill=BLACK)
    top = tab_y + tab_h + 1
    end = album_rows(d, ALBUMS, top, W - 10, selected)
    scroll_bar(d, W - 6, top + 2, end - 2, len(ALBUMS))
    d.line([(0, end + 1), (W, end + 1)], fill=BLACK)
    pos = f"{FIRST_ROW + selected} / {TOTAL}"
    centered(d, W, end + 6, pos, font(12))
    return img


# ---- Home screen and the other apps (portrait) ----
# Pure black and white except the book cover on the shelf, so moving between home and
# the apps can use fast partial refreshes.

BOOK = dict(title="雾港来信", author="林知秋", fmt="EPUB", chapter="第七章 灯塔", percent=37, page=142, pages=388)
BOOKS = [  # the rest of the shelf, most recently read first: title, author, format, progress
    ("The Lighthouse Ledger", "Mara Quill", "EPUB", "19%"),
    ("Calculus Notes", "Week 1–12", "PDF", "64%"),
    ("月曜日の図書室", "森川しずく", "TXT", "New"),
    ("山海旧事", "周晚", "TXT", "Done"),
    ("Field Notes on Moss", "R. Ellery", "DOCX", "3%"),
    ("夏至の駅", "青木そら", "EPUB", "New"),
]
BOOK_TOTAL = 42
CHAPTERS = [  # (title, level, book percent where it starts)
    ("序", 1, 0), ("第一章 无名信", 1, 2), ("第二章 潮汐表", 1, 9), ("第三章 旧码头", 1, 15),
    ("第四章 渔火", 1, 21), ("第五章 南风", 1, 27), ("第六章 守夜人", 1, 32), ("第七章 灯塔", 1, 36),
    ("　灯室", 2, 39), ("　第三本日志", 2, 42), ("第八章 雾中的船", 1, 45), ("第九章 回信", 1, 57),
    ("第十章 岸", 1, 70),
]
CURRENT_CHAPTER = 7
PAGE_TEXT = [  # (paragraph, first line indented) — the page starts inside the first paragraph
    ("下来的时候，整条街都安静了。", False),
    ("雾是从海上来的。每到傍晚，港口的灯就一盏一盏亮起来，像有人在水面上写字，写一行，又被浪抹掉一行。", True),
    ("阿禾站在码头的尽头，手里攥着那封没有署名的信。信纸很薄，边角已经被海风吹得发软，上面只有一句话：“灯塔还亮着吗？”", True),
    ("她想起小时候，祖父总说，灯塔不是为了照亮海，而是为了让回家的人知道，岸还在那里。", True),
]
PAGE_TEXT_EN = [
    ("Every entry in the ledger began the same way: the date, the wind, and the state of the lamp. "
     "Elsie had read them so often that she could recite whole winters by heart.", True),
    ("Calm, north-east, lamp trimmed. Gale, south, glass cracked and replaced before midnight. "
     "Her grandfather's handwriting leaned forward, as if it were walking into weather.", True),
]
READER_SIZE, READER_PITCH, READER_MARGIN = 18, 27, 14  # px; line spacing 1.5
# Kinsoku: characters that may not start a line, and ones that may not end it.
NO_START = set("、。，．,.:：;；!！?？)）]］」』】〕〉》’”ー々ゝゞぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮヵヶ…‥・")
NO_END = set("(（[［「『【〔〈《‘“")
HANG = set("、。，．")


def sample_book_cover(w=300, h=400):
    img = Image.new("L", (w, h), 210)
    d = ImageDraw.Draw(img)
    for y in range(h):  # pale fog on top, darker sea at the bottom
        d.line([(0, y), (w, y)], fill=round(225 - 150 * (y / h) ** 2.2))
    bx, top, base = w * 0.66, h * 0.42, h * 0.8
    d.polygon([(bx, top + 22), (w * 1.15, top - 40), (w * 1.15, top + 80)], fill=245)  # beam
    d.polygon([(bx - 18, base), (bx - 10, top + 12), (bx + 10, top + 12), (bx + 18, base)], fill=240)
    for i in range(3):  # tower stripes
        y = top + 40 + i * 32
        d.rectangle([bx - 16, y, bx + 16, y + 12], fill=60)
    d.rectangle([bx - 12, top - 6, bx + 12, top + 12], fill=250)
    d.polygon([(bx - 15, top - 6), (bx, top - 22), (bx + 15, top - 6)], fill=40)
    for k in range(4):  # waves
        pts = [(x, base + 6 + k * 18 + 5 * math.sin(x / 23 + k)) for x in range(0, w + 10, 10)]
        d.polygon(pts + [(w, h), (0, h)], fill=110 - k * 25)
    title = ImageFont.truetype(FONT_FILE, 58, index=2)
    d.text((w * 0.09, h * 0.07), "雾港\n来信", font=title, fill=20, spacing=6)
    d.text((w * 0.1, h * 0.43), "林知秋 著", font=ImageFont.truetype(FONT_FILE, 22, index=0), fill=40)
    return img


def icon_app_music(d, x, y):  # 32 x 32: two beamed eighth notes
    d.ellipse([x + 1, y + 21, x + 12, y + 29], fill=BLACK)
    d.ellipse([x + 18, y + 17, x + 29, y + 25], fill=BLACK)
    d.rectangle([x + 10, y + 7, x + 12, y + 25], fill=BLACK)
    d.rectangle([x + 27, y + 3, x + 29, y + 21], fill=BLACK)
    d.polygon([(x + 10, y + 7), (x + 29, y + 2), (x + 29, y + 8), (x + 10, y + 13)], fill=BLACK)


def icon_app_book(d, x, y):  # 32 x 32: an open book
    d.polygon([(x + 1, y + 5), (x + 15, y + 9), (x + 15, y + 29), (x + 1, y + 25)], outline=BLACK, width=2)
    d.polygon([(x + 17, y + 9), (x + 31, y + 5), (x + 31, y + 25), (x + 17, y + 29)], outline=BLACK, width=2)
    for i in range(3):
        d.line([(x + 5, y + 12 + 5 * i), (x + 12, y + 14 + 5 * i)], fill=BLACK)
        d.line([(x + 20, y + 14 + 5 * i), (x + 27, y + 12 + 5 * i)], fill=BLACK)


def icon_app_gear(d, x, y):  # 32 x 32
    cx, cy, steps = x + 16, y + 16, 32
    pts = []
    for i in range(steps):
        a = 2 * math.pi * (i + 0.5) / steps
        r = 15 if i % 4 < 2 else 11
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    d.polygon(pts, fill=BLACK)
    d.ellipse([cx - 5, cy - 5, cx + 5, cy + 5], fill=WHITE)


def icon_bookmark(d, x, y, filled):
    pts = [(x, y), (x + 9, y), (x + 9, y + 13), (x + 4.5, y + 9), (x, y + 13)]
    d.polygon(pts, fill=BLACK if filled else WHITE, outline=BLACK)


def icon_list(d, x, y):
    for i in range(3):
        d.rectangle([x, y + 1 + 4 * i, x + 1, y + 2 + 4 * i], fill=BLACK)
        d.line([(x + 4, y + 1 + 4 * i), (x + 12, y + 1 + 4 * i)], fill=BLACK, width=2)


def chevron(d, x, y):
    d.line([(x, y), (x + 4, y + 4), (x, y + 8)], fill=BLACK, width=2)


def back_arrow(d, x, y):
    d.line([(x + 4, y), (x, y + 4), (x + 4, y + 8)], fill=BLACK, width=2)


def tabs(d, width, names, selected, y=STATUS_H + 1, h=26):
    tab_f = font(14, True)
    for i, name in enumerate(names):
        x0, x1 = round(i * width / len(names)), round((i + 1) * width / len(names))
        if i == selected:
            d.rectangle([x0, y, x1 - 1, y + h - 1], fill=BLACK)
        elif i:
            d.line([(x0, y), (x0, y + h - 1)], fill=BLACK)
        d.text(((x0 + x1 - text_w(d, name, tab_f)) / 2, y + 4), name, font=tab_f,
               fill=WHITE if i == selected else BLACK)
    d.line([(0, y + h), (width, y + h)], fill=BLACK)
    return y + h + 1


def button(d, x0, y0, x1, y1, label, f, inverted=False, icon=None):
    d.rounded_rectangle([x0, y0, x1, y1], radius=5, outline=BLACK, fill=BLACK if inverted else WHITE)
    tw = text_w(d, label, f) + (18 if icon else 0)
    tx = (x0 + x1 - tw) / 2
    if icon:
        icon(d, tx, (y0 + y1) / 2 - 6)
        tx += 18
    d.text((tx, (y0 + y1) / 2 - f.size / 2 - 1), label, font=f, fill=WHITE if inverted else BLACK)


def segmented(d, right, y, options, selected, h=24):
    """Choice of a few values, right-aligned at `right`; the chosen one is inverted."""
    f = font(12)
    widths = [text_w(d, o, f) + 16 for o in options]
    x = right - sum(widths)
    d.rounded_rectangle([x, y, right, y + h], radius=5, outline=BLACK)
    for i, (o, w) in enumerate(zip(options, widths)):
        if i == selected:
            d.rectangle([x + (1 if i == 0 else 0), y + 1, x + w - (1 if i == len(options) - 1 else 0), y + h - 1],
                        fill=BLACK)
        elif i and i != selected + 1:
            d.line([(x, y), (x, y + h)], fill=BLACK)
        d.text((x + 8, y + 5), o, font=f, fill=WHITE if i == selected else BLACK)
        x += w


def stepper(d, right, y, value, h=24):
    """[-] value [+], right-aligned."""
    f, bf = font(13), font(15, True)
    x1 = right
    x0 = x1 - 26
    d.rounded_rectangle([x0, y, x1, y + h], radius=5, outline=BLACK)
    d.text((x0 + 8, y + 2), "+", font=bf, fill=BLACK)
    vw = 52
    centered_in(d, x0 - vw, x0, y + 4, value, f)
    d.rounded_rectangle([x0 - vw - 26, y, x0 - vw, y + h], radius=5, outline=BLACK)
    d.rectangle([x0 - vw - 18, y + 11, x0 - vw - 8, y + 12], fill=BLACK)  # minus, drawn


def centered_in(d, x0, x1, y, text, f, fill=BLACK):
    text = fit(d, text, f, x1 - x0)
    d.text(((x0 + x1 - text_w(d, text, f)) / 2, y), text, font=f, fill=fill)


def break_lines(d, text, f, width, indent):
    """Lines of a paragraph as (tokens, x offset, last line?, hanging token or None). A token
    is one CJK character or a Latin word with its trailing space. Kinsoku: a line never
    starts with closing punctuation or ends with opening punctuation. A comma or full stop
    that doesn't fit hangs into the right margin; anything else moves the character before
    it down to the next line."""
    toks, word = [], ""
    for ch in text:
        if ord(ch) > 0x2E7F:
            if word:
                toks.append(word)
                word = ""
            toks.append(ch)
        elif ch == " ":
            toks.append(word + " ")
            word = ""
        else:
            word += ch
    if word:
        toks.append(word)
    lines, i, first = [], 0, True
    while i < len(toks):
        x0 = indent if first else 0
        line, w = [], 0
        while i < len(toks) and (not line or w + text_w(d, toks[i].rstrip(), f) <= width - x0):
            line.append(toks[i])
            w += text_w(d, toks[i], f)
            i += 1
        hang = None
        if i < len(toks) and toks[i] in HANG and (i + 1 == len(toks) or toks[i + 1][0] not in NO_START):
            hang = toks[i]
            i += 1
        while hang is None and i < len(toks) and len(line) > 1 and toks[i][0] in NO_START:
            line.pop()
            i -= 1
        while hang is None and i < len(toks) and len(line) > 1 and line[-1][-1] in NO_END:
            line.pop()
            i -= 1
        lines.append((line, x0, i >= len(toks), hang))
        first = False
    return lines


def draw_line(d, x, y, toks, f, width, justify, hang=None):
    """Tokens left to right; justified lines spread the leftover space between tokens. A
    hanging token goes right after the line, in the margin."""
    widths = [text_w(d, t, f) for t in toks]
    widths[-1] = text_w(d, toks[-1].rstrip(), f)
    gap = (width - sum(widths)) / (len(toks) - 1) if justify and len(toks) > 1 else 0
    pos = x
    for t, w in zip(toks, widths):
        d.text((round(pos), y), t.rstrip(), font=f, fill=BLACK)
        pos += w + gap
    if hang:
        d.text((round(pos - gap), y), hang, font=f, fill=BLACK)


def page_body(d, paragraphs, top, bottom, width=PORTRAIT[0]):
    """Reading text from `top` until no further line fits above `bottom`."""
    f = font(READER_SIZE)
    inner = width - 2 * READER_MARGIN
    y = top
    for text, indent in paragraphs:
        for toks, x0, last, hang in break_lines(d, text, f, inner, 2 * READER_SIZE if indent else 0):
            if y + READER_PITCH > bottom:
                return
            draw_line(d, READER_MARGIN + x0, y, toks, f, inner - x0, not last, hang)
            y += READER_PITCH


def home_screen():
    img, d = new_screen(PORTRAIT)
    W, H = PORTRAIT
    status_bar(d, W, "FLAC 96/24")
    x, tw = 60, W - 18 - 60
    name_f, line_f, small = font(18, True), font(14, True), font(12)

    y = 30  # Music: what is playing
    d.rounded_rectangle([8, y, W - 9, y + 116], radius=7, outline=BLACK)
    icon_app_music(d, 17, y + 12)
    d.text((x, y + 10), "Music", font=name_f, fill=BLACK)
    d.text((x, y + 40), fit(d, TITLE, line_f, tw), font=line_f, fill=BLACK)
    meta_line(d, x, y + 60, [ARTIST, ALBUM], small, BLACK, tw)
    progress(d, x, y + 84, tw, 5, POS / LENGTH)
    d.text((x, y + 93), time_text(POS), font=small, fill=BLACK)
    end = time_text(LENGTH)
    d.text((x + tw - text_w(d, end, small), y + 93), end, font=small, fill=BLACK)

    y = 154  # Reader: the book you are in
    d.rounded_rectangle([8, y, W - 9, y + 116], radius=7, outline=BLACK)
    icon_app_book(d, 17, y + 12)
    d.text((x, y + 10), "Reader", font=name_f, fill=BLACK)
    d.text((x, y + 40), fit(d, BOOK["title"], line_f, tw), font=line_f, fill=BLACK)
    meta_line(d, x, y + 60, [BOOK["author"], BOOK["chapter"]], small, BLACK, tw)
    progress(d, x, y + 84, tw, 5, BOOK["percent"] / 100)
    d.text((x, y + 93), f"{BOOK['percent']}%", font=small, fill=BLACK)
    pages = f"{BOOK['page']} / {BOOK['pages']}"
    d.text((x + tw - text_w(d, pages, small), y + 93), pages, font=small, fill=BLACK)

    y = 278
    d.rounded_rectangle([8, y, W - 9, y + 70], radius=7, outline=BLACK)
    icon_app_gear(d, 17, y + 19)
    d.text((x, y + 9), "Settings", font=name_f, fill=BLACK)
    d.text((x, y + 36), "Music · Reader", font=small, fill=BLACK)
    d.text((x, y + 52), "Display · System", font=small, fill=BLACK)

    dotted_hline(d, 16, W - 16, 364)
    centered(d, W, 374, "2,481 songs · 42 books", small)
    centered(d, W, 392, "96.3 GB free", small)
    return img


def shelf_screen(cover):
    img, d = new_screen(PORTRAIT)
    W, H = PORTRAIT
    status_bar(d, W, "FLAC 96/24", home=True)
    top = tabs(d, W, ["Recent", "Title", "Author"], 0)
    # The book you are in, with its cover; tapping anywhere here opens it where you left off.
    cy = top + 8
    img.paste(cover, (10, cy))
    d.rectangle([9, cy - 1, 10 + cover.width, cy + cover.height], outline=BLACK)
    x, tw = 94, W - 10 - 94
    y = cy - 1
    for line in wrap(d, BOOK["title"], font(17, True), tw, 2):
        d.text((x, y), line, font=font(17, True), fill=BLACK)
        y += 23
    d.text((x, y + 1), fit(d, BOOK["author"], font(13), tw), font=font(13), fill=BLACK)
    bf = font(11)
    bw = text_w(d, BOOK["fmt"], bf) + 8
    d.rectangle([x, y + 24, x + bw, y + 37], outline=BLACK)
    d.text((x + 4, y + 25), BOOK["fmt"], font=bf, fill=BLACK)
    progress(d, x, cy + cover.height - 24, tw, 6, BOOK["percent"] / 100)
    meta_line(d, x, cy + cover.height - 13, [f"{BOOK['percent']}%", BOOK["chapter"]], font(12), BLACK, tw)
    end = cy + cover.height + 8
    d.line([(0, end), (W, end)], fill=BLACK)

    row_h, title_f, sub_f, badge_f = 38, font(14, True), font(12), font(11)
    y = end + 1
    for i, (title, author, fmt, prog) in enumerate(BOOKS):
        bw = text_w(d, fmt, badge_f) + 8
        d.text((10, y + 2), fit(d, title, title_f, W - 20 - bw - 12), font=title_f, fill=BLACK)
        meta_line(d, 10, y + 21, [author, prog], sub_f, BLACK, W - 20)
        bx = W - 10 - bw
        d.rectangle([bx, y + 5, bx + bw, y + 18], outline=BLACK)
        d.text((bx + 4, y + 6), fmt, font=badge_f, fill=BLACK)
        if i + 1 < len(BOOKS):
            dotted_hline(d, 10, W - 10, y + row_h - 1)
        y += row_h
    d.line([(0, y + 1), (W, y + 1)], fill=BLACK)
    centered(d, W, y + 6, f"1–{len(BOOKS) + 1} / {BOOK_TOTAL}", font(12))
    return img


def reader_header_footer(d, chapter, left, right):
    W, H = PORTRAIT
    small = font(12)
    d.text((READER_MARGIN, 3), fit(d, chapter, small, W - 60), font=small, fill=BLACK)
    icon_play(d, W - READER_MARGIN - 8, 5)  # music is playing
    d.text((READER_MARGIN, H - 19), left, font=small, fill=BLACK)
    d.text((W - READER_MARGIN - text_w(d, right, small), H - 19), right, font=small, fill=BLACK)


def reader_page():
    """A page, with nothing but the chapter, a playing indicator and where you are."""
    img, d = new_screen(PORTRAIT)
    W, H = PORTRAIT
    reader_header_footer(d, BOOK["chapter"], f"{BOOK['percent']}%", f"{BOOK['page']} / {BOOK['pages']}")
    page_body(d, PAGE_TEXT, 27, H - 24)
    return img


def reader_menu():
    """Tapping the middle of a page: bars over the page with everything else."""
    img, d = new_screen(PORTRAIT)
    W, H = PORTRAIT
    reader_header_footer(d, "3 · The Keeper's Book", "19%", "41 / 212")
    page_body(d, PAGE_TEXT_EN, 27, H - 24)

    d.rectangle([0, 0, W, 48], fill=WHITE)
    status_bar(d, W, "FLAC 96/24", home=True)
    back_arrow(d, 9, 30)
    d.text((18, 25), "Shelf", font=font(14, True), fill=BLACK)
    centered_in(d, 66, W - 34, 26, "The Lighthouse Ledger", font(13))
    icon_bookmark(d, W - 22, 27, filled=True)
    d.rectangle([0, 48, W, 49], fill=BLACK)

    top = 282
    d.rectangle([0, top, W, H], fill=WHITE)
    d.rectangle([0, top, W, top + 1], fill=BLACK)
    y = top + 9
    d.text((10, y), fit(d, "3 · The Keeper's Book", font(13, True), 150), font=font(13, True), fill=BLACK)
    right = "41 / 212"
    d.text((W - 10 - text_w(d, right, font(12)), y + 1), right, font=font(12), fill=BLACK)
    y += 26  # where you are in the book: chapter ticks under a slider
    x0, x1 = 12, W - 12
    d.rectangle([x0, y, x1, y + 1], fill=BLACK)
    px = x0 + round((x1 - x0) * 0.19)
    d.rectangle([x0, y - 1, px, y + 2], fill=BLACK)
    d.rectangle([px - 3, y - 6, px + 3, y + 7], fill=BLACK)
    for p in (0, 0.05, 0.12, 0.17, 0.26, 0.34, 0.45, 0.58, 0.66, 0.79, 0.91):
        tx = x0 + round((x1 - x0) * p)
        d.line([(tx, y + 5), (tx, y + 8)], fill=BLACK)
    y += 18
    f = font(13, True)
    button(d, 8, y, W // 2 - 4, y + 30, "Contents", f, icon=icon_list)
    button(d, W // 2 + 4, y, W - 9, y + 30, "Bookmarks", f, icon=lambda dd, xx, yy: icon_bookmark(dd, xx, yy - 1, False))
    y += 40
    button(d, 8, y, 44, y + 30, "A", font(12, True))
    centered_in(d, 44, 96, y + 7, "18 px", font(13))
    button(d, 96, y, 132, y + 30, "A", font(17, True))
    button(d, 140, y, W - 9, y + 30, "Aa  More", f)
    return img


def reader_contents():
    img, d = new_screen(PORTRAIT)
    W, H = PORTRAIT
    status_bar(d, W, "FLAC 96/24", home=True)
    top = tabs(d, W, ["Contents", "Bookmarks 3"], 0)
    row_h, f, small = 30, font(14), font(12)
    shown = CHAPTERS[:11]
    for i, (title, level, pct) in enumerate(shown):
        y = top + i * row_h
        sel = i == CURRENT_CHAPTER
        fg = WHITE if sel else BLACK
        if sel:
            d.rectangle([0, y, W, y + row_h - 2], fill=BLACK)
        x = 12 if level == 1 else 26
        tf = font(14, True) if sel else f
        d.text((x, y + 6), fit(d, title.strip("　"), tf, W - x - 50), font=tf, fill=fg)
        p = f"{pct}%"
        d.text((W - 12 - text_w(d, p, small), y + 8), p, font=small, fill=fg)
        if not sel and i + 1 != CURRENT_CHAPTER and i + 1 < len(shown):
            dotted_hline(d, 12, W - 12, y + row_h - 1)
    y = top + len(shown) * row_h
    d.line([(0, y + 1), (W, y + 1)], fill=BLACK)
    centered(d, W, y + 7, f"{BOOK['title']} · {len(CHAPTERS)} chapters", font(12))
    return img


SETTINGS = [  # category, summary of its current values
    ("Music", "Start volume 10 · limit 40"),
    ("Reader", "18 px · line spacing 1.5"),
    ("Display", "Full refresh every 10 pages"),
    ("System", "Lock 2 min · sleep 15 min"),
    ("About", "Firmware 0.1 · built Oct 19"),
]


def settings_screen():
    img, d = new_screen(PORTRAIT)
    W, H = PORTRAIT
    status_bar(d, W, "FLAC 96/24", home=True)
    d.text((10, 26), "Settings", font=font(17, True), fill=BLACK)
    d.line([(0, 50), (W, 50)], fill=BLACK)
    row_h = 54
    for i, (name, summary) in enumerate(SETTINGS):
        y = 51 + i * row_h
        d.text((12, y + 8), name, font=font(15, True), fill=BLACK)
        d.text((12, y + 30), fit(d, summary, font(12), W - 44), font=font(12), fill=BLACK)
        chevron(d, W - 18, y + 22)
        if i + 1 < len(SETTINGS):
            dotted_hline(d, 12, W - 12, y + row_h - 1)
    y = 51 + len(SETTINGS) * row_h
    d.line([(0, y), (W, y)], fill=BLACK)
    y += 12
    d.text((12, y), "Storage", font=font(13, True), fill=BLACK)
    free = "96.3 GB free of 119 GB"
    d.text((W - 12 - text_w(d, free, font(12)), y + 1), free, font=font(12), fill=BLACK)
    progress(d, 12, y + 22, W - 24, 8, 0.19)
    meta_line(d, 12, y + 36, ["Music 21.4 GB", "Books 0.6 GB"], font(12), BLACK, W - 24)
    return img


def settings_reader():
    img, d = new_screen(PORTRAIT)
    W, H = PORTRAIT
    status_bar(d, W, "FLAC 96/24", home=True)
    back_arrow(d, 9, 32)
    d.text((18, 27), "Settings", font=font(13), fill=BLACK)
    centered_in(d, 0, W, 26, "Reader", font(16, True))
    d.line([(0, 50), (W, 50)], fill=BLACK)
    rows = [
        ("Font size", lambda y: stepper(d, W - 10, y, "18 px")),
        ("Line spacing", lambda y: stepper(d, W - 10, y, "1.5")),
        ("Margins", lambda y: segmented(d, W - 10, y, ["S", "M", "L"], 1)),
        ("Indent", lambda y: segmented(d, W - 10, y, ["Auto", "On", "Off"], 0)),
        ("Justify", lambda y: segmented(d, W - 10, y, ["On", "Off"], 0)),
        ("Volume keys", lambda y: segmented(d, W - 10, y, ["Volume", "Pages"], 0)),
    ]
    row_h, lf = 36, font(13)
    for i, (label, control) in enumerate(rows):
        y = 51 + i * row_h
        d.text((12, y + 10), label, font=lf, fill=BLACK)
        control(y + 6)
        if i + 1 < len(rows):
            dotted_hline(d, 12, W - 12, y + row_h - 1)
    y = 51 + len(rows) * row_h + 10
    d.text((12, y), "Preview", font=font(12, True), fill=BLACK)
    box_top = y + 18
    d.rounded_rectangle([8, box_top, W - 9, H - 10], radius=6, outline=BLACK)
    page_body(d, [("雾是从海上来的。每到傍晚，港口的灯就一盏一盏亮起来。", True),
                  ("The fog came in from the sea, quietly.", True)], box_top + 8, H - 12)
    return img


# ---- E-paper look and review sheets ----

EINK_TONES = {BLACK: (40, 40, 42), DARK: (94, 94, 92), LIGHT: (152, 151, 147), WHITE: (216, 214, 206)}
DESK = (236, 236, 232)


def eink_look(img, scale=2):
    """The screen toned like e-paper, enlarged, in a device frame with the 4 buttons below."""
    lut = [EINK_TONES.get(v, (v, v, v)) for v in range(256)]
    rgb = Image.merge("RGB", [img.point([t[c] for t in lut]) for c in range(3)])
    rgb = rgb.resize((img.width * scale, img.height * scale), Image.Resampling.NEAREST)
    rgb = rgb.filter(ImageFilter.GaussianBlur(0.55 * scale / 2))  # ink spreads a little
    noise = Image.effect_noise(rgb.size, 40).convert("RGB")
    rgb = Image.blend(rgb, noise, 0.035)  # paper grain
    bezel, chin = 22, 46
    body = Image.new("RGB", (rgb.width + 2 * bezel, rgb.height + bezel + chin), DESK)
    d = ImageDraw.Draw(body)
    d.rounded_rectangle([0, 0, body.width - 1, body.height - 1], radius=30, fill=(58, 60, 64))
    d.rounded_rectangle([3, 3, body.width - 4, body.height - 4], radius=28, outline=(86, 88, 93), width=2)
    d.rectangle([bezel - 3, bezel - 3, bezel + rgb.width + 2, bezel + rgb.height + 2], fill=(30, 31, 33))
    body.paste(rgb, (bezel, bezel))
    for i in range(4):  # the physical buttons, as dots on the chin
        cx = body.width // 2 + (i - 1.5) * 56
        cy = bezel + rgb.height + chin // 2
        d.ellipse([cx - 9, cy - 9, cx + 9, cy + 9], fill=(44, 45, 48), outline=(96, 98, 104), width=2)
    return body


def sheet_font(size):
    return ImageFont.truetype(FONT_FILE, size, index=2)


def row_sheet(images, horizontal, background, gap=30):
    """Images in one row (horizontal) or one column, with a margin around them."""
    if horizontal:
        size = (sum(i.width for i in images) + gap * (len(images) + 1), max(i.height for i in images) + 2 * gap)
    else:
        size = (max(i.width for i in images) + 2 * gap, sum(i.height for i in images) + gap * (len(images) + 1))
    sheet = Image.new(images[0].mode, size, background)
    pos = gap
    for img in images:
        sheet.paste(img, (pos, gap) if horizontal else (gap, pos))
        pos += (img.width if horizontal else img.height) + gap
    return sheet


def pixel_overview(screens, horizontal):
    """Exact pixels at 2x, each with a thin frame and its file name."""
    tiles = []
    for name, img in screens:
        big = img.resize((img.width * 2, img.height * 2), Image.Resampling.NEAREST)
        tile = Image.new("L", (big.width + 4, big.height + 30), 225)
        d = ImageDraw.Draw(tile)
        d.text((2, 2), f"{name}.png  ({img.width} x {img.height}, shown at 2x)", font=font(15), fill=BLACK)
        d.rectangle([0, 26, big.width + 3, big.height + 29], outline=BLACK, width=2)
        tile.paste(big, (2, 28))
        tiles.append(tile)
    return row_sheet(tiles, horizontal, 225, gap=16)


def captioned_grid(screens, cols):
    """Exact pixels at 2x in a grid; each tile has its file name above and a caption below."""
    cap_f = font(15)
    tiles = []
    for name, img, caption in screens:
        big = img.resize((img.width * 2, img.height * 2), Image.Resampling.NEAREST)
        tile = Image.new("L", (big.width + 4, big.height + 30 + 50), 225)
        d = ImageDraw.Draw(tile)
        d.fontmode = "1"
        d.text((2, 2), f"{name}.png", font=font(15, True), fill=BLACK)
        d.rectangle([0, 26, big.width + 3, big.height + 29], outline=BLACK, width=2)
        tile.paste(big, (2, 28))
        for i, line in enumerate(wrap(d, caption, cap_f, big.width, 2)):
            d.text((2, big.height + 36 + i * 21), line, font=cap_f, fill=BLACK)
        tiles.append(tile)
    gap = 16
    tw, th = tiles[0].size
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("L", (gap + cols * (tw + gap), gap + rows * (th + gap)), 225)
    for i, tile in enumerate(tiles):
        sheet.paste(tile, (gap + (i % cols) * (tw + gap), gap + (i // cols) * (th + gap)))
    return sheet


def grid_sheet(images, cols, background, gap=30):
    w, h = max(i.width for i in images), max(i.height for i in images)
    rows = (len(images) + cols - 1) // cols
    sheet = Image.new(images[0].mode, (gap + cols * (w + gap), gap + rows * (h + gap)), background)
    for i, img in enumerate(images):
        sheet.paste(img, (gap + (i % cols) * (w + gap), gap + (i // cols) * (h + gap)))
    return sheet


def orientation_sheet(landscape, portrait, names):
    """Each screen as a row: landscape device on the left, portrait device on the right."""
    margin, col_gap, label_h = 40, 60, 54
    lw = max(dv.width for dv in landscape)
    pw = max(dv.width for dv in portrait)
    row_h = [max(a.height, b.height) for a, b in zip(landscape, portrait)]
    width = margin * 2 + lw + col_gap + pw
    height = margin + 40 + sum(h + label_h + margin for h in row_h)
    sheet = Image.new("RGB", (width, height), DESK)
    d = ImageDraw.Draw(sheet)
    ink = (40, 40, 42)
    d.text((margin, margin), "Landscape  416 × 240", font=sheet_font(26), fill=ink)
    d.text((margin + lw + col_gap, margin), "Portrait  240 × 416", font=sheet_font(26), fill=ink)
    y = margin + 40
    for a, b, h, name in zip(landscape, portrait, row_h, names):
        y += 14
        d.text((margin, y), name, font=sheet_font(22), fill=(110, 110, 112))
        y += label_h - 14
        sheet.paste(a, (margin, y + (h - a.height) // 2))
        sheet.paste(b, (margin + lw + col_gap, y))
        y += h + margin
    return sheet


def check_grays(img, name):
    used = sorted(set(img.tobytes()))
    assert set(used) <= {BLACK, DARK, LIGHT, WHITE}, f"{name}: uses grays {used}"


def save(img, name, **kw):
    img.save(OUT / name, **kw)
    print(OUT / name)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    _, cover = cover_art.convert(sample_cover(), (ART, ART))
    landscape = [("now_playing", now_playing(cover)), ("lyrics", lyrics_screen()), ("library", library_screen())]
    portrait = [("now_playing_portrait", now_playing_portrait(cover)), ("lyrics_portrait", lyrics_portrait()),
                ("library_portrait", library_portrait())]
    for name, img in landscape + portrait:
        check_grays(img, name)
        save(img, f"{name}.png")

    save(pixel_overview(landscape, horizontal=False), "overview_x2.png")
    save(pixel_overview(portrait, horizontal=True), "overview_portrait_x2.png")

    land_dev = [eink_look(img) for _, img in landscape]
    port_dev = [eink_look(img) for _, img in portrait]
    save(row_sheet(land_dev, horizontal=False, background=DESK), "eink_look.jpg", quality=88)
    save(row_sheet(port_dev, horizontal=True, background=DESK), "eink_look_portrait.jpg", quality=88)
    save(orientation_sheet(land_dev, port_dev, ["Now playing", "Lyrics", "Library"]), "orientations.jpg", quality=88)

    _, book_cover = cover_art.convert(sample_book_cover(), BOOK_COVER)
    apps = [
        ("home", home_screen(), "Home. From any screen: tap the status bar, or hold Lock."),
        ("shelf", shelf_screen(book_cover), "Reader: tap the Reader card. The book you are in is on top."),
        ("reader_page", reader_page(), "Tap a book. Tap the left or right third to turn the page."),
        ("reader_menu", reader_menu(), "Tap the middle of a page for the menu (an English book)."),
        ("reader_contents", reader_contents(), "Contents or Bookmarks in the menu. Tap a row to go there."),
        ("settings", settings_screen(), "Settings: tap the Settings card."),
        ("settings_reader", settings_reader(), "Settings > Reader, or Aa More in the reader menu."),
        ("now_playing_portrait", portrait[0][1], "Music: tap the Music card (now playing, as before)."),
    ]
    for name, img, _ in apps[:-1]:
        check_grays(img, name)
        save(img, f"{name}.png")
    save(captioned_grid(apps, cols=4), "overview_apps_x2.png")
    save(grid_sheet([eink_look(img) for _, img, _ in apps], cols=4, background=DESK), "eink_look_apps.jpg",
         quality=88)


if __name__ == "__main__":
    main()
