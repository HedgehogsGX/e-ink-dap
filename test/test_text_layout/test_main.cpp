// Host tests for lib/text_layout: pio test -e native
// A made-up font: CJK characters 10 px wide, everything else 5 px.
#include <unity.h>

#include <string>
#include <vector>

#include "text_layout.h"

struct FakeFont : FontMetrics {
  int cjk = 10, other = 5;
  int advance(uint32_t c) const override { return booktext::isCjk(c) ? cjk : other; }
};

static FakeFont font;

static LayoutStyle style(int width, int height = 1000) {
  LayoutStyle st;
  st.body = &font;
  st.bodySize = 10;
  st.headingSize = 10;
  st.width = width;
  st.height = height;
  st.lineSpacing = 150;  // 15 px lines
  st.indentEms = 0;
  return st;
}

static PageLayout page(const std::string& text, const LayoutStyle& st, uint32_t start = 0) {
  PageLayout p;
  TextLayout::layoutPage(text, 0, start, st, &p);
  return p;
}

static std::string lineText(const std::string& text, const Line& l) { return text.substr(l.start, l.end - l.start); }

void setUp() {}
void tearDown() {}

static void test_latin_wraps_at_spaces_and_justifies() {
  std::string t = "aaaa bbbb cccc dddd\n";
  PageLayout p = page(t, style(50));
  TEST_ASSERT_EQUAL(2, p.lines.size());
  TEST_ASSERT_EQUAL_STRING("aaaa bbbb", lineText(t, p.lines[0]).c_str());
  TEST_ASSERT_EQUAL(45, p.lines[0].width);
  TEST_ASSERT_EQUAL(5, p.lines[0].extra);  // spread at the one space
  TEST_ASSERT_EQUAL(1, p.lines[0].gaps);
  TEST_ASSERT_EQUAL_STRING("cccc dddd", lineText(t, p.lines[1]).c_str());
  TEST_ASSERT_EQUAL(0, p.lines[1].extra);  // a paragraph's last line isn't justified
  TEST_ASSERT_EQUAL_UINT32(t.size(), p.end);
}

static void test_cjk_breaks_between_any_characters() {
  std::string t = "一二三四五六七\n";
  PageLayout p = page(t, style(45));
  TEST_ASSERT_EQUAL(2, p.lines.size());
  TEST_ASSERT_EQUAL_STRING("一二三四", lineText(t, p.lines[0]).c_str());
  TEST_ASSERT_EQUAL(40, p.lines[0].width);
  TEST_ASSERT_EQUAL(5, p.lines[0].extra);
  TEST_ASSERT_EQUAL(3, p.lines[0].gaps);
}

static void test_closing_bracket_takes_the_character_before_it_along() {
  std::string t = "一二三四」五六\n";
  PageLayout p = page(t, style(40));
  TEST_ASSERT_EQUAL_STRING("一二三", lineText(t, p.lines[0]).c_str());
  TEST_ASSERT_EQUAL(10, p.lines[0].extra);
  TEST_ASSERT_EQUAL_STRING("四」五六", lineText(t, p.lines[1]).c_str());
}

static void test_comma_hangs_in_the_margin() {
  std::string t = "一二三四，五六\n";
  LayoutStyle st = style(40);
  PageLayout p = page(t, st);
  TEST_ASSERT_EQUAL_STRING("一二三四，", lineText(t, p.lines[0]).c_str());
  TEST_ASSERT_TRUE(p.lines[0].hang);
  TEST_ASSERT_EQUAL(40, p.lines[0].width);  // the comma isn't counted
  std::vector<int> xs;
  TextLayout::forEachGlyph(t, 0, p.lines[0], st, [&](uint32_t, int x, bool) { xs.push_back(x); });
  TEST_ASSERT_EQUAL(5, xs.size());
  TEST_ASSERT_EQUAL(40, xs[4]);  // right of the text area
  TEST_ASSERT_EQUAL_STRING("五六", lineText(t, p.lines[1]).c_str());
}

