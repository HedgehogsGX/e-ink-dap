// Reader layout benchmark, nothing to wire. Lays out a made-up 450 KB Chinese novel with
// an 18 px font the way the reader will (text from PSRAM, reader settings' defaults) and
// reports how long a section takes, which is what the first page turn into a new chapter
// or a font size change costs, and how long one page takes to lay out and draw.
// Files: tools/make_reader_bench.sh, then `pio run -e reader_bench -t upload`.
// Send "r" over serial to repeat, "p" to print the first page of every chapter as text.
#include <Arduino.h>
#include <esp_timer.h>

#include "bitmap_font.h"
#include "book.h"
#include "reader.h"
#include "settings.h"

extern const uint8_t bookStart[] asm("_binary_bench_reader_nosync_book_dbk_start");
extern const uint8_t bookEnd[] asm("_binary_bench_reader_nosync_book_dbk_end");
extern const uint8_t fontStart[] asm("_binary_bench_reader_nosync_font_dfn_start");
extern const uint8_t fontEnd[] asm("_binary_bench_reader_nosync_font_dfn_end");

static constexpr int kWidth = 240, kHeight = 416, kHeader = 24, kFooter = 24;
static uint8_t frame[kWidth * kHeight / 8];  // 1 bit per pixel, like the display's buffer

static uint8_t* bookData;
static uint8_t* fontData;
static size_t bookSize, fontSize;
static Book book;
static BitmapFont font;
static LayoutStyle style;

static uint8_t* toPsram(const uint8_t* start, const uint8_t* end, size_t* size) {
  *size = end - start;
  uint8_t* p = (uint8_t*)ps_malloc(*size);
  if (p) memcpy(p, start, *size);
  return p;
}

static std::string_view sectionText(uint32_t i) {
  return book.text().substr(book.sectionStart(i), book.sectionEnd(i) - book.sectionStart(i));
}

static void plot(int x, int y) {
  if (x >= 0 && x < kWidth && y >= 0 && y < kHeight) frame[(y * kWidth + x) / 8] |= 0x80 >> (x & 7);
}

// Lays out and draws one page into the frame buffer; returns the lines drawn.
static int drawPage(const ReaderSession& r, int marginX) {
  memset(frame, 0, sizeof frame);
  const PageLayout& page = r.page();
  for (const Line& line : page.lines) {
    int baseline = kHeader + line.y + (line.height + font.ascent() - font.descent()) / 2;
    TextLayout::forEachGlyph(r.sectionText(), r.sectionBase(), line, style, [&](uint32_t cp, int x, bool bold) {
      font.draw(cp, marginX + x, baseline, plot, bold);
    });
  }
  return (int)page.lines.size();
}

static void printPage(const ReaderSession& r) {
  for (const Line& line : r.page().lines) {
    std::string_view t = r.sectionText().substr(line.start - r.sectionBase(), line.end - line.start);
    std::string s;
    for (char c : t)
      if ((uint8_t)c >= 0x20) s += c;
    Serial.printf("  |%s%s\n", s.c_str(), line.hang ? "  (hangs)" : "");
  }
}

