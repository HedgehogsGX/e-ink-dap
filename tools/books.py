#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["pillow>=10.0", "pypdfium2>=4.30", "mammoth>=1.8", "charset-normalizer>=3.3", "fonttools>=4.50"]
# ///
"""Converts the books in /Books on the card into the player's reader format, and writes
the shelf index and the covers (formats: docs/formats.md).

    uv run tools/books.py /Volumes/MUSIC          (build_index.py does this for you)
    uv run tools/books.py --convert book.epub     -> book.dbk, to try one file
    uv run tools/books.py --dump /Volumes/MUSIC/.dap/books.idx
    uv run tools/books.py --dump book.dbk         (add --text to print the whole text)

Reads EPUB, PDF (its text layer; scanned PDFs have none), TXT, Markdown and DOCX. The
player lays the text out itself, so font size and margins can change on the device;
this tool only turns each format into the same simple paragraphs, finds the chapters,
and makes a 72 x 96 cover (the book's own, or one lettered with the title).

Books that haven't changed since the last run are not converted again.
"""
import argparse
import io
import os
import posixpath
import re
import struct
import sys
import time
import unicodedata
import zipfile
import zlib
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote
from xml.etree import ElementTree

import cover_art
from dap_common import INDEX_DIR, Strings, card_path, read_string, skipped_name, sort_key, write_atomic

BOOKS_DIR = "Books"
SHELF_FILE = "books.idx"
BOOK_DIR = "books"
COVER_SIZE = (72, 96)

EPUB, PDF, TXT, MARKDOWN, DOCX = 1, 2, 3, 4, 5
FORMATS = {".epub": EPUB, ".pdf": PDF, ".txt": TXT, ".md": MARKDOWN, ".markdown": MARKDOWN, ".docx": DOCX}
FORMAT_NAMES = {EPUB: "EPUB", PDF: "PDF", TXT: "TXT", MARKDOWN: "MD", DOCX: "DOCX"}
OTHER_BOOKS = {".doc", ".mobi", ".azw", ".azw3", ".fb2", ".rtf", ".djvu", ".cbz", ".cbr", ".pages"}
PDF_MAX_PAGES = 5000

# Paragraph styles: the first byte of a paragraph (none = body text).
BODY, H1, H2, H3, QUOTE, ITEM, PRE, CENTER, RULE = 0, 1, 2, 3, 4, 5, 6, 7, 8
LINE_BREAK = 0x0B  # continues the paragraph before it on a new line (<br>, a split paragraph)
BOLD_ON, BOLD_OFF = "\x0e", "\x0f"
STYLE_NAMES = {BODY: "", H1: "h1", H2: "h2", H3: "h3", QUOTE: "quote", ITEM: "item", PRE: "pre",
               CENTER: "center", RULE: "rule", LINE_BREAK: "br"}
# Layout restarts at the top of a page at every section start; the player lays out one
# section at a time, so sections are kept small. A paragraph longer than PARA_MAX is split.
SECTION_MAX = 64 * 1024
PARA_MAX = 8 * 1024
FLAG_CJK = 1
SHELF_FLAG_OWN_COVER = 1

MAGIC_BOOK, MAGIC_SHELF = b"DAPB", b"DAPS"
VERSION = 1
# Raise this when a change here alters what a book converts to, so every book is
# converted again on the next run instead of being reused.
CONVERTER = 1
# magic, version, header size, file size, CRC-32 of everything after the header, text
# offset/size, sections offset/count, TOC offset/count, strings offset/size, title,
# author, language, source format, flags, reserved
BOOK_HEADER = struct.Struct("<4sHH II II II II II III BBH")
TOC_ENTRY = struct.Struct("<IIB3x")
# magic, version, header size, file size, CRC-32, book count, offsets of books, of "by
# author" and of strings, strings size, book record size, reserved, build time, converter
SHELF_HEADER = struct.Struct("<4sHH II I IIII HH II")
SHELF_BOOK = struct.Struct("<IIIIIII BBH")
assert (BOOK_HEADER.size, TOC_ENTRY.size, SHELF_HEADER.size, SHELF_BOOK.size) == (64, 12, 48, 32)

CJK_RANGES = "⺀-鿿豈-﫿＀-￯　-〿"
CJK_CHAR = re.compile(f"[{CJK_RANGES}]")
NEWLINE_IN_CJK = re.compile(f"(?<=[{CJK_RANGES}])[ \t]*\n\\s*(?=[{CJK_RANGES}])")
# Control characters except our two bold markers, plus line/paragraph separators.
CONTROL = re.compile("[\x00-\x0d\x10-\x1f\x7f-\x9f  ]")
INVISIBLE = re.compile("[­​‎‏﻿]")
SENTENCE_END = re.compile(r"[。！？!?.…」』”\"](?=\s|[^\s.]|$)")


# ---- Building a document ----

@dataclass
class Doc:
    title: str = ""
    author: str = ""
    language: str = ""
    paras: list = field(default_factory=list)   # (style, text with bold markers)
    toc: list = field(default_factory=list)     # (paragraph index, level, title)
    breaks: set = field(default_factory=set)    # paragraph indexes that start a section
    cover: object = None                        # PIL image or None
    notes: list = field(default_factory=list)


def clean_inline(text):
    """Running text: NFC, no controls, whitespace collapsed."""
    text = unicodedata.normalize("NFC", text)
    text = INVISIBLE.sub("", CONTROL.sub(" ", text.replace("\t", " ")))
    text = re.sub(r" {2,}", " ", text)
    text = text.replace(BOLD_ON + BOLD_OFF, "").replace(BOLD_OFF + BOLD_ON, "")
    return text.strip(" 　")


