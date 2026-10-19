// Host tests for lib/book and lib/reader: pio test -e native
//
// The fixtures are real output of the PC tools, so the Python writer and the C++ reader
// are checked against each other. To remake them:
//   uv run tools/make_sample_books.py --long
//   uv run tools/books.py --convert "sample_books.nosync/Books/中文/雾港来信.epub" -o test/test_reader/sample_book.dbk
//   SOURCE_DATE_EPOCH=1792108800 uv run tools/books.py --force sample_books.nosync
//   cp sample_books.nosync/.dap/books.idx test/test_reader/sample_shelf.idx
#include <unity.h>

#include <cstdio>
#include <string>
#include <vector>

#include "book.h"
#include "g4image.h"
#include "reader.h"

static std::vector<uint8_t> bookFile, shelfFile, coverFile;

static std::vector<uint8_t> readFixture(const char* name) {
  std::string path = __FILE__;
  path = path.substr(0, path.find_last_of("/\\") + 1) + name;
  std::vector<uint8_t> data;
  if (FILE* f = fopen(path.c_str(), "rb")) {
    int c;
    while ((c = fgetc(f)) != EOF) data.push_back((uint8_t)c);
    fclose(f);
  }
  return data;
}

static std::string s(std::string_view v) { return std::string(v); }

struct FakeFont : FontMetrics {
  int cjk = 10;
  int advance(uint32_t c) const override { return booktext::isCjk(c) ? cjk : cjk / 2; }
};
static FakeFont small, big;

static LayoutStyle style(const FakeFont& f) {
  LayoutStyle st;
  st.body = &f;
  st.bodySize = f.cjk;
  st.headingSize = f.cjk;
  st.width = 100;
  st.height = 60;  // 4 lines of 15 px with the small font
  return st;
}

static Book openBook() {
  Book b;
  TEST_ASSERT_EQUAL(Book::Error::None, b.open(bookFile.data(), bookFile.size(), bookFile.size(), true));
  return b;
}

// Section text straight from the whole file in memory.
static ReaderSession::SectionText sections(const Book& b) {
  return [&b](uint32_t i) { return b.text().substr(b.sectionStart(i), b.sectionEnd(i) - b.sectionStart(i)); };
}

void setUp() {}
void tearDown() {}

static void test_fixtures_present() {
  TEST_ASSERT_TRUE_MESSAGE(bookFile.size() > 64 && shelfFile.size() > 48 && coverFile.size() > 8,
                           "test/test_reader fixtures missing");
}

static void test_book_header_and_contents() {
  Book b = openBook();
  TEST_ASSERT_EQUAL_STRING("雾港来信", s(b.title()).c_str());
  TEST_ASSERT_EQUAL_STRING("林知秋", s(b.author()).c_str());
  TEST_ASSERT_EQUAL_STRING("zh", s(b.language()).c_str());
  TEST_ASSERT_EQUAL(BookFormat::Epub, b.format());
  TEST_ASSERT_TRUE(b.mostlyCjk());
  TEST_ASSERT_EQUAL_UINT32(1741, b.textSize());
  TEST_ASSERT_EQUAL_UINT32(5, b.sectionCount());
  TEST_ASSERT_EQUAL_UINT32(87, b.sectionStart(1));
  TEST_ASSERT_EQUAL_UINT32(1741, b.sectionEnd(4));
  TEST_ASSERT_EQUAL_UINT32(Book::kNone, b.sectionStart(5));
  TEST_ASSERT_EQUAL_UINT32(1, b.sectionAt(397));
  TEST_ASSERT_EQUAL_UINT32(4, b.sectionAt(5000));
  TEST_ASSERT_EQUAL_UINT32(5, b.tocCount());
  Book::TocEntry e = b.toc(2);
  TEST_ASSERT_EQUAL_STRING("信封", s(e.title).c_str());
  TEST_ASSERT_EQUAL(2, e.level);
  TEST_ASSERT_EQUAL_UINT32(751, e.pos);
  TEST_ASSERT_EQUAL(1, b.tocAt(397));  // inside 第一章
  TEST_ASSERT_EQUAL(2, b.tocAt(800));
  TEST_ASSERT_EQUAL(0, b.tocAt(0));
  // Text: the first chapter starts with its heading paragraph.
  std::string_view ch1 = b.text().substr(87);
  TEST_ASSERT_EQUAL_UINT8(booktext::kH2, (uint8_t)ch1[0]);
  TEST_ASSERT_EQUAL_STRING("第一章 无名信", s(ch1.substr(1, ch1.find('\n') - 1)).c_str());
}

