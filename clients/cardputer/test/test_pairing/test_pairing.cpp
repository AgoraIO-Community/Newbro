#include <unity.h>
#include "Pairing.h"

using namespace nb;

void test_begin_moves_to_awaiting_start(void) {
  PairingMachine m;
  TEST_ASSERT_TRUE(m.state() == PairState::Idle);
  m.begin();
  TEST_ASSERT_TRUE(m.state() == PairState::AwaitingStart);
}

void test_on_start_moves_to_polling_and_exposes_code(void) {
  PairingMachine m;
  m.begin();
  PairStart s;
  s.deviceCode = "DEV1";
  s.userCode = "7QF2";
  s.interval = 2;
  m.onStart(s);
  TEST_ASSERT_TRUE(m.state() == PairState::Polling);
  TEST_ASSERT_EQUAL_STRING("7QF2", m.userCode().c_str());
  TEST_ASSERT_EQUAL_STRING("DEV1", m.deviceCode().c_str());
}

void test_poll_pending_stays_polling(void) {
  PairingMachine m;
  m.begin();
  PairStart s; s.deviceCode = "DEV1"; s.userCode = "7QF2";
  m.onStart(s);
  PollResult r; r.status = "pending";
  m.onPoll(r);
  TEST_ASSERT_TRUE(m.state() == PairState::Polling);
}

void test_poll_claimed_moves_to_claimed_with_token(void) {
  PairingMachine m;
  m.begin();
  PairStart s; s.deviceCode = "DEV1"; s.userCode = "7QF2";
  m.onStart(s);
  PollResult r; r.status = "claimed"; r.token = "abc.def";
  m.onPoll(r);
  TEST_ASSERT_TRUE(m.state() == PairState::Claimed);
  TEST_ASSERT_EQUAL_STRING("abc.def", m.token().c_str());
}

void test_claimed_without_token_stays_polling(void) {
  PairingMachine m;
  m.begin();
  PairStart s; s.deviceCode = "DEV1"; s.userCode = "7QF2";
  m.onStart(s);
  PollResult r; r.status = "claimed"; r.token = "";
  m.onPoll(r);
  TEST_ASSERT_TRUE(m.state() == PairState::Polling);
}

void test_expired_and_error(void) {
  PairingMachine m;
  m.begin();
  m.onExpired();
  TEST_ASSERT_TRUE(m.state() == PairState::Expired);

  PairingMachine m2;
  m2.begin();
  m2.onError("boom");
  TEST_ASSERT_TRUE(m2.state() == PairState::Failed);
  TEST_ASSERT_EQUAL_STRING("boom", m2.error().c_str());
}

int main(int, char **) {
  UNITY_BEGIN();
  RUN_TEST(test_begin_moves_to_awaiting_start);
  RUN_TEST(test_on_start_moves_to_polling_and_exposes_code);
  RUN_TEST(test_poll_pending_stays_polling);
  RUN_TEST(test_poll_claimed_moves_to_claimed_with_token);
  RUN_TEST(test_claimed_without_token_stays_polling);
  RUN_TEST(test_expired_and_error);
  return UNITY_END();
}
