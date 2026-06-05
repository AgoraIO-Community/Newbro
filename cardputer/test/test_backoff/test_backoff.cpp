#include <unity.h>
#include "Backoff.h"

using namespace nb;

void test_backoff_grows_and_caps(void) {
  Backoff b(1000, 8000);
  TEST_ASSERT_EQUAL_UINT32(1000, b.next());  // returns current, then doubles
  TEST_ASSERT_EQUAL_UINT32(2000, b.next());
  TEST_ASSERT_EQUAL_UINT32(4000, b.next());
  TEST_ASSERT_EQUAL_UINT32(8000, b.next());
  TEST_ASSERT_EQUAL_UINT32(8000, b.next());  // capped
}

void test_backoff_reset(void) {
  Backoff b(1000, 8000);
  b.next();
  b.next();
  b.reset();
  TEST_ASSERT_EQUAL_UINT32(1000, b.current());
  TEST_ASSERT_EQUAL_UINT32(1000, b.next());
}

int main(int, char **) {
  UNITY_BEGIN();
  RUN_TEST(test_backoff_grows_and_caps);
  RUN_TEST(test_backoff_reset);
  return UNITY_END();
}
