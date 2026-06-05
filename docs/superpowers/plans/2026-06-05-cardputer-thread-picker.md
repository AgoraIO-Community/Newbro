# Cardputer Thread Picker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After selecting a Bro, the Cardputer lists that Bro's existing threads; the user picks one and the chat sends instructions targeting that `thread_id` (never creating a thread), clearing the server's "explicit thread intent" 409.

**Architecture:** A host-tested `parseBroThreads` reads the snapshot's `bro_threads` for a persona; `buildAudioQuery`/`buildTextBody` and `NewbroClient::sendAudio`/`sendText` gain a `targetThreadId` (and drop `create_new_thread`); a new device-only `ThreadListScreen` (mirroring `BroListScreen`) sits between the Bro list and chat, wired by `main.cpp` into a 3-page flow.

**Tech Stack:** C++17, PlatformIO, Arduino-ESP32 (`m5stack/M5Cardputer`), `bblanchon/ArduinoJson` v7, Unity (host tests). Builds on the working device firmware (no-PSRAM + pinned-CA + push-to-talk fixes).

---

## Prerequisites

- Branch `feat/cardputer-thread-picker` (stacked on the device-fix branch). The `cardputer/` firmware boots, connects, pairs, and records/uploads; push-to-talk currently fails only with the 409 this plan fixes.
- Run `pio` from inside `cardputer/`.
- Snapshot contract: `GET /api/sessions/{id}` returns `bro_threads[]` with `thread_id`, `persona_id`, `title`, `preview` (str|null), `status`, `updated_at` (str|null). Audio: `POST /api/sessions/{id}/executor-audio-instructions?...&target_thread_id=<id>` (no `create_new_thread`).

## File Structure

| Path | Responsibility | Built in |
|---|---|---|
| `cardputer/lib/nb_session_json/SessionJson.{h,cpp}` | add `ThreadInfo` + `parseBroThreads`; add `targetThreadId` to `buildAudioQuery`/`buildTextBody` | both |
| `cardputer/lib/nb_client/NewbroClient.{h,cpp}` | add `getThreads`; add `targetThreadId` to `sendAudio`/`sendText` | both |
| `cardputer/test/test_session_json/test_session_json.cpp` | tests for `parseBroThreads` + updated builders | native |
| `cardputer/test/test_client_convo/test_client_convo.cpp` | tests for `getThreads` + updated send signatures | native |
| `cardputer/src/ui/ThreadListScreen.{h,cpp}` | Ink thread-picker screen | device |
| `cardputer/src/ui/ChatScreen.{h,cpp}` | add `setThread` | device |
| `cardputer/src/main.cpp` | 3-page flow (Bro list → Thread list → Chat) | device |

---

### Task 1: `parseBroThreads` (+ `ThreadInfo`)

**Files:**
- Modify: `cardputer/lib/nb_session_json/SessionJson.h`, `cardputer/lib/nb_session_json/SessionJson.cpp`
- Modify: `cardputer/test/test_session_json/test_session_json.cpp`

- [ ] **Step 1: Append tests** (add functions above `main`, and their `RUN_TEST(...)` inside `main`)

```cpp
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
  // newest-first: t-new (00:00:05) before t-old (00:00:01)
  TEST_ASSERT_EQUAL_STRING("t-new", out[0].id.c_str());
  TEST_ASSERT_EQUAL_STRING("Ship it", out[0].title.c_str());
  TEST_ASSERT_TRUE(out[0].preview.empty());  // null preview -> empty
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
```

- [ ] **Step 2: Run red**

Run: `cd cardputer && pio test -e native -f test_session_json`
Expected: FAIL — `ThreadInfo` / `parseBroThreads` undeclared.

- [ ] **Step 3: Declare in `cardputer/lib/nb_session_json/SessionJson.h`** (after the `TurnView` struct, before the function declarations)

```cpp
struct ThreadInfo {
  std::string id;
  std::string title;
  std::string preview;    // empty if null
  std::string status;
  std::string updatedAt;  // ISO-8601; empty if null
};
```

And add this declaration (with the other `parse*` declarations):

