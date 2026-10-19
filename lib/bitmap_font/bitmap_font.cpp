#include "bitmap_font.h"

#include <cstring>

#include "dapfile.h"

using dap::rd16;
using dap::rd32;

namespace {
constexpr size_t kHeaderSize = 32, kGlyphSize = 16;
constexpr uint16_t kVersion = 1;
}  // namespace

const char* BitmapFont::errorText(Error e) {
  switch (e) {
    case Error::None: return "ok";
    case Error::TooSmall: return "file too small";
    case Error::BadMagic: return "not a font";
    case Error::UnsupportedVersion: return "font version not supported (remake it with tools/fonts.py)";
    case Error::SizeMismatch: return "file size differs from the header (cut short while copying?)";
    case Error::BadLayout: return "glyphs out of bounds (damaged file)";
  }
  return "?";
}

BitmapFont::Error BitmapFont::open(const uint8_t* data, size_t size) {
  data_ = nullptr;
  replacement_ = -1;
  if (data == nullptr || size < kHeaderSize) return Error::TooSmall;
  if (memcmp(data, "DAPF", 4) != 0) return Error::BadMagic;
  if (rd16(data + 4) != kVersion) return Error::UnsupportedVersion;
  if (rd32(data + 8) != size) return Error::SizeMismatch;
  uint32_t count = rd32(data + 12), glyphsAt = rd32(data + 24), bitmapsAt = rd32(data + 28);
  if (glyphsAt < rd16(data + 6) || glyphsAt > size || (uint64_t)count * kGlyphSize > size - glyphsAt ||
      bitmapsAt < glyphsAt + count * kGlyphSize || bitmapsAt > size) {
    return Error::BadLayout;
  }
  // Every bitmap must lie inside the file, so drawing never reads past it.
  uint32_t bitmapsSize = (uint32_t)size - bitmapsAt;
  for (uint32_t i = 0; i < count; i++) {
    const uint8_t* g = data + glyphsAt + i * kGlyphSize;
    uint64_t bytes = (uint64_t)((g[9] + 7) / 8) * g[10];
    if (rd32(g + 4) > bitmapsSize || bytes > bitmapsSize - rd32(g + 4)) return Error::BadLayout;
    if (i && rd32(g) <= rd32(g - kGlyphSize)) return Error::BadLayout;  // sorted, for binary search
  }
  data_ = data;
  count_ = count;
  glyphsAt_ = glyphsAt;
  bitmapsAt_ = bitmapsAt;
  bitmapsSize_ = bitmapsSize;
  size_ = rd16(data + 16);
  lineHeight_ = rd16(data + 18);
  ascent_ = (int16_t)rd16(data + 20);
  descent_ = (int16_t)rd16(data + 22);
  for (int c = 0; c < 128; c++) ascii_[c] = -1;
  for (uint32_t i = 0; i < count && rd32(data + glyphsAt + i * kGlyphSize) < 128; i++) {
    ascii_[rd32(data + glyphsAt + i * kGlyphSize)] = (int16_t)i;
  }
  replacement_ = find(kReplacement);
  return Error::None;
}

int BitmapFont::find(uint32_t cp) const {
  if (!data_) return -1;
  if (cp < 128) return ascii_[cp];
  uint32_t lo = 0, hi = count_;
  while (lo < hi) {
    uint32_t mid = (lo + hi) / 2;
    uint32_t c = rd32(data_ + glyphsAt_ + mid * kGlyphSize);
    if (c == cp) return (int)mid;
    if (c < cp) lo = mid + 1;
    else hi = mid;
  }
  return -1;
}

BitmapFont::Glyph BitmapFont::at(int index) const {
  Glyph g;
  if (index < 0 || !data_) return g;
  const uint8_t* p = data_ + glyphsAt_ + (size_t)index * kGlyphSize;
  g.bits = data_ + bitmapsAt_ + rd32(p + 4);
  g.advance = p[8];
  g.width = p[9];
  g.height = p[10];
  g.left = (int8_t)p[11];
  g.top = (int8_t)p[12];
  return g;
}

BitmapFont::Glyph BitmapFont::glyph(uint32_t cp) const {
  int i = find(cp);
  return at(i >= 0 ? i : replacement_);
}
