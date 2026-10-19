// The reader's model: an open book with its current page (ReaderSession), and where you
// are in every book (ReadingState). Plain C++17, no Arduino dependency.
//
// Like ImmerseRead, a position is an offset in the book's text, not a page number, so
// changing the font size reopens the page that holds the same text. Page numbers are only
// known within the current section (the reader lays out one section at a time); progress
// through the book is shown as a fraction of the text.
#pragma once
#include <cstdint>
#include <functional>
#include <string>
#include <string_view>
#include <vector>

#include "book.h"
#include "text_layout.h"

class ReaderSession {
 public:
  // Returns the text of section i: the book text from sectionStart(i) to sectionEnd(i).
  // The view must stay valid until the next call (on the board: read it from the card into
  // a buffer; on the host: a slice of the whole file).
  using SectionText = std::function<std::string_view(uint32_t section)>;

  // Opens at the page holding `position` (0 = the start).
  void open(const Book* book, SectionText text, const LayoutStyle& style, uint32_t position = 0);
  bool isOpen() const { return book_ != nullptr; }

  // New font size, margins, ...: lays the section out again and stays on the page that
  // holds the first character of the page you were on.
  void setStyle(const LayoutStyle& style);

  bool next();  // false at the end of the book
  bool prev();  // false at the start
  void goTo(uint32_t position);
  void goToChapter(uint32_t tocIndex);

  const PageLayout& page() const { return page_; }
  uint32_t position() const { return page_.start; }  // save this
  uint32_t section() const { return section_; }
  uint32_t sectionBase() const { return base_; }
  std::string_view sectionText() const { return text_; }
  size_t pageInSection() const { return pageIndex_; }  // 0-based
  size_t pagesInSection() const { return starts_.size(); }
  uint32_t permille() const;     // how far through the book the page ends, 0-1000
  int chapter() const;           // contents entry of this page, -1 before the first
  bool atEnd() const;
  const LayoutStyle& style() const { return style_; }

  // Text of the current page, without style bytes and bold marks, at most maxBytes long
  // (for a bookmark's snippet).
  std::string snippet(size_t maxBytes = 60) const;

 private:
  void loadSection(uint32_t s);
  void showPage(size_t index);

  const Book* book_ = nullptr;
  SectionText fetch_;
  LayoutStyle style_;
  uint32_t section_ = 0, base_ = 0;
  std::string_view text_;
  std::vector<uint32_t> starts_;
  size_t pageIndex_ = 0;
  PageLayout page_;
};

// Reading position, last-opened order and bookmarks of every book, kept in a small text
// file on the card (/.dap/reading.txt, docs/formats.md) that the player rewrites.
class ReadingState {
 public:
  static constexpr size_t kMaxBookmarks = 100;

  struct Entry {
    uint32_t id = 0;
    uint32_t position = 0;
    uint32_t opened = 0;  // a counter: the higher, the more recently opened (no clock on the board)
    bool finished = false;
    std::vector<uint32_t> bookmarks;  // page start offsets, sorted
  };

  // Replaces everything with the file's contents; lines it can't read are skipped. False
  // if it isn't a reading state file (version 1), and the state is then empty.
  bool parse(std::string_view text);
  std::string serialize() const;

  const Entry* find(uint32_t id) const;
  uint32_t position(uint32_t id) const;  // 0 if never opened
  void opened(uint32_t id);              // makes it the most recently read book
  void setPosition(uint32_t id, uint32_t position);
  void setFinished(uint32_t id, bool finished);
  // Bookmarks belong to a page: [pageStart, pageEnd). Toggling removes any bookmark on the
  // page, or adds one at pageStart. Returns whether the page is bookmarked afterwards.
  bool toggleBookmark(uint32_t id, uint32_t pageStart, uint32_t pageEnd);
  bool hasBookmark(uint32_t id, uint32_t pageStart, uint32_t pageEnd) const;
  // Books by last opened, most recent first (never-opened books aren't in it).
  std::vector<uint32_t> recent() const;
  void forget(uint32_t id);
  size_t size() const { return books_.size(); }

 private:
  Entry& entry(uint32_t id);
  std::vector<Entry> books_;
  uint32_t clock_ = 0;
};
