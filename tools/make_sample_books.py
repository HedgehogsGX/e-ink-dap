#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["pillow>=10.0"]
# ///
"""Makes a small made-up book collection in every format the reader takes, to try the
tools and the reader without real books:

    uv run tools/make_sample_books.py              -> sample_books.nosync/Books/...
    uv run tools/make_sample_books.py --long       also a 450 KB novel, for timing page layout

All titles, names and text are invented. EPUB, DOCX and PDF files are written by hand
(they are zip and text formats), so nothing but Pillow is needed.
"""
import argparse
import io
import random
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "sample_books.nosync" / "Books"

FOG_HARBOR = [  # (chapter title, paragraphs) of 雾港来信
    ("序", ["这是一本关于等待的书。写下它的时候，港口的雾还没有散。"]),
    ("第一章 无名信", [
        "雾是从海上来的。每到傍晚，港口的灯就一盏一盏亮起来，像有人在水面上写字，写一行，又被浪抹掉一行。",
        "阿禾站在码头的尽头，手里攥着那封没有署名的信。信纸很薄，边角已经被海风吹得发软，上面只有一句话：“灯塔还亮着吗？”",
        "她想起小时候，祖父总说，灯塔不是为了照亮海，而是为了让回家的人知道，岸还在那里。",
        "邮局的老陈说，这封信没有邮戳，也没有寄信地址，是夹在一捆旧报纸里送来的。他把信递给她的时候，特意看了她一眼，"
        "好像在等她说出寄信人的名字。",
    ]),
    ("第二章 潮汐表", [
        "祖父留下的东西不多：一只铜壳怀表，一本翻烂了的潮汐表，还有一摞用麻绳捆着的值班日志。",
        "潮汐表的页边写满了铅笔字。有的是天气，有的是船名，还有一些只是数字，像是某种只有他自己看得懂的记号。",
        "“<b>涨潮的时候别去礁石那边</b>。”这句话他写了三遍，每一遍的字都比上一遍更用力。",
    ]),
    ("第三章 旧码头", [
        "旧码头早就不用了。木桩一根根歪着，像一排站累了的人。",
        "她在桩子之间找到一块松动的木板，<br/>木板下面压着一只铁皮盒子，<br/>盒子上刻着两个字：守夜。",
        "盒子里只有一张照片。照片上的灯塔还很新，塔下站着一个年轻人，手里举着一盏马灯，冲着镜头笑。",
    ]),
]

LEDGER = [  # The Lighthouse Ledger
    ("Chapter 1: The Keeper's Book", [
        "Every entry in the ledger began the same way: the date, the wind, and the state of the lamp. "
        "Elsie had read them so often that she could recite whole winters by heart.",
        "Calm, north-east, lamp trimmed. Gale, south, glass cracked and replaced before midnight. Her grandfather's "
        "handwriting leaned forward, as if it were walking into weather.",
        "<blockquote>Fog from four until dawn. Rang the bell every two minutes. No ships.</blockquote>",
    ]),
    ("Chapter 2: Oil and Glass", [
        "The lamp room smelled of paraffin and old brass. On the shelf by the door stood the things a keeper needed: "
        "<ul><li>a tin of wick scissors,</li><li>a soft cloth for the lens,</li><li>and a <b>spare</b> chimney, "
        "wrapped in newspaper from a year nobody remembered.</li></ul>",
        "She polished the lens the way he had shown her, in slow circles, never against the grain of the prisms.",
    ]),
    ("Chapter 3: The Third Ledger", [
        "There should have been two ledgers. There were three. The third had no dates at all, only names of boats, "
        "and beside each name a small drawn star.",
    ]),
]

MOUNTAINS = [  # 山海旧事, as a GB18030 text file with volumes and chapters
    ("第一卷 山", None),
    ("第一章 采药人", ["山里的雾比海边的还要重，早上推开门，院子里的石磨都看不清。",
                     "采药的周老汉说，雾天不上山，上了山也找不到路，找到了路也找不到药。"]),
    ("第二章 石阶", ["石阶一共九百级，没有人真的数过，可每个人都这么说。"]),
    ("第二卷 海", None),
    ("第三章 渡口", ["渡口的船夫只认得一种钱，就是用旧了的铜板。新钱他不收，说新钱没有分量。"]),
]