```cpp
// Threads for one persona from a full SessionSnapshot, newest-first
// (updated_at descending; empty updated_at sorts last).
bool parseBroThreads(const std::string &snapshotJson, const std::string &personaId,
                     std::vector<ThreadInfo> &out);
```

- [ ] **Step 4: Implement in `cardputer/lib/nb_session_json/SessionJson.cpp`**

Add `#include <algorithm>` near the top (below `#include <ArduinoJson.h>`). Add the function before the closing `}  // namespace nb`:

```cpp
bool parseBroThreads(const std::string &snapshotJson, const std::string &personaId,
                     std::vector<ThreadInfo> &out) {
  JsonDocument filter;
  JsonObject t = filter["bro_threads"].add<JsonObject>();
  t["thread_id"] = true;
  t["persona_id"] = true;
  t["title"] = true;
  t["preview"] = true;
  t["status"] = true;
  t["updated_at"] = true;

  JsonDocument doc;
  if (deserializeJson(doc, snapshotJson, DeserializationOption::Filter(filter)) != DeserializationError::Ok) {
    return false;
  }
  out.clear();
  for (JsonObject th : doc["bro_threads"].as<JsonArray>()) {
    const char *pid = th["persona_id"].is<const char *>() ? th["persona_id"].as<const char *>() : "";
    if (personaId != pid) continue;
    ThreadInfo info;
    info.id = th["thread_id"].as<std::string>();
    info.title = th["title"].is<const char *>() ? th["title"].as<std::string>() : std::string();
    info.preview = th["preview"].is<const char *>() ? th["preview"].as<std::string>() : std::string();
    info.status = th["status"].is<const char *>() ? th["status"].as<std::string>() : std::string();
    info.updatedAt = th["updated_at"].is<const char *>() ? th["updated_at"].as<std::string>() : std::string();
    out.push_back(info);
  }
  std::sort(out.begin(), out.end(), [](const ThreadInfo &a, const ThreadInfo &b) {
    return a.updatedAt > b.updatedAt;  // ISO-8601 desc; "" sorts last
  });
  return true;
}
```

- [ ] **Step 5: Run green**

Run: `cd cardputer && pio test -e native -f test_session_json`
Expected: PASS (existing + 3 new).

- [ ] **Step 6: Commit**

```bash
git add cardputer/lib/nb_session_json cardputer/test/test_session_json
git commit -m "feat(cardputer): parse a Bro's threads from the snapshot (parseBroThreads)"
```

---

### Task 2: `targetThreadId` in the request builders

**Files:**
- Modify: `cardputer/lib/nb_session_json/SessionJson.h`, `cardputer/lib/nb_session_json/SessionJson.cpp`
- Modify: `cardputer/test/test_session_json/test_session_json.cpp`

- [ ] **Step 1: Update the two builder tests** in `test_session_json.cpp`

Replace `test_build_audio_query` body and `test_build_text_body` body with:

```cpp
void test_build_audio_query(void) {
  AudioMeta m = computeAudioMeta(16000, 16000, 1);
  std::string q = buildAudioQuery("p1", m, "t-7");
  TEST_ASSERT_EQUAL_STRING(
      "target_persona_id=p1&target_thread_id=t-7&duration_ms=1000&sample_rate=16000"
      "&num_channels=1&samples_per_channel=16000",
      q.c_str());
}

void test_build_text_body(void) {
  std::string b = buildTextBody("p1", "hi", "t-7");
  TEST_ASSERT_TRUE(b.find(R"("target_persona_id":"p1")") != std::string::npos);
  TEST_ASSERT_TRUE(b.find(R"("target_thread_id":"t-7")") != std::string::npos);
  TEST_ASSERT_TRUE(b.find(R"("text":"hi")") != std::string::npos);
  TEST_ASSERT_TRUE(b.find(R"("create_new_thread":false)") != std::string::npos);
}
```

- [ ] **Step 2: Run red**

Run: `cd cardputer && pio test -e native -f test_session_json`
Expected: FAIL — `buildAudioQuery`/`buildTextBody` called with 3 args but declared with 2.

- [ ] **Step 3: Update declarations in `SessionJson.h`**

