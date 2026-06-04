# Cardputer Firmware Plan B — Conversation Data Path

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the paired Cardputer the full conversation data path — discover the user's Bros, push-to-talk a voice instruction to the selected Bro, and receive the Bro's streamed reply — verified headlessly (serial + minimal text), with the styled Ink chat UI deferred to Plan C.

**Architecture:** Builds on Plan A's `Transport`/`NewbroClient` seam over the proven `HttpsTransport`. Voice is sent as raw PCM16 to `POST /api/sessions/{id}/executor-audio-instructions` (the server transcribes and returns `transcript_text`). The Bro's reply is read by polling `GET /api/sessions/{id}` and extracting the latest `bro_timeline_turns` entry for the target persona via ArduinoJson filtered parsing (the direct-executor path publishes full snapshots, with no fine-grained deltas — polling reuses the existing HTTPS transport and avoids a WebSocket-over-TLS integration). All parsing/JSON/metadata logic lives in host-tested `lib/` modules; mic capture and the router are device glue verified by compile + an on-device smoke checklist.

**Tech Stack:** C++17, PlatformIO, Arduino-ESP32, `m5stack/M5Cardputer` (mic via `M5Cardputer.Mic.record`), `bblanchon/ArduinoJson` v7, Unity (host tests), reuses Plan A's `WiFiClientSecure`+`HTTPClient` `HttpsTransport`.

---

## Prerequisites

- Plan A is merged/available on this branch: `cardputer/` PlatformIO project with `device`+`native` envs; libs `nb_json`, `nb_config`, `nb_backoff`, `nb_pairing`, `nb_transport` (the `Transport` interface + `HttpResponse`), `nb_client` (`NewbroClient` with `startPairing`/`pollPairing`); glue `src/transport/HttpsTransport`, `src/store/ConfigStore`, `src/net/WifiManager`, `src/ui/TextScreen`, `src/main.cpp`.
- The device already obtains and persists a `newbro_session` token (Plan A). Plan B uses that token as the `Cookie: newbro_session=<token>` on all authenticated calls.
- Run `pio` from inside `cardputer/`. Tasks 1–6 are host-verifiable; Tasks 7–8 add device compiles; Task 8's smoke check needs hardware + a reachable server with at least one Bro (persona) configured.

---

## Contract (authoritative, from the server)

- `GET /api/me/bootstrap` → `{ "user": {...}, "session_id": str, "default_persona_id": str|null, "default_bro_detail_session_id": str|null }`.
- `GET /api/sessions/{session_id}/personas` → array of `{ "persona_id", "name", "avatar", "base_prompt", "executor_node_id": str|null, "bro_detail_session_id", "status": "idle"|"busy" }`.
- `POST /api/sessions/{session_id}/executor-audio-instructions?target_persona_id=…&duration_ms=…&sample_rate=…&num_channels=…&samples_per_channel=…` with `Content-Type: audio/pcm` and body = raw little-endian PCM16. Server validates: `body_len == samples_per_channel * num_channels * 2`, `sample_rate` 8000–96000, `|expected_duration_ms − duration_ms| ≤ 1500` where `expected = round(samples_per_channel / sample_rate * 1000)`. Response: `{ "audio_instruction_id", "target_persona_id", "status", "transcript_text": str|null, ... }`.
- `POST /api/sessions/{session_id}/executor-text-instructions` with JSON `{ "target_persona_id", "text", "create_new_thread": bool, "target_thread_id": null, "workspace_id": null, "plan_mode": false }` → `{ "instruction_id", ... }`.
- `GET /api/sessions/{session_id}` → full `SessionSnapshot`. Relevant slice: `bro_timeline_turns: [{ "persona_id", "status": "pending"|"running"|"completed"|"failed"|"cancelled", "user": { "text": str|null, "transcript": str|null }|null, "assistant": { "text": str|null }|null, "created_at": str|null }]`.

All authenticated requests carry `Cookie: newbro_session=<token>`.

---

## File Structure

| Path | Responsibility | Built in |
|---|---|---|
| `cardputer/lib/nb_audio/AudioMeta.{h,cpp}` | PCM16 metadata math (samples↔bytes↔duration) | both |
| `cardputer/lib/nb_session_json/SessionJson.{h,cpp}` | parse bootstrap, personas, snapshot turn; build audio query + text body + parse audio response | both |
| `cardputer/lib/nb_transport/Transport.h` | extend with a binary/content-typed request | both |
| `cardputer/lib/nb_client/NewbroClient.{h,cpp}` | add auth token + bootstrap/listPersonas/sendText/sendAudio/getReply | both |
| `cardputer/src/transport/HttpsTransport.{h,cpp}` | implement the new binary request method | device |
| `cardputer/src/audio/MicRecorder.{h,cpp}` | push-to-talk PDM capture → PCM16 buffer | device |
| `cardputer/src/main.cpp` | extend router: discover Bro → record → send → poll reply (headless) | device |
| `cardputer/test/test_audio/`, `test/test_session_json/`, `test/test_client_convo/` | native Unity tests | native |

