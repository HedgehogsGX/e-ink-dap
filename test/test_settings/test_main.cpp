// Host tests for lib/settings: pio test -e native
#include <unity.h>

#include <cstring>
#include <string>
#include <vector>

#include "settings.h"

void setUp() {}
void tearDown() {}

static void test_defaults_survive_a_round_trip() {
  Settings a;
  a.fontSize = 22;
  a.margins = Settings::kMarginsLarge;
  a.volumeKeysTurnPages = 1;
  a.repeat = Settings::kRepeatOne;
  Settings b;
  std::vector<std::string> problems;
  b.parse(a.serialize(), &problems);
  TEST_ASSERT_EQUAL(0, problems.size());
  TEST_ASSERT_EQUAL_STRING(a.serialize().c_str(), b.serialize().c_str());
  TEST_ASSERT_EQUAL(22, b.fontSize);
  TEST_ASSERT_EQUAL(Settings::kRepeatOne, b.repeat);
}

static void test_file_is_readable() {
  std::string text = Settings().serialize();
  TEST_ASSERT_NOT_NULL(strstr(text.c_str(), "[music]\nstart_volume = 10\n"));
  TEST_ASSERT_NOT_NULL(strstr(text.c_str(), "margins = medium\n"));
  TEST_ASSERT_NOT_NULL(strstr(text.c_str(), "justify = on\n"));
}

static void test_values_are_kept_in_range() {
  Settings s;
  s.parse("[music]\nstart_volume = 50\nvolume_limit = 20   ; quieter\n[reader]\nfont_size = 19 # odd\n"
          "line_spacing = 999\n");
  TEST_ASSERT_EQUAL(20, s.volumeLimit);
  TEST_ASSERT_EQUAL(20, s.startVolume);  // never louder than the limit
  TEST_ASSERT_EQUAL(18, s.fontSize);     // the nearest size there is a font for
  TEST_ASSERT_EQUAL(200, s.lineSpacing);
}

static void test_bad_lines_are_reported_and_skipped() {
  Settings s;
  std::vector<std::string> problems;
  s.parse("# comment\n\n[reader]\r\nJustify = Off\r\nmargins = LARGE\nindent = sideways\nfoo = 1\n"
          "no equals sign\n[display]\ninvert = yes\nfull_refresh_every = ten\n",
          &problems);
  TEST_ASSERT_EQUAL(4, problems.size());  // indent, foo, the line without '=', "ten"
  TEST_ASSERT_EQUAL(0, s.justify);        // keys and words in any case
  TEST_ASSERT_EQUAL(Settings::kMarginsLarge, s.margins);
  TEST_ASSERT_EQUAL(Settings::kIndentAuto, s.indent);
  TEST_ASSERT_EQUAL(1, s.invert);
  TEST_ASSERT_EQUAL(10, s.fullRefreshEvery);
}

static void test_stepping_and_showing_values() {
  const SettingInfo* font = findSetting("reader", "font_size");
  TEST_ASSERT_NOT_NULL(font);
  TEST_ASSERT_EQUAL(20, stepSetting(*font, 18, +1));
  TEST_ASSERT_EQUAL(16, stepSetting(*font, 18, -1));
  TEST_ASSERT_EQUAL(32, stepSetting(*font, 32, +1));
  TEST_ASSERT_EQUAL(28, stepSetting(*font, 24, +1));
  TEST_ASSERT_EQUAL_STRING("18 px", formatSetting(*font, 18).c_str());
  const SettingInfo* spacing = findSetting("reader", "line_spacing");
  TEST_ASSERT_EQUAL(160, stepSetting(*spacing, 150, +1));
  TEST_ASSERT_EQUAL_STRING("1.5", formatSetting(*spacing, 150).c_str());
  TEST_ASSERT_EQUAL_STRING("M", formatSetting(*findSetting("reader", "margins"), 1).c_str());
  TEST_ASSERT_EQUAL_STRING("On", formatSetting(*findSetting("reader", "justify"), 1).c_str());
  TEST_ASSERT_EQUAL_STRING("Never", formatSetting(*findSetting("system", "sleep_minutes"), 0).c_str());
  TEST_ASSERT_EQUAL_STRING("15 min", formatSetting(*findSetting("system", "sleep_minutes"), 15).c_str());
  TEST_ASSERT_EQUAL(0, stepSetting(*findSetting("display", "invert"), 1, +1));  // toggles flip
  TEST_ASSERT_NULL(findSetting("reader", "nope"));
}

static void test_reader_helpers() {
  Settings s;
  TEST_ASSERT_EQUAL(14, s.marginPx());
  TEST_ASSERT_EQUAL(2, s.indentEms(true));
  TEST_ASSERT_EQUAL(1, s.indentEms(false));
  s.indent = Settings::kIndentOff;
  TEST_ASSERT_EQUAL(0, s.indentEms(true));
  TEST_ASSERT_EQUAL(20, s.headingSize());
  s.fontSize = 32;
  TEST_ASSERT_EQUAL(32, s.headingSize());
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_defaults_survive_a_round_trip);
  RUN_TEST(test_file_is_readable);
  RUN_TEST(test_values_are_kept_in_range);
  RUN_TEST(test_bad_lines_are_reported_and_skipped);
  RUN_TEST(test_stepping_and_showing_values);
  RUN_TEST(test_reader_helpers);
  return UNITY_END();
}