```cpp
std::string buildAudioQuery(const std::string &personaId, const AudioMeta &m,
                            const std::string &targetThreadId);
std::string buildTextBody(const std::string &personaId, const std::string &text,
                          const std::string &targetThreadId);
```

- [ ] **Step 4: Update definitions in `SessionJson.cpp`**

```cpp
std::string buildAudioQuery(const std::string &personaId, const AudioMeta &m,
                            const std::string &targetThreadId) {
  std::string q;
  q += "target_persona_id=" + personaId;
  q += "&target_thread_id=" + targetThreadId;
  q += "&duration_ms=" + std::to_string(m.durationMs);
  q += "&sample_rate=" + std::to_string(m.sampleRate);
  q += "&num_channels=" + std::to_string(static_cast<unsigned>(m.numChannels));
  q += "&samples_per_channel=" + std::to_string(m.samplesPerChannel);
  return q;
}

std::string buildTextBody(const std::string &personaId, const std::string &text,
                          const std::string &targetThreadId) {
  JsonDocument doc;
  doc["target_persona_id"] = personaId;
  doc["target_thread_id"] = targetThreadId;
  doc["text"] = text;
  doc["create_new_thread"] = false;
  std::string out;
  serializeJson(doc, out);
  return out;
}
```

- [ ] **Step 5: Run green**

Run: `cd cardputer && pio test -e native -f test_session_json`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add cardputer/lib/nb_session_json cardputer/test/test_session_json
git commit -m "feat(cardputer): target a thread in audio/text request builders"
```

---

### Task 3: `NewbroClient::getThreads` + thread id in `sendAudio`/`sendText`

**Files:**
- Modify: `cardputer/lib/nb_client/NewbroClient.h`, `cardputer/lib/nb_client/NewbroClient.cpp`
- Modify: `cardputer/test/test_client_convo/test_client_convo.cpp`

- [ ] **Step 1: Update/extend tests in `test_client_convo.cpp`**

Replace the `test_send_audio_posts_pcm_and_returns_transcript` and `test_send_text` calls to pass a thread id, and add a `getThreads` test. Concretely:

- In `test_send_audio_posts_pcm_and_returns_transcript`, change the call line to:
  ```cpp
  TEST_ASSERT_TRUE(client.sendAudio("s1", "p1", "t-7", m, pcm, 4, transcript));
  ```
  and add after the existing path assertions:
  ```cpp
  TEST_ASSERT_TRUE(t.calls[0].path.find("target_thread_id=t-7") != std::string::npos);
  ```
- In `test_send_text`, change the call line to:
  ```cpp
  TEST_ASSERT_TRUE(client.sendText("s1", "p1", "t-7", "ship it"));
  ```
  and add:
  ```cpp
  TEST_ASSERT_TRUE(t.calls[0].body.find("t-7") != std::string::npos);
  ```
- Add this new test function (and its `RUN_TEST` in `main`):
  ```cpp
  void test_get_threads(void) {
    FakeTransport t;
    t.responses.push_back(HttpResponse{true, 200, R"({
      "bro_threads":[
        {"thread_id":"t-new","persona_id":"p1","title":"Ship it","preview":null,"status":"running","updated_at":"2026-06-04T00:00:05+00:00"}
      ]})"});
    NewbroClient client(t);
    client.setAuthToken("tok");
    std::vector<ThreadInfo> out;
    TEST_ASSERT_TRUE(client.getThreads("s1", "p1", out));
    TEST_ASSERT_EQUAL_INT(1, (int)out.size());
    TEST_ASSERT_EQUAL_STRING("t-new", out[0].id.c_str());
    TEST_ASSERT_EQUAL_STRING("GET", t.calls[0].method.c_str());
    TEST_ASSERT_EQUAL_STRING("/api/sessions/s1", t.calls[0].path.c_str());
    TEST_ASSERT_EQUAL_STRING("tok", t.calls[0].cookie.c_str());
  }
  ```

- [ ] **Step 2: Run red**

Run: `cd cardputer && pio test -e native -f test_client_convo`
Expected: FAIL — `sendAudio`/`sendText` arity mismatch; `getThreads` undeclared.

- [ ] **Step 3: Update declarations in `NewbroClient.h`**

Change the `sendText`/`sendAudio` declarations and add `getThreads`:

```cpp
  bool sendText(const std::string &sessionId, const std::string &personaId,
                const std::string &targetThreadId, const std::string &text);
  bool sendAudio(const std::string &sessionId, const std::string &personaId,
                 const std::string &targetThreadId, const AudioMeta &meta,
                 const uint8_t *pcm, size_t len, std::string &transcriptOut);
  bool getReply(const std::string &sessionId, const std::string &personaId, TurnView &out);
  bool getThreads(const std::string &sessionId, const std::string &personaId,
                  std::vector<ThreadInfo> &out);
