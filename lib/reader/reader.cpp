#include "reader.h"

#include <algorithm>
#include <cstdio>
#include <cstdlib>

// ---- ReaderSession ----

void ReaderSession::open(const Book* book, SectionText text, const LayoutStyle& style, uint32_t position) {
  book_ = book;
  fetch_ = std::move(text);
  style_ = style;
  section_ = Book::kNone;
  goTo(position);
}

void ReaderSession::loadSection(uint32_t s) {
  section_ = s;
  base_ = book_->sectionStart(s);
  text_ = fetch_(s);
  starts_ = TextLayout::paginate(text_, base_, style_);
}

void ReaderSession::showPage(size_t index) {
  pageIndex_ = std::min(index, starts_.size() - 1);
  TextLayout::layoutPage(text_, base_, starts_[pageIndex_], style_, &page_);
}

void ReaderSession::goTo(uint32_t position) {
  if (!book_) return;
  position = std::min(position, book_->textSize() ? book_->textSize() - 1 : 0);
  uint32_t s = book_->sectionAt(position);
  if (s != section_) loadSection(s);
  showPage(TextLayout::pageContaining(starts_, position));
}

void ReaderSession::setStyle(const LayoutStyle& style) {
  if (!book_) return;
  uint32_t keep = page_.start;
  style_ = style;
  section_ = Book::kNone;  // lay out again
  goTo(keep);
}

void ReaderSession::goToChapter(uint32_t tocIndex) {
  if (book_ && tocIndex < book_->tocCount()) goTo(book_->toc(tocIndex).pos);
}

bool ReaderSession::next() {
  if (!book_) return false;
  if (pageIndex_ + 1 < starts_.size()) {
    showPage(pageIndex_ + 1);
    return true;
  }
  if (section_ + 1 >= book_->sectionCount()) return false;
  loadSection(section_ + 1);
  showPage(0);
  return true;
}

bool ReaderSession::prev() {
  if (!book_) return false;
  if (pageIndex_ > 0) {
    showPage(pageIndex_ - 1);
    return true;
  }
  if (section_ == 0) return false;
  loadSection(section_ - 1);
  showPage(starts_.size() - 1);
  return true;
}

bool ReaderSession::atEnd() const {
  return book_ && section_ + 1 >= book_->sectionCount() && pageIndex_ + 1 >= starts_.size();
}

uint32_t ReaderSession::permille() const {
  if (!book_ || book_->textSize() == 0) return 0;
  if (atEnd()) return 1000;
  return (uint32_t)((uint64_t)page_.end * 1000 / book_->textSize());
}

int ReaderSession::chapter() const { return book_ ? book_->tocAt(page_.start) : -1; }

std::string ReaderSession::snippet(size_t maxBytes) const {
  std::string out;
  if (!book_) return out;
  size_t i = page_.start - base_, end = std::min<size_t>(page_.end - base_, text_.size());
  while (i < end && out.size() < maxBytes) {
    uint8_t c = (uint8_t)text_[i];
    if (c == '\n') {
      if (!out.empty() && out.back() != ' ') out += ' ';
      i++;
      continue;
    }
    if (c < 0x20) {  // style bytes and bold marks
      i++;
      continue;
    }
    size_t len = c < 0x80 ? 1 : c < 0xE0 ? 2 : c < 0xF0 ? 3 : 4;
    if (out.size() + len > maxBytes) break;
    out.append(text_.substr(i, len));
    i += len;
  }
  while (!out.empty() && out.back() == ' ') out.pop_back();
  return out;
}

// ---- ReadingState ----

namespace {
const char kHeader[] = "# E-ink DAP reading state 1";
}