---

### Task 1: `nb_audio` — PCM16 metadata math

**Files:**
- Create: `cardputer/lib/nb_audio/AudioMeta.h`, `cardputer/lib/nb_audio/AudioMeta.cpp`, `cardputer/test/test_audio/test_audio.cpp`

- [ ] **Step 1: Write the failing test `cardputer/test/test_audio/test_audio.cpp`**

```cpp
#include <unity.h>
#include "AudioMeta.h"

using namespace nb;

void test_mono_one_second(void) {
  AudioMeta m = computeAudioMeta(/*samplesPerChannel=*/16000, /*sampleRate=*/16000, /*numChannels=*/1);
  TEST_ASSERT_EQUAL_UINT32(16000, m.samplesPerChannel);
  TEST_ASSERT_EQUAL_UINT32(16000, m.sampleRate);
  TEST_ASSERT_EQUAL_UINT8(1, m.numChannels);
  TEST_ASSERT_EQUAL_UINT32(1000, m.durationMs);
  TEST_ASSERT_EQUAL_UINT32(32000, m.byteLen);  // 16000 * 1 * 2
}

void test_half_second(void) {
  AudioMeta m = computeAudioMeta(8000, 16000, 1);
  TEST_ASSERT_EQUAL_UINT32(500, m.durationMs);
  TEST_ASSERT_EQUAL_UINT32(16000, m.byteLen);
}

void test_duration_rounds(void) {
  // 17000 samples @ 16000 Hz = 1062.5 ms → integer division gives 1062 ms,
  // well within the server's 1500 ms tolerance.
  AudioMeta m = computeAudioMeta(17000, 16000, 1);
  TEST_ASSERT_EQUAL_UINT32(1062, m.durationMs);
  TEST_ASSERT_EQUAL_UINT32(34000, m.byteLen);
}

int main(int, char **) {
  UNITY_BEGIN();
  RUN_TEST(test_mono_one_second);
  RUN_TEST(test_half_second);
  RUN_TEST(test_duration_rounds);
  return UNITY_END();
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd cardputer && pio test -e native -f test_audio`
Expected: FAIL — `AudioMeta.h` not found.

- [ ] **Step 3: Create `cardputer/lib/nb_audio/AudioMeta.h`**

```cpp
#pragma once
#include <cstdint>

namespace nb {

struct AudioMeta {
  uint32_t sampleRate;
  uint8_t numChannels;
  uint32_t samplesPerChannel;
  uint32_t durationMs;
  uint32_t byteLen;  // samplesPerChannel * numChannels * 2
};

// Compute the metadata the server requires for an executor-audio-instruction.
AudioMeta computeAudioMeta(uint32_t samplesPerChannel, uint32_t sampleRate, uint8_t numChannels);

}  // namespace nb
```

- [ ] **Step 4: Create `cardputer/lib/nb_audio/AudioMeta.cpp`**

```cpp
#include "AudioMeta.h"

namespace nb {

AudioMeta computeAudioMeta(uint32_t samplesPerChannel, uint32_t sampleRate, uint8_t numChannels) {
  AudioMeta m;
  m.sampleRate = sampleRate;
  m.numChannels = numChannels;
  m.samplesPerChannel = samplesPerChannel;
  m.byteLen = samplesPerChannel * static_cast<uint32_t>(numChannels) * 2u;
  // durationMs = samplesPerChannel / sampleRate * 1000, computed in 64-bit to avoid overflow.
  m.durationMs = sampleRate == 0
                     ? 0
                     : static_cast<uint32_t>((static_cast<uint64_t>(samplesPerChannel) * 1000ull) / sampleRate);
  return m;
}

}  // namespace nb
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd cardputer && pio test -e native -f test_audio`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add cardputer/lib/nb_audio cardputer/test/test_audio
git commit -m "feat(cardputer): add PCM16 audio metadata math (nb_audio)"
```

---

### Task 2: `nb_session_json` — parse bootstrap + personas

**Files:**
- Create: `cardputer/lib/nb_session_json/SessionJson.h`, `cardputer/lib/nb_session_json/SessionJson.cpp`, `cardputer/test/test_session_json/test_session_json.cpp`

- [ ] **Step 1: Write the failing test `cardputer/test/test_session_json/test_session_json.cpp`**

```cpp
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd cardputer && pio test -e native -f test_session_json`
Expected: FAIL — `SessionJson.h` not found.

- [ ] **Step 3: Create `cardputer/lib/nb_session_json/SessionJson.h`**

```cpp
#pragma once
#include <string>
#include <vector>
#include "AudioMeta.h"

