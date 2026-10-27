// A 1-bit image of the whole screen that the UI draws into before it goes to the panel,
// with what the screens need: lines, boxes, simple shapes for icons, and text in the .dfn
// bitmap fonts. Plain C++17, no Arduino dependency, so the same screens can be drawn on
// the host (src/ui_sim) to check them without the panel.
//
// Coordinates are portrait pixels, (0, 0) top left. Rectangles take both corners
// inclusive, like the mockups in tools/render_previews.py, so their numbers carry over.
#pragma once
#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <string>
#include <string_view>

#include "bitmap_font.h"

class Frame {
 public:
  static constexpr int kWidth = 240, kHeight = 416;
  static constexpr size_t kBytes = kWidth * kHeight / 8;

  // Rows of 30 bytes, leftmost pixel in bit 7, 1 = black (GxEPD2's writeImage takes this
  // layout, with invert set because its 1 is white).
  const uint8_t* data() const { return bits_; }

  void clear() { std::fill(bits_, bits_ + kBytes, 0); }
  void pixel(int x, int y, bool black = true) {
    if (x < 0 || x >= kWidth || y < 0 || y >= kHeight) return;
    uint8_t& b = bits_[(y * kWidth + x) >> 3];
    uint8_t m = 0x80 >> (x & 7);
    b = black ? b | m : b & ~m;
  }
  bool black(int x, int y) const {
    return x >= 0 && x < kWidth && y >= 0 && y < kHeight && (bits_[(y * kWidth + x) >> 3] & (0x80 >> (x & 7)));
  }

  void fill(int x0, int y0, int x1, int y1, bool black = true);
  void rect(int x0, int y0, int x1, int y1) {  // outline
    hline(x0, x1, y0);
    hline(x0, x1, y1);
    vline(x0, y0, y1);
    vline(x1, y0, y1);
  }
  void hline(int x0, int x1, int y, bool black = true) { fill(x0, y, x1, y, black); }
  void vline(int x, int y0, int y1, bool black = true) { fill(x, y0, x, y1, black); }
  void dottedHline(int x0, int x1, int y);
  // Rounded box: an outline, or filled.
  void roundRect(int x0, int y0, int x1, int y1, int r, bool filled = false, bool black = true);
  void line(int x0, int y0, int x1, int y1, int width = 1, bool black = true);
  // Polygon given as x0, y0, x1, y1, ... (n points), filled at pixel centres.
  void fillPolygon(const float* xy, int n, bool black = true);
  void fillEllipse(int x0, int y0, int x1, int y1, bool black = true);

  // Text. `y` is the top of the line (the baseline is at y + ascent), as in the mockups.
  // Returns the x after the text.
  int text(const BitmapFont& f, int x, int y, std::string_view s, bool black = true);
  void centered(const BitmapFont& f, int x0, int x1, int y, std::string_view s, bool black = true);
  void rightAligned(const BitmapFont& f, int right, int y, std::string_view s, bool black = true);
  static int width(const BitmapFont& f, std::string_view s);
  // `s`, cut and ended with "…" if it is wider than `width`.
  static std::string fit(const BitmapFont& f, std::string_view s, int width);

 private:
  uint8_t bits_[kBytes] = {};
};

// Breaks text into at most maxLines lines of `width` px: Latin at spaces, CJK between any
// two characters. The last line ends with "…" if the text doesn't fit.
int wrapText(const BitmapFont& f, std::string_view s, int width, int maxLines, std::string* lines);