static void test_opening_bracket_never_ends_a_line() {
  std::string t = "一二三「四五」\n";
  PageLayout p = page(t, style(40));
  TEST_ASSERT_EQUAL_STRING("一二三", lineText(t, p.lines[0]).c_str());
  TEST_ASSERT_EQUAL_STRING("「四五」", lineText(t, p.lines[1]).c_str());
}

static void test_indent_only_on_a_paragraphs_first_line() {
  std::string t = "一二三四五六\n\x0b七八九\n";
  LayoutStyle st = style(40);
  st.indentEms = 2;
  st.paragraphSpacing = 4;
  PageLayout p = page(t, st);
  TEST_ASSERT_EQUAL(3, p.lines.size());
  TEST_ASSERT_EQUAL(20, p.lines[0].x);
  TEST_ASSERT_EQUAL_STRING("一二", lineText(t, p.lines[0]).c_str());
  TEST_ASSERT_EQUAL(0, p.lines[1].x);
  // A line-break paragraph continues the one before: no indent, no paragraph space.
  TEST_ASSERT_EQUAL(0, p.lines[2].x);
  TEST_ASSERT_EQUAL(30, p.lines[2].y);
}

static void test_word_longer_than_the_line_is_cut() {
  std::string t = "abcdefghijklmnop\n";
  PageLayout p = page(t, style(40));
  TEST_ASSERT_EQUAL_STRING("abcdefgh", lineText(t, p.lines[0]).c_str());
  TEST_ASSERT_EQUAL_STRING("ijklmnop", lineText(t, p.lines[1]).c_str());
}

static void test_breaks_after_a_hyphen() {
  std::string t = "well-known words\n";
  PageLayout p = page(t, style(40));
  TEST_ASSERT_EQUAL_STRING("well-", lineText(t, p.lines[0]).c_str());
  TEST_ASSERT_EQUAL_STRING("known", lineText(t, p.lines[1]).c_str());
  TEST_ASSERT_EQUAL_STRING("words", lineText(t, p.lines[2]).c_str());
}

static void test_bold_glyphs_are_wider() {
  std::string t = "\x0e一\x0f二\n";
  LayoutStyle st = style(100);
  PageLayout p = page(t, st);
  TEST_ASSERT_EQUAL(21, p.lines[0].width);
  std::vector<bool> bold;
  TextLayout::forEachGlyph(t, 0, p.lines[0], st, [&](uint32_t, int, bool b) { bold.push_back(b); });
  TEST_ASSERT_EQUAL(2, bold.size());
  TEST_ASSERT_TRUE(bold[0]);
  TEST_ASSERT_FALSE(bold[1]);
}

static void test_preformatted_keeps_spaces_and_centered_is_centered() {
  std::string t = "\x06" "a  b\n\x07一二\n\x08\n";
  PageLayout p = page(t, style(100));
  TEST_ASSERT_EQUAL(3, p.lines.size());
  TEST_ASSERT_EQUAL(20, p.lines[0].width);
  TEST_ASSERT_EQUAL(0, p.lines[0].extra);
  TEST_ASSERT_EQUAL(40, p.lines[1].x);  // (100 - 20) / 2
  TEST_ASSERT_EQUAL(booktext::kRule, p.lines[2].style);
  TEST_ASSERT_EQUAL_UINT32(p.lines[2].start, p.lines[2].end);
}

static void test_malformed_utf8_does_not_stop_layout() {
  std::string t = "\xff\xfe" "abc\xe4\xb8\n";
  PageLayout p = page(t, style(100));
  TEST_ASSERT_EQUAL(1, p.lines.size());
  int count = 0;
  TextLayout::forEachGlyph(t, 0, p.lines[0], style(100), [&](uint32_t, int, bool) { count++; });
  TEST_ASSERT_EQUAL(7, count);  // a replacement character for each bad byte, and abc
}