namespace nb {

struct Bootstrap {
  std::string sessionId;
  std::string defaultPersonaId;  // empty if null
};

struct Persona {
  std::string id;
  std::string name;
  std::string avatar;
  bool busy = false;  // status == "busy"
};

// A compact view of the latest Bro-detail timeline turn for one persona.
struct TurnView {
  bool found = false;
  std::string userText;       // user transcript/text
  std::string assistantText;  // the Bro's reply so far
  std::string status;         // "pending"|"running"|"completed"|"failed"|"cancelled"
};

bool parseBootstrap(const std::string &json, Bootstrap &out);
bool parsePersonas(const std::string &json, std::vector<Persona> &out);

// Extract the latest turn for `personaId` from a full SessionSnapshot JSON.
// Uses a filtered parse so only `bro_timeline_turns` is deserialized.
bool extractLatestTurn(const std::string &snapshotJson, const std::string &personaId, TurnView &out);

// Parse transcript_text out of an executor-audio-instruction response.
std::string parseAudioTranscript(const std::string &json);

// Build the query string (without leading '?') for executor-audio-instructions.
std::string buildAudioQuery(const std::string &personaId, const AudioMeta &m);

// Build the JSON body for executor-text-instructions.
std::string buildTextBody(const std::string &personaId, const std::string &text);

}  // namespace nb
```

- [ ] **Step 4: Create `cardputer/lib/nb_session_json/SessionJson.cpp` (bootstrap + personas only for now)**

```cpp
#include "SessionJson.h"
#include <ArduinoJson.h>

namespace nb {

bool parseBootstrap(const std::string &json, Bootstrap &out) {
  JsonDocument doc;
  if (deserializeJson(doc, json) != DeserializationError::Ok) return false;
  if (!doc["session_id"].is<const char *>()) return false;
  out.sessionId = doc["session_id"].as<std::string>();
  out.defaultPersonaId =
      doc["default_persona_id"].is<const char *>() ? doc["default_persona_id"].as<std::string>() : std::string();
  return true;
}

bool parsePersonas(const std::string &json, std::vector<Persona> &out) {
  JsonDocument doc;
  if (deserializeJson(doc, json) != DeserializationError::Ok) return false;
  if (!doc.is<JsonArray>()) return false;
  out.clear();
  for (JsonObject item : doc.as<JsonArray>()) {
    Persona p;
    p.id = item["persona_id"].as<std::string>();
    p.name = item["name"].as<std::string>();
    p.avatar = item["avatar"].as<std::string>();
    p.busy = std::string("busy") == (item["status"].is<const char *>() ? item["status"].as<const char *>() : "");
    out.push_back(p);
  }
  return true;
}

// (extractLatestTurn, parseAudioTranscript, buildAudioQuery, buildTextBody added in Task 3)

}  // namespace nb
```

- [ ] **Step 5: Run to verify the bootstrap/personas tests pass**

Run: `cd cardputer && pio test -e native -f test_session_json`
Expected: PASS (5 tests).

- [ ] **Step 6: Commit**

```bash
git add cardputer/lib/nb_session_json cardputer/test/test_session_json
git commit -m "feat(cardputer): parse bootstrap + personas (nb_session_json)"
```

---

### Task 3: `nb_session_json` — snapshot turn extraction + request builders

**Files:**
- Modify: `cardputer/lib/nb_session_json/SessionJson.cpp`
- Modify: `cardputer/test/test_session_json/test_session_json.cpp`

- [ ] **Step 1: Append tests to `cardputer/test/test_session_json/test_session_json.cpp`** (add the `RUN_TEST` lines into the existing `main`)

Add these test functions above `main`, and add their `RUN_TEST(...)` calls inside `main`:

```cpp
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
  // create_new_thread defaults false; only required fields are emitted.
  TEST_ASSERT_TRUE(b.find(R"("target_persona_id":"p1")") != std::string::npos);
  TEST_ASSERT_TRUE(b.find(R"("text":"hi")") != std::string::npos);
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd cardputer && pio test -e native -f test_session_json`
Expected: FAIL — `extractLatestTurn`/`parseAudioTranscript`/`buildAudioQuery`/`buildTextBody` undefined (linker/compile error).

- [ ] **Step 3: Implement the new functions in `cardputer/lib/nb_session_json/SessionJson.cpp`**

Replace the `// (… added in Task 3)` comment with:

```cpp
bool extractLatestTurn(const std::string &snapshotJson, const std::string &personaId, TurnView &out) {
  // Filter: deserialize only bro_timeline_turns and the few fields we render.
  JsonDocument filter;
  JsonObject t = filter["bro_timeline_turns"].add<JsonObject>();
  t["persona_id"] = true;
  t["status"] = true;
  t["created_at"] = true;
  t["user"]["text"] = true;
  t["user"]["transcript"] = true;
  t["assistant"]["text"] = true;

  JsonDocument doc;
  if (deserializeJson(doc, snapshotJson, DeserializationOption::Filter(filter)) != DeserializationError::Ok) {
    return false;
  }
  out = TurnView{};
  std::string bestCreatedAt;
  for (JsonObject turn : doc["bro_timeline_turns"].as<JsonArray>()) {
    if (personaId != (turn["persona_id"].is<const char *>() ? turn["persona_id"].as<const char *>() : "")) continue;
    std::string createdAt = turn["created_at"].as<std::string>();
    // ISO-8601 timestamps sort lexicographically; keep the latest.
    if (out.found && createdAt < bestCreatedAt) continue;
    bestCreatedAt = createdAt;
    out.found = true;
    out.status = turn["status"].as<std::string>();
    JsonObject user = turn["user"];
    out.userText = user["transcript"].is<const char *>() ? user["transcript"].as<std::string>()
                   : user["text"].is<const char *>()     ? user["text"].as<std::string>()
                                                          : std::string();
    JsonObject assistant = turn["assistant"];
    out.assistantText = assistant["text"].is<const char *>() ? assistant["text"].as<std::string>() : std::string();
  }
  return true;
}

std::string parseAudioTranscript(const std::string &json) {
  JsonDocument doc;
  if (deserializeJson(doc, json) != DeserializationError::Ok) return std::string();
  return doc["transcript_text"].is<const char *>() ? doc["transcript_text"].as<std::string>() : std::string();
}

std::string buildAudioQuery(const std::string &personaId, const AudioMeta &m) {
  std::string q;
  q += "target_persona_id=" + personaId;
  q += "&duration_ms=" + std::to_string(m.durationMs);
  q += "&sample_rate=" + std::to_string(m.sampleRate);
  q += "&num_channels=" + std::to_string(static_cast<unsigned>(m.numChannels));
  q += "&samples_per_channel=" + std::to_string(m.samplesPerChannel);
  return q;
}

std::string buildTextBody(const std::string &personaId, const std::string &text) {
  JsonDocument doc;
  doc["target_persona_id"] = personaId;
  doc["text"] = text;
  doc["create_new_thread"] = false;
  std::string out;
  serializeJson(doc, out);
  return out;
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd cardputer && pio test -e native -f test_session_json`
Expected: PASS (10 tests total).

- [ ] **Step 5: Commit**

```bash
git add cardputer/lib/nb_session_json cardputer/test/test_session_json
git commit -m "feat(cardputer): snapshot turn extraction + request builders (nb_session_json)"
```

---

### Task 4: Extend `Transport` for binary/content-typed requests

**Files:**
- Modify: `cardputer/lib/nb_transport/Transport.h`
- Modify: `cardputer/src/transport/HttpsTransport.h`, `cardputer/src/transport/HttpsTransport.cpp`

Add a second virtual method for a body with an explicit content type and raw bytes (used by the audio POST). Keep the existing JSON `request(...)` for compatibility with Plan A's pairing calls.

- [ ] **Step 1: Extend `cardputer/lib/nb_transport/Transport.h`**

Add this pure-virtual method to the `Transport` class (after the existing `request(...)`):

```cpp
  // POST raw bytes with an explicit Content-Type (e.g. "audio/pcm").
  // cookieToken, when non-empty, is sent as "Cookie: newbro_session=<cookieToken>".
  virtual HttpResponse postBytes(const std::string &path, const std::string &contentType,
                                 const uint8_t *body, size_t len, const std::string &cookieToken) = 0;
```

Add `#include <cstdint>` and `#include <cstddef>` at the top of the header.

- [ ] **Step 2: Implement it in `cardputer/src/transport/HttpsTransport.h`**

Add the override declaration to the class:

```cpp
  HttpResponse postBytes(const std::string &path, const std::string &contentType,
                         const uint8_t *body, size_t len, const std::string &cookieToken) override;
```

- [ ] **Step 3: Implement it in `cardputer/src/transport/HttpsTransport.cpp`**

Add this method (mirrors the existing `request`, but with a caller-supplied content type and raw body):

```cpp
HttpResponse HttpsTransport::postBytes(const std::string &path, const std::string &contentType,
                                       const uint8_t *body, size_t len, const std::string &cookieToken) {
  HttpResponse out;
  WiFiClientSecure client;
  client.setCACertBundle(rootca_crt_bundle_start);

  HTTPClient https;
  std::string url = "https://" + host_ + ":" + std::to_string(port_) + path;
  if (!https.begin(client, url.c_str())) {
    out.transportOk = false;
    return out;
  }
  https.addHeader("Content-Type", contentType.c_str());
  if (!cookieToken.empty()) {
    https.addHeader("Cookie", ("newbro_session=" + cookieToken).c_str());
  }
  int code = https.POST(const_cast<uint8_t *>(body), len);
  if (code <= 0) {
    out.transportOk = false;
  } else {
    out.transportOk = true;
    out.status = code;
    out.body = std::string(https.getString().c_str());
  }
  https.end();
  return out;
}
```

- [ ] **Step 4: Verify device compile**

Run: `cd cardputer && pio run -e device`
Expected: compiles + links (the existing `probe`/`store` references in `main.cpp` still pull in the transport).

> Native tests don't build `src/`, so `HttpsTransport` isn't compiled there. The interface change is exercised by the fake in Task 5.

- [ ] **Step 5: Commit**

```bash
git add cardputer/lib/nb_transport/Transport.h cardputer/src/transport
git commit -m "feat(cardputer): add binary postBytes to Transport + HttpsTransport"
```

---

### Task 5: `NewbroClient` — auth token + bootstrap + listPersonas + sendText

