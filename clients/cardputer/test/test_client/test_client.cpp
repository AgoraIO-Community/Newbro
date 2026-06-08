#include <unity.h>
#include <vector>
#include "NewbroClient.h"
#include "Transport.h"

using namespace nb;

// A scripted transport that records requests and returns canned responses.
class FakeTransport : public Transport {
 public:
  struct Call { std::string method, path, body, cookie; };
  std::vector<Call> calls;
  std::vector<HttpResponse> responses;
  size_t idx = 0;

  HttpResponse request(const std::string &method, const std::string &path,
                       const std::string &body, const std::string &cookieToken) override {
    calls.push_back({method, path, body, cookieToken});
    if (idx < responses.size()) return responses[idx++];
    return HttpResponse{};  // transportOk=false
  }

  HttpResponse postBytes(const std::string &, const std::string &, const uint8_t *, size_t,
                         const std::string &) override {
    return HttpResponse{};  // not exercised by the pairing tests
  }
};

void test_start_pairing_success(void) {
  FakeTransport t;
  t.responses.push_back(HttpResponse{
      true, 200,
      R"({"device_code":"DEV1","user_code":"7QF2","interval":2,"expires_at":"x"})"});
  NewbroClient client(t);

  PairStart out;
  TEST_ASSERT_TRUE(client.startPairing(out));
  TEST_ASSERT_EQUAL_STRING("DEV1", out.deviceCode.c_str());
  TEST_ASSERT_EQUAL_STRING("7QF2", out.userCode.c_str());
  TEST_ASSERT_EQUAL_INT(1, (int)t.calls.size());
  TEST_ASSERT_EQUAL_STRING("POST", t.calls[0].method.c_str());
  TEST_ASSERT_EQUAL_STRING("/api/devices/pair/start", t.calls[0].path.c_str());
}

void test_start_pairing_transport_failure(void) {
  FakeTransport t;
  t.responses.push_back(HttpResponse{});  // transportOk=false
  NewbroClient client(t);
  PairStart out;
  TEST_ASSERT_FALSE(client.startPairing(out));
  TEST_ASSERT_FALSE(client.lastError().empty());
}

void test_poll_pending(void) {
  FakeTransport t;
  t.responses.push_back(HttpResponse{true, 200, R"({"status":"pending"})"});
  NewbroClient client(t);
  PollResult out;
  TEST_ASSERT_TRUE(client.pollPairing("DEV1", out));
  TEST_ASSERT_EQUAL_STRING("pending", out.status.c_str());
  TEST_ASSERT_EQUAL_STRING("POST", t.calls[0].method.c_str());
  TEST_ASSERT_EQUAL_STRING("/api/devices/pair/poll", t.calls[0].path.c_str());
  TEST_ASSERT_EQUAL_STRING(R"({"device_code":"DEV1"})", t.calls[0].body.c_str());
}

void test_poll_claimed(void) {
  FakeTransport t;
  t.responses.push_back(HttpResponse{true, 200, R"({"status":"claimed","token":"abc"})"});
  NewbroClient client(t);
  PollResult out;
  TEST_ASSERT_TRUE(client.pollPairing("DEV1", out));
  TEST_ASSERT_EQUAL_STRING("claimed", out.status.c_str());
  TEST_ASSERT_EQUAL_STRING("abc", out.token.c_str());
}

void test_poll_404_is_error(void) {
  FakeTransport t;
  t.responses.push_back(HttpResponse{true, 404, R"({"detail":"Unknown pairing."})"});
  NewbroClient client(t);
  PollResult out;
  TEST_ASSERT_FALSE(client.pollPairing("DEV1", out));
  TEST_ASSERT_FALSE(client.lastError().empty());
}

int main(int, char **) {
  UNITY_BEGIN();
  RUN_TEST(test_start_pairing_success);
  RUN_TEST(test_start_pairing_transport_failure);
  RUN_TEST(test_poll_pending);
  RUN_TEST(test_poll_claimed);
  RUN_TEST(test_poll_404_is_error);
  return UNITY_END();
}
