#include "text_layout.h"

#include <algorithm>

namespace booktext {

bool isCjk(uint32_t c) {
  return (c >= 0x1100 && c <= 0x11FF) || (c >= 0x2E80 && c <= 0x9FFF) || (c >= 0xA960 && c <= 0xA97F) ||
         (c >= 0xAC00 && c <= 0xD7FF) || (c >= 0xF900 && c <= 0xFAFF) || (c >= 0xFE30 && c <= 0xFE4F) ||
         (c >= 0xFF00 && c <= 0xFFEF) || (c >= 0x20000 && c <= 0x3FFFF);
}

namespace {
// Sorted, for binary search.
const uint32_t kNoStart[] = {
    0x21,   0x29,   0x2C,   0x2E,   0x3A,   0x3B,   0x3F,   0x5D,   0x7D,   0xBB,   0x2019, 0x201D, 0x2025,
    0x2026, 0x203A, 0x3001, 0x3002, 0x3005, 0x3009, 0x300B, 0x300D, 0x300F, 0x3011, 0x3015, 0x3017, 0x3019,
    0x301B, 0x301E, 0x301F, 0x3041, 0x3043, 0x3045, 0x3047, 0x3049, 0x3063, 0x3083, 0x3085, 0x3087, 0x308E,
    0x3095, 0x3096, 0x309B, 0x309C, 0x309D, 0x309E, 0x30A1, 0x30A3, 0x30A5, 0x30A7, 0x30A9, 0x30C3, 0x30E3,
    0x30E5, 0x30E7, 0x30EE, 0x30F5, 0x30F6, 0x30FB, 0x30FC, 0x30FD, 0x30FE, 0xFF01, 0xFF09, 0xFF0C, 0xFF0E,
    0xFF1A, 0xFF1B, 0xFF1F, 0xFF3D, 0xFF5D, 0xFF60, 0xFF61, 0xFF63, 0xFF64, 0xFF65, 0xFF9E, 0xFF9F,
};
const uint32_t kNoEnd[] = {
    0x28,   0x5B,   0x7B,   0xAB,   0x2018, 0x201C, 0x2039, 0x3008, 0x300A, 0x300C, 0x300E,
    0x3010, 0x3014, 0x3016, 0x3018, 0x301A, 0x301D, 0xFF08, 0xFF3B, 0xFF5B, 0xFF5F, 0xFF62,
};

template <size_t N>
bool contains(const uint32_t (&table)[N], uint32_t c) {
  return std::binary_search(table, table + N, c);
}
}  // namespace

bool noLineStart(uint32_t c) { return contains(kNoStart, c); }
bool noLineEnd(uint32_t c) { return contains(kNoEnd, c); }
bool canHang(uint32_t c) { return c == 0x3001 || c == 0x3002 || c == 0xFF0C || c == 0xFF0E || c == 0xFF61 || c == 0xFF64; }

}  // namespace booktext

namespace {

using namespace booktext;

bool isLetter(uint32_t c) {
  return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= 0xC0 && c <= 0x24F && c != 0xD7 && c != 0xF7);
}

// The paragraph around section index i.
struct Para {
  size_t start = 0;    // its first byte (the style byte, if it has one)
  size_t content = 0;  // its first text byte
  size_t end = 0;      // its '\n' (the section size if the section is cut short)
  uint8_t style = 0;
};

Para paragraphAt(std::string_view s, size_t i) {
  Para p;
  size_t a = i;
  while (a > 0 && s[a - 1] != '\n') a--;
  p.start = a;
  uint8_t b = a < s.size() ? (uint8_t)s[a] : 0;
  p.style = ((b >= kH1 && b <= kRule) || b == kLineBreak) ? b : 0;
  p.content = a + (p.style ? 1 : 0);
  size_t e = s.find('\n', std::max(i, p.content));
  p.end = e == std::string_view::npos ? s.size() : e;
  return p;
}

// How a paragraph style is laid out.
struct Shape {
  const FontMetrics* font;
  int pitch;       // line height
  bool heading;    // heading font
  bool bold;       // always bold
  int inset;       // px left and right (quotes)
  int indent;      // first line
  int hanging;     // lines after the first (list items)
  bool justify;
  bool center;
  bool anywhere;   // break between any two characters, keep spaces (preformatted)
  int before;      // space above the paragraph, unless at the top of a page
  int after;       // space below
};