```

- [ ] **Step 4: Update definitions in `NewbroClient.cpp`**

Change `sendText`, `sendAudio`, and add `getThreads`:

```cpp
bool NewbroClient::sendText(const std::string &sessionId, const std::string &personaId,
                            const std::string &targetThreadId, const std::string &text) {
  lastError_.clear();
  HttpResponse r = t_.request("POST", "/api/sessions/" + sessionId + "/executor-text-instructions",
                              buildTextBody(personaId, text, targetThreadId), token_);
  if (!r.transportOk) { lastError_ = "network error"; return false; }
  if (r.status != 200) { lastError_ = "text HTTP " + std::to_string(r.status) + ": " + r.body; return false; }
  return true;
}

bool NewbroClient::sendAudio(const std::string &sessionId, const std::string &personaId,
                             const std::string &targetThreadId, const AudioMeta &meta,
                             const uint8_t *pcm, size_t len, std::string &transcriptOut) {
  lastError_.clear();
  transcriptOut.clear();
  std::string path = "/api/sessions/" + sessionId + "/executor-audio-instructions?" +
                     buildAudioQuery(personaId, meta, targetThreadId);
  HttpResponse r = t_.postBytes(path, "audio/pcm", pcm, len, token_);
  if (!r.transportOk) { lastError_ = "network error"; return false; }
  if (r.status != 200) {
    lastError_ = "audio HTTP " + std::to_string(r.status) + ": " + r.body;
    return false;
  }
  transcriptOut = parseAudioTranscript(r.body);
  return true;
}

bool NewbroClient::getThreads(const std::string &sessionId, const std::string &personaId,
                              std::vector<ThreadInfo> &out) {
  lastError_.clear();
  HttpResponse r = t_.request("GET", "/api/sessions/" + sessionId, "", token_);
  if (!r.transportOk) { lastError_ = "network error"; return false; }
  if (r.status != 200) { lastError_ = "threads HTTP " + std::to_string(r.status); return false; }
  if (!parseBroThreads(r.body, personaId, out)) { lastError_ = "bad snapshot"; return false; }
  return true;
}
```

> Note: `sendText` already wasn't called anywhere in `main.cpp`; this only changes its signature. `sendAudio`'s `main.cpp` call site is updated in Task 6.

- [ ] **Step 5: Run green + full native suite**

Run: `cd cardputer && pio test -e native -f test_client_convo` → PASS.
Run: `cd cardputer && pio test -e native` → all suites green.

- [ ] **Step 6: Commit**

```bash
git add cardputer/lib/nb_client cardputer/test/test_client_convo
git commit -m "feat(cardputer): NewbroClient.getThreads + thread-targeted send"
```

---

### Task 4: `ThreadListScreen`

**Files:**
- Create: `cardputer/src/ui/ThreadListScreen.h`, `cardputer/src/ui/ThreadListScreen.cpp`

Device-only Ink screen, mirroring `BroListScreen`. Verified by device compile + Task 6 smoke.

- [ ] **Step 1: Create `cardputer/src/ui/ThreadListScreen.h`**

```cpp
#pragma once
#include <functional>
#include <string>
#include <vector>
#include "SessionJson.h"  // nb::ThreadInfo
#include "ui/Screen.h"