def plain(text):
    return text.replace(BOLD_ON, "").replace(BOLD_OFF, "")


def add_para(doc, style, text):
    """Adds a paragraph unless it is empty. Returns True if added."""
    if style == PRE:
        text = INVISIBLE.sub("", CONTROL.sub(" ", unicodedata.normalize("NFC", text).replace("\t", "    "))).rstrip()
        if not text.strip():
            text = " "
    elif style == RULE:
        text = ""
    else:
        text = clean_inline(text)
        opens = text.count(BOLD_ON) - text.count(BOLD_OFF)
        if opens > 0:
            text += BOLD_OFF
        if not plain(text).strip():
            return False
    doc.paras.append((style, text))
    return True


def headings_toc(doc):
    """A contents list from the headings, for formats without one."""
    levels = {H1: 1, H2: 2}
    doc.toc = [(i, levels[s], plain(t)) for i, (s, t) in enumerate(doc.paras) if s in levels]


# ---- HTML (EPUB chapters, and DOCX through mammoth) ----

class HtmlBlocks(HTMLParser):
    """Collects paragraphs from XHTML. Block elements become paragraphs; <b>/<strong> become
    bold; ruby readings, scripts, styles and images are dropped; ids are remembered so a
    table of contents can point at them."""
    BLOCKS = {"p", "div", "section", "article", "li", "blockquote", "pre", "h1", "h2", "h3", "h4", "h5", "h6",
              "tr", "dd", "dt", "figcaption", "aside", "header", "footer", "nav", "table", "ul", "ol", "body",
              "main", "figure", "center", "dl", "td", "th", "caption", "address"}
    SKIP = {"head", "script", "style", "svg", "math", "rt", "rp", "title", "noscript", "template"}
    HEADINGS = {"h1": H1, "h2": H2, "h3": H3, "h4": H3, "h5": H3, "h6": H3}

    def __init__(self, doc):
        super().__init__(convert_charrefs=True)
        self.doc = doc
        self.buf = []
        self.stack = []        # (tag, style or None)
        self.skip = 0
        self.bold = 0
        self.lists = []        # per open list: next number, or None for bullets
        self.pending_ids = []
        self.anchors = {}      # id -> paragraph index
        self.after_br = False

    def style(self):
        for tag, st in reversed(self.stack):
            if st is not None:
                return st
        return BODY

    def flush(self):
        text = "".join(self.buf)
        self.buf = []
        style = self.style()
        added = False
        if style == PRE:
            for line in text.split("\n"):
                added |= add_para(self.doc, PRE, line)
        else:
            if self.after_br and style == BODY:
                style = LINE_BREAK
            added = add_para(self.doc, style, text)
        if added:
            index = len(self.doc.paras) - 1
            for i in self.pending_ids:
                self.anchors.setdefault(i, index)
            self.pending_ids = []
        self.after_br = False
        if self.bold:  # keep bold going into the next paragraph
            self.buf.append(BOLD_ON)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in self.SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        for key in ("id", "name"):
            if attrs.get(key) and (key == "id" or tag == "a"):
                self.pending_ids.append(attrs[key])
        if tag == "br":
            if plain("".join(self.buf)).strip():
                self.flush()
                self.after_br = True
            return
        if tag == "hr":
            self.flush()
            add_para(self.doc, RULE, "")
            return
        if tag in ("b", "strong"):
            self.bold += 1
            self.buf.append(BOLD_ON)
            return
        if tag in self.BLOCKS:
            self.flush()
            self.after_br = False
            style = None
            if tag in self.HEADINGS:
                style = self.HEADINGS[tag]
            elif tag == "pre":
                style = PRE
            elif tag == "blockquote":
                style = QUOTE
            elif tag in ("ul", "ol"):
                self.lists.append(1 if tag == "ol" else None)
            elif tag == "li":
                style = ITEM
                number = self.lists[-1] if self.lists else None
                if number is None:
                    self.buf.append("• ")
                else:
                    self.buf.append(f"{number}. ")
                    self.lists[-1] += 1
            elif tag == "center" or re.search(r"text-align\s*:\s*center", attrs.get("style", "")):
                style = CENTER
            self.stack.append((tag, style))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in ("br", "hr") and tag not in self.SKIP:
            self.handle_endtag(tag)
        elif tag in self.SKIP:
            self.skip -= 1

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if tag in ("b", "strong") and self.bold:
            self.bold -= 1
            self.buf.append(BOLD_OFF)
            return
        if tag in self.BLOCKS:
            if not any(t == tag for t, _ in self.stack):
                return
            self.flush()
            while self.stack:
                t, _ = self.stack.pop()
                if t == tag:
                    break
            if tag in ("ul", "ol") and self.lists:
                self.lists.pop()

    def handle_data(self, data):
        if not self.skip:
            # A line break between two CJK characters in the source is not a space.
            self.buf.append(data if self.style() == PRE else NEWLINE_IN_CJK.sub("", data).replace("\n", " "))

    def close(self):
        super().close()
        self.flush()


def read_html(doc, html):
    parser = HtmlBlocks(doc)
    parser.feed(html)
    parser.close()
    return parser.anchors


# ---- EPUB ----

def xml_children(el, name):
    return [c for c in el if c.tag.rsplit("}", 1)[-1] == name]


def xml_find(el, name):
    for c in el.iter():
        if c.tag.rsplit("}", 1)[-1] == name:
            yield c


def xml_text(el):
    return "".join(el.itertext()).strip() if el is not None else ""


