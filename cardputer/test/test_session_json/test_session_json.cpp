#include <unity.h>
#include <vector>
#include "SessionJson.h"

using namespace nb;

void test_parse_bootstrap(void) {
  Bootstrap b;
  bool ok = parseBootstrap(
      R"({"user":{"user_id":"u1"},"session_id":"sess-1","default_persona_id":"persona-a","default_bro_detail_session_id":"bd-1"})",
      b);
  TEST_ASSERT_TRUE(ok);
  TEST_ASSERT_EQUAL_STRING("sess-1", b.sessionId.c_str());
  TEST_ASSERT_EQUAL_STRING("persona-a", b.defaultPersonaId.c_str());
}

void test_parse_bootstrap_null_persona(void) {
  Bootstrap b;
  TEST_ASSERT_TRUE(parseBootstrap(R"({"session_id":"s","default_persona_id":null})", b));
  TEST_ASSERT_EQUAL_STRING("s", b.sessionId.c_str());
  TEST_ASSERT_TRUE(b.defaultPersonaId.empty());
}

void test_parse_bootstrap_rejects_no_session(void) {
  Bootstrap b;
  TEST_ASSERT_FALSE(parseBootstrap(R"({"user":{"user_id":"u1"}})", b));
}

void test_parse_personas(void) {
  std::vector<Persona> out;
  bool ok = parsePersonas(
      R"([{"persona_id":"p1","name":"Pixel","avatar":"rabbit","status":"busy"},
          {"persona_id":"p2","name":"Mochi","avatar":"cat","status":"idle"}])",
      out);
  TEST_ASSERT_TRUE(ok);
  TEST_ASSERT_EQUAL_INT(2, (int)out.size());
  TEST_ASSERT_EQUAL_STRING("p1", out[0].id.c_str());
  TEST_ASSERT_EQUAL_STRING("Pixel", out[0].name.c_str());
  TEST_ASSERT_EQUAL_STRING("rabbit", out[0].avatar.c_str());
  TEST_ASSERT_TRUE(out[0].busy);
  TEST_ASSERT_FALSE(out[1].busy);
}

void test_parse_personas_empty(void) {
  std::vector<Persona> out;
  TEST_ASSERT_TRUE(parsePersonas("[]", out));
  TEST_ASSERT_EQUAL_INT(0, (int)out.size());
}

int main(int, char **) {
  UNITY_BEGIN();
  RUN_TEST(test_parse_bootstrap);
  RUN_TEST(test_parse_bootstrap_null_persona);
  RUN_TEST(test_parse_bootstrap_rejects_no_session);
  RUN_TEST(test_parse_personas);
  RUN_TEST(test_parse_personas_empty);
  return UNITY_END();
}