namespace nb {

class ThreadListScreen : public Screen {
 public:
  void setBroName(const std::string &name) { broName_ = name; }
  void setThreads(const std::vector<ThreadInfo> &threads) {
    threads_ = threads;
    if (selected_ >= (int)threads_.size()) selected_ = 0;
  }
  void onPick(std::function<void(const ThreadInfo &)> cb) { onPick_ = std::move(cb); }
  void onBack(std::function<void()> cb) { onBack_ = std::move(cb); }

  void render(M5Canvas &canvas, uint32_t frame) override;
  void onKey(Key key) override;

 private:
  std::string broName_;
  std::vector<ThreadInfo> threads_;
  int selected_ = 0;
  std::function<void(const ThreadInfo &)> onPick_;
  std::function<void()> onBack_;
};

}  // namespace nb
```

- [ ] **Step 2: Create `cardputer/src/ui/ThreadListScreen.cpp`**

```cpp
#include "ui/ThreadListScreen.h"
#include "ui/Theme.h"
#include "UiLayout.h"

namespace nb {

static constexpr int kRows = 3;
static constexpr int kRowH = 32;
static constexpr int kHeaderH = 26;

void ThreadListScreen::render(M5Canvas &canvas, uint32_t frame) {
  (void)frame;
  canvas.setFont(theme::fontName());
  canvas.setTextColor(theme::text);
  canvas.setCursor(8, 16);
  canvas.print(truncate(broName_.empty() ? "Threads" : broName_, 18).c_str());
  canvas.setFont(theme::fontSmall());
  canvas.setTextColor(theme::muted);
  canvas.setCursor(176, 10);
  canvas.print("threads");
  canvas.drawFastHLine(0, kHeaderH, canvas.width(), theme::line);

  if (threads_.empty()) {
    canvas.setFont(theme::fontBody());
    canvas.setTextColor(theme::muted);
    canvas.setCursor(8, 56);
    canvas.print("No threads.");
    canvas.setFont(theme::fontSmall());
    canvas.setCursor(8, 78);
    canvas.print("Start one in the newbro web app.");
    return;
  }

  int top = listScrollTop(selected_, (int)threads_.size(), kRows);
  for (int row = 0; row < kRows && top + row < (int)threads_.size(); ++row) {
    int idx = top + row;
    const ThreadInfo &th = threads_[idx];
    int y = kHeaderH + 4 + row * kRowH;
    if (idx == selected_) {
      canvas.fillRoundRect(4, y, canvas.width() - 8, kRowH - 4, 6, theme::line);
      canvas.fillRect(4, y, 3, kRowH - 4, theme::coral);
    }
    canvas.setFont(theme::fontName());
    canvas.setTextColor(theme::text);
    canvas.setCursor(12, y + 3);
    canvas.print(truncate(th.title.empty() ? "(untitled)" : th.title, 22).c_str());

    canvas.setFont(theme::fontSmall());
    canvas.setTextColor(theme::muted);
    canvas.setCursor(12, y + 19);
    canvas.print(truncate(th.preview.empty() ? th.status : th.preview, 38).c_str());
  }

  canvas.setFont(theme::fontSmall());
  canvas.setTextColor(theme::muted);
  canvas.setCursor(8, canvas.height() - 12);
  canvas.print("; / .  pick     enter  open     `  back");
}

void ThreadListScreen::onKey(Key key) {
  if (key == Key::Back) {
    if (onBack_) onBack_();
    return;
  }
  if (threads_.empty()) return;
  if (key == Key::Up) selected_ = moveSelection(selected_, (int)threads_.size(), -1);
  else if (key == Key::Down) selected_ = moveSelection(selected_, (int)threads_.size(), +1);
  else if (key == Key::Enter && onPick_) onPick_(threads_[selected_]);
}

}  // namespace nb
```

- [ ] **Step 3: Verify device compile**

Run: `cd cardputer && pio run -e device`
Expected: compiles + links (not wired until Task 6).

- [ ] **Step 4: Commit**

```bash
git add cardputer/src/ui/ThreadListScreen.h cardputer/src/ui/ThreadListScreen.cpp
git commit -m "feat(cardputer): Ink thread-picker screen (ThreadListScreen)"
```

---

### Task 5: `ChatScreen::setThread`

**Files:**
- Modify: `cardputer/src/ui/ChatScreen.h`

The chat needs to remember which thread it targets so the voice turn can send it. (The thread id isn't rendered; it's read by `main.cpp`.)

- [ ] **Step 1: Add a thread field + setter/getter to `cardputer/src/ui/ChatScreen.h`**

In the `public:` section (next to `setBro`):

```cpp
  void setThread(const std::string &threadId) { threadId_ = threadId; }
  const std::string &threadId() const { return threadId_; }
