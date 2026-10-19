// Host tests for lib/lyrics: pio test -e native
#include <unity.h>

#include <string>

#include "lyrics.h"

void setUp() {}
void tearDown() {}

static void assertLine(const Lyrics& l, size_t i, uint32_t ms, const char* text) {
  TEST_ASSERT_TRUE(i < l.size());
  TEST_ASSERT_EQUAL_UINT32(ms, l.timeMs(i));
  TEST_ASSERT_EQUAL_STRING(text, std::string(l.text(i)).c_str());
}

static void test_basic_lines_sorted() {
  Lyrics l;
  TEST_ASSERT_TRUE(l.parse("[00:20.00]second\n[00:05.50]first\n[01:02.03]third\n"));
  TEST_ASSERT_EQUAL(3, l.size());
  assertLine(l, 0, 5500, "first");
  assertLine(l, 1, 20000, "second");
  assertLine(l, 2, 62030, "third");
}

static void test_time_formats() {
  Lyrics l;
  TEST_ASSERT_TRUE(l.parse("[00:01]a\n[00:01.5]b\n[00:01.25]c\n[00:01.125]d\n[00:01:75]e\n[0:02.3456]f\n[100:00.00]g\n"));
  TEST_ASSERT_EQUAL(7, l.size());
  assertLine(l, 0, 1000, "a");
  assertLine(l, 1, 1125, "d");
  assertLine(l, 2, 1250, "c");
  assertLine(l, 3, 1500, "b");
  assertLine(l, 4, 1750, "e");
  assertLine(l, 5, 2345, "f");
  assertLine(l, 6, 6000000, "g");
}

static void test_several_times_on_one_line() {
  Lyrics l;
  TEST_ASSERT_TRUE(l.parse("[00:10.00][01:10.00][02:10.00]Chorus line\n[00:40.00]Verse\n"));
  TEST_ASSERT_EQUAL(4, l.size());
  assertLine(l, 0, 10000, "Chorus line");
  assertLine(l, 1, 40000, "Verse");
  assertLine(l, 2, 70000, "Chorus line");
  assertLine(l, 3, 130000, "Chorus line");
}

static void test_info_tags() {
  Lyrics l;
  TEST_ASSERT_TRUE(l.parse("[ti: 群青の午後 ]\n[ar:Mizuiro Tape]\n[al:Paper Weather]\n[by:someone]\n[length:03:45]\n[00:01.00]x\n"));
  TEST_ASSERT_EQUAL_STRING("群青の午後", std::string(l.title()).c_str());
  TEST_ASSERT_EQUAL_STRING("Mizuiro Tape", std::string(l.artist()).c_str());
  TEST_ASSERT_EQUAL_STRING("Paper Weather", std::string(l.album()).c_str());
  TEST_ASSERT_EQUAL(1, l.size());
}

static void test_offset_positive_shows_earlier() {
  Lyrics l;
  TEST_ASSERT_TRUE(l.parse("[offset:+500]\n[00:00.20]clamped\n[00:10.00]ten\n"));
  TEST_ASSERT_EQUAL_INT32(500, l.offsetMs());
  assertLine(l, 0, 0, "clamped");
  assertLine(l, 1, 9500, "ten");
}

static void test_offset_negative_and_late_in_file() {
  Lyrics l;
  TEST_ASSERT_TRUE(l.parse("[00:10.00]ten\n[offset:-250]\n"));
  TEST_ASSERT_EQUAL_INT32(-250, l.offsetMs());
  assertLine(l, 0, 10250, "ten");
}

static void test_utf8_cjk_bom_crlf() {
  Lyrics l;
  const char* lrc =
      "\xEF\xBB\xBF[00:12.00]窓の外は まだ雨のまま  \r\n"
      "[00:12.00]窗外依旧下着雨\r\n"
      "[00:15.40]  우산은 없어도 괜찮아\r\n";
  TEST_ASSERT_TRUE(l.parse(lrc));
  TEST_ASSERT_EQUAL(3, l.size());
  assertLine(l, 0, 12000, "窓の外は まだ雨のまま");
  assertLine(l, 1, 12000, "窗外依旧下着雨");
  assertLine(l, 2, 15400, "우산은 없어도 괜찮아");
}

static void test_bare_cr_line_ends() {
  Lyrics l;
  TEST_ASSERT_TRUE(l.parse("[00:01.00]one\r[00:02.00]two\r"));
  TEST_ASSERT_EQUAL(2, l.size());
  assertLine(l, 1, 2000, "two");
}

