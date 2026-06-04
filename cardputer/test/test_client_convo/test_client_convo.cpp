#include <unity.h>
#include <vector>
#include "NewbroClient.h"
#include "Transport.h"

using namespace nb;

class FakeTransport : public Transport {
 public:
  struct Call { std::string method, path, body, cookie, contentType; bool binary; };
  std::vector<Call> calls;
  std::vector<HttpResponse> responses;
  size_t idx = 0;

  HttpResponse request(const std::string &method, const std::string &path,
                       const std::string &body, const std::string &cookieToken) override {
    calls.push_back({method, path, body, cookieToken, "application/json", false});
    return idx < responses.size() ? responses[idx++] : HttpResponse{};
  }
  HttpResponse postBytes(const std::string &path, const std::string &contentType,
                         const uint8_t *body, size_t len, const std::string &cookieToken) override {
    calls.push_back({"POST", path, std::string((const char *)body, len), cookieToken, contentType, true});
    return idx < responses.size() ? responses[idx++] : HttpResponse{};
  }
};

void test_bootstrap_sends_cookie_and_parses(void) {
  FakeTransport t;
  t.responses.push_back(HttpResponse{true, 200, R"({"session_id":"s1","default_persona_id":"p1"})"});
  NewbroClient client(t);
  client.setAuthToken("tok123");

  Bootstrap b;
  TEST_ASSERT_TRUE(client.bootstrap(b));
  TEST_ASSERT_EQUAL_STRING("s1", b.sessionId.c_str());
  TEST_ASSERT_EQUAL_STRING("GET", t.calls[0].method.c_str());
  TEST_ASSERT_EQUAL_STRING("/api/me/bootstrap", t.calls[0].path.c_str());
  TEST_ASSERT_EQUAL_STRING("tok123", t.calls[0].cookie.c_str());
}

void test_list_personas(void) {
  FakeTransport t;
  t.responses.push_back(HttpResponse{true, 200,
      R"([{"persona_id":"p1","name":"Pixel","avatar":"rabbit","status":"idle"}])"});
  NewbroClient client(t);
  client.setAuthToken("tok");
  std::vector<Persona> out;
  TEST_ASSERT_TRUE(client.listPersonas("s1", out));
  TEST_ASSERT_EQUAL_INT(1, (int)out.size());
  TEST_ASSERT_EQUAL_STRING("/api/sessions/s1/personas", t.calls[0].path.c_str());
  TEST_ASSERT_EQUAL_STRING("tok", t.calls[0].cookie.c_str());
}

void test_send_text(void) {
  FakeTransport t;
  t.responses.push_back(HttpResponse{true, 200, R"({"instruction_id":"i1"})"});
  NewbroClient client(t);
  client.setAuthToken("tok");
  TEST_ASSERT_TRUE(client.sendText("s1", "p1", "ship it"));
  TEST_ASSERT_EQUAL_STRING("POST", t.calls[0].method.c_str());
  TEST_ASSERT_EQUAL_STRING("/api/sessions/s1/executor-text-instructions", t.calls[0].path.c_str());
  TEST_ASSERT_TRUE(t.calls[0].body.find("ship it") != std::string::npos);
}

int main(int, char **) {
  UNITY_BEGIN();
  RUN_TEST(test_bootstrap_sends_cookie_and_parses);
  RUN_TEST(test_list_personas);
  RUN_TEST(test_send_text);
  return UNITY_END();
}