def read_epub(path, doc):
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())

        def read(name):
            return z.read(name)

        container = ElementTree.fromstring(read("META-INF/container.xml"))
        opf_path = next(xml_find(container, "rootfile")).get("full-path")
        opf_dir = posixpath.dirname(opf_path)
        opf = ElementTree.fromstring(read(opf_path))

        def resolve(base_dir, href):
            return posixpath.normpath(posixpath.join(base_dir, unquote(href.split("#")[0])))

        meta = next(xml_find(opf, "metadata"))
        doc.title = xml_text(next((e for e in meta if e.tag.endswith("}title")), None))
        doc.author = ", ".join(xml_text(e) for e in meta if e.tag.endswith("}creator") and xml_text(e))
        doc.language = xml_text(next((e for e in meta if e.tag.endswith("}language")), None))
        manifest = {}
        for item in xml_find(opf, "item"):
            manifest[item.get("id")] = (resolve(opf_dir, item.get("href", "")), item.get("media-type", ""),
                                        item.get("properties", ""))
        spine = next(xml_find(opf, "spine"))

        # Cover: EPUB 3 cover-image, EPUB 2 <meta name="cover">, else an image named cover.
        cover = next((h for h, mt, props in manifest.values() if "cover-image" in props.split()), None)
        if cover is None:
            cid = next((m.get("content") for m in xml_find(meta, "meta") if m.get("name") == "cover"), None)
            if cid in manifest and manifest[cid][1].startswith("image/"):
                cover = manifest[cid][0]
        if cover is None:
            cover = next((h for h, mt, _ in manifest.values() if mt.startswith("image/") and "cover" in h.lower()), None)
        if cover in names:
            try:
                from PIL import Image
                doc.cover = Image.open(io.BytesIO(read(cover)))
                doc.cover.load()
            except Exception as e:
                doc.notes.append(f"cover not readable: {e}")

        anchors = {}  # (file, id or None) -> paragraph index
        for ref in xml_children(spine, "itemref"):
            href, mt, _ = manifest.get(ref.get("idref"), (None, "", ""))
            if href not in names or "html" not in mt:
                continue
            start = len(doc.paras)
            html = read(href).decode("utf-8", errors="replace")
            file_anchors = read_html(doc, html)
            if len(doc.paras) > start:
                doc.breaks.add(start)
            anchors[(href, None)] = start
            for i, p in file_anchors.items():
                anchors[(href, i)] = p

        def target(base_dir, href):
            file = resolve(base_dir, href)
            frag = unquote(href.split("#", 1)[1]) if "#" in href else None
            return anchors.get((file, frag), anchors.get((file, None)))

        # Contents: EPUB 3 nav document, else the EPUB 2 NCX.
        toc = []
        nav = next((h for h, mt, props in manifest.values() if "nav" in props.split()), None)
        try:
            root = ElementTree.fromstring(read(nav)) if nav in names else None
        except ElementTree.ParseError:
            root = None
        if root is not None:
            navs = [n for n in xml_find(root, "nav")
                    if any(v == "toc" for k, v in n.attrib.items() if k.endswith("type"))] or list(xml_find(root, "nav"))
            if navs:
                def walk(ol, level):
                    for li in xml_children(ol, "li"):
                        a = next((c for c in li if c.tag.rsplit("}", 1)[-1] in ("a", "span")), None)
                        if a is not None and a.get("href"):
                            p = target(posixpath.dirname(nav), a.get("href"))
                            if p is not None:
                                toc.append((p, level, xml_text(a)))
                        for sub in xml_children(li, "ol"):
                            walk(sub, level + 1)
                for ol in xml_children(navs[0], "ol"):
                    walk(ol, 1)
        if not toc:
            ncx = manifest.get(spine.get("toc"), (None,))[0] or next(
                (h for h, mt, _ in manifest.values() if mt == "application/x-dtbncx+xml"), None)
            try:
                root = ElementTree.fromstring(read(ncx)) if ncx in names else None
            except ElementTree.ParseError:
                root = None
            if root is not None:

                def walk_ncx(el, level):
                    for np in xml_children(el, "navPoint"):
                        label = xml_text(next(xml_find(np, "text"), None))
                        content = next(xml_find(np, "content"), None)
                        if content is not None:
                            p = target(posixpath.dirname(ncx), content.get("src", ""))
                            if p is not None:
                                toc.append((p, level, label))
                        walk_ncx(np, level + 1)
                nav_map = next(xml_find(root, "navMap"), None)
                if nav_map is not None:
                    walk_ncx(nav_map, 1)
        doc.toc = toc
    if not doc.toc:
        headings_toc(doc)


# ---- DOCX ----

def read_docx(path, doc):
    import mammoth

    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if "docProps/core.xml" in names:
            core = ElementTree.fromstring(z.read("docProps/core.xml"))
            doc.title = xml_text(next((e for e in core if e.tag.endswith("}title")), None))
            doc.author = xml_text(next((e for e in core if e.tag.endswith("}creator")), None))
        pic = next((n for n in names if n.lower().startswith("docprops/thumbnail.")), None) or next(
            (n for n in sorted(names) if n.startswith("word/media/") and n.lower().endswith(
                (".png", ".jpg", ".jpeg", ".gif", ".bmp"))), None)
        if pic:
            try:
                from PIL import Image
                doc.cover = Image.open(io.BytesIO(z.read(pic)))
                doc.cover.load()
            except Exception:
                doc.cover = None
    with open(path, "rb") as f:
        result = mammoth.convert_to_html(f, convert_image=mammoth.images.img_element(lambda image: {"src": ""}))
    read_html(doc, result.value)
    headings_toc(doc)


# ---- PDF ----

