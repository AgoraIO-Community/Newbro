#include <unity.h>
#include "UiView.h"

using namespace nb;

void test_glyph_kind_for_avatar(void) {
  TEST_ASSERT_TRUE(glyphKindFor("rabbit") == GlyphKind::Rabbit);
  TEST_ASSERT_TRUE(glyphKindFor("cat") == GlyphKind::Cat);
  TEST_ASSERT_TRUE(glyphKindFor("fox") == GlyphKind::Fox);
  TEST_ASSERT_TRUE(glyphKindFor("person") == GlyphKind::Person);
  TEST_ASSERT_TRUE(glyphKindFor("bro") == GlyphKind::Person);
  TEST_ASSERT_TRUE(glyphKindFor("") == GlyphKind::Person);
}

void test_is_turn_active(void) {
  TEST_ASSERT_TRUE(isTurnActive("running"));
  TEST_ASSERT_TRUE(isTurnActive("pending"));
  TEST_ASSERT_FALSE(isTurnActive("completed"));
  TEST_ASSERT_FALSE(isTurnActive("failed"));
  TEST_ASSERT_FALSE(isTurnActive(""));
}

void test_phase_label(void) {
  TEST_ASSERT_EQUAL_STRING("hold to talk", phaseLabel(Phase::Idle));
  TEST_ASSERT_EQUAL_STRING("listening", phaseLabel(Phase::Recording));
  TEST_ASSERT_EQUAL_STRING("transcribing", phaseLabel(Phase::Transcribing));
  TEST_ASSERT_EQUAL_STRING("thinking", phaseLabel(Phase::Streaming));
}

int main(int, char **) {
  UNITY_BEGIN();
  RUN_TEST(test_glyph_kind_for_avatar);
  RUN_TEST(test_is_turn_active);
  RUN_TEST(test_phase_label);
  return UNITY_END();
}
