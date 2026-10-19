// Helpers for reading the files the PC tools write to the card (docs/formats.md): all
// numbers little-endian, read byte by byte so unaligned data works on any CPU.
#pragma once
#include <cstddef>
#include <cstdint>
#include <string_view>

namespace dap {

inline uint16_t rd16(const uint8_t* p) { return (uint16_t)(p[0] | p[1] << 8); }
inline uint32_t rd32(const uint8_t* p) {
  return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}

// CRC-32 as used by zip/zlib (Python's zlib.crc32). Pass the previous result to continue.
inline uint32_t crc32(const uint8_t* data, size_t size, uint32_t crc = 0) {
  // Half-byte table: 64 bytes instead of 1 KB, fast enough for a few MB at boot.
  static const uint32_t kTable[16] = {
      0x00000000, 0x1DB71064, 0x3B6E20C8, 0x26D930AC, 0x76DC4190, 0x6B6B51F4, 0x4DB26158, 0x5005713C,
      0xEDB88320, 0xF00F9344, 0xD6D6A3E8, 0xCB61B38C, 0x9B64C2B0, 0x86D3D2D4, 0xA00AE278, 0xBDBDF21C,
  };
  crc = ~crc;
  for (size_t i = 0; i < size; i++) {
    crc ^= data[i];
    crc = (crc >> 4) ^ kTable[crc & 15];
    crc = (crc >> 4) ^ kTable[crc & 15];
  }
  return ~crc;
}

// The NUL-terminated string at `offset` in a string pool whose last byte is NUL (checked
// when the file is opened); empty if the offset is outside the pool.
inline std::string_view poolString(const uint8_t* pool, uint32_t poolSize, uint32_t offset) {
  if (offset >= poolSize) return {};
  return std::string_view(reinterpret_cast<const char*>(pool + offset));
}

// Decodes one UTF-8 character at s[i] and moves i past it. Malformed bytes give U+FFFD and
// move one byte, so text with errors still draws and never loops.
inline uint32_t nextUtf8(const char* s, size_t size, size_t& i) {
  uint8_t c = (uint8_t)s[i++];
  if (c < 0x80) return c;
  int extra = c >= 0xF0 ? 3 : c >= 0xE0 ? 2 : c >= 0xC2 ? 1 : -1;
  if (extra < 0 || c > 0xF4 || i + extra > size) return 0xFFFD;
  uint32_t cp = c & (0x3F >> extra);
  for (int k = 0; k < extra; k++) {
    uint8_t d = (uint8_t)s[i + k];
    if ((d & 0xC0) != 0x80) return 0xFFFD;
    cp = cp << 6 | (d & 0x3F);
  }
  static const uint32_t kMin[4] = {0, 0x80, 0x800, 0x10000};
  if (cp < kMin[extra] || cp > 0x10FFFF || (cp >= 0xD800 && cp <= 0xDFFF)) return 0xFFFD;
  i += extra;
  return cp;
}

}  // namespace dap