```

In the `private:` section (next to `bro_`):

```cpp
  std::string threadId_;
```

- [ ] **Step 2: Verify device compile**

Run: `cd cardputer && pio run -e device`
Expected: compiles.

- [ ] **Step 3: Commit**

```bash
git add cardputer/src/ui/ChatScreen.h
git commit -m "feat(cardputer): ChatScreen remembers its target thread"
```

---

### Task 6: Wire the 3-page flow in `main.cpp`

**Files:**
- Modify: `cardputer/src/main.cpp`

Replace the `g_inChat` bool with a 3-state page enum; opening a Bro fetches its threads and shows the picker; picking a thread opens the chat bound to that thread; the voice turn targets it.

- [ ] **Step 1: Add the includes, screen, page state, and thread id**

At the top includes (with the other `ui/...` includes), add:
```cpp
#include "ui/ThreadListScreen.h"
```

Replace the global block:
```cpp
nb::Router g_router;
nb::BroListScreen g_listScreen;
nb::ChatScreen g_chatScreen;

nb::NewbroClient *g_clientPtr = nullptr;
std::string g_sessionId;
std::vector<nb::Persona> g_personas;
nb::Persona g_activeBro;
bool g_inChat = false;
```
with:
```cpp
nb::Router g_router;
nb::BroListScreen g_listScreen;
nb::ThreadListScreen g_threadListScreen;
nb::ChatScreen g_chatScreen;

nb::NewbroClient *g_clientPtr = nullptr;
std::string g_sessionId;
std::vector<nb::Persona> g_personas;
nb::Persona g_activeBro;
std::string g_threadId;

