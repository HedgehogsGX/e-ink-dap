// Host tests for lib/bitmap_font: pio test -e native
//
// sample_font.dfn is real output of the PC tool (Pillow's built-in Latin font, which has
// ASCII only), so the Python writer and the C++ reader are checked against each other:
//   uv run tools/fonts.py --text "éü" --size 16 --reader-font pillow -o test/test_font/sample_font.dfn
#include <unity.h>

#include <algorithm>
#include <cstdio>
#include <string>
#include <vector>

#include "bitmap_font.h"

static std::vector<uint8_t> fixture;

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

static BitmapFont openFixture() {
  BitmapFont f;
  TEST_ASSERT_EQUAL(BitmapFont::Error::None, f.open(fixture.data(), fixture.size()));
  return f;
}

void setUp() {}
void tearDown() {}

static void test_fixture_present() { TEST_ASSERT_TRUE_MESSAGE(fixture.size() > 32, "sample_font.dfn missing"); }

static void test_header() {
  BitmapFont f = openFixture();
  TEST_ASSERT_EQUAL(16, f.size());
  TEST_ASSERT_TRUE(f.ascent() > 0 && f.descent() >= 0);
  TEST_ASSERT_EQUAL(f.ascent() + f.descent(), f.lineHeight());
  TEST_ASSERT_TRUE(f.glyphCount() > 95);
}

static void test_glyphs() {
  BitmapFont f = openFixture();
  TEST_ASSERT_TRUE(f.has('A'));
  BitmapFont::Glyph a = f.glyph('A');
  TEST_ASSERT_TRUE(a.advance > 5 && a.width > 0 && a.height > 5 && a.top > 5);
  int set = 0;
  for (int y = 0; y < a.height; y++)
    for (int x = 0; x < a.width; x++) set += a.pixel(x, y);
  TEST_ASSERT_TRUE(set > 10);
  BitmapFont::Glyph space = f.glyph(' ');
  TEST_ASSERT_TRUE(space.advance > 0);
  TEST_ASSERT_EQUAL(0, space.width);
  TEST_ASSERT_TRUE(f.glyph('g').top < f.glyph('g').height);  // the descender goes below the baseline
}

static void test_missing_characters_draw_the_replacement_box() {
  BitmapFont f = openFixture();
  TEST_ASSERT_FALSE(f.has(0x4E2D));
  TEST_ASSERT_TRUE(f.has(BitmapFont::kReplacement));
  TEST_ASSERT_EQUAL_PTR(f.glyph(BitmapFont::kReplacement).bits, f.glyph(0x4E2D).bits);
  TEST_ASSERT_EQUAL(f.advance(BitmapFont::kReplacement), f.advance(0xE9));  // é isn't in this font either
}

static void test_draw_plots_pixels_and_bold_adds_a_column() {
  BitmapFont f = openFixture();
  int plain = 0, bold = 0, minX = 1000, maxY = -1000;
  int adv = f.draw('H', 10, 20, [&](int x, int y) {
    plain++;
    minX = std::min(minX, x);
    maxY = std::max(maxY, y);
  });
  TEST_ASSERT_EQUAL(f.advance('H'), adv);
  TEST_ASSERT_TRUE(plain > 10);
  TEST_ASSERT_TRUE(minX >= 10 && maxY < 20);  // H sits on the baseline
  TEST_ASSERT_EQUAL(f.advance('H') + 1, f.draw('H', 10, 20, [&](int, int) { bold++; }, true));
  TEST_ASSERT_EQUAL(2 * plain, bold);
}

static void test_works_as_layout_metrics() {
  BitmapFont f = openFixture();
  LayoutStyle st;
  st.body = &f;
  st.bodySize = 16;
  st.width = 1000;
  std::string t = "Hello world\n";
  PageLayout p;
  TextLayout::layoutPage(t, 0, 0, st, &p);
  int expected = 0;
  for (char c : std::string("Hello world")) expected += f.advance((uint8_t)c);
  TEST_ASSERT_EQUAL(1, p.lines.size());
  TEST_ASSERT_EQUAL(expected + st.indentEms * 16, p.lines[0].width + p.lines[0].x);
}

static void test_rejects_damaged_files() {
  BitmapFont f;
  std::vector<uint8_t> d = fixture;
  TEST_ASSERT_EQUAL(BitmapFont::Error::SizeMismatch, f.open(d.data(), d.size() - 1));
  d[0] = 'X';
  TEST_ASSERT_EQUAL(BitmapFont::Error::BadMagic, f.open(d.data(), d.size()));
  d = fixture;
  d[32 + 16 + 4] = 0xFF;  // the second glyph's bitmap offset, far past the end
  d[32 + 16 + 5] = 0xFF;
  TEST_ASSERT_EQUAL(BitmapFont::Error::BadLayout, f.open(d.data(), d.size()));
  TEST_ASSERT_FALSE(f.isOpen());
  TEST_ASSERT_EQUAL(0, f.advance('A'));
}

int main() {
  fixture = readFixture("sample_font.dfn");
  UNITY_BEGIN();
  RUN_TEST(test_fixture_present);
  if (fixture.size() > 32) {
    RUN_TEST(test_header);
    RUN_TEST(test_glyphs);
    RUN_TEST(test_missing_characters_draw_the_replacement_box);
    RUN_TEST(test_draw_plots_pixels_and_bold_adds_a_column);
    RUN_TEST(test_works_as_layout_metrics);
    RUN_TEST(test_rejects_damaged_files);
  }
  return UNITY_END();
}