int pitchOf(int size, const LayoutStyle& st) { return std::max(size * st.lineSpacing / 100, size); }

Shape shapeOf(uint8_t style, const LayoutStyle& st) {
  Shape sh{};
  int bodyPitch = pitchOf(st.bodySize, st);
  sh.font = st.body;
  sh.pitch = bodyPitch;
  sh.justify = st.justify;
  sh.before = st.paragraphSpacing;
  switch (style) {
    case kH1:
    case kH2:
      sh.font = st.heading ? st.heading : st.body;
      sh.pitch = pitchOf(st.heading ? st.headingSize : st.bodySize, st);
      sh.heading = sh.bold = true;
      sh.justify = false;
      sh.before = bodyPitch;
      sh.after = bodyPitch / 2;
      break;
    case kH3:
      sh.bold = true;
      sh.justify = false;
      sh.before = bodyPitch / 2;
      sh.after = bodyPitch / 4;
      break;
    case kQuote:
      sh.inset = st.bodySize;
      break;
    case kItem:
      sh.hanging = st.bodySize;
      break;
    case kPre:
      sh.anywhere = true;
      sh.justify = false;
      break;
    case kCenter:
    case kRule:
      sh.center = true;
      sh.justify = false;
      break;
    case kLineBreak:
      sh.before = 0;
      break;
    default:
      sh.indent = st.indentEms * st.bodySize;
      break;
  }
  return sh;
}

struct Broken {
  size_t end;   // after the last glyph drawn
  size_t next;  // where the next line starts
  int width;
  int gaps;
  bool hang;
  bool paraEnd;
};

size_t skipSpaces(std::string_view s, size_t i, size_t limit) {
  while (i < limit && s[i] == ' ') i++;
  return i;
}

// One line from s[i], not past the paragraph end, at most `avail` px wide.
Broken breakLine(std::string_view s, size_t i, size_t paraEnd, int avail, const Shape& sh, bool bold,
                 int boldExtra) {
  const char* d = s.data();
  int x = 0, gaps = 0;
  int widthDrawn = 0, gapsDrawn = 0;  // up to the last glyph that isn't a space
  size_t endDrawn = i;
  bool any = false, haveBreak = false;
  Broken brk{};
  uint32_t prev = 0, prev2 = 0;
  size_t pos = i;
  while (pos < paraEnd) {
    size_t at = pos;
    uint32_t c = dap::nextUtf8(d, paraEnd, pos);
    if (c == kBoldOn || c == kBoldOff) {
      bold = c == kBoldOn || sh.bold;
      continue;
    }
    if (c < 0x20) continue;
    int w = sh.font->advance(c) + (bold ? boldExtra : 0);
    if (any && c != ' ') {
      bool opportunity = sh.anywhere || prev == ' ' ||
                         ((isCjk(prev) || isCjk(c)) && !noLineStart(c) && !noLineEnd(prev)) ||
                         (prev == '-' && isLetter(c) && isLetter(prev2));
      if (opportunity) {
        haveBreak = true;
        brk = {endDrawn, at, widthDrawn, gapsDrawn, false, false};
      }
    }
    if (any && x + w > avail) {
      if (c == ' ' && !sh.anywhere) return {endDrawn, pos, widthDrawn, gapsDrawn, false, false};
      if (canHang(c) && !sh.anywhere) {
        size_t look = pos;
        uint32_t n = 0;
        while (look < paraEnd && (n = dap::nextUtf8(d, paraEnd, look)) < 0x20) n = 0;
        if (!noLineStart(n)) return {pos, pos, widthDrawn, gapsDrawn, true, false};
      }
      if (haveBreak) return brk;
      return {endDrawn, at, widthDrawn, gapsDrawn, false, false};  // nowhere to break: cut the word
    }
    if (any && TextLayout::isGap(prev, c)) gaps++;
    x += w;
    if (c != ' ' || sh.anywhere) {
      widthDrawn = x;
      gapsDrawn = gaps;
      endDrawn = pos;
    }
    prev2 = prev;
    prev = c;
    any = true;
  }
  return {endDrawn, paraEnd, widthDrawn, gapsDrawn, false, true};
}