**Files:**
- Modify: `cardputer/lib/nb_client/NewbroClient.h`, `cardputer/lib/nb_client/NewbroClient.cpp`
- Create: `cardputer/test/test_client_convo/test_client_convo.cpp`

- [ ] **Step 1: Write the failing test `cardputer/test/test_client_convo/test_client_convo.cpp`**

```cpp
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd cardputer && pio test -e native -f test_client_convo`
Expected: FAIL — `setAuthToken`/`bootstrap`/`listPersonas`/`sendText` undefined; `SessionJson.h` types unused yet.

- [ ] **Step 3: Extend `cardputer/lib/nb_client/NewbroClient.h`**

Add the include, the auth token, and the new method declarations:

```cpp
#pragma once
#include <string>
#include <vector>
#include "Transport.h"
#include "PairingJson.h"
#include "SessionJson.h"
#include "AudioMeta.h"

namespace nb {

class NewbroClient {
 public:
  explicit NewbroClient(Transport &transport) : t_(transport) {}

  void setAuthToken(const std::string &token) { token_ = token; }

  // Pairing (Plan A)
  bool startPairing(PairStart &out);
  bool pollPairing(const std::string &deviceCode, PollResult &out);

  // Conversation (Plan B)
  bool bootstrap(Bootstrap &out);
  bool listPersonas(const std::string &sessionId, std::vector<Persona> &out);
  bool sendText(const std::string &sessionId, const std::string &personaId, const std::string &text);
  bool sendAudio(const std::string &sessionId, const std::string &personaId, const AudioMeta &meta,
                 const uint8_t *pcm, size_t len, std::string &transcriptOut);
  bool getReply(const std::string &sessionId, const std::string &personaId, TurnView &out);

  const std::string &lastError() const { return lastError_; }

 private:
  Transport &t_;
  std::string lastError_;
  std::string token_;
};

}  // namespace nb
```

- [ ] **Step 4: Implement bootstrap/listPersonas/sendText in `cardputer/lib/nb_client/NewbroClient.cpp`**

Add at the top (keep existing pairing methods unchanged):

```cpp
#include "NewbroClient.h"

namespace nb {

// ... existing startPairing / pollPairing unchanged ...

bool NewbroClient::bootstrap(Bootstrap &out) {
  lastError_.clear();
  HttpResponse r = t_.request("GET", "/api/me/bootstrap", "", token_);
  if (!r.transportOk) { lastError_ = "network error"; return false; }
  if (r.status != 200) { lastError_ = "bootstrap failed: HTTP " + std::to_string(r.status); return false; }
  if (!parseBootstrap(r.body, out)) { lastError_ = "bad bootstrap response"; return false; }
  return true;
}

bool NewbroClient::listPersonas(const std::string &sessionId, std::vector<Persona> &out) {
  lastError_.clear();
  HttpResponse r = t_.request("GET", "/api/sessions/" + sessionId + "/personas", "", token_);
  if (!r.transportOk) { lastError_ = "network error"; return false; }
  if (r.status != 200) { lastError_ = "personas failed: HTTP " + std::to_string(r.status); return false; }
  if (!parsePersonas(r.body, out)) { lastError_ = "bad personas response"; return false; }
  return true;
}

bool NewbroClient::sendText(const std::string &sessionId, const std::string &personaId, const std::string &text) {
  lastError_.clear();
  HttpResponse r = t_.request("POST", "/api/sessions/" + sessionId + "/executor-text-instructions",
                              buildTextBody(personaId, text), token_);
  if (!r.transportOk) { lastError_ = "network error"; return false; }
  if (r.status != 200) { lastError_ = "text failed: HTTP " + std::to_string(r.status); return false; }
  return true;
}

}  // namespace nb
```

> Note: `sendAudio` and `getReply` are added in Task 6; this file will reference them only after Task 6. The three tests above don't call them.

- [ ] **Step 5: Run to verify it passes**

Run: `cd cardputer && pio test -e native -f test_client_convo`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add cardputer/lib/nb_client cardputer/test/test_client_convo
git commit -m "feat(cardputer): NewbroClient auth token + bootstrap/personas/text"
```

---

### Task 6: `NewbroClient` — sendAudio + getReply

**Files:**
- Modify: `cardputer/lib/nb_client/NewbroClient.cpp`
- Modify: `cardputer/test/test_client_convo/test_client_convo.cpp`

- [ ] **Step 1: Append tests** (add functions above `main`, add `RUN_TEST` calls inside `main`)

```cpp
void test_send_audio_posts_pcm_and_returns_transcript(void) {
  FakeTransport t;
  t.responses.push_back(HttpResponse{true, 200, R"({"status":"accepted","transcript_text":"ship it"})"});
  NewbroClient client(t);
  client.setAuthToken("tok");

  uint8_t pcm[4] = {1, 2, 3, 4};
  AudioMeta m = computeAudioMeta(/*samplesPerChannel=*/2, /*sampleRate=*/16000, /*numChannels=*/1);  // byteLen=4
  std::string transcript;
  TEST_ASSERT_TRUE(client.sendAudio("s1", "p1", m, pcm, 4, transcript));
  TEST_ASSERT_EQUAL_STRING("ship it", transcript.c_str());
  TEST_ASSERT_TRUE(t.calls[0].binary);
  TEST_ASSERT_EQUAL_STRING("audio/pcm", t.calls[0].contentType.c_str());
  TEST_ASSERT_TRUE(t.calls[0].path.find("/api/sessions/s1/executor-audio-instructions?") != std::string::npos);
  TEST_ASSERT_TRUE(t.calls[0].path.find("target_persona_id=p1") != std::string::npos);
  TEST_ASSERT_TRUE(t.calls[0].path.find("samples_per_channel=2") != std::string::npos);
  TEST_ASSERT_EQUAL_STRING("tok", t.calls[0].cookie.c_str());
}

