#include <unity.h>
#include "UiColor.h"

using namespace nb;

void test_rgb565_extremes(void) {
  TEST_ASSERT_EQUAL_HEX16(0x0000, rgb565(0, 0, 0));
  TEST_ASSERT_EQUAL_HEX16(0xFFFF, rgb565(255, 255, 255));
  TEST_ASSERT_EQUAL_HEX16(0xF800, rgb565(255, 0, 0));
  TEST_ASSERT_EQUAL_HEX16(0x07E0, rgb565(0, 255, 0));
  TEST_ASSERT_EQUAL_HEX16(0x001F, rgb565(0, 0, 255));
}

void test_palette_present(void) {
  TEST_ASSERT_EQUAL_HEX16(rgb565(0xff, 0x6a, 0x3d), kInkCoral);
  TEST_ASSERT_EQUAL_HEX16(rgb565(0x10, 0xb9, 0x81), kInkGreen);
  TEST_ASSERT_EQUAL_HEX16(rgb565(0xe9, 0xea, 0xf0), kInkText);
}

void test_lerp565_endpoints_and_mid(void) {
  uint16_t black = rgb565(0, 0, 0);
  uint16_t white = rgb565(255, 255, 255);
  TEST_ASSERT_EQUAL_HEX16(black, lerp565(black, white, 0));
  TEST_ASSERT_EQUAL_HEX16(white, lerp565(black, white, 255));
  uint16_t mid = lerp565(black, white, 128);
  TEST_ASSERT_NOT_EQUAL(black, mid);
  TEST_ASSERT_NOT_EQUAL(white, mid);
}

int main(int, char **) {
  UNITY_BEGIN();
  RUN_TEST(test_rgb565_extremes);
  RUN_TEST(test_palette_present);
  RUN_TEST(test_lerp565_endpoints_and_mid);
  return UNITY_END();
}