bool boldAfter(std::string_view s, size_t from, size_t to, bool bold, bool forced) {
  for (size_t k = from; k < to; k++) {
    if ((uint8_t)s[k] == kBoldOn) bold = true;
    if ((uint8_t)s[k] == kBoldOff) bold = forced;
  }
  return bold;
}

}  // namespace

uint32_t TextLayout::layoutPage(std::string_view s, uint32_t base, uint32_t start, const LayoutStyle& st,
                                PageLayout* out) {
  size_t n = s.size();
  size_t i = start < base ? 0 : std::min<size_t>(start - base, n);
  if (out) {
    out->start = base + (uint32_t)i;
    out->lines.clear();
  }
  int y = 0;
  bool top = true;  // nothing on the page yet
  auto finish = [&](size_t at) {
    if (out) out->end = base + (uint32_t)at;
    return base + (uint32_t)at;
  };
  while (i < n) {
    Para p = paragraphAt(s, i);
    bool firstLine = i <= p.content;
    if (i < p.content) i = p.content;
    Shape sh = shapeOf(p.style, st);
    bool bold = boldAfter(s, p.content, i, sh.bold, sh.bold);
    int yBefore = y;
    size_t linesBefore = out ? out->lines.size() : 0;
    if (firstLine && !top) y += sh.before;

    size_t lineStart = i;
    for (;;) {
      if (y + sh.pitch > st.height && !top) return finish(firstLine ? p.start : lineStart);
      int left = sh.inset + (firstLine ? sh.indent : sh.hanging);
      int avail = std::max(1, st.width - left - sh.inset);
      Broken r = p.style == kRule ? Broken{p.content, p.end, 0, 0, false, true}
                                  : breakLine(s, lineStart, p.end, avail, sh, bold, st.boldExtra);
      if (out) {
        Line ln;
        ln.start = base + (uint32_t)lineStart;
        ln.end = base + (uint32_t)r.end;
        ln.x = (int16_t)(sh.center ? left + std::max(0, avail - r.width) / 2 : left);
        ln.y = (int16_t)y;
        ln.height = (int16_t)sh.pitch;
        ln.width = (int16_t)r.width;
        ln.gaps = (int16_t)r.gaps;
        ln.extra = (int16_t)(sh.justify && !r.paraEnd && r.gaps > 0 ? std::max(0, avail - r.width) : 0);
        ln.style = p.style;
        ln.heading = sh.heading;
        ln.bold = bold;
        ln.hang = r.hang;
        out->lines.push_back(ln);
      }
      y += sh.pitch;
      top = false;
      bold = boldAfter(s, lineStart, r.next, bold, sh.bold);
      firstLine = false;
      if (r.paraEnd) break;
      lineStart = sh.anywhere ? r.next : skipSpaces(s, r.next, p.end);
      if (lineStart >= p.end) break;
    }
    i = p.end + 1;
    y += sh.after;

    // A heading never ends a page: if the next paragraph's first line doesn't fit under
    // it, the heading moves to the next page too.
    if (sh.heading || p.style == kH3) {
      if (i < n && yBefore > 0) {
        Shape next = shapeOf(paragraphAt(s, i).style, st);
        if (y + next.before + next.pitch > st.height) {
          if (out) out->lines.resize(linesBefore);
          return finish(p.start);
        }
      }
    }
  }
  return finish(n);
}

std::vector<uint32_t> TextLayout::paginate(std::string_view section, uint32_t base, const LayoutStyle& style) {
  std::vector<uint32_t> starts{base};
  uint32_t end = base + (uint32_t)section.size();
  for (uint32_t at = base;;) {
    uint32_t next = layoutPage(section, base, at, style, nullptr);
    if (next <= at) next = at + 1;  // can't happen with a sane style; never loop
    if (next >= end) break;
    starts.push_back(next);
    at = next;
  }
  return starts;
}

size_t TextLayout::pageContaining(const std::vector<uint32_t>& starts, uint32_t pos) {
  if (starts.empty()) return 0;
  auto it = std::upper_bound(starts.begin(), starts.end(), pos);
  return it == starts.begin() ? 0 : (size_t)(it - starts.begin() - 1);
}