void test_get_reply_extracts_turn(void) {
  FakeTransport t;
  t.responses.push_back(HttpResponse{true, 200, R"({
    "bro_timeline_turns":[
      {"persona_id":"p1","status":"running","user":{"transcript":"ship it"},"assistant":{"text":"on it"},"created_at":"2026-06-04T00:00:03+00:00"}
    ]})"});
  NewbroClient client(t);
  client.setAuthToken("tok");
  TurnView v;
  TEST_ASSERT_TRUE(client.getReply("s1", "p1", v));
  TEST_ASSERT_TRUE(v.found);
  TEST_ASSERT_EQUAL_STRING("on it", v.assistantText.c_str());
  TEST_ASSERT_EQUAL_STRING("/api/sessions/s1", t.calls[0].path.c_str());
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd cardputer && pio test -e native -f test_client_convo`
Expected: FAIL — `sendAudio`/`getReply` undefined.

- [ ] **Step 3: Implement in `cardputer/lib/nb_client/NewbroClient.cpp`** (add before the closing `}  // namespace nb`)

```cpp
bool NewbroClient::sendAudio(const std::string &sessionId, const std::string &personaId, const AudioMeta &meta,
                             const uint8_t *pcm, size_t len, std::string &transcriptOut) {
  lastError_.clear();
  transcriptOut.clear();
  std::string path =
      "/api/sessions/" + sessionId + "/executor-audio-instructions?" + buildAudioQuery(personaId, meta);
  HttpResponse r = t_.postBytes(path, "audio/pcm", pcm, len, token_);
  if (!r.transportOk) { lastError_ = "network error"; return false; }
  if (r.status != 200) { lastError_ = "audio failed: HTTP " + std::to_string(r.status); return false; }
  transcriptOut = parseAudioTranscript(r.body);
  return true;
}

bool NewbroClient::getReply(const std::string &sessionId, const std::string &personaId, TurnView &out) {
  lastError_.clear();
  HttpResponse r = t_.request("GET", "/api/sessions/" + sessionId, "", token_);
  if (!r.transportOk) { lastError_ = "network error"; return false; }
  if (r.status != 200) { lastError_ = "snapshot failed: HTTP " + std::to_string(r.status); return false; }
  if (!extractLatestTurn(r.body, personaId, out)) { lastError_ = "bad snapshot"; return false; }
  return true;
}
```

- [ ] **Step 4: Run to verify it passes; then the full native suite**

Run: `cd cardputer && pio test -e native -f test_client_convo` → PASS (5 tests).
Run: `cd cardputer && pio test -e native` → all suites pass (Plan A's 24 + Plan B's: test_audio, test_session_json, test_client_convo).

- [ ] **Step 5: Commit**

```bash
git add cardputer/lib/nb_client cardputer/test/test_client_convo
git commit -m "feat(cardputer): NewbroClient sendAudio + snapshot reply (getReply)"
```

---

### Task 7: `MicRecorder` — push-to-talk PCM16 capture (device glue)

**Files:**
- Create: `cardputer/src/audio/MicRecorder.h`, `cardputer/src/audio/MicRecorder.cpp`

Device-only (uses `M5Cardputer.Mic`); verified by device compile + Task 8 smoke. Captures mono PCM16 at 16 kHz into a fixed buffer while called repeatedly, capping at a max duration.

- [ ] **Step 1: Create `cardputer/src/audio/MicRecorder.h`**

```cpp
#pragma once
#include <cstddef>
#include <cstdint>

namespace nb {

// Fixed-capacity mono PCM16 capture buffer for push-to-talk.
class MicRecorder {
 public:
  static constexpr uint32_t kSampleRate = 16000;
  static constexpr size_t kMaxSamples = kSampleRate * 10;  // 10 s cap

  void beginRecording();                 // start mic, reset buffer
  void poll();                           // capture available samples (call frequently while held)
  void endRecording();                   // stop mic
  const int16_t *data() const { return buffer_; }
  size_t sampleCount() const { return count_; }

 private:
  int16_t buffer_[kMaxSamples];
  size_t count_ = 0;
};

}  // namespace nb
```

- [ ] **Step 2: Create `cardputer/src/audio/MicRecorder.cpp`**