static void test_same_time_group_keeps_file_order() {
  Lyrics l;
  TEST_ASSERT_TRUE(l.parse("[00:20.00]B original\n[00:10.00]A original\n[00:20.00]B translation\n[00:10.00]A translation\n"));
  assertLine(l, 0, 10000, "A original");
  assertLine(l, 1, 10000, "A translation");
  assertLine(l, 2, 20000, "B original");
  assertLine(l, 3, 20000, "B translation");
  TEST_ASSERT_EQUAL(2, l.groupEnd(0));
  TEST_ASSERT_EQUAL(4, l.groupEnd(2));
}

static void test_index_at() {
  Lyrics l;
  l.parse("[00:10.00]a\n[00:20.00]b\n[00:20.00]b2\n[00:30.00]c\n");
  TEST_ASSERT_EQUAL_INT(-1, l.indexAt(0));
  TEST_ASSERT_EQUAL_INT(-1, l.indexAt(9999));
  TEST_ASSERT_EQUAL_INT(0, l.indexAt(10000));
  TEST_ASSERT_EQUAL_INT(0, l.indexAt(19999));
  TEST_ASSERT_EQUAL_INT(1, l.indexAt(20000));  // first of the 00:20 group
  TEST_ASSERT_EQUAL_INT(1, l.indexAt(25000));
  TEST_ASSERT_EQUAL_INT(3, l.indexAt(30000));
  TEST_ASSERT_EQUAL_INT(3, l.indexAt(UINT32_MAX));
}

static void test_empty_timed_line_is_kept() {
  Lyrics l;
  TEST_ASSERT_TRUE(l.parse("[00:10.00]sing\n[00:14.00]\n[00:30.00]again\n"));
  TEST_ASSERT_EQUAL(3, l.size());
  assertLine(l, 1, 14000, "");
}

static void test_enhanced_word_times_removed() {
  Lyrics l;
  TEST_ASSERT_TRUE(l.parse("[00:05.00]<00:05.00>Hello <00:05.60>paper <00:06.10>world <a>\n"));
  assertLine(l, 0, 5000, "Hello paper world <a>");
}

static void test_non_time_tags_and_garbage() {
  Lyrics l;
  const char* lrc =
      "plain text without a tag\n"
      "[Chorus]\n"
      "[00:7x.00]bad seconds\n"
      "[00:61.00]seconds out of range\n"
      "[00:01.00\n"
      "[00:02.00][Chorus] text after a non-time tag\n"
      "[:30]x\n"
      "\n";
  TEST_ASSERT_TRUE(l.parse(lrc));
  TEST_ASSERT_EQUAL(1, l.size());
  assertLine(l, 0, 2000, "[Chorus] text after a non-time tag");
}

static void test_no_timed_lines() {
  Lyrics l;
  TEST_ASSERT_FALSE(l.parse(""));
  TEST_ASSERT_FALSE(l.parse("[ti:Only a title]\njust words\n"));
  TEST_ASSERT_EQUAL(0, l.size());
  TEST_ASSERT_EQUAL_INT(-1, l.indexAt(1000));
}

static void test_reparse_replaces_content() {
  Lyrics l;
  l.parse("[offset:100]\n[ti:Old]\n[00:01.00]old\n");
  l.parse("[00:03.00]new\n");
  TEST_ASSERT_EQUAL(1, l.size());
  assertLine(l, 0, 3000, "new");
  TEST_ASSERT_EQUAL_INT32(0, l.offsetMs());
  TEST_ASSERT_TRUE(l.title().empty());
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_basic_lines_sorted);
  RUN_TEST(test_time_formats);
  RUN_TEST(test_several_times_on_one_line);
  RUN_TEST(test_info_tags);
  RUN_TEST(test_offset_positive_shows_earlier);
  RUN_TEST(test_offset_negative_and_late_in_file);
  RUN_TEST(test_utf8_cjk_bom_crlf);
  RUN_TEST(test_bare_cr_line_ends);
  RUN_TEST(test_same_time_group_keeps_file_order);
  RUN_TEST(test_index_at);
  RUN_TEST(test_empty_timed_line_is_kept);
  RUN_TEST(test_enhanced_word_times_removed);
  RUN_TEST(test_non_time_tags_and_garbage);
  RUN_TEST(test_no_timed_lines);
  RUN_TEST(test_reparse_replaces_content);
  return UNITY_END();
}