bool ReadingState::parse(std::string_view text) {
  books_.clear();
  clock_ = 0;
  size_t nl = text.find('\n');
  std::string_view first = text.substr(0, nl);
  while (!first.empty() && (first.back() == '\r' || first.back() == ' ')) first.remove_suffix(1);
  if (first != kHeader) return false;
  while (nl != std::string_view::npos) {
    size_t from = nl + 1;
    nl = text.find('\n', from);
    std::string line(text.substr(from, nl == std::string_view::npos ? std::string_view::npos : nl - from));
    if (line.empty() || line[0] == '#') continue;
    // id (hex) position opened finished [bookmark ...]
    const char* p = line.c_str();
    char* e;
    Entry b;
    b.id = (uint32_t)strtoul(p, &e, 16);
    if (e == p) continue;
    p = e;
    unsigned long v[3];
    bool ok = true;
    for (int k = 0; k < 3 && ok; k++) {
      v[k] = strtoul(p, &e, 10);
      ok = e != p;
      p = e;
    }
    if (!ok || find(b.id)) continue;
    b.position = (uint32_t)v[0];
    b.opened = (uint32_t)v[1];
    b.finished = v[2] != 0;
    for (;;) {
      unsigned long m = strtoul(p, &e, 10);
      if (e == p) break;
      p = e;
      if (b.bookmarks.size() < kMaxBookmarks) b.bookmarks.push_back((uint32_t)m);
    }
    std::sort(b.bookmarks.begin(), b.bookmarks.end());
    b.bookmarks.erase(std::unique(b.bookmarks.begin(), b.bookmarks.end()), b.bookmarks.end());
    clock_ = std::max(clock_, b.opened);
    books_.push_back(std::move(b));
  }
  return true;
}

std::string ReadingState::serialize() const {
  std::string out = std::string(kHeader) + "\n# book, position, last opened, finished, bookmarks\n";
  char buf[48];
  for (const Entry& b : books_) {
    snprintf(buf, sizeof buf, "%08lx %lu %lu %d", (unsigned long)b.id, (unsigned long)b.position,
             (unsigned long)b.opened, b.finished ? 1 : 0);
    out += buf;
    for (uint32_t m : b.bookmarks) {
      snprintf(buf, sizeof buf, " %lu", (unsigned long)m);
      out += buf;
    }
    out += '\n';
  }
  return out;
}

const ReadingState::Entry* ReadingState::find(uint32_t id) const {
  for (const Entry& b : books_)
    if (b.id == id) return &b;
  return nullptr;
}

ReadingState::Entry& ReadingState::entry(uint32_t id) {
  for (Entry& b : books_)
    if (b.id == id) return b;
  books_.push_back(Entry());
  books_.back().id = id;
  return books_.back();
}

uint32_t ReadingState::position(uint32_t id) const {
  const Entry* b = find(id);
  return b ? b->position : 0;
}

void ReadingState::opened(uint32_t id) { entry(id).opened = ++clock_; }
void ReadingState::setPosition(uint32_t id, uint32_t position) { entry(id).position = position; }
void ReadingState::setFinished(uint32_t id, bool finished) { entry(id).finished = finished; }

bool ReadingState::hasBookmark(uint32_t id, uint32_t pageStart, uint32_t pageEnd) const {
  const Entry* b = find(id);
  if (!b) return false;
  auto it = std::lower_bound(b->bookmarks.begin(), b->bookmarks.end(), pageStart);
  return it != b->bookmarks.end() && *it < pageEnd;
}

bool ReadingState::toggleBookmark(uint32_t id, uint32_t pageStart, uint32_t pageEnd) {
  Entry& b = entry(id);
  auto first = std::lower_bound(b.bookmarks.begin(), b.bookmarks.end(), pageStart);
  auto last = std::lower_bound(first, b.bookmarks.end(), pageEnd);
  if (first != last) {
    b.bookmarks.erase(first, last);
    return false;
  }
  if (b.bookmarks.size() >= kMaxBookmarks) return false;
  b.bookmarks.insert(first, pageStart);
  return true;
}

std::vector<uint32_t> ReadingState::recent() const {
  std::vector<const Entry*> opened;
  for (const Entry& b : books_)
    if (b.opened) opened.push_back(&b);
  std::sort(opened.begin(), opened.end(), [](const Entry* a, const Entry* b) { return a->opened > b->opened; });
  std::vector<uint32_t> ids;
  for (const Entry* b : opened) ids.push_back(b->id);
  return ids;
}

void ReadingState::forget(uint32_t id) {
  books_.erase(std::remove_if(books_.begin(), books_.end(), [id](const Entry& b) { return b.id == id; }),
               books_.end());
}
