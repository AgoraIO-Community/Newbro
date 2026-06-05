#include <unity.h>
#include <vector>
#include "SessionJson.h"
#include "AudioMeta.h"

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

void test_parse_personas_rejects_non_array(void) {
  std::vector<Persona> out;
  TEST_ASSERT_FALSE(parsePersonas(R"({"not":"an array"})", out));
}

void test_parse_personas_skips_malformed_entries(void) {
  std::vector<Persona> out;
  TEST_ASSERT_TRUE(parsePersonas(R"([{"persona_id":"p1","name":"Pixel","avatar":"rabbit","status":"idle"}, null, {"name":"no id"}])", out));
  TEST_ASSERT_EQUAL_INT(1, (int)out.size());
  TEST_ASSERT_EQUAL_STRING("p1", out[0].id.c_str());
}

static const char *kSnapshot = R"({
  "session_id":"s",
  "tasks":[],
  "bro_timeline_turns":[
    {"persona_id":"p1","status":"completed","user":{"transcript":"old"},"assistant":{"text":"old reply"},"created_at":"2026-06-04T00:00:01+00:00"},
    {"persona_id":"p2","status":"running","user":{"transcript":"other"},"assistant":{"text":"nope"},"created_at":"2026-06-04T00:00:02+00:00"},
    {"persona_id":"p1","status":"running","user":{"transcript":"ship it"},"assistant":{"text":"on it"},"created_at":"2026-06-04T00:00:03+00:00"}
  ],
  "personas":[]
})";

void test_extract_latest_turn_for_persona(void) {
  TurnView t;
  TEST_ASSERT_TRUE(extractLatestTurn(kSnapshot, "p1", t));
  TEST_ASSERT_TRUE(t.found);
  TEST_ASSERT_EQUAL_STRING("ship it", t.userText.c_str());
  TEST_ASSERT_EQUAL_STRING("on it", t.assistantText.c_str());
  TEST_ASSERT_EQUAL_STRING("running", t.status.c_str());
}

void test_extract_no_turn_for_unknown_persona(void) {
  TurnView t;
  TEST_ASSERT_TRUE(extractLatestTurn(kSnapshot, "pX", t));
  TEST_ASSERT_FALSE(t.found);
}

void test_parse_audio_transcript(void) {
  std::string tx = parseAudioTranscript(R"({"status":"accepted","transcript_text":"hello there"})");
  TEST_ASSERT_EQUAL_STRING("hello there", tx.c_str());
  TEST_ASSERT_EQUAL_STRING("", parseAudioTranscript(R"({"status":"accepted","transcript_text":null})").c_str());
}

void test_build_audio_query(void) {
  AudioMeta m = computeAudioMeta(16000, 16000, 1);
  std::string q = buildAudioQuery("p1", m);
  TEST_ASSERT_EQUAL_STRING(
      "target_persona_id=p1&duration_ms=1000&sample_rate=16000&num_channels=1&samples_per_channel=16000",
      q.c_str());
}

void test_build_text_body(void) {
  std::string b = buildTextBody("p1", "hi");
  TEST_ASSERT_TRUE(b.find(R"("target_persona_id":"p1")") != std::string::npos);
  TEST_ASSERT_TRUE(b.find(R"("text":"hi")") != std::string::npos);
}

static const char *kThreadsSnapshot = R"({
  "session_id":"s",
  "bro_timeline_turns":[],
  "bro_threads":[
    {"thread_id":"t-old","persona_id":"p1","title":"Old build","preview":"fixed the bug","status":"completed","updated_at":"2026-06-04T00:00:01+00:00"},
    {"thread_id":"t-other","persona_id":"p2","title":"Other bro","preview":null,"status":"running","updated_at":"2026-06-04T00:00:09+00:00"},
    {"thread_id":"t-new","persona_id":"p1","title":"Ship it","preview":null,"status":"running","updated_at":"2026-06-04T00:00:05+00:00"}
  ]
})";

void test_parse_bro_threads_filters_and_sorts(void) {
  std::vector<ThreadInfo> out;
  TEST_ASSERT_TRUE(parseBroThreads(kThreadsSnapshot, "p1", out));
  TEST_ASSERT_EQUAL_INT(2, (int)out.size());
  TEST_ASSERT_EQUAL_STRING("t-new", out[0].id.c_str());
  TEST_ASSERT_EQUAL_STRING("Ship it", out[0].title.c_str());
  TEST_ASSERT_TRUE(out[0].preview.empty());
  TEST_ASSERT_EQUAL_STRING("running", out[0].status.c_str());
  TEST_ASSERT_EQUAL_STRING("t-old", out[1].id.c_str());
  TEST_ASSERT_EQUAL_STRING("fixed the bug", out[1].preview.c_str());
}

void test_parse_bro_threads_empty_for_unknown_persona(void) {
  std::vector<ThreadInfo> out;
  TEST_ASSERT_TRUE(parseBroThreads(kThreadsSnapshot, "pX", out));
  TEST_ASSERT_EQUAL_INT(0, (int)out.size());
}

void test_parse_bro_threads_rejects_garbage(void) {
  std::vector<ThreadInfo> out;
  TEST_ASSERT_FALSE(parseBroThreads("not json", out));
}

int main(int, char **) {
  UNITY_BEGIN();
  RUN_TEST(test_parse_bootstrap);
  RUN_TEST(test_parse_bootstrap_null_persona);
  RUN_TEST(test_parse_bootstrap_rejects_no_session);
  RUN_TEST(test_parse_personas);
  RUN_TEST(test_parse_personas_empty);
  RUN_TEST(test_parse_personas_rejects_non_array);
  RUN_TEST(test_parse_personas_skips_malformed_entries);
  RUN_TEST(test_extract_latest_turn_for_persona);
  RUN_TEST(test_extract_no_turn_for_unknown_persona);
  RUN_TEST(test_parse_audio_transcript);
  RUN_TEST(test_build_audio_query);
  RUN_TEST(test_build_text_body);
  RUN_TEST(test_parse_bro_threads_filters_and_sorts);
  RUN_TEST(test_parse_bro_threads_empty_for_unknown_persona);
  RUN_TEST(test_parse_bro_threads_rejects_garbage);
  return UNITY_END();
}