static void test_book_opens_from_its_front_only() {
  uint32_t front = Book::frontSize(bookFile.data(), 64);
  TEST_ASSERT_EQUAL_UINT32(bookFile.size() - 1741, front);
  Book b;
  TEST_ASSERT_EQUAL(Book::Error::None, b.open(bookFile.data(), front, bookFile.size()));
  TEST_ASSERT_EQUAL_STRING("雾港来信", s(b.title()).c_str());
  TEST_ASSERT_TRUE(b.text().empty());
  TEST_ASSERT_EQUAL_UINT32(front, b.textOffset());
  TEST_ASSERT_EQUAL(Book::Error::BadLayout, b.open(bookFile.data(), front - 1, bookFile.size()));
}

static void test_book_rejects_damaged_files() {
  Book b;
  std::vector<uint8_t> d = bookFile;
  d.back() ^= 1;
  TEST_ASSERT_EQUAL(Book::Error::BadChecksum, b.open(d.data(), d.size(), d.size(), true));
  TEST_ASSERT_EQUAL(Book::Error::SizeMismatch, b.open(d.data(), d.size(), d.size() + 1));
  d = bookFile;
  d[64 + 4] = 0;  // second section start = 0: not rising
  d[64 + 5] = 0;
  TEST_ASSERT_EQUAL(Book::Error::BadLayout, b.open(d.data(), d.size(), d.size()));
  TEST_ASSERT_EQUAL(0, Book::frontSize(shelfFile.data(), shelfFile.size()));
}

static void test_shelf() {
  Shelf sh;
  TEST_ASSERT_EQUAL(Shelf::Error::None, sh.open(shelfFile.data(), shelfFile.size()));
  TEST_ASSERT_EQUAL_UINT32(9, sh.count());
  uint32_t i = sh.find(0x652fee49);
  TEST_ASSERT_EQUAL_UINT32(8, i);  // sorted by title: Latin first, kana, then hanzi
  Shelf::Entry e = sh.book(i);
  TEST_ASSERT_EQUAL_STRING("雾港来信", s(e.title).c_str());
  TEST_ASSERT_EQUAL_STRING("/Books/中文/雾港来信.epub", s(e.source).c_str());
  TEST_ASSERT_EQUAL(BookFormat::Epub, e.format);
  TEST_ASSERT_TRUE(e.ownCover);
  TEST_ASSERT_EQUAL_UINT32(1741, e.textSize);
  TEST_ASSERT_EQUAL(5, e.tocCount);
  TEST_ASSERT_FALSE(sh.book(sh.find(0x6ca3c136)).ownCover);  // The Lighthouse Ledger: lettered
  TEST_ASSERT_EQUAL_STRING("Mara Quill", s(sh.book(sh.byAuthor(0)).author).c_str());
  TEST_ASSERT_TRUE(sh.book(sh.byAuthor(8)).author.empty());  // unknown authors last
  TEST_ASSERT_EQUAL_UINT32(Shelf::kNone, sh.find(1));
  TEST_ASSERT_EQUAL_UINT32(1792108800, sh.builtUnixTime());
  char path[26];
  Shelf::bookPath(0x0a0b0c0d, path);
  TEST_ASSERT_EQUAL_STRING("/.dap/books/0a0b0c0d.dbk", path);
  Shelf::coverPath(e.id, path);
  TEST_ASSERT_EQUAL_STRING("/.dap/books/652fee49.g4", path);
  std::vector<uint8_t> d = shelfFile;
  d[60] ^= 1;
  TEST_ASSERT_EQUAL(Shelf::Error::BadChecksum, sh.open(d.data(), d.size()));
}

