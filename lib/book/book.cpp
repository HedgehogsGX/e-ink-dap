#include "book.h"

#include <cstdio>
#include <cstring>

#include "dapfile.h"

using dap::rd16;
using dap::rd32;

namespace {
constexpr uint16_t kVersion = 1;
constexpr uint32_t kTocSize = 12, kBookRecordSize = 32;

const char* errorTextOf(int e) {
  static const char* const kText[] = {"ok",
                                      "file too small",
                                      "not a book file",
                                      "version not supported (convert the books again with tools/build_index.py)",
                                      "file size differs from the header (cut short while copying?)",
                                      "sections out of bounds (damaged file)",
                                      "checksum mismatch (damaged file)"};
  return e >= 0 && e < 7 ? kText[e] : "?";
}
}  // namespace

const char* bookFormatName(BookFormat f) {
  switch (f) {
    case BookFormat::Epub: return "EPUB";
    case BookFormat::Pdf: return "PDF";
    case BookFormat::Txt: return "TXT";
    case BookFormat::Markdown: return "MD";
    case BookFormat::Docx: return "DOCX";
    default: return "?";
  }
}

// ---- Book ----

const char* Book::errorText(Error e) { return errorTextOf((int)e); }

uint32_t Book::frontSize(const uint8_t* header, size_t size) {
  if (header == nullptr || size < kHeaderSize || memcmp(header, "DAPB", 4) != 0) return 0;
  return rd32(header + 16);
}

Book::Error Book::open(const uint8_t* data, size_t size, uint32_t fileSize, bool verifyChecksum) {
  *this = Book();
  if (data == nullptr || size < kHeaderSize) return Error::TooSmall;
  if (memcmp(data, "DAPB", 4) != 0) return Error::BadMagic;
  if (rd16(data + 4) != kVersion) return Error::UnsupportedVersion;
  if (rd32(data + 8) != fileSize || size > fileSize) return Error::SizeMismatch;
  uint32_t headerSize = rd16(data + 6);
  uint32_t textAt = rd32(data + 16), textSize = rd32(data + 20);
  uint32_t sectionsAt = rd32(data + 24), sections = rd32(data + 28);
  uint32_t tocAt = rd32(data + 32), toc = rd32(data + 36);
  uint32_t stringsAt = rd32(data + 40), stringsSize = rd32(data + 44);
  // Tables must lie between the header and the text, inside what was loaded.
  auto fits = [&](uint32_t at, uint64_t count, uint64_t recSize) {
    return at >= headerSize && at <= textAt && count * recSize <= textAt - at;
  };
  if (headerSize < kHeaderSize || textAt > size || (uint64_t)textAt + textSize != fileSize || sections == 0 ||
      !fits(sectionsAt, sections, 4) || !fits(tocAt, toc, kTocSize) || stringsSize == 0 ||
      !fits(stringsAt, stringsSize, 1) || data[stringsAt + stringsSize - 1] != 0) {
    return Error::BadLayout;
  }
  for (uint32_t i = 0; i < sections; i++) {  // rising, starting at 0, inside the text
    uint32_t s = rd32(data + sectionsAt + i * 4);
    if ((i == 0 && s != 0) || (i > 0 && s <= rd32(data + sectionsAt + (i - 1) * 4)) || (s >= textSize && textSize)) {
      return Error::BadLayout;
    }
  }
  if (verifyChecksum && size == fileSize && dap::crc32(data + headerSize, size - headerSize) != rd32(data + 12)) {
    return Error::BadChecksum;
  }
  data_ = data;
  size_ = size;
  textAt_ = textAt;
  textSize_ = textSize;
  sectionsAt_ = sectionsAt;
  sectionCount_ = sections;
  tocAt_ = tocAt;
  tocCount_ = toc;
  stringsAt_ = stringsAt;
  stringsSize_ = stringsSize;
  format_ = data[60] <= (uint8_t)BookFormat::Docx ? (BookFormat)data[60] : BookFormat::Unknown;
  flags_ = data[61];
  return Error::None;
}

std::string_view Book::str(uint32_t offset) const {
  return data_ ? dap::poolString(data_ + stringsAt_, stringsSize_, offset) : std::string_view();
}

std::string_view Book::title() const { return data_ ? str(rd32(data_ + 48)) : std::string_view(); }
std::string_view Book::author() const { return data_ ? str(rd32(data_ + 52)) : std::string_view(); }
std::string_view Book::language() const { return data_ ? str(rd32(data_ + 56)) : std::string_view(); }

std::string_view Book::text() const {
  if (!data_ || size_ < (size_t)textAt_ + textSize_) return {};
  return std::string_view(reinterpret_cast<const char*>(data_ + textAt_), textSize_);
}