```cpp
#include "audio/MicRecorder.h"

#include <M5Cardputer.h>

namespace nb {

void MicRecorder::beginRecording() {
  count_ = 0;
  M5Cardputer.Speaker.end();  // mic and speaker can't run together
  M5Cardputer.Mic.begin();
}

void MicRecorder::poll() {
  if (!M5Cardputer.Mic.isEnabled() || count_ >= kMaxSamples) return;
  // Pull a chunk; M5Cardputer.Mic.record fills the buffer with mono samples at the given rate.
  static constexpr size_t kChunk = 256;
  size_t room = kMaxSamples - count_;
  size_t want = room < kChunk ? room : kChunk;
  if (M5Cardputer.Mic.record(buffer_ + count_, want, kSampleRate)) {
    count_ += want;
  }
}

void MicRecorder::endRecording() { M5Cardputer.Mic.end(); }

}  // namespace nb
```

- [ ] **Step 3: Verify device compile**

Run: `cd cardputer && pio run -e device`
Expected: compiles. (Not referenced yet — main.cpp wires it in Task 8. PlatformIO compiles all of `src/`.)

> Note: `M5Cardputer.Mic.record(buf, len, rate)` is the documented capture API; if a parameter form differs on the installed library version and the device build fails, report the exact compile error rather than guessing.

- [ ] **Step 4: Commit**

```bash
git add cardputer/src/audio
git commit -m "feat(cardputer): push-to-talk PCM16 mic capture (MicRecorder)"
```

---

### Task 8: Router — discover Bro, push-to-talk, poll reply (headless)

**Files:**
- Modify: `cardputer/src/main.cpp`