enum class Page { BroList, ThreadList, Chat };
Page g_page = Page::BroList;
```

- [ ] **Step 2: Target the thread in `runVoiceTurn`**

In `runVoiceTurn`, change the `sendAudio` call to pass `g_threadId`:
```cpp
  if (!g_clientPtr->sendAudio(g_sessionId, g_activeBro.id, g_threadId, meta,
                              reinterpret_cast<const uint8_t *>(g_mic.data()), meta.byteLen, transcript)) {
```

- [ ] **Step 3: Replace the navigation callbacks**

Replace the existing `openChat` and `backToList` functions with:
```cpp
void openThreads(const nb::Persona &bro) {
  g_activeBro = bro;
  g_threadListScreen.setBroName(bro.name);
  std::vector<nb::ThreadInfo> threads;
  if (!g_clientPtr->getThreads(g_sessionId, bro.id, threads)) {
    Serial.printf("[threads] load failed: %s\n", g_clientPtr->lastError().c_str());
    threads.clear();  // show the empty state rather than a stale list
  }
  g_threadListScreen.setThreads(threads);
  g_page = Page::ThreadList;
  g_router.setScreen(&g_threadListScreen);
}

void openChat(const nb::ThreadInfo &thread) {
  g_threadId = thread.id;
  g_chatScreen.setBro(g_activeBro);
  g_chatScreen.setThread(thread.id);
  g_chatScreen.setTranscript("");
  g_chatScreen.setReply("");
  g_chatScreen.setPhase(nb::Phase::Idle);
  g_page = Page::Chat;
  g_router.setScreen(&g_chatScreen);
}

void backToThreads() {
  g_page = Page::ThreadList;
  g_router.setScreen(&g_threadListScreen);
}

void backToBros() {
  g_page = Page::BroList;
  g_router.setScreen(&g_listScreen);
}
```

- [ ] **Step 4: Wire the callbacks in `setup()`**

Where `setup()` currently has:
```cpp
  g_listScreen.onOpen(openChat);
  g_chatScreen.onBack(backToList);
```
replace with:
```cpp
  g_listScreen.onOpen(openThreads);
  g_threadListScreen.onPick(openChat);
  g_threadListScreen.onBack(backToBros);
  g_chatScreen.onBack(backToThreads);
```

- [ ] **Step 5: Replace the `loop()` key routing**

Replace the body of `loop()` with the 3-page switch:
```cpp
void loop() {
  M5Cardputer.update();
  nb::Key key = g_router.readKey();

  switch (g_page) {
    case Page::BroList:
      if (key != nb::Key::None) g_listScreen.onKey(key);
      break;
    case Page::ThreadList:
      if (key != nb::Key::None) g_threadListScreen.onKey(key);
      break;
    case Page::Chat:
      if (key == nb::Key::Back) g_chatScreen.onKey(nb::Key::Back);
      else if (key == nb::Key::Other) runVoiceTurn();
      break;
  }

  g_router.tick();
  delay(5);
}
```

- [ ] **Step 6: Verify device compile**

Run: `cd cardputer && pio run -e device`
Expected: compiles + links (report flash/RAM).

- [ ] **Step 7: Confirm native tests still pass**

Run: `cd cardputer && pio test -e native`
Expected: all suites green.

- [ ] **Step 8: On-device smoke** (requires hardware + a paired device + a Bro with ≥1 existing thread)

DO NOT attempt without hardware. Note it's deferred to the user. Verify:
1. Boot → Bro list → press Enter on a Bro.
2. The **thread list** appears with that Bro's threads (title + preview, newest first). `;`/`.` move, backtick returns to the Bro list.
3. Press Enter on a thread → chat opens.
4. Hold a key + speak → `recording…` → `transcribing…` → your transcript → the Bro's reply (no more 409).
5. Back (backtick) returns to the thread list.

- [ ] **Step 9: Commit**

```bash
git add cardputer/src/main.cpp
git commit -m "feat(cardputer): Bro list -> thread picker -> chat flow"
```

---

## Self-Review

**Spec coverage:**
- Flow Bro list → Thread list → Chat, Back transitions, never create (spec §2) → Task 6. ✓
- `ThreadInfo` + `parseBroThreads` (filter by persona, newest-first, null handling) (spec §3) → Task 1. ✓
- `target_thread_id` in builders, no `create_new_thread` for audio (spec §4) → Task 2; `sendAudio`/`sendText` thread arg + `getThreads` (spec §4) → Task 3. ✓
- `ThreadListScreen` (title + preview rows, empty state) (spec §5) → Task 4; `ChatScreen::setThread` → Task 5; router/main wiring → Task 6. ✓
- Error handling: snapshot fail → empty state + log; no threads → message (spec §6) → Task 6 Step 3 + Task 4. ✓
- Testing: `parseBroThreads`, builders, `getThreads` host tests; device compile + smoke (spec §7) → Tasks 1–3 tests, Task 6 Steps 7–8. ✓
- `bro-threads/open` verification (spec §8) → covered by the Task 6 on-device smoke (if Step 4 still 409s with a "thread not open"-style detail, add the open call; the surfaced error body makes this visible).

**Placeholder scan:** No TBD/TODO; every code step is complete. The on-device smoke (Task 6 Step 8) is a concrete numbered procedure, deferred (not faked).

**Type/name consistency:** `nb::ThreadInfo{id,title,preview,status,updatedAt}` and `parseBroThreads(snapshotJson, personaId, out)` (Task 1) are used by `getThreads` (Task 3), `ThreadListScreen` (Task 4), and `main.cpp` (Task 6). `buildAudioQuery(personaId, meta, targetThreadId)` / `buildTextBody(personaId, text, targetThreadId)` (Task 2) match `sendAudio`/`sendText` (Task 3) and the `main.cpp` call (Task 6 Step 2). `ThreadListScreen::setBroName/setThreads/onPick/onBack` (Task 4) match the `setup()` wiring (Task 6 Step 4). `ChatScreen::setThread` (Task 5) is set in `openChat` (Task 6 Step 3). The `Page` enum + `g_page` (Task 6 Step 1) drive `loop()` (Task 6 Step 5). ✓