static void test_heading_moves_to_the_next_page_with_its_text() {
  // 4 lines of 15 px fit. Two body lines, then a heading with 15 px above it ends at 60:
  // it fits, but the paragraph after it doesn't, so the heading starts the next page.
  std::string body = "一二三四五六七八\n";
  std::string t = body + "\x02" "章\n" + "九十\n";
  PageLayout p = page(t, style(40, 60));
  TEST_ASSERT_EQUAL(2, p.lines.size());
  TEST_ASSERT_EQUAL_UINT32(body.size(), p.end);
  PageLayout p2 = page(t, style(40, 60), p.end);
  TEST_ASSERT_TRUE(p2.lines[0].heading);
  TEST_ASSERT_EQUAL(0, p2.lines[0].y);  // no space above a heading at the top of a page
}

// Pages laid out one at a time break lines exactly where one long page would: the same
// line starts and ends, in order, with nothing left out.
static void test_pages_match_one_continuous_layout() {
  std::string t;
  for (int k = 0; k < 6; k++) {
    t += "\x02第" + std::to_string(k) + "章 雾港\n";
    t += "雾是从海上来的。每到傍晚，港口的灯就一盏一盏亮起来，像有人在水面上写字。\n";
    t += "The fog came in from the sea, and \x0equietly\x0f filled the harbour streets.\n";
    t += "\x0b“灯塔还亮着吗？”她问。\n";
    t += "\x05• a list item that is long enough to wrap\n";
  }
  LayoutStyle st = style(100, 100);
  st.indentEms = 2;
  st.paragraphSpacing = 3;
  std::vector<uint32_t> starts = TextLayout::paginate(t, 0, st);
  TEST_ASSERT_TRUE(starts.size() > 5);
  std::vector<std::pair<uint32_t, uint32_t>> paged;
  for (size_t k = 0; k < starts.size(); k++) {
    PageLayout p;
    uint32_t next = TextLayout::layoutPage(t, 0, starts[k], st, &p);
    TEST_ASSERT_EQUAL_UINT32(k + 1 < starts.size() ? starts[k + 1] : t.size(), next);
    TEST_ASSERT_TRUE(!p.lines.empty());
    for (const Line& l : p.lines) {
      paged.push_back({l.start, l.end});
      TEST_ASSERT_TRUE(l.y + l.height <= st.height);
    }
  }
  LayoutStyle tall = st;
  tall.height = 100000;
  PageLayout all = page(t, tall);
  TEST_ASSERT_EQUAL(all.lines.size(), paged.size());
  for (size_t i = 0; i < paged.size(); i++) {
    TEST_ASSERT_EQUAL_UINT32(all.lines[i].start, paged[i].first);
    TEST_ASSERT_EQUAL_UINT32(all.lines[i].end, paged[i].second);
  }
}

static void test_page_containing() {
  std::vector<uint32_t> starts{10, 20, 30};
  TEST_ASSERT_EQUAL(0, TextLayout::pageContaining(starts, 5));
  TEST_ASSERT_EQUAL(0, TextLayout::pageContaining(starts, 10));
  TEST_ASSERT_EQUAL(1, TextLayout::pageContaining(starts, 25));
  TEST_ASSERT_EQUAL(2, TextLayout::pageContaining(starts, 99));
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_latin_wraps_at_spaces_and_justifies);
  RUN_TEST(test_cjk_breaks_between_any_characters);
  RUN_TEST(test_closing_bracket_takes_the_character_before_it_along);
  RUN_TEST(test_comma_hangs_in_the_margin);
  RUN_TEST(test_opening_bracket_never_ends_a_line);
  RUN_TEST(test_indent_only_on_a_paragraphs_first_line);
  RUN_TEST(test_word_longer_than_the_line_is_cut);
  RUN_TEST(test_breaks_after_a_hyphen);
  RUN_TEST(test_bold_glyphs_are_wider);
  RUN_TEST(test_preformatted_keeps_spaces_and_centered_is_centered);
  RUN_TEST(test_malformed_utf8_does_not_stop_layout);
  RUN_TEST(test_heading_moves_to_the_next_page_with_its_text);
  RUN_TEST(test_pages_match_one_continuous_layout);
  RUN_TEST(test_page_containing);
  return UNITY_END();
}
