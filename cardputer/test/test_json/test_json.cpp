#include <unity.h>
#include "PairingJson.h"

using namespace nb;

void test_parse_pair_start(void) {
  PairStart s;
  bool ok = parsePairStart(
      R"({"device_code":"DEV123","user_code":"7QF2","interval":2,"expires_at":"2026-06-04T00:10:00+00:00"})",
      s);
  TEST_ASSERT_TRUE(ok);
  TEST_ASSERT_EQUAL_STRING("DEV123", s.deviceCode.c_str());
  TEST_ASSERT_EQUAL_STRING("7QF2", s.userCode.c_str());
  TEST_ASSERT_EQUAL_INT(2, s.interval);
  TEST_ASSERT_EQUAL_STRING("2026-06-04T00:10:00+00:00", s.expiresAt.c_str());
}

void test_parse_pair_start_rejects_garbage(void) {
  PairStart s;
  TEST_ASSERT_FALSE(parsePairStart("not json", s));
}

void test_parse_poll_pending(void) {
  PollResult r;
  TEST_ASSERT_TRUE(parsePollResult(R"({"status":"pending"})", r));
  TEST_ASSERT_EQUAL_STRING("pending", r.status.c_str());
  TEST_ASSERT_TRUE(r.token.empty());
}

void test_parse_poll_claimed(void) {
  PollResult r;
  TEST_ASSERT_TRUE(parsePollResult(R"({"status":"claimed","token":"abc.def"})", r));
  TEST_ASSERT_EQUAL_STRING("claimed", r.status.c_str());
  TEST_ASSERT_EQUAL_STRING("abc.def", r.token.c_str());
}

void test_parse_poll_claimed_null_token(void) {
  PollResult r;
  TEST_ASSERT_TRUE(parsePollResult(R"({"status":"claimed","token":null})", r));
  TEST_ASSERT_EQUAL_STRING("claimed", r.status.c_str());
  TEST_ASSERT_TRUE(r.token.empty());
}

void test_build_poll_body(void) {
  TEST_ASSERT_EQUAL_STRING(R"({"device_code":"DEV123"})", buildPollBody("DEV123").c_str());
}

int main(int, char **) {
  UNITY_BEGIN();
  RUN_TEST(test_parse_pair_start);
  RUN_TEST(test_parse_pair_start_rejects_garbage);
  RUN_TEST(test_parse_poll_pending);
  RUN_TEST(test_parse_poll_claimed);
  RUN_TEST(test_parse_poll_claimed_null_token);
  RUN_TEST(test_build_poll_body);
  return UNITY_END();
}
