// 4-gray image in the .g4 format that tools/cover_art.py makes (album covers in
// /.dap/art/; format: docs/formats.md). Plain C++17, no Arduino dependency.
//
// Draw it pixel by pixel into the display's frame buffer, e.g. with a 4-gray driver:
//   static const uint16_t kColor[4] = {GxEPD_BLACK, GxEPD_DARKGREY, GxEPD_LIGHTGREY, GxEPD_WHITE};
//   for (int y = 0; y < img.height(); y++)
//     for (int x = 0; x < img.width(); x++) display.drawPixel(x0 + x, y0 + y, kColor[img.level(x, y)]);
// In black/white mode use blackInBw(x, y) instead of level().
#pragma once
#include <cstddef>
#include <cstdint>
#include <cstring>

class G4Image {
 public:
  enum Level : uint8_t { Black = 0, DarkGray = 1, LightGray = 2, White = 3 };
  static constexpr size_t kHeaderSize = 8;

  // `data` must stay valid while the image is used. False if it isn't a complete .g4 image.
  bool open(const uint8_t* data, size_t size) {
    pixels_ = nullptr;
    width_ = height_ = 0;
    if (data == nullptr || size < kHeaderSize || memcmp(data, "G4BM", 4) != 0) return false;
    uint16_t w = (uint16_t)(data[4] | data[5] << 8), h = (uint16_t)(data[6] | data[7] << 8);
    if (w == 0 || h == 0 || size - kHeaderSize < (size_t)((w + 3) / 4) * h) return false;
    width_ = w;
    height_ = h;
    pixels_ = data + kHeaderSize;
    return true;
  }

  int width() const { return width_; }
  int height() const { return height_; }
  // Bytes per row: 4 pixels per byte, rounded up.
  size_t stride() const { return (width_ + 3) / 4; }

  // 0 = black ... 3 = white. x and y must be inside the image.
  uint8_t level(int x, int y) const { return (pixels_[y * stride() + x / 4] >> (6 - 2 * (x & 3))) & 3; }

  // For drawing in black and white only: dark gray becomes 3 of every 2x2 pixels black,
  // light gray 1 of them.
  bool blackInBw(int x, int y) const {
    bool corner = (x & 1) == 0 && (y & 1) == 0;
    switch (level(x, y)) {
      case Black: return true;
      case DarkGray: return !corner;
      case LightGray: return corner;
      default: return false;
    }
  }

 private:
  const uint8_t* pixels_ = nullptr;
  uint16_t width_ = 0, height_ = 0;
};