MONDAY = [  # 月曜日の図書室, as a Shift-JIS text file
    ("第一話 返却ポスト", ["月曜日の朝、返却ポストには一冊だけ本が入っていた。貸出カードには、誰の名前も書かれていない。",
                       "司書の真鍋さんは、その本をしばらく手のひらにのせたまま、窓の外の雨を見ていた。"]),
    ("第二話 しおり", ["本の間に、押し花のしおりが挟まっていた。すみれの色は、もうほとんど残っていない。"]),
]

MOSS_MD = """---
title: Field Notes on Moss
author: R. Ellery
---

# Field Notes on Moss

Moss grows where nothing else bothers to: on north walls, on old roofs, between the
stones of a path nobody walks any more.

## Where to look

- Shaded stone, especially *limestone*
- Fallen logs, after the bark has gone
- The **north side** of almost anything

> Look down before you look around. The best patches are under your boots.

## Keeping notes

Write the date, the place and the weather. Then draw what you see, even badly.

```
date: 3 March
place: churchyard wall, north side
note: cushion moss, bright after rain
```

---

That is all there is to it.
"""

TIDES_TXT = """THE TIDE TABLES

CHAPTER I.

The harbour master kept the tide tables in a drawer that did not quite close, and
every spring he would take out the old ones and read them aloud to whoever was in
the office, as if the numbers might have changed while nobody was looking.

Nobody minded. The office was warm, and the numbers had a rhythm to them, like a
song with only one verse that you could sing for the rest of your life.

CHAPTER II.

In April a stranger came asking for last year's tables. The harbour master looked
at him for a long time before he opened the drawer.

"What do you want with old tides?" he asked.

"I want to know when the water was lowest," said the stranger, "on the night my
brother's boat came in."
"""


