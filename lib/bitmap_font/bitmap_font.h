// Reader for the .dfn bitmap fonts that tools/fonts.py writes to /.dap/fonts/ on the card
// (format: docs/formats.md). Plain C++17, no Arduino dependency.
//
// Load the whole file into memory (PSRAM on the board: a reader font is a few hundred KB),
// then open() it; glyphs are read in place. A character the font doesn't have is drawn as
// its U+FFFD box. Draw a glyph by plotting its set pixels:
//   font.draw(cp, x, baselineY, [&](int px, int py) { display.drawPixel(px, py, GxEPD_BLACK); });
// Bold text is drawn twice, the second time 1 px to the right (LayoutStyle::boldExtra).
#pragma once
#include <cstddef>
#include <cstdint>

#include "text_layout.h"

class BitmapFont : public FontMetrics {
 public:
  static constexpr uint32_t kReplacement = 0xFFFD;

  struct Glyph {
    uint8_t advance = 0;
    uint8_t width = 0, height = 0;  // bitmap size
    int8_t left = 0;                // bitmap's left edge, from the pen position
    int8_t top = 0;                 // bitmap's top row, pixels above the baseline
    const uint8_t* bits = nullptr;  // rows of (width + 7) / 8 bytes, leftmost pixel in bit 7
    bool pixel(int x, int y) const { return bits[y * ((width + 7) / 8) + x / 8] & (0x80 >> (x & 7)); }
  };

  enum class Error { None, TooSmall, BadMagic, UnsupportedVersion, SizeMismatch, BadLayout };
  static const char* errorText(Error e);

  Error open(const uint8_t* data, size_t size);
  bool isOpen() const { return data_ != nullptr; }

  int size() const { return size_; }  // nominal size in px (one em)
  int lineHeight() const { return lineHeight_; }
  int ascent() const { return ascent_; }
  int descent() const { return descent_; }
  uint32_t glyphCount() const { return count_; }

  bool has(uint32_t cp) const { return find(cp) >= 0; }
  // The glyph, or U+FFFD's if the font hasn't got it (an empty glyph if neither exists).
  Glyph glyph(uint32_t cp) const;
  int advance(uint32_t cp) const override { return glyph(cp).advance; }

  template <class Plot>
  int draw(uint32_t cp, int x, int baseline, Plot plot, bool bold = false) const {
    Glyph g = glyph(cp);
    for (int yy = 0; yy < g.height; yy++)
      for (int xx = 0; xx < g.width; xx++)
        if (g.pixel(xx, yy)) {
          plot(x + g.left + xx, baseline - g.top + yy);
          if (bold) plot(x + g.left + xx + 1, baseline - g.top + yy);
        }
    return g.advance + (bold ? 1 : 0);
  }

 private:
  int find(uint32_t cp) const;  // glyph index, -1 if missing
  Glyph at(int index) const;

  const uint8_t* data_ = nullptr;
  uint32_t count_ = 0, glyphsAt_ = 0, bitmapsAt_ = 0, bitmapsSize_ = 0;
  int size_ = 0, lineHeight_ = 0, ascent_ = 0, descent_ = 0;
  int16_t ascii_[128] = {};  // glyph index of each ASCII character, -1 if missing
  int replacement_ = -1;
};