uint32_t Book::sectionStart(uint32_t i) const {
  return i < sectionCount_ ? rd32(data_ + sectionsAt_ + i * 4) : kNone;
}

uint32_t Book::sectionEnd(uint32_t i) const {
  if (i >= sectionCount_) return kNone;
  return i + 1 < sectionCount_ ? sectionStart(i + 1) : textSize_;
}

uint32_t Book::sectionAt(uint32_t pos) const {
  uint32_t lo = 0, hi = sectionCount_;  // last section with start <= pos
  while (hi - lo > 1) {
    uint32_t mid = (lo + hi) / 2;
    if (sectionStart(mid) <= pos) lo = mid;
    else hi = mid;
  }
  return lo;
}

Book::TocEntry Book::toc(uint32_t i) const {
  TocEntry e;
  if (i >= tocCount_) return e;
  const uint8_t* p = data_ + tocAt_ + i * kTocSize;
  e.pos = rd32(p);
  e.title = str(rd32(p + 4));
  e.level = p[8];
  return e;
}

int Book::tocAt(uint32_t pos) const {
  int found = -1;
  for (uint32_t i = 0; i < tocCount_ && toc(i).pos <= pos; i++) found = (int)i;  // entries are in text order
  return found;
}

// ---- Shelf ----

Shelf::Error Shelf::open(const uint8_t* data, size_t size, bool verifyChecksum) {
  *this = Shelf();
  if (data == nullptr || size < kHeaderSize) return Error::TooSmall;
  if (memcmp(data, "DAPS", 4) != 0) return Error::BadMagic;
  if (rd16(data + 4) != kVersion) return Error::UnsupportedVersion;
  if (rd32(data + 8) != size) return Error::SizeMismatch;
  uint32_t headerSize = rd16(data + 6), count = rd32(data + 16), recordSize = rd16(data + 36);
  uint32_t booksAt = rd32(data + 20), byAuthorAt = rd32(data + 24);
  uint32_t stringsAt = rd32(data + 28), stringsSize = rd32(data + 32);
  auto fits = [&](uint32_t at, uint64_t n, uint64_t recSize) {
    return at >= headerSize && at <= size && n * recSize <= size - at;
  };
  if (headerSize < kHeaderSize || recordSize < kBookRecordSize || !fits(booksAt, count, recordSize) ||
      !fits(byAuthorAt, count, 4) || stringsSize == 0 || !fits(stringsAt, stringsSize, 1) ||
      data[stringsAt + stringsSize - 1] != 0) {
    return Error::BadLayout;
  }
  if (verifyChecksum && dap::crc32(data + headerSize, size - headerSize) != rd32(data + 12)) return Error::BadChecksum;
  data_ = data;
  count_ = count;
  booksAt_ = booksAt;
  byAuthorAt_ = byAuthorAt;
  stringsAt_ = stringsAt;
  stringsSize_ = stringsSize;
  recordSize_ = recordSize;
  return Error::None;
}

Shelf::Entry Shelf::book(uint32_t i) const {
  Entry e;
  if (i >= count_) return e;
  const uint8_t* p = data_ + booksAt_ + (size_t)i * recordSize_;
  const uint8_t* pool = data_ + stringsAt_;
  e.id = rd32(p);
  e.title = dap::poolString(pool, stringsSize_, rd32(p + 4));
  e.author = dap::poolString(pool, stringsSize_, rd32(p + 8));
  e.source = dap::poolString(pool, stringsSize_, rd32(p + 12));
  e.textSize = rd32(p + 24);
  e.format = p[28] <= (uint8_t)BookFormat::Docx ? (BookFormat)p[28] : BookFormat::Unknown;
  e.ownCover = p[29] & 1;
  e.tocCount = rd16(p + 30);
  return e;
}

uint32_t Shelf::byAuthor(uint32_t n) const { return n < count_ ? rd32(data_ + byAuthorAt_ + (size_t)n * 4) : kNone; }

uint32_t Shelf::find(uint32_t id) const {
  for (uint32_t i = 0; i < count_; i++)
    if (rd32(data_ + booksAt_ + (size_t)i * recordSize_) == id) return i;
  return kNone;
}

uint32_t Shelf::builtUnixTime() const { return data_ ? rd32(data_ + 40) : 0; }

void Shelf::bookPath(uint32_t id, char* out) { snprintf(out, 26, "/.dap/books/%08lx.dbk", (unsigned long)id); }
void Shelf::coverPath(uint32_t id, char* out) { snprintf(out, 26, "/.dap/books/%08lx.g4", (unsigned long)id); }