Extend the post-"Ready" flow: load the token into the transport, bootstrap, list personas, pick the first one, then loop — hold the `` ` `` (or any) key to record; on release, upload audio, show the transcript, and poll the snapshot for the reply until the turn completes. Plain text screens (Ink UI is Plan C). Device compile + on-device smoke.

- [ ] **Step 1: Replace the body of `setup()`'s final phase and `loop()` in `cardputer/src/main.cpp`**

Add these includes at the top (with the existing ones):

```cpp
#include <vector>
#include "AudioMeta.h"
#include "SessionJson.h"
#include "audio/MicRecorder.h"
```

Add these file-scope globals (in the existing anonymous namespace, alongside `g_store`/`g_wifi`/`g_config`):

```cpp
nb::MicRecorder g_mic;
std::string g_sessionId;
std::string g_personaId;
std::string g_personaName;
```

Add this helper in the anonymous namespace (after `runPairing`):

```cpp
// One push-to-talk turn: record while a key is held, upload, then poll the reply.
void runVoiceTurn(nb::NewbroClient &client) {
  nb::screen::status(g_personaName, "recording...");
  g_mic.beginRecording();
  // Record while any key remains held.
  while (true) {
    M5Cardputer.update();
    g_mic.poll();
    if (!M5Cardputer.Keyboard.isPressed()) break;
    delay(5);
  }
  g_mic.endRecording();

  if (g_mic.sampleCount() == 0) {
    nb::screen::status(g_personaName, "nothing recorded");
    return;
  }

  nb::AudioMeta meta = nb::computeAudioMeta(g_mic.sampleCount(), nb::MicRecorder::kSampleRate, 1);
  nb::screen::status(g_personaName, "transcribing...");
  std::string transcript;
  if (!client.sendAudio(g_sessionId, g_personaId, meta,
                        reinterpret_cast<const uint8_t *>(g_mic.data()), meta.byteLen, transcript)) {
    nb::screen::status("Send failed", client.lastError());
    return;
  }
  Serial.printf("you: %s\n", transcript.c_str());

  // Poll the snapshot until the Bro's turn completes (bounded).
  std::string lastShown;
  for (int i = 0; i < 60; ++i) {  // ~60s max at 1s intervals
    delay(1000);
    M5Cardputer.update();
    nb::TurnView v;
    if (client.getReply(g_sessionId, g_personaId, v) && v.found) {
      if (v.assistantText != lastShown) {
        lastShown = v.assistantText;
        nb::screen::status(g_personaName, v.assistantText);
        Serial.printf("%s: %s [%s]\n", g_personaName.c_str(), v.assistantText.c_str(), v.status.c_str());
      }
      if (v.status == "completed" || v.status == "failed" || v.status == "cancelled") break;
    }
  }
}
```

Replace the final lines of `setup()` (the `nb::screen::status("Ready", ...)` line) with the conversation bootstrap:

```cpp
  // --- Conversation bootstrap (Plan B) ---
  static nb::HttpsTransport g_transport(g_config.serverHost, g_config.serverPort);
  static nb::NewbroClient g_client(g_transport);
  g_client.setAuthToken(g_config.deviceToken);

  nb::Bootstrap boot;
  if (!g_client.bootstrap(boot)) {
    nb::screen::status("Bootstrap failed", g_client.lastError());
    return;
  }
  g_sessionId = boot.sessionId;

  std::vector<nb::Persona> personas;
  if (!g_client.listPersonas(g_sessionId, personas) || personas.empty()) {
    nb::screen::status("No bros yet", "add a bro in the newbro app, then reboot");
    return;
  }
  g_personaId = personas[0].id;
  g_personaName = personas[0].name;

  nb::screen::status(g_personaName, "hold a key to talk");
  // Stash the client pointer for loop() use.
  g_clientPtr = &g_client;
}
```

Add a file-scope `nb::NewbroClient *g_clientPtr = nullptr;` in the anonymous namespace, and replace `loop()`:

```cpp
void loop() {
  M5Cardputer.update();
  if (g_clientPtr && !g_sessionId.empty() && !g_personaId.empty() &&
      M5Cardputer.Keyboard.isChange() && M5Cardputer.Keyboard.isPressed()) {
    runVoiceTurn(*g_clientPtr);
    nb::screen::status(g_personaName, "hold a key to talk");
  }
  delay(5);
}
```

> Design note: the `static` transport/client inside `setup()` persist for the program lifetime (Arduino `setup()` runs once); `g_clientPtr` exposes the client to `loop()`. This is intentional and matches the single-threaded Arduino model.

- [ ] **Step 2: Verify device compile**

Run: `cd cardputer && pio run -e device`
Expected: compiles + links.

- [ ] **Step 3: Confirm native tests still pass**

Run: `cd cardputer && pio test -e native`
Expected: all suites green (Plan A + Plan B).

- [ ] **Step 4: On-device smoke** (requires a Cardputer, a reachable server with ≥1 Bro, and a completed Plan A pairing)

DO NOT attempt without hardware. Note in your report that this is deferred to the user.

Flash + monitor: `cd cardputer && pio run -e device -t upload && pio device monitor`
1. Device reaches "Ready" → bootstraps → shows the first Bro's name + "hold a key to talk".
2. Hold a key and speak; screen shows "recording..." then "transcribing...".
3. Serial prints `you: <transcript>` matching what you said.
4. Screen + serial show the Bro's reply text, updating until the turn status is `completed`.
5. Repeat a second turn to confirm the loop is reusable.

Record pass/fail per step in the PR.

- [ ] **Step 5: Commit**

```bash
git add cardputer/src/main.cpp
git commit -m "feat(cardputer): wire push-to-talk voice turn + reply polling"
```

---

## Self-Review

**Spec coverage (against spec §3, §5–§7 for the Plan-B slice):**
- `MicRecorder` (PDM push-to-talk → PCM16) → Task 7. ✓
- `NewbroClient` bootstrap/personas/audio/text → Tasks 5–6; the `Cookie: newbro_session` auth is set via `setAuthToken` + carried by `HttpsTransport` (Task 4). ✓
- Voice send via `executor-audio-instructions` (raw PCM16 + metadata), transcript returned → `sendAudio` + `nb_audio` metadata + `buildAudioQuery` (Tasks 1, 3, 6). ✓
- Bro's reply rendered (streaming-ish) → snapshot polling + `extractLatestTurn` (Tasks 3, 6, 8). Replaces the WebSocket `EventStream` from the spec's module list: the direct-executor path only publishes full snapshots, so polling `GET /sessions/{id}` over the existing HTTPS transport is simpler and avoids a WebSocket-over-TLS integration. The WS push remains a possible later optimization.
- Bro list / selection → `listPersonas` + first-persona selection in the router (Task 8); the visual `BroListScreen`/`ChatScreen` are Plan C.
- Text instruction path (secondary input) → `sendText` (Task 5). ✓
- Host-testable logic split from hardware (spec §9) → all parsing/metadata/client logic in `lib/` with native Unity tests (Tasks 1–6); mic capture + router are device glue (Tasks 7–8). ✓
- Out of Plan B (deferred to Plan C): `Theme`, `BroGlyph`, `BroListScreen`, `ChatScreen` Ink UI, on-screen scrolling/animation. Speaker TTS of replies remains out of scope per the spec.

**Placeholder scan:** No TBD/TODO. Every code step contains complete code. Risky hardware specifics (mic `record` parameter form) carry an explicit "report the compile error" escalation rather than a vague instruction. The on-device smoke is a concrete numbered procedure.

**Type/name consistency:** `nb::AudioMeta` + `computeAudioMeta` (Task 1) feed `buildAudioQuery`/`sendAudio` (Tasks 3, 6). `nb::Bootstrap`/`Persona`/`TurnView` (Task 2/3) are produced by `parseBootstrap`/`parsePersonas`/`extractLatestTurn` and consumed by `NewbroClient::bootstrap`/`listPersonas`/`getReply` (Tasks 5–6) and the router (Task 8). `Transport::postBytes` (Task 4) is implemented by `HttpsTransport` and the test `FakeTransport`, and called by `sendAudio` (Task 6). `NewbroClient::setAuthToken` sets `token_`, passed as the `cookieToken` arg on every authenticated call. Endpoint paths match the contract section. `MicRecorder::kSampleRate`/`data()`/`sampleCount()` (Task 7) are used by the router (Task 8). ✓