def read_pdf(path, doc):
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(path))
    try:
        meta = pdf.get_metadata_dict()
        doc.title, doc.author = meta.get("Title", "").strip(), meta.get("Author", "").strip()
        pages = []
        for i in range(min(len(pdf), PDF_MAX_PAGES)):
            page = pdf[i]
            tp = page.get_textpage()
            pages.append(tp.get_text_range().replace("\r\n", "\n").replace("\r", "\n"))
            tp.close()
            page.close()
        if len(pdf) > PDF_MAX_PAGES:
            doc.notes.append(f"only the first {PDF_MAX_PAGES} of {len(pdf)} pages")
        try:
            doc.cover = pdf[0].render(scale=1).to_pil()
        except Exception:
            doc.cover = None
        outline = []
        for item in pdf.get_toc():
            if hasattr(item, "get_title"):  # pypdfium2 5
                dest = item.get_dest()
                outline.append((item.level, item.get_title(), dest.get_index() if dest else None))
            else:
                outline.append((item.level, item.title, item.page_index))
    finally:
        pdf.close()

    page_para = reflow_pdf(pages, doc)
    for level, title, page_index in outline:
        if page_index is not None and 0 <= page_index < len(page_para) and title.strip():
            doc.toc.append((page_para[page_index], level + 1, title.strip()))


def text_width(s):
    """Rough width of a line in Latin-character units (CJK counts double)."""
    return len(s) + len(CJK_CHAR.findall(s))


def join_lines(a, b):
    if a.endswith("-") and b[:1].islower():
        return a[:-1] + b
    if CJK_CHAR.match(a[-1:]) or CJK_CHAR.match(b[:1]):
        return a + b
    return a + " " + b