def cover_image(title):
    img = Image.new("RGB", (600, 800), (40, 70, 90))
    d = ImageDraw.Draw(img)
    for y in range(800):
        d.line([(0, y), (600, y)], fill=(40 + y // 8, 70 + y // 10, 90 + y // 12))
    d.polygon([(380, 650), (400, 300), (440, 300), (460, 650)], fill=(235, 235, 225))
    d.rectangle([395, 270, 445, 300], fill=(255, 230, 150))
    d.polygon([(445, 285), (600, 200), (600, 380)], fill=(250, 240, 200))
    d.rectangle([0, 650, 600, 800], fill=(20, 40, 55))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def xhtml(title, body, lang):
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="{lang}">
<head><title>{title}</title><style>p {{ text-indent: 2em; }}</style></head>
<body>{body}</body></html>
"""


def write_epub(path, title, author, lang, chapters, epub3=True, cover=None):
    """chapters: (title, paragraphs as HTML). EPUB 3 with a nav document, or EPUB 2 with an NCX."""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip")  # stored, first
        z.writestr("META-INF/container.xml", """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>""")
        items, spine, nav_items, ncx_points = [], [], [], []
        for i, (ch_title, paras) in enumerate(chapters):
            name = f"text/ch{i:02d}.xhtml"
            body = f'<h2 id="c{i}">{ch_title}</h2>\n' + "\n".join(
                p if p.startswith("<") else f"<p>{p}</p>" for p in paras)
            if i == 1 and epub3:  # a section inside a chapter, for a nested contents entry
                body += f'\n<h3 id="c{i}s">{"信封" if lang == "zh" else "The Envelope"}</h3>\n<p>{paras[-1]}</p>'
            z.writestr(f"OEBPS/{name}", xhtml(ch_title, body, lang))
            items.append(f'<item id="ch{i}" href="{name}" media-type="application/xhtml+xml"/>')
            spine.append(f'<itemref idref="ch{i}"/>')
            sub = (f'<ol><li><a href="{name}#c{i}s">{"信封" if lang == "zh" else "The Envelope"}</a></li></ol>'
                   if i == 1 and epub3 else "")
            nav_items.append(f'<li><a href="{name}#c{i}">{ch_title}</a>{sub}</li>')
            ncx_points.append(f'<navPoint id="n{i}" playOrder="{i + 1}"><navLabel><text>{ch_title}</text></navLabel>'
                              f'<content src="{name}"/></navPoint>')
        meta_cover = ""
        if cover:
            z.writestr("OEBPS/images/cover.jpg", cover)
            items.append('<item id="cover" href="images/cover.jpg" media-type="image/jpeg"'
                         + (' properties="cover-image"/>' if epub3 else "/>"))
            meta_cover = '<meta name="cover" content="cover"/>'
        if epub3:
            z.writestr("OEBPS/nav.xhtml", xhtml("Contents", f'<nav epub:type="toc"><ol>{"".join(nav_items)}</ol></nav>',
                                                lang))
            items.append('<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>')
        else:
            z.writestr("OEBPS/toc.ncx", f"""<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1"><head/><docTitle><text>{title}</text></docTitle>
<navMap>{"".join(ncx_points)}</navMap></ncx>""")
            items.append('<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>')
        z.writestr("OEBPS/content.opf", f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="{'3.0' if epub3 else '2.0'}" unique-identifier="id">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:identifier id="id">sample-{abs(hash(title)) % 10000}</dc:identifier><dc:title>{title}</dc:title>
<dc:creator>{author}</dc:creator><dc:language>{lang}</dc:language>{meta_cover}</metadata>
<manifest>{"".join(items)}</manifest>
<spine{'' if epub3 else ' toc="ncx"'}>{"".join(spine)}</spine></package>""")


def write_docx(path, title, author, blocks):
    """blocks: (style or None, text); **x** in text is bold. Minimal WordprocessingML."""
    def run(text):
        out = []
        for k, part in enumerate(text.split("**")):
            if part:
                bold = "<w:rPr><w:b/></w:rPr>" if k % 2 else ""
                out.append(f'<w:r>{bold}<w:t xml:space="preserve">{part}</w:t></w:r>')
        return "".join(out)

    def props(style):
        return f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""

    paras = "".join(f"<w:p>{props(s)}{run(t)}</w:p>" for s, t in blocks)
    W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    styles = "".join(f'<w:style w:type="paragraph" w:styleId="{sid}"><w:name w:val="{name}"/></w:style>'
                     for sid, name in (("Heading1", "heading 1"), ("Heading2", "heading 2")))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
</Types>""")
        z.writestr("_rels/.rels", """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
<Relationship Id="r2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
</Relationships>""")
        z.writestr("word/_rels/document.xml.rels", """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="s1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>""")
        z.writestr("word/styles.xml", f'<?xml version="1.0" encoding="UTF-8"?><w:styles {W}>{styles}</w:styles>')
        z.writestr("word/document.xml", f'<?xml version="1.0" encoding="UTF-8"?><w:document {W}><w:body>{paras}'
                                        '</w:body></w:document>')
        z.writestr("docProps/core.xml", f"""<?xml version="1.0" encoding="UTF-8"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
 xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>{title}</dc:title><dc:creator>{author}</dc:creator>
</cp:coreProperties>""")


