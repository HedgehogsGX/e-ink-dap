// The card's /.dap files packed into one blob by tools/make_ui_demo.py (format in its
// docstring), so the UI demo runs from flash before the microSD card is wired. Files are
// read in place. Plain C++17, no Arduino dependency.
#pragma once
#include <cstring>

#include "dapfile.h"
#include "ui_app.h"

class CardPack : public CardFiles {
 public:
  static constexpr size_t kHeaderSize = 16, kRecordSize = 64, kPathSize = 48;

  // False if it isn't a complete pack.
  bool open(const uint8_t* data, size_t size) {
    data_ = nullptr;
    if (data == nullptr || size < kHeaderSize || memcmp(data, "DPAK", 4) != 0 || dap::rd32(data + 4) != 1) return false;
    uint32_t count = dap::rd32(data + 8);
    if ((size - kHeaderSize) / kRecordSize < count) return false;
    for (uint32_t i = 0; i < count; i++) {
      const uint8_t* r = data + kHeaderSize + i * kRecordSize;
      uint32_t at = dap::rd32(r + kPathSize), n = dap::rd32(r + kPathSize + 4);
      if (at > size || n > size - at) return false;
    }
    data_ = data;
    count_ = count;
    size_ = size;
    return true;
  }

  std::string_view file(std::string_view path) const override {
    for (uint32_t i = 0; data_ && i < count_; i++) {
      const char* r = reinterpret_cast<const char*>(data_ + kHeaderSize + i * kRecordSize);
      if (strnlen(r, kPathSize) == path.size() && memcmp(r, path.data(), path.size()) == 0) {
        const uint8_t* p = reinterpret_cast<const uint8_t*>(r) + kPathSize;
        return std::string_view(reinterpret_cast<const char*>(data_) + dap::rd32(p), dap::rd32(p + 4));
      }
    }
    return {};
  }

  uint32_t count() const { return count_; }
  size_t size() const { return size_; }

 private:
  const uint8_t* data_ = nullptr;
  uint32_t count_ = 0;
  size_t size_ = 0;
};
