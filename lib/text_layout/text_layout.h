// Lays out book text (the .dbk text format, docs/formats.md) into lines and pages for the
// reader. Plain C++17, no Arduino dependency (tested on the host with `pio test -e native`).
//
// Text comes one section at a time: layout restarts at the top of a page at every section
// start, so a page can be laid out from its first byte alone, and a section's pages from
// the section alone. Positions are byte offsets in the whole book text, so a saved
// position survives a change of font size: reopen the page that contains it.
//
// Line breaking:
// - Latin text breaks at spaces (and after a hyphen inside a word); a word longer than
//   the line is cut where it overflows.
// - CJK text breaks between any two characters, with kinsoku: a line never starts with
//   closing punctuation (、。，」…) or ends with opening punctuation (「（“…); the
//   character before moves down instead. A comma or full stop that doesn't fit hangs in
//   the right margin, so the line keeps its last character.
// - Lines are justified (spread between CJK characters and at spaces), except a
//   paragraph's last line, headings, centred and preformatted text.
#pragma once
#include <cstdint>
#include <string_view>
#include <vector>

#include "dapfile.h"

// What layout needs to know about a font.
class FontMetrics {
 public:
  virtual ~FontMetrics() = default;
  // Pen advance of a character in pixels (a missing character gives the width that is drawn
  // instead, e.g. a box).
  virtual int advance(uint32_t codepoint) const = 0;
};

namespace booktext {
// First byte of a paragraph (none = body text). Every paragraph ends with '\n'.
constexpr uint8_t kH1 = 1, kH2 = 2, kH3 = 3, kQuote = 4, kItem = 5, kPre = 6, kCenter = 7, kRule = 8;
constexpr uint8_t kLineBreak = 0x0B;  // continues the paragraph before it on a new line
// Inside a paragraph: bold on / off (bold always ends with the paragraph).
constexpr uint8_t kBoldOn = 0x0E, kBoldOff = 0x0F;

bool isCjk(uint32_t c);       // CJK ideographs, kana, Hangul, CJK and full-width punctuation
bool noLineStart(uint32_t c);  // closing punctuation, small kana, prolonged sound mark
bool noLineEnd(uint32_t c);    // opening brackets and quotes
bool canHang(uint32_t c);      // 、。，．: may hang into the right margin
}  // namespace booktext

struct LayoutStyle {
  const FontMetrics* body = nullptr;
  const FontMetrics* heading = nullptr;  // for h1/h2; nullptr = the body font
  int bodySize = 18;                     // px, one em of the body font
  int headingSize = 22;
  int width = 212, height = 368;  // the text area, px
  int lineSpacing = 150;          // line pitch, percent of the font size
  int paragraphSpacing = 0;       // extra px between paragraphs
  int indentEms = 2;              // first-line indent of body paragraphs, ems
  bool justify = true;
  int boldExtra = 1;  // a bold glyph is drawn twice, 1 px apart, so it is this much wider
};

struct Line {
  uint32_t start = 0, end = 0;  // the line's bytes in the book text, without trailing spaces
  int16_t x = 0, y = 0;         // top-left in the text area
  int16_t height = 0;           // line pitch; the baseline is the renderer's choice inside it
  int16_t width = 0;            // natural width of the drawn glyphs (not counting a hanging one)
  int16_t extra = 0;            // px to spread over the gaps for justification
  int16_t gaps = 0;             // places where `extra` goes (see TextLayout::forEachGlyph)
  uint8_t style = 0;            // paragraph style (booktext::k…), 0 = body
  bool heading = false;         // drawn with the heading font
  bool bold = false;            // bold at the start of the line
  bool hang = false;            // the last character hangs in the right margin
};

struct PageLayout {
  uint32_t start = 0;  // first byte of the page
  uint32_t end = 0;    // where the next page starts
  std::vector<Line> lines;
};

class TextLayout {
 public:
  // Lays out the page that starts at `start` (a book offset in [base, base + section.size())).
  // `section` is that section's text, `base` its book offset. Returns the next page's start;
  // the section end once the section is used up. `out` may be null when only the page
  // boundaries are needed.
  static uint32_t layoutPage(std::string_view section, uint32_t base, uint32_t start, const LayoutStyle& style,
                             PageLayout* out);

  // Every page start of a section, in order; the first is `base`.
  static std::vector<uint32_t> paginate(std::string_view section, uint32_t base, const LayoutStyle& style);

  // Index into `starts` of the page holding book offset `pos` (the first page if pos is
  // before it, the last one if after).
  static size_t pageContaining(const std::vector<uint32_t>& starts, uint32_t pos);

  // Calls f(codepoint, x, bold) for each glyph of a line, x relative to the text area, with
  // justification applied: the line's `extra` px are shared out over its gaps, and a gap is
  // after a space or next to a CJK character.
  template <class F>
  static void forEachGlyph(std::string_view section, uint32_t base, const Line& line, const LayoutStyle& style,
                           F f) {
    const FontMetrics* font = line.heading && style.heading ? style.heading : style.body;
    bool forced = line.heading || line.style == booktext::kH3;  // headings are bold throughout
    bool bold = line.bold || forced;
    int x = 0, gap = 0;
    uint32_t prev = 0;
    bool first = true;
    const char* s = section.data();
    size_t i = line.start - base, end = line.end - base, lastStart = end;
    if (line.hang) {  // find where the hanging character starts
      lastStart = end - 1;
      while (lastStart > i && ((uint8_t)s[lastStart] & 0xC0) == 0x80) lastStart--;
    }
    while (i < end) {
      size_t at = i;
      uint32_t c = dap::nextUtf8(s, end, i);
      if (c == booktext::kBoldOn || c == booktext::kBoldOff) {
        bold = c == booktext::kBoldOn || forced;
        continue;
      }
      if (c < 0x20) continue;
      if (at == lastStart && line.hang) {
        f(c, line.x + line.width + line.extra, bold);
        break;
      }
      if (!first && isGap(prev, c) && line.gaps > 0) {
        x += line.extra * (gap + 1) / line.gaps - line.extra * gap / line.gaps;
        gap++;
      }
      f(c, line.x + x, bold);
      x += font->advance(c) + (bold ? style.boldExtra : 0);
      prev = c;
      first = false;
    }
  }

  static bool isGap(uint32_t before, uint32_t after) {
    return before == ' ' || booktext::isCjk(before) || booktext::isCjk(after);
  }
};