static void test_cover_is_a_72_by_96_image() {
  G4Image img;
  TEST_ASSERT_TRUE(img.open(coverFile.data(), coverFile.size()));
  TEST_ASSERT_EQUAL(72, img.width());
  TEST_ASSERT_EQUAL(96, img.height());
}

static void test_session_pages_through_the_whole_book_and_back() {
  Book b = openBook();
  ReaderSession r;
  r.open(&b, sections(b), style(small));
  TEST_ASSERT_EQUAL_UINT32(0, r.position());
  std::vector<uint32_t> forward{r.position()};
  while (r.next()) {
    TEST_ASSERT_TRUE(r.position() > forward.back());
    forward.push_back(r.position());
  }
  TEST_ASSERT_TRUE(forward.size() > 2 * b.sectionCount());  // several pages per section
  TEST_ASSERT_TRUE(r.atEnd());
  TEST_ASSERT_EQUAL_UINT32(1000, r.permille());
  TEST_ASSERT_EQUAL_UINT32(4, r.section());
  std::vector<uint32_t> backward{r.position()};
  while (r.prev()) backward.insert(backward.begin(), r.position());
  TEST_ASSERT_EQUAL(forward.size(), backward.size());
  for (size_t k = 0; k < forward.size(); k++) TEST_ASSERT_EQUAL_UINT32(forward[k], backward[k]);
  // Every chapter starts a page.
  for (uint32_t c = 0; c < b.tocCount(); c++) {
    bool found = false;
    for (uint32_t p : forward) found |= p == b.toc(c).pos;
    TEST_ASSERT_TRUE(found);
  }
}

static void test_session_goes_to_positions_and_chapters() {
  Book b = openBook();
  ReaderSession r;
  r.open(&b, sections(b), style(small), 397);  // inside 第一章
  TEST_ASSERT_TRUE(r.page().start <= 397 && 397 < r.page().end);
  TEST_ASSERT_EQUAL(1, r.chapter());
  TEST_ASSERT_TRUE(r.pageInSection() > 0);
  TEST_ASSERT_TRUE(r.permille() > 200 && r.permille() < 500);
  r.goToChapter(3);
  TEST_ASSERT_EQUAL_UINT32(964, r.position());
  TEST_ASSERT_EQUAL_STRING("第二章 潮汐表 祖父留下的", r.snippet(35).c_str());
  r.goTo(999999);  // past the end: the last page
  TEST_ASSERT_TRUE(r.atEnd());
}

static void test_session_keeps_the_place_when_the_font_changes() {
  Book b = openBook();
  big.cjk = 20;
  ReaderSession r;
  r.open(&b, sections(b), style(small), 1300);
  uint32_t was = r.position();
  r.setStyle(style(big));
  TEST_ASSERT_TRUE(r.page().start <= was && was < r.page().end);
  // Each change keeps the first character of the page you are on.
  uint32_t bigStart = r.page().start;
  size_t bigPages = r.pagesInSection();
  r.setStyle(style(small));
  TEST_ASSERT_TRUE(r.pagesInSection() < bigPages);
  TEST_ASSERT_TRUE(r.page().start <= bigStart && bigStart < r.page().end);
}

