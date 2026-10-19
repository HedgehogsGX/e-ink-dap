// Readers for the reader's files that tools/books.py writes to the card (formats:
// docs/formats.md): a converted book (/.dap/books/<id>.dbk) and the shelf index
// (/.dap/books.idx). Plain C++17, no Arduino dependency.
//
// A book's text comes last in its file, so the player doesn't need the whole book in
// memory: read the first frontSize() bytes (header, sections, contents, strings) and open()
// them, then read one section's text at a time from textOffset() + sectionStart(i).
#pragma once
#include <cstddef>
#include <cstdint>
#include <string_view>

enum class BookFormat : uint8_t { Unknown = 0, Epub = 1, Pdf = 2, Txt = 3, Markdown = 4, Docx = 5 };
const char* bookFormatName(BookFormat f);  // "EPUB", "PDF", "TXT", "MD", "DOCX"

class Book {
 public:
  static constexpr size_t kHeaderSize = 64;
  static constexpr uint32_t kNone = 0xFFFFFFFF;

  struct TocEntry {
    uint32_t pos = 0;  // book text offset of the chapter's first paragraph (a section start)
    std::string_view title;
    uint8_t level = 0;  // 1 = top level
  };

  enum class Error { None, TooSmall, BadMagic, UnsupportedVersion, SizeMismatch, BadLayout, BadChecksum };
  static const char* errorText(Error e);

  // Bytes from the file start that open() needs, from the first kHeaderSize bytes; 0 if
  // they aren't a book's header.
  static uint32_t frontSize(const uint8_t* header, size_t size);

  // `data` holds the first `size` bytes of a file of `fileSize` bytes: at least
  // frontSize(), or the whole file. With the whole file and verifyChecksum, the CRC-32 is
  // checked too.
  Error open(const uint8_t* data, size_t size, uint32_t fileSize, bool verifyChecksum = false);
  bool isOpen() const { return data_ != nullptr; }

  std::string_view title() const;
  std::string_view author() const;
  std::string_view language() const;  // e.g. "zh", "en"; empty if unknown
  BookFormat format() const { return format_; }
  bool mostlyCjk() const { return flags_ & 1; }

  uint32_t textOffset() const { return textAt_; }  // file offset of the text
  uint32_t textSize() const { return textSize_; }
  // The text itself, if open() was given the whole file (else empty).
  std::string_view text() const;

  uint32_t sectionCount() const { return sectionCount_; }
  uint32_t sectionStart(uint32_t i) const;  // book text offsets; kNone if i is out of range
  uint32_t sectionEnd(uint32_t i) const;
  uint32_t sectionAt(uint32_t pos) const;  // the section holding pos (the last one if past the end)

  uint32_t tocCount() const { return tocCount_; }
  TocEntry toc(uint32_t i) const;
  // The contents entry a position is under: the last one starting at or before it, -1 if
  // the position comes before the first entry (or there are none).
  int tocAt(uint32_t pos) const;

 private:
  std::string_view str(uint32_t offset) const;

  const uint8_t* data_ = nullptr;
  size_t size_ = 0;
  uint32_t textAt_ = 0, textSize_ = 0, sectionsAt_ = 0, sectionCount_ = 0, tocAt_ = 0, tocCount_ = 0;
  uint32_t stringsAt_ = 0, stringsSize_ = 0;
  BookFormat format_ = BookFormat::Unknown;
  uint8_t flags_ = 0;
};

class Shelf {
 public:
  static constexpr size_t kHeaderSize = 48;
  static constexpr uint32_t kNone = 0xFFFFFFFF;

  struct Entry {
    uint32_t id = 0;  // names its files: /.dap/books/<8 hex digits>.dbk and .g4
    std::string_view title, author;
    std::string_view source;  // the original file on the card, e.g. "/Books/中文/雾港来信.epub"
    uint32_t textSize = 0;    // for the progress shown on the shelf: position / textSize
    BookFormat format = BookFormat::Unknown;
    bool ownCover = false;  // false: the cover is lettered with the title
    uint16_t tocCount = 0;
  };

  enum class Error { None, TooSmall, BadMagic, UnsupportedVersion, SizeMismatch, BadLayout, BadChecksum };

  Error open(const uint8_t* data, size_t size, bool verifyChecksum = true);
  bool isOpen() const { return data_ != nullptr; }

  uint32_t count() const { return count_; }
  Entry book(uint32_t i) const;            // sorted by title
  uint32_t byAuthor(uint32_t n) const;     // n-th book in author order (an index for book()), kNone if out of range
  uint32_t find(uint32_t id) const;        // index of the book with this id, kNone if none
  uint32_t builtUnixTime() const;

  // "/.dap/books/1a2b3c4d.dbk" and ".g4"; `out` needs 26 bytes.
  static void bookPath(uint32_t id, char* out);
  static void coverPath(uint32_t id, char* out);

 private:
  const uint8_t* data_ = nullptr;
  uint32_t count_ = 0, booksAt_ = 0, byAuthorAt_ = 0, stringsAt_ = 0, stringsSize_ = 0, recordSize_ = 0;
};