static void runBench(bool printChapters) {
  Settings settings;  // defaults: 18 px, line spacing 1.5, medium margins
  style.body = &font;
  style.heading = &font;  // only one size embedded
  style.bodySize = font.size();
  style.headingSize = font.size();
  style.width = kWidth - 2 * settings.marginPx();
  style.height = kHeight - kHeader - kFooter;
  style.lineSpacing = settings.lineSpacing;
  style.indentEms = settings.indentEms(book.mostlyCjk());
  style.justify = settings.justify;

  Serial.printf("\n===== Reader layout benchmark (CPU %lu MHz, text and font in PSRAM) =====\n", ESP.getCpuFreqMHz());
  Serial.printf("Book: %.*s, %lu bytes of text, %lu sections, %lu chapters. Font: %d px, %lu glyphs, %u bytes.\n",
                (int)book.title().size(), book.title().data(), (unsigned long)book.textSize(),
                (unsigned long)book.sectionCount(), (unsigned long)book.tocCount(), font.size(),
                (unsigned long)font.glyphCount(), (unsigned)fontSize);
  Serial.printf("Text area %d x %d px, %d px lines.\n", style.width, style.height,
                style.bodySize * style.lineSpacing / 100);

  int64_t totalUs = 0, worstUs = 0;
  uint32_t worstSection = 0, worstBytes = 0;
  size_t pages = 0;
  for (uint32_t s = 0; s < book.sectionCount(); s++) {
    std::string_view text = sectionText(s);
    int64_t t0 = esp_timer_get_time();
    std::vector<uint32_t> starts = TextLayout::paginate(text, book.sectionStart(s), style);
    int64_t us = esp_timer_get_time() - t0;
    totalUs += us;
    pages += starts.size();
    if (us > worstUs) {
      worstUs = us;
      worstSection = s;
      worstBytes = text.size();
    }
  }
  Serial.printf("Whole book: %u pages, laid out in %.1f ms = %.2f ms per 10 KB of text.\n", (unsigned)pages,
                totalUs / 1000.0, totalUs / 1000.0 / (book.textSize() / 10240.0));
  Serial.printf("Slowest section: #%lu, %lu bytes, %.1f ms (the wait on a page turn into it, or a font change).\n",
                (unsigned long)worstSection, (unsigned long)worstBytes, worstUs / 1000.0);

  // One page at a time, as when reading: next() within a section, then draw it.
  ReaderSession r;
  r.open(&book, sectionText, style, book.toc(1).pos);
  int64_t layoutUs = 0, drawUs = 0, worstTurn = 0;
  int turns = 0, lines = 0;
  for (; turns < 200; turns++) {
    int64_t t0 = esp_timer_get_time();
    if (!r.next()) break;
    int64_t t1 = esp_timer_get_time();
    lines += drawPage(r, settings.marginPx());
    int64_t t2 = esp_timer_get_time();
    layoutUs += t1 - t0;
    drawUs += t2 - t1;
    worstTurn = std::max(worstTurn, t1 - t0);
  }
  Serial.printf("Page turn: %.2f ms to lay out the next page (worst %.1f ms, at a section start), "
                "%.2f ms to draw it (%.1f lines) - %d turns.\n",
                layoutUs / 1000.0 / turns, worstTurn / 1000.0, drawUs / 1000.0 / turns, (double)lines / turns, turns);

  // Font size change: lay out the section again at another size (same glyphs, so the
  // timing is the layout's; real sizes come from other font files).
  int64_t t0 = esp_timer_get_time();
  LayoutStyle bigger = style;
  bigger.bodySize = 24;
  r.setStyle(bigger);
  r.setStyle(style);
  Serial.printf("Font size change and back: %.1f ms.\n", (esp_timer_get_time() - t0) / 1000.0);
  Serial.printf("Free heap %u bytes, free PSRAM %u bytes.\n", (unsigned)ESP.getFreeHeap(), (unsigned)ESP.getFreePsram());

  r.goToChapter(1);
  Serial.printf("\nFirst page of %.*s, as laid out:\n", (int)book.toc(1).title.size(), book.toc(1).title.data());
  printPage(r);
  if (printChapters) {
    for (uint32_t c = 2; c < book.tocCount(); c++) {
      r.goToChapter(c);
      Serial.printf("\nChapter %lu:\n", (unsigned long)c);
      printPage(r);
    }
  }
}

void setup() {
  Serial.begin(115200);
  for (uint32_t start = millis(); !Serial && millis() - start < 3000;) delay(10);
  bookData = toPsram(bookStart, bookEnd, &bookSize);
  fontData = toPsram(fontStart, fontEnd, &fontSize);
  if (!bookData || !fontData) {
    Serial.println("Cannot allocate PSRAM for the book and font.");
    return;
  }
  Book::Error be = book.open(bookData, bookSize, bookSize, true);
  BitmapFont::Error fe = font.open(fontData, fontSize);
  if (be != Book::Error::None || fe != BitmapFont::Error::None) {
    Serial.printf("Book: %s. Font: %s. Run tools/make_reader_bench.sh and build again.\n", Book::errorText(be),
                  BitmapFont::errorText(fe));
    return;
  }
  runBench(false);
}

void loop() {
  if (Serial.available()) {
    char c = Serial.read();
    if (c == 'r' || c == 'p') runBench(c == 'p');
  }
  delay(10);
}
