// Host tests for lib/g4image: pio test -e native
#include <unity.h>

#include "g4image.h"

void setUp() {}
void tearDown() {}

// Made by tools/cover_art.py from a 7x2 PNG whose pixels are exactly the 4 grays
// (--size 7x2 --dither none --no-enhance), so it checks the tool and this reader agree.
// Row 0: levels 0 1 2 3 0 1 2, row 1: 3 2 1 0 3 2 1.
static const uint8_t kPattern[] = {'G', '4', 'B', 'M', 7, 0, 2, 0, 0x1B, 0x1B, 0xE4, 0xE7};
static const uint8_t kLevels[2][7] = {{0, 1, 2, 3, 0, 1, 2}, {3, 2, 1, 0, 3, 2, 1}};

static void test_reads_tool_output() {
  G4Image img;
  TEST_ASSERT_TRUE(img.open(kPattern, sizeof kPattern));
  TEST_ASSERT_EQUAL_INT(7, img.width());
  TEST_ASSERT_EQUAL_INT(2, img.height());
  TEST_ASSERT_EQUAL(2, img.stride());
  for (int y = 0; y < 2; y++)
    for (int x = 0; x < 7; x++) TEST_ASSERT_EQUAL_UINT8(kLevels[y][x], img.level(x, y));
}

static void test_black_white_fallback() {
  G4Image img;
  img.open(kPattern, sizeof kPattern);
  TEST_ASSERT_TRUE(img.blackInBw(0, 0));   // black
  TEST_ASSERT_FALSE(img.blackInBw(3, 0));  // white
  TEST_ASSERT_TRUE(img.blackInBw(1, 0));   // dark gray off the 2x2 corner (even x, even y)
  TEST_ASSERT_TRUE(img.blackInBw(2, 0));   // light gray on the corner
  TEST_ASSERT_FALSE(img.blackInBw(1, 1));  // light gray off the corner
}

static void test_rejects_bad_data() {
  G4Image img;
  uint8_t bad[sizeof kPattern];
  memcpy(bad, kPattern, sizeof bad);
  TEST_ASSERT_FALSE(img.open(nullptr, 0));
  TEST_ASSERT_FALSE(img.open(kPattern, sizeof kPattern - 1));  // last row cut short
  TEST_ASSERT_EQUAL_INT(0, img.width());
  bad[0] = 'X';
  TEST_ASSERT_FALSE(img.open(bad, sizeof bad));
  memcpy(bad, kPattern, sizeof bad);
  bad[4] = 0;  // width 0
  TEST_ASSERT_FALSE(img.open(bad, sizeof bad));
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_reads_tool_output);
  RUN_TEST(test_black_white_fallback);
  RUN_TEST(test_rejects_bad_data);
  return UNITY_END();
}