def write_pdf(path, title, pages, outline):
    """A text PDF in Helvetica. pages: lists of lines; outline: (title, page index)."""
    objs = []

    def obj(body):
        objs.append(body)
        return len(objs)

    def esc(s):
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    font = obj("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    pages_id = len(objs) + 1 + 2 * len(pages)  # pages tree comes after the page and content objects
    page_ids = []
    for lines in pages:
        stream = "BT /F1 11 Tf 14 TL 72 760 Td " + " ".join(f"({esc(ln)}) '" for ln in lines) + " ET"
        content = obj(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
        page_ids.append(obj(f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 612 792] "
                            f"/Resources << /Font << /F1 {font} 0 R >> >> /Contents {content} 0 R >>"))
    assert obj(f"<< /Type /Pages /Kids [{' '.join(f'{p} 0 R' for p in page_ids)}] /Count {len(pages)} >>") == pages_id
    outlines_id = len(objs) + 1 + len(outline)
    items = []
    for k, (t, page) in enumerate(outline):
        first = len(objs) + 1
        links = (f" /Prev {first - 1} 0 R" if k else "") + (f" /Next {first + 1} 0 R" if k + 1 < len(outline) else "")
        items.append(obj(f"<< /Title ({esc(t)}) /Parent {outlines_id} 0 R /Dest [{page_ids[page]} 0 R /Fit]{links} >>"))
    assert obj(f"<< /Type /Outlines /First {items[0]} 0 R /Last {items[-1]} 0 R /Count {len(items)} >>") == outlines_id
    info = obj(f"<< /Title ({esc(title)}) /Author (Sample) >>")
    catalog = obj(f"<< /Type /Catalog /Pages {pages_id} 0 R /Outlines {outlines_id} 0 R /PageMode /UseOutlines >>")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root {catalog} 0 R /Info {info} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(bytes(out))


CALCULUS = [
    ("Week 1: Limits", ["A limit describes what a function approaches, not what it reaches.",
                        "We write the limit of f(x) as x approaches a, and we care only about values near a,",
                        "never about the value at a itself.",
                        "",
                        "Example. The function (x*x - 1)/(x - 1) is undefined at 1, yet its limit there is 2."]),
    ("Week 2: Derivatives", ["The derivative is the limit of the difference quotient.",
                             "Geometrically it is the slope of the tangent line; physically, a rate of change.",
                             "",
                             "Rules worth memorising: the power rule, the product rule and the chain rule."]),
    ("Week 3: Integrals", ["An integral adds up infinitely many infinitely thin pieces.",
                           "The fundamental theorem says that integration undoes differentiation."]),
]


def long_novel(rng):
    """About 450 KB of Chinese text: 24 chapters, one of them far longer than a section."""
    sentences = [s for _, paras in FOG_HARBOR + MOUNTAINS[1:3] for p in (paras or []) for s in
                 p.replace("<b>", "").replace("</b>", "").replace("<br/>", "").split("。") if s]
    lines = ["书名：长夜行", "作者：林知秋", ""]
    numbers = "一二三四五六七八九十"
    for c in range(24):
        n = numbers[c] if c < 10 else ("十" + numbers[c - 10] if c < 19 else "二十" + (numbers[c - 20] if c > 19 else ""))
        lines.append(f"第{n}章 {rng.choice(['雾', '灯', '潮', '岸', '信', '船'])}{rng.choice(['起', '落', '远', '近'])}")
        for _ in range(300 if c == 11 else 50):
            lines.append("　　" + "。".join(rng.choice(sentences) for _ in range(rng.randint(2, 6))) + "。")
        lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--long", action="store_true", help="also write a long novel (for timing page layout)")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    out = args.out
    (out / "中文").mkdir(parents=True, exist_ok=True)
    (out / "English").mkdir(parents=True, exist_ok=True)
    (out / "日本語").mkdir(parents=True, exist_ok=True)

    write_epub(out / "中文" / "雾港来信.epub", "雾港来信", "林知秋", "zh", FOG_HARBOR, cover=cover_image("雾港来信"))
    write_epub(out / "English" / "The Lighthouse Ledger.epub", "The Lighthouse Ledger", "Mara Quill", "en", LEDGER,
               epub3=False)
    text = "作者：周晚\n\n" + "\n".join(
        f"{t}\n" + ("" if not ps else "\n".join("　　" + p for p in ps) + "\n") for t, ps in MOUNTAINS)
    (out / "中文" / "山海旧事.txt").write_bytes(text.encode("gb18030"))
    text = "\n\n".join(f"{t}\n\n" + "\n".join("　" + p for p in ps) for t, ps in MONDAY)
    (out / "日本語" / "月曜日の図書室.txt").write_bytes(text.encode("shift_jis"))
    (out / "English" / "Field Notes on Moss.md").write_text(MOSS_MD, encoding="utf-8")
    (out / "English" / "The Tide Tables.txt").write_text(TIDES_TXT, encoding="utf-8")
    write_docx(out / "English" / "Moss Survey.docx", "Moss Survey", "R. Ellery", [
        ("Heading1", "Moss Survey"), (None, "A short survey of the mosses in the old churchyard, **spring** edition."),
        ("Heading2", "North wall"), (None, "Cushion moss in every joint of the stones, thickest near the gutter."),
        ("Heading2", "Path"), (None, "Thin and patchy; the path is still walked more than it looks."),
    ])
    write_pdf(out / "English" / "Calculus Notes.pdf", "Calculus Notes",
              [lines for _, lines in CALCULUS], [(t, i) for i, (t, _) in enumerate(CALCULUS)])
    if args.long:
        (out / "中文" / "长夜行.txt").write_text(long_novel(random.Random(7)), encoding="utf-8")
    print(f"{out}: sample books written")


if __name__ == "__main__":
    main()