static void test_reading_state_round_trip() {
  ReadingState st;
  st.opened(0x652fee49);
  st.setPosition(0x652fee49, 964);
  TEST_ASSERT_TRUE(st.toggleBookmark(0x652fee49, 100, 160));
  TEST_ASSERT_TRUE(st.toggleBookmark(0x652fee49, 964, 1000));
  st.opened(0x6ca3c136);
  st.setFinished(0x6ca3c136, true);
  ReadingState back;
  TEST_ASSERT_TRUE(back.parse(st.serialize()));
  TEST_ASSERT_EQUAL_STRING(st.serialize().c_str(), back.serialize().c_str());
  TEST_ASSERT_EQUAL_UINT32(964, back.position(0x652fee49));
  TEST_ASSERT_EQUAL(2, back.find(0x652fee49)->bookmarks.size());
  TEST_ASSERT_TRUE(back.find(0x6ca3c136)->finished);
  std::vector<uint32_t> recent = back.recent();
  TEST_ASSERT_EQUAL(2, recent.size());
  TEST_ASSERT_EQUAL_HEX32(0x6ca3c136, recent[0]);
  back.opened(0x652fee49);  // opening keeps counting from what was saved
  TEST_ASSERT_EQUAL_HEX32(0x652fee49, back.recent()[0]);
}

static void test_bookmarks_belong_to_pages() {
  ReadingState st;
  TEST_ASSERT_FALSE(st.hasBookmark(1, 0, 50));
  TEST_ASSERT_TRUE(st.toggleBookmark(1, 0, 50));
  TEST_ASSERT_TRUE(st.hasBookmark(1, 0, 50));
  // After a font change the page is 0..80: the bookmark at 0 is still on it.
  TEST_ASSERT_TRUE(st.hasBookmark(1, 0, 80));
  TEST_ASSERT_FALSE(st.hasBookmark(1, 50, 100));
  TEST_ASSERT_FALSE(st.toggleBookmark(1, 0, 80));  // removes it
  TEST_ASSERT_FALSE(st.hasBookmark(1, 0, 80));
  for (uint32_t k = 0; k < ReadingState::kMaxBookmarks + 5; k++) st.toggleBookmark(1, k * 10, k * 10 + 10);
  TEST_ASSERT_EQUAL(ReadingState::kMaxBookmarks, st.find(1)->bookmarks.size());
}

static void test_reading_state_skips_what_it_cannot_read() {
  ReadingState st;
  TEST_ASSERT_FALSE(st.parse("something else\n0000002a 5 1 0\n"));
  TEST_ASSERT_EQUAL(0, st.size());
  TEST_ASSERT_TRUE(st.parse("# E-ink DAP reading state 1\r\n"
                            "0000002a 5 3 0 30 10 10\n"
                            "garbage\n"
                            "0000002b 7\n"
                            "0000002a 9 9 0\n"  // the same book again: the first line wins
                            "0000002c 1 2 1"));  // no newline at the end
  TEST_ASSERT_EQUAL(2, st.size());
  TEST_ASSERT_EQUAL_UINT32(5, st.position(0x2a));
  TEST_ASSERT_EQUAL(2, st.find(0x2a)->bookmarks.size());  // sorted, duplicates dropped
  TEST_ASSERT_EQUAL_UINT32(10, st.find(0x2a)->bookmarks[0]);
  TEST_ASSERT_TRUE(st.find(0x2c)->finished);
  st.forget(0x2a);
  TEST_ASSERT_NULL(st.find(0x2a));
}

int main() {
  bookFile = readFixture("sample_book.dbk");
  shelfFile = readFixture("sample_shelf.idx");
  coverFile = readFixture("sample_book.g4");
  UNITY_BEGIN();
  RUN_TEST(test_fixtures_present);
  if (bookFile.size() > 64 && shelfFile.size() > 48 && coverFile.size() > 8) {
    RUN_TEST(test_book_header_and_contents);
    RUN_TEST(test_book_opens_from_its_front_only);
    RUN_TEST(test_book_rejects_damaged_files);
    RUN_TEST(test_shelf);
    RUN_TEST(test_cover_is_a_72_by_96_image);
    RUN_TEST(test_session_pages_through_the_whole_book_and_back);
    RUN_TEST(test_session_goes_to_positions_and_chapters);
    RUN_TEST(test_session_keeps_the_place_when_the_font_changes);
  }
  RUN_TEST(test_reading_state_round_trip);
  RUN_TEST(test_bookmarks_belong_to_pages);
  RUN_TEST(test_reading_state_skips_what_it_cannot_read);
  return UNITY_END();
}