def reflow_pdf(pages, doc):
    """Joins a PDF's lines back into paragraphs. A line ends a paragraph when it is clearly
    shorter than the page's usual line and ends a sentence, before a blank line, or when it
    ends a sentence at the bottom of a page. Page
    numbers and running headers (the same first or last line on many pages) are dropped.
    Returns, for each page, the index of the first paragraph that starts on it or after."""
    split = [[ln.strip() for ln in p.split("\n")] for p in pages]
    edges = {}
    for lines in split:
        text_lines = [ln for ln in lines if ln]
        for ln in text_lines[:1] + text_lines[-1:]:
            key = re.sub(r"\d+", "#", ln)
            edges[key] = edges.get(key, 0) + 1
    repeated = {k for k, n in edges.items() if n >= max(3, len(pages) // 2)}

    page_para, para = [], ""
    for lines in split:
        page_para.append(len(doc.paras) + (1 if para else 0))
        widths = sorted(text_width(ln) for ln in lines if ln)
        usual = widths[int(len(widths) * 0.8)] if widths else 0
        last = max((k for k, ln in enumerate(lines) if ln), default=-1)
        for k, ln in enumerate(lines):
            if not ln or re.fullmatch(r"[-–— ]*\d+[-–— ]*", ln) or re.sub(r"\d+", "#", ln) in repeated:
                if not ln and para:
                    add_para(doc, BODY, para)
                    para = ""
                continue
            para = join_lines(para, ln) if para else ln
            if (text_width(ln) < usual * 0.8 or k == last) and re.search(r"[.。!！?？:：”」』\")）]$", ln):
                add_para(doc, BODY, para)
                para = ""
    if para:
        add_para(doc, BODY, para)
    return [min(p, max(len(doc.paras) - 1, 0)) for p in page_para]


# ---- Plain text and Markdown ----

def decode_text(data, doc):
    for bom, enc in ((b"\xef\xbb\xbf", "utf-8"), (b"\xff\xfe", "utf-16-le"), (b"\xfe\xff", "utf-16-be")):
        if data.startswith(bom):
            return data[len(bom):].decode(enc, errors="replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    from charset_normalizer import from_bytes

    best = from_bytes(data).best()
    if best is None:
        doc.notes.append("encoding not recognised, read as UTF-8 with errors replaced")
        return data.decode("utf-8", errors="replace")
    doc.notes.append(f"not UTF-8, read as {best.encoding}")
    return str(best)


NUM = "0-9０-９零〇一二三四五六七八九十百千万两"
WORD_NUM = (r"([0-9]+|[ivxlcdm]+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|"
            r"fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|(twenty|thirty|forty|fifty)[\w-]*)")
VOLUME_LINE = re.compile(rf"^(第[{NUM}]+[卷部篇集]|卷[{NUM}]+|(part|book|volume)\s+{WORD_NUM}\b)", re.I)
CHAPTER_LINE = re.compile(rf"^(第[{NUM}]+[章节回话話幕]|chapter\s+{WORD_NUM}\b)", re.I)
NAMED_LINE = re.compile(r"^(序章|序言|序|楔子|引子|前言|后记|後記|尾声|番外|终章|終章|プロローグ|エピローグ|あとがき|"
                        r"prologue|epilogue|interlude|preface|introduction|afterword)(\s|$|[:：])", re.I)
AFTER_MARKER = re.compile(r"(\s|$|[:：、.．·])")


def heading_kind(line):
    """'volume', 'chapter' or None for one line of a text file. A heading is short; after a
    numbered marker (第七章, Chapter 7) comes the end, a space or a colon, unless the whole
    line is short (第七章灯塔). Named ones (序章, Prologue) must stand alone or before a space."""
    if len(line) > 40:
        return None
    for kind, pattern in (("volume", VOLUME_LINE), ("chapter", CHAPTER_LINE)):
        m = pattern.match(line)
        if m and (len(line) <= 20 or AFTER_MARKER.match(line, m.end())):
            return kind
    return "chapter" if NAMED_LINE.match(line) else None


def hard_wrapped(lines):
    """True for text wrapped at a fixed width with blank lines between paragraphs (Project
    Gutenberg style), where the lines of a paragraph must be joined again: no line is much
    longer than about 100 characters, many lines are close to that width, and lines often
    follow each other without a blank line."""
    filled = [ln.rstrip() for ln in lines if ln.strip()]
    if len(filled) < 8 or len(filled) == len(lines):
        return False
    widths = sorted(text_width(ln) for ln in filled)
    longest = widths[int(len(widths) * 0.95)]
    near = sum(1 for w in widths if w >= 0.8 * longest) / len(widths)
    followed = sum(1 for a, b in zip(lines, lines[1:]) if a.strip() and b.strip()) / len(filled)
    return 40 <= longest <= 110 and near >= 0.4 and followed > 0.3


def read_txt(text, doc):
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    for k, ln in enumerate(lines[:20]):  # "作者：…" / "书名：…" near the top, common in Chinese text files
        m = re.match(r"^(作者|著者|author|书名|書名|title)\s*[:：]\s*(.+)$", ln.strip(" \t\u3000"), re.I)
        if m:
            if m.group(1).lower() in ("作者", "著者", "author"):
                doc.author = doc.author or m.group(2).strip()
            else:
                doc.title = doc.title or m.group(2).strip().strip("《》")
            lines[k] = ""
    joined = hard_wrapped(lines)
    has_volumes = any(heading_kind(ln.strip(" \t\u3000")) == "volume" for ln in lines)
    para = ""

    def end_para():
        nonlocal para
        if para:
            add_para(doc, BODY, para)
            para = ""

    for ln in lines:
        s = ln.strip(" \t　")
        if not s:
            end_para()
            continue
        kind = heading_kind(s)
        if kind:
            end_para()
            level = 1 if kind == "volume" or not has_volumes else 2
            if add_para(doc, H1 if level == 1 else H2, s):
                doc.toc.append((len(doc.paras) - 1, level, plain(doc.paras[-1][1])))
            continue
        if re.fullmatch(r"([*＊·•~～=\-—_] ?){3,}", s):
            end_para()
            add_para(doc, CENTER, s)
            continue
        if joined:
            para = join_lines(para, s) if para else s
        else:
            add_para(doc, BODY, s)
    end_para()


def md_inline(text):
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)            # images
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)         # links -> their text
    text = re.sub(r"<[^>]+>", "", text)                          # inline HTML
    text = re.sub(r"`([^`]*)`", r"\1", text)                     # code
    text = re.sub(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1", BOLD_ON + r"\2" + BOLD_OFF, text)
    text = re.sub(r"(?<![\w*])([*_])(?=\S)(.+?)(?<=\S)\1(?![\w*])", r"\2", text)
    return re.sub(r"\\([\\`*_{}\[\]()#+\-.!>])", r"\1", text)


def read_markdown(text, doc):
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and lines[0].strip() == "---":  # front matter
        for k in range(1, min(len(lines), 50)):
            if lines[k].strip() == "---":
                for ln in lines[1:k]:
                    key, _, value = ln.partition(":")
                    value = value.strip().strip("\"'")
                    if key.strip().lower() == "title":
                        doc.title = value
                    elif key.strip().lower() in ("author", "authors"):
                        doc.author = value
                lines = lines[k + 1:]
                break
    para, style, fence = "", BODY, None

    def end_para():
        nonlocal para, style
        if para:
            add_para(doc, style, md_inline(para))
        para, style = "", BODY

    for ln in lines:
        if fence is not None:
            if ln.strip().startswith(fence):
                fence = None
            else:
                add_para(doc, PRE, ln)
            continue
        s = ln.strip()
        m = re.match(r"^(```+|~~~+)", s)
        if m:
            end_para()
            fence = m.group(1)
            continue
        if not s:
            end_para()
            continue
        m = re.match(r"^(#{1,6})\s+(.*?)\s*#*$", s)
        if m:
            end_para()
            add_para(doc, (H1, H2, H3)[min(len(m.group(1)), 3) - 1], md_inline(m.group(2)))
            if not doc.title and len(m.group(1)) == 1:
                doc.title = plain(doc.paras[-1][1])
            continue
        if para and style == BODY and re.fullmatch(r"=+|-+", s):  # underlined heading
            text, para = para, ""
            add_para(doc, H1 if s[0] == "=" else H2, md_inline(text))
            if not doc.title and s[0] == "=":
                doc.title = plain(doc.paras[-1][1])
            continue
        if re.fullmatch(r"([-*_] *){3,}", s):
            end_para()
            add_para(doc, RULE, "")
            continue
        m = re.match(r"^([-*+]|\d+[.)])\s+(.*)$", s)
        if m:
            end_para()
            bullet = "• " if m.group(1) in "-*+" else m.group(1).rstrip(")") .rstrip(".") + ". "
            para, style = bullet + m.group(2), ITEM
            continue
        if s.startswith(">"):
            s = s.lstrip("> ")
            if style != QUOTE:
                end_para()
                style = QUOTE
        hard_break = ln.endswith("  ") or ln.endswith("\\")
        para = join_lines(para, s.rstrip("\\")) if para else s.rstrip("\\")
        if hard_break:
            st = style
            end_para()
            style = st if st != BODY else LINE_BREAK
    end_para()
    headings_toc(doc)


# ---- Encoding a book ----

def split_long(style, text):
    """Splits a paragraph longer than PARA_MAX bytes at sentence ends (else at a space, else
    anywhere); the pieces after the first continue it on a new line."""
    pieces = []
    while len(text.encode("utf-8")) > PARA_MAX:
        limit = len(text.encode("utf-8")[:PARA_MAX - 8].decode("utf-8", errors="ignore"))
        cut = 0
        for m in SENTENCE_END.finditer(text, limit // 2, limit):
            cut = m.end()
        if not cut:
            cut = text.rfind(" ", limit // 2, limit) + 1 or limit
        head, text = text[:cut], text[cut:].lstrip(" ")
        if head.count(BOLD_ON) > head.count(BOLD_OFF):
            head += BOLD_OFF
            text = BOLD_ON + text
        pieces.append((style, head))
        style = LINE_BREAK if style in (BODY, LINE_BREAK) else style
    pieces.append((style, text))
    return pieces


def encode_text(doc):
    """Text bytes, and the byte offset of each paragraph."""
    out, offsets, owner = bytearray(), [], []
    for index, (style, text) in enumerate(doc.paras):
        for piece_style, piece in split_long(style, text):
            offsets.append(len(out))
            owner.append(index)
            if piece_style:
                out.append(piece_style)
            out += piece.encode("utf-8") + b"\n"
    return bytes(out), offsets, owner


def encode_book(doc, fmt):
    text, offsets, owner = encode_text(doc)
    first_piece = {}
    for k, idx in enumerate(owner):
        first_piece.setdefault(idx, k)
    toc = []
    for para, level, title in doc.toc:
        if para in first_piece:
            toc.append((offsets[first_piece[para]], max(1, min(level, 255)), clean_inline(plain(title))[:200]))
    toc.sort(key=lambda e: e[0])
    starts = {0} | {pos for pos, _, _ in toc} | {offsets[first_piece[p]] for p in doc.breaks if p in first_piece}
    sections, cur = [], None
    for k, pos in enumerate(offsets):
        end = offsets[k + 1] if k + 1 < len(offsets) else len(text)
        if cur is None or pos in starts or end - cur > SECTION_MAX:
            sections.append(pos)
            cur = pos

    strings = Strings()
    title, author, language = strings.add(doc.title), strings.add(doc.author), strings.add(doc.language)
    sec_toc = b"".join(TOC_ENTRY.pack(pos, strings.add(t), level) for pos, level, t in toc)
    sec_sections = struct.pack(f"<{len(sections)}I", *sections)
    sample = text[:200000].decode("utf-8", errors="ignore")
    flags = FLAG_CJK if len(CJK_CHAR.findall(sample)) > 0.3 * len(sample) else 0

    body = bytearray()
    at = {}
    for name, sec in (("sections", sec_sections), ("toc", sec_toc), ("strings", strings.data), ("text", text)):
        at[name] = BOOK_HEADER.size + len(body)
        body += sec
    header = BOOK_HEADER.pack(MAGIC_BOOK, VERSION, BOOK_HEADER.size, BOOK_HEADER.size + len(body), zlib.crc32(body),
                              at["text"], len(text), at["sections"], len(sections), at["toc"], len(toc),
                              at["strings"], len(strings.data), title, author, language, fmt, flags, 0)
    return header + body


def read_book(data):
    """Parses a .dbk the way the player does. Returns a dict."""
    if len(data) < BOOK_HEADER.size:
        raise ValueError("file too small")
    (magic, version, hsize, fsize, crc, text_at, text_size, sec_at, sec_n, toc_at, toc_n, str_at, str_size,
     title, author, language, fmt, flags, _) = BOOK_HEADER.unpack_from(data)
    if magic != MAGIC_BOOK or version != VERSION:
        raise ValueError(f"not a version {VERSION} book")
    if fsize != len(data):
        raise ValueError(f"size is {len(data)}, header says {fsize}")
    if zlib.crc32(data[hsize:]) != crc:
        raise ValueError("checksum mismatch")
    s = lambda off: read_string(data, str_at + off)  # noqa: E731
    sections = list(struct.unpack_from(f"<{sec_n}I", data, sec_at))
    toc = [TOC_ENTRY.unpack_from(data, toc_at + i * TOC_ENTRY.size) for i in range(toc_n)]
    return dict(title=s(title), author=s(author), language=s(language), format=fmt, flags=flags,
                text=data[text_at:text_at + text_size], sections=sections,
                toc=[(pos, level, s(t)) for pos, t, level in toc])


# ---- Covers ----

def lettering_cover(title, author, face):
    """A cover for books without one: the title and author, black on white, in a frame."""
    from PIL import Image, ImageDraw

    w, h = COVER_SIZE
    img = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(img)
    d.fontmode = "1"
    d.rectangle([0, 0, w - 1, h - 1], outline=0)
    d.rectangle([3, 3, w - 4, h - 4], outline=0)
    lines = []
    for size in (16, 14, 13, 12, 11):
        f = face(size, True)
        lines = wrap_title(d, title, f, w - 14)
        if len(lines) <= 4:
            break
    lines = lines[:4]
    y = 12
    for ln in lines:
        d.text(((w - d.textlength(ln, font=f)) / 2, y), ln, font=f, fill=0)
        y += f.size + 3
    d.line([(w / 2 - 8, y + 4), (w / 2 + 8, y + 4)], fill=0)
    if author:
        af = face(10, False)
        a = author
        while a and d.textlength(a, font=af) > w - 12:
            a = a[:-1]
        d.text(((w - d.textlength(a, font=af)) / 2, h - 20), a, font=af, fill=0)
    return img


def wrap_title(d, text, f, width):
    lines, line = [], ""
    for tok in re.findall(rf"[{CJK_RANGES}]|[^\s{CJK_RANGES}]+\s*|\s+", text):
        if line and d.textlength((line + tok).rstrip(), font=f) > width:
            lines.append(line.rstrip())
            line = tok.lstrip()
        else:
            line += tok
    if line.strip():
        lines.append(line.rstrip())
    return lines


# ---- The shelf on the card ----

@dataclass
class Entry:
    source: str
    file: Path
    size: int
    mtime: int
    id: int = 0
    title: str = ""
    author: str = ""
    fmt: int = 0
    flags: int = 0
    text_size: int = 0
    toc_count: int = 0


def convert(file, fmt, face, notes):
    """(Doc, .dbk bytes, .g4 cover bytes, own cover?) for one book file."""
    doc = Doc()
    if fmt == EPUB:
        read_epub(file, doc)
    elif fmt == DOCX:
        read_docx(file, doc)
    elif fmt == PDF:
        read_pdf(file, doc)
    else:
        text = decode_text(file.read_bytes(), doc)
        (read_markdown if fmt == MARKDOWN else read_txt)(text, doc)
    if not doc.title:
        doc.title = file.stem
    doc.title, doc.author = clean_inline(doc.title), clean_inline(doc.author)
    notes.extend(doc.notes)
    data = encode_book(doc, fmt)
    own = False
    cover = None
    if doc.cover is not None:
        try:
            cover, _ = cover_art.convert(doc.cover, COVER_SIZE)
            own = True
        except Exception as e:
            notes.append(f"cover not usable: {e}")
    if cover is None:
        img = lettering_cover(doc.title, doc.author, face)
        cover = cover_art.encode([0 if v < 128 else 3 for v in img.tobytes()], *COVER_SIZE)
    return doc, data, cover, own


def read_shelf(data):
    if len(data) < SHELF_HEADER.size:
        raise ValueError("file too small")
    (magic, version, hsize, fsize, crc, count, books_at, by_author_at, str_at, str_size, rec_size, _, built,
     converter) = SHELF_HEADER.unpack_from(data)
    if magic != MAGIC_SHELF or version != VERSION:
        raise ValueError(f"not a version {VERSION} shelf index")
    if fsize != len(data) or zlib.crc32(data[hsize:]) != crc:
        raise ValueError("damaged or cut short")
    books = []
    for i in range(count):
        (bid, title, author, source, size, mtime, text_size, fmt, flags, toc_count) = SHELF_BOOK.unpack_from(
            data, books_at + i * rec_size)
        books.append(dict(id=bid, title=read_string(data, str_at + title), author=read_string(data, str_at + author),
                          source=read_string(data, str_at + source), size=size, mtime=mtime, text_size=text_size,
                          format=fmt, flags=flags, toc_count=toc_count))
    by_author = list(struct.unpack_from(f"<{count}I", data, by_author_at))
    return dict(books=books, by_author=by_author, built=built, converter=converter)


def encode_shelf(entries, built):
    entries = sorted(entries, key=lambda e: (sort_key(e.title), sort_key(e.author), e.source))
    strings = Strings()
    recs = b"".join(SHELF_BOOK.pack(e.id, strings.add(e.title), strings.add(e.author), strings.add(e.source),
                                    min(e.size, 0xFFFFFFFF), e.mtime, e.text_size, e.fmt, e.flags,
                                    min(e.toc_count, 0xFFFF)) for e in entries)
    order = sorted(range(len(entries)), key=lambda i: (sort_key(entries[i].author), sort_key(entries[i].title), i))
    by_author = struct.pack(f"<{len(order)}I", *order)
    body = bytearray()
    at = []
    for sec in (recs, by_author, strings.data):
        at.append(SHELF_HEADER.size + len(body))
        body += sec
    header = SHELF_HEADER.pack(MAGIC_SHELF, VERSION, SHELF_HEADER.size, SHELF_HEADER.size + len(body),
                               zlib.crc32(body), len(entries), at[0], at[1], at[2], len(strings.data),
                               SHELF_BOOK.size, 0, built, CONVERTER)
    return header + body


def scan_books(root):
    found, other = [], {}
    base = root / BOOKS_DIR
    if not base.is_dir():
        return found, other
    for file in sorted(base.rglob("*")):
        rel = file.relative_to(root).parts
        if any(skipped_name(p) for p in rel) or not file.is_file():
            continue
        ext = file.suffix.lower()
        if ext in FORMATS:
            found.append(file)
        elif ext in OTHER_BOOKS:
            other[ext] = other.get(ext, 0) + 1
    return found, other


def book_id(source, used):
    """CRC-32 of the book's path on the card; a clash gets the path with '#n' added."""
    n, key = 0, source
    while True:
        bid = zlib.crc32(key.encode("utf-8"))
        if bid not in used:
            used.add(bid)
            return bid
        n += 1
        key = f"{source}#{n}"


def build(root, face, warnings, force=False):
    """Converts /Books on the card. Returns (entries, text characters, title characters) so
    the fonts can be made with exactly the characters needed."""
    root = root.resolve()
    files, other = scan_books(root)
    out_dir = root / INDEX_DIR / BOOK_DIR
    shelf_path = root / INDEX_DIR / SHELF_FILE
    old = {}
    if shelf_path.exists() and not force:
        try:
            shelf = read_shelf(shelf_path.read_bytes())
            if shelf["converter"] == CONVERTER:
                old = {b["source"]: b for b in shelf["books"]}
        except ValueError:
            old = {}
    used, entries, text_chars, title_chars = set(), [], set(), set()
    converted = reused = 0
    for n, file in enumerate(files, 1):
        source = card_path(file, root)
        st = file.stat()
        e = Entry(source=source, file=file, size=st.st_size, mtime=int(st.st_mtime), fmt=FORMATS[file.suffix.lower()])
        prev = old.get(source)
        dbk = None
        if prev and prev["size"] == e.size and prev["mtime"] == e.mtime and prev["id"] not in used:
            path = out_dir / f"{prev['id']:08x}.dbk"
            if path.exists() and (out_dir / f"{prev['id']:08x}.g4").exists():
                try:
                    book = read_book(path.read_bytes())
                    used.add(prev["id"])
                    e.id, dbk = prev["id"], book
                    reused += 1
                except ValueError:
                    dbk = None
        if dbk is None:
            if n % 10 == 0 or file.suffix.lower() == ".pdf":
                print(f"  converting {n}/{len(files)}: {file.name}", file=sys.stderr)
            notes = []
            try:
                doc, data, cover, own = convert(file, e.fmt, face, notes)
            except Exception as ex:
                warnings.append(f"skipped, can't read it ({type(ex).__name__}: {ex}): {source}")
                continue
            for note in notes:
                warnings.append(f"{source}: {note}")
            book = read_book(data)
            if not book["text"].strip():
                warnings.append(f"skipped, no text in it{' (a scanned PDF?)' if e.fmt == PDF else ''}: {source}")
                continue
            e.id = book_id(source, used)
            write_atomic(out_dir / f"{e.id:08x}.dbk", data)
            write_atomic(out_dir / f"{e.id:08x}.g4", cover)
            e.flags = SHELF_FLAG_OWN_COVER if own else 0
            dbk = book
            converted += 1
        else:
            e.flags = prev["flags"]
        e.title, e.author, e.text_size, e.toc_count = dbk["title"], dbk["author"], len(dbk["text"]), len(dbk["toc"])
        text_chars.update(dbk["text"].decode("utf-8"))
        for s in [e.title, e.author] + [t for _, _, t in dbk["toc"]]:
            title_chars.update(s)
        entries.append(e)

    keep = {f"{e.id:08x}" for e in entries}
    if out_dir.is_dir():
        for p in out_dir.iterdir():
            if p.suffix in (".dbk", ".g4") and p.stem not in keep:
                p.unlink()
    built = int(os.environ.get("SOURCE_DATE_EPOCH", time.time()))
    data = encode_shelf(entries, built)
    read_shelf(data)  # self-check
    write_atomic(shelf_path, data)
    size = sum(e.text_size for e in entries)
    print(f"{shelf_path}: {len(entries)} books ({converted} converted, {reused} unchanged), "
          f"{size / 1e6:.1f} MB of text")
    if other:
        print("Not converted (the reader can't open these): "
              + ", ".join(f"{n} {ext}" for ext, n in sorted(other.items())))
    text_chars.discard("\n")
    return entries, text_chars, title_chars


# ---- Dumping ----

def show_text(text, limit=None):
    out = []
    for raw in text.split(b"\n")[:-1][:limit]:
        style = raw[0] if raw and raw[0] in STYLE_NAMES else BODY
        line = raw[1:] if style else raw
        line = line.decode("utf-8").replace(BOLD_ON, "**").replace(BOLD_OFF, "**")
        out.append(f"{STYLE_NAMES[style]:>6} | {line}")
    return "\n".join(out)


def dump(path, full_text=False):
    data = Path(path).read_bytes()
    if data[:4] == MAGIC_SHELF:
        shelf = read_shelf(data)
        built = time.strftime("%Y-%m-%d %H:%M", time.localtime(shelf["built"]))
        print(f"{path}: {len(shelf['books'])} books, built {built}")
        for b in shelf["books"]:
            print(f"  {b['id']:08x}  {FORMAT_NAMES.get(b['format'], '?'):>4}  {b['title']} — {b['author'] or '?'}  "
                  f"{b['text_size']:,} bytes, {b['toc_count']} chapters{'' if b['flags'] & 1 else ', lettered cover'}"
                  f"  {b['source']}")
        print("  by author: " + " | ".join(shelf["books"][i]["author"] or "?" for i in shelf["by_author"]))
        return
    b = read_book(data)
    print(f"{path}: {b['title']} — {b['author'] or '?'} [{b['language'] or '?'}], "
          f"{FORMAT_NAMES.get(b['format'], '?')}, {len(b['text']):,} bytes of text, {len(b['sections'])} sections, "
          f"{'CJK' if b['flags'] & FLAG_CJK else 'Latin'}")
    sizes = [e - s for s, e in zip(b["sections"], b["sections"][1:] + [len(b["text"])])]
    print(f"  sections: largest {max(sizes):,} bytes, starts {b['sections'][:12]}{' …' if len(sizes) > 12 else ''}")
    print("  contents:")
    for pos, level, title in b["toc"]:
        print(f"    {'  ' * (level - 1)}{title}  @{pos}")
    print(show_text(b["text"], None if full_text else 40))


def default_face():
    import fonts

    return fonts.pil_face(fonts.DEFAULT_UI, fonts.DEFAULT_UI_BOLD)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", type=Path, nargs="?", help="the card (its Books folder is converted)")
    ap.add_argument("--convert", type=Path, metavar="BOOK", help="convert one file to a .dbk next to it (or -o)")
    ap.add_argument("-o", "--output", type=Path)
    ap.add_argument("--dump", type=Path, metavar="FILE", help="print a .dbk book or the books.idx shelf")
    ap.add_argument("--text", action="store_true", help="with --dump: the whole text, not the start")
    ap.add_argument("--force", action="store_true", help="convert every book again")
    args = ap.parse_args()
    if args.dump:
        dump(args.dump, args.text)
    elif args.convert:
        notes = []
        fmt = FORMATS.get(args.convert.suffix.lower())
        if not fmt:
            sys.exit(f"{args.convert}: not a format the reader takes ({', '.join(FORMATS)})")
        _, data, cover, own = convert(args.convert, fmt, default_face(), notes)
        out = args.output or args.convert.with_suffix(".dbk")
        out.write_bytes(data)
        out.with_suffix(".g4").write_bytes(cover)
        print(f"{out}: {len(data):,} bytes; cover {out.with_suffix('.g4')} ({'its own' if own else 'lettered'})")
        for n in notes:
            print("note: " + n)
    elif args.folder:
        warnings = []
        build(args.folder, default_face(), warnings, args.force)
        for w in warnings:
            print("warning: " + w)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
