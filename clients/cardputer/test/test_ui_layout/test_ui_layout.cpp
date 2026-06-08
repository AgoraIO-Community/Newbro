#include <unity.h>
#include <vector>
#include "UiLayout.h"

using namespace nb;

void test_scroll_top_keeps_selection_visible(void) {
  TEST_ASSERT_EQUAL_INT(0, listScrollTop(0, 10, 3));
  TEST_ASSERT_EQUAL_INT(0, listScrollTop(2, 10, 3));
  TEST_ASSERT_EQUAL_INT(1, listScrollTop(3, 10, 3));
  TEST_ASSERT_EQUAL_INT(7, listScrollTop(9, 10, 3));
}

void test_scroll_top_small_list(void) {
  TEST_ASSERT_EQUAL_INT(0, listScrollTop(0, 2, 3));
}

void test_move_selection_clamps(void) {
  TEST_ASSERT_EQUAL_INT(0, moveSelection(0, 5, -1));
  TEST_ASSERT_EQUAL_INT(1, moveSelection(0, 5, +1));
  TEST_ASSERT_EQUAL_INT(4, moveSelection(4, 5, +1));
  TEST_ASSERT_EQUAL_INT(0, moveSelection(3, 0, +1));
}

void test_truncate(void) {
  TEST_ASSERT_EQUAL_STRING("hello", truncate("hello", 8).c_str());
  TEST_ASSERT_EQUAL_STRING("hello...", truncate("hello world", 8).c_str());
  TEST_ASSERT_EQUAL_STRING("...", truncate("hello", 2).c_str());
}

void test_wrap_lines(void) {
  std::vector<std::string> lines = wrapLines("the quick brown fox", 10, 3);
  TEST_ASSERT_EQUAL_INT(2, (int)lines.size());
  TEST_ASSERT_EQUAL_STRING("the quick", lines[0].c_str());
  TEST_ASSERT_EQUAL_STRING("brown fox", lines[1].c_str());
}

void test_wrap_lines_truncates_overflow(void) {
  std::vector<std::string> lines = wrapLines("aaa bbb ccc ddd eee fff", 7, 2);
  TEST_ASSERT_EQUAL_INT(2, (int)lines.size());
  TEST_ASSERT_TRUE(lines[1].size() >= 3 && lines[1].substr(lines[1].size() - 3) == "...");
}

void test_wrap_lines_truncates_long_word(void) {
  std::vector<std::string> lines = wrapLines("supercalifragilisticexpialidocious", 10, 3);
  TEST_ASSERT_EQUAL_INT(1, (int)lines.size());
  TEST_ASSERT_EQUAL_INT(10, (int)lines[0].size());
  TEST_ASSERT_TRUE(lines[0].substr(7) == "...");
}

int main(int, char **) {
  UNITY_BEGIN();
  RUN_TEST(test_scroll_top_keeps_selection_visible);
  RUN_TEST(test_scroll_top_small_list);
  RUN_TEST(test_move_selection_clamps);
  RUN_TEST(test_truncate);
  RUN_TEST(test_wrap_lines);
  RUN_TEST(test_wrap_lines_truncates_overflow);
  RUN_TEST(test_wrap_lines_truncates_long_word);
  return UNITY_END();
}
