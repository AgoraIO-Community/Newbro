# Cardputer Firmware Plan A — Skeleton, Connectivity & Pairing

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the M5Stack Cardputer PlatformIO firmware so the device connects to Wi-Fi, completes the device-pairing flow against the newbro server (PR #55 endpoints), and persists its session token — with the pairing/connection logic covered by host-run unit tests.

**Architecture:** Pure, portable logic (config codec, pairing JSON, pairing state machine, backoff, the `NewbroClient`) lives in `cardputer/lib/` with no Arduino dependencies and is unit-tested on the host via PlatformIO's `native` env + Unity. Arduino/hardware glue (HTTPS transport, Wi-Fi, NVS storage, screens, the `main.cpp` router) lives in `cardputer/src/`, depends on the logic through a `Transport` interface, and is verified by a device compile plus an on-device smoke checklist. This is the first of three firmware plans (B = conversation data path, C = the Ink UI).

**Tech Stack:** C++17, PlatformIO, Arduino-ESP32, `m5stack/M5Cardputer` (M5Unified/M5GFX), `bblanchon/ArduinoJson` (v7), Unity (PlatformIO's default test framework), `WiFiClientSecure` + `HTTPClient`, `Preferences` (NVS).

---

## Prerequisites for the implementing engineer

- PlatformIO Core installed (`pio --version`). A host C/C++ toolchain (`gcc`/`clang`) is required for the `native` test env.
- A physical M5Stack Cardputer is required only for the on-device smoke checklist (Tasks 8–10). Tasks 1–7 are fully verifiable on the host; Tasks 8–10 additionally require a **device compile** (`pio run -e device`), which PlatformIO can do without hardware attached.
- The server pairing endpoints from PR #55 (`/api/devices/pair/{start,poll,claim}`) must be reachable for the live smoke test (Task 10). The contract is documented in `docs/superpowers/specs/2026-06-04-cardputer-ui-design.md` §3–§4.

All firmware lives under a new top-level `cardputer/` directory (sibling to `macos/`). Run all `pio` commands from inside `cardputer/`.

---

## Contract: server pairing (authoritative, from the spec)

- `POST /api/devices/pair/start` (no body) → `{"device_code","user_code","interval","expires_at"}`.
- `POST /api/devices/pair/poll` body `{"device_code":"…"}` → `{"status":"pending"}` or `{"status":"claimed","token":"…"}`; unknown/expired → HTTP 404.
- The issued `token` is sent on later requests as the cookie header `Cookie: newbro_session=<token>`.

---

## File Structure

| Path | Responsibility | Built in |
|---|---|---|
| `cardputer/platformio.ini` | `device` + `native` envs, deps, build flags | both |
| `cardputer/.gitignore` | ignore `.pio/` | — |
| `cardputer/lib/nb_json/PairingJson.{h,cpp}` | parse pair start/poll JSON, build poll body (ArduinoJson) | both |
| `cardputer/lib/nb_config/Config.{h,cpp}` | `DeviceConfig` struct + JSON codec + readiness predicates | both |
| `cardputer/lib/nb_backoff/Backoff.{h,cpp}` | exponential backoff calculator | both |
| `cardputer/lib/nb_pairing/Pairing.{h,cpp}` | pairing state machine (pure) | both |
| `cardputer/lib/nb_transport/Transport.h` | abstract HTTP transport interface + `HttpResponse` | both |
| `cardputer/lib/nb_client/NewbroClient.{h,cpp}` | pairing API calls over a `Transport` | both |
| `cardputer/src/transport/HttpsTransport.{h,cpp}` | `Transport` impl: `WiFiClientSecure`+`HTTPClient`+cert bundle | device |
| `cardputer/src/net/WifiManager.{h,cpp}` | Wi-Fi connect/status | device |
| `cardputer/src/store/ConfigStore.{h,cpp}` | load/save `DeviceConfig` blob in NVS (`Preferences`) | device |
| `cardputer/src/ui/TextScreen.{h,cpp}` | minimal text rendering helpers (boot/wifi/pair) | device |
| `cardputer/src/main.cpp` | Arduino `setup()`/`loop()` router wiring the boot→wifi→pair→ready flow | device |
| `cardputer/test/test_json/` … `test/test_client/` | native Unity tests | native |

---

### Task 1: PlatformIO project scaffold + native test harness

**Files:**
- Create: `cardputer/platformio.ini`, `cardputer/.gitignore`, `cardputer/src/main.cpp`, `cardputer/test/test_smoke/test_smoke.cpp`

- [ ] **Step 1: Create `cardputer/.gitignore`**

```gitignore
.pio/
```

- [ ] **Step 2: Create `cardputer/platformio.ini`**

```ini
; Cardputer firmware — device build + host (native) unit tests.

[env]
build_flags = -std=gnu++17

[env:device]
platform = espressif32
board = m5stack-stamps3
framework = arduino
monitor_speed = 115200
build_flags =
  -std=gnu++17
  -DBOARD_HAS_PSRAM
  -DARDUINO_USB_CDC_ON_BOOT=1
  -DARDUINO_USB_MODE=1
lib_deps =
  m5stack/M5Cardputer@^1.0.3
  bblanchon/ArduinoJson@^7.0.0
; No on-device unit tests in Plan A.
test_ignore = *

[env:native]
platform = native
build_flags =
  -std=gnu++17
; Do not compile src/ (it is Arduino-only) when running host tests.
build_src_filter = -<*>
lib_deps =
  bblanchon/ArduinoJson@^7.0.0
```

- [ ] **Step 3: Create a trivial device entry point `cardputer/src/main.cpp`**

```cpp
#include <M5Cardputer.h>

void setup() {
  auto cfg = M5.config();
  M5Cardputer.begin(cfg, true);  // true => enable keyboard
  M5Cardputer.Display.setTextSize(2);
  M5Cardputer.Display.print("newbro");
}

void loop() {
  M5Cardputer.update();
  delay(5);
}
```

- [ ] **Step 4: Create a smoke test `cardputer/test/test_smoke/test_smoke.cpp`**

```cpp
#include <unity.h>

void test_harness_runs(void) {
  TEST_ASSERT_EQUAL_INT(2, 1 + 1);
}

int main(int, char **) {
  UNITY_BEGIN();
  RUN_TEST(test_harness_runs);
  return UNITY_END();
}
```

- [ ] **Step 5: Run the native test to verify the harness works**

Run: `cd cardputer && pio test -e native`
Expected: builds and runs on the host; `test_harness_runs` PASSES.

- [ ] **Step 6: Verify the device target compiles**

Run: `cd cardputer && pio run -e device`
Expected: compiles successfully (downloads the ESP32 toolchain + M5Cardputer/ArduinoJson on first run). No hardware needed.

- [ ] **Step 7: Commit**

```bash
git add cardputer/platformio.ini cardputer/.gitignore cardputer/src/main.cpp cardputer/test/test_smoke/test_smoke.cpp
git commit -m "feat(cardputer): scaffold PlatformIO project with native test harness"
```

---

### Task 2: `nb_json` — parse pairing responses + build poll body

**Files:**
- Create: `cardputer/lib/nb_json/PairingJson.h`, `cardputer/lib/nb_json/PairingJson.cpp`, `cardputer/test/test_json/test_json.cpp`

- [ ] **Step 1: Write the failing test `cardputer/test/test_json/test_json.cpp`**

```cpp
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd cardputer && pio test -e native -f test_json`
Expected: FAIL — `PairingJson.h` not found.

- [ ] **Step 3: Create `cardputer/lib/nb_json/PairingJson.h`**

```cpp
#pragma once
#include <string>

namespace nb {

struct PairStart {
  std::string deviceCode;
  std::string userCode;
  int interval = 0;
  std::string expiresAt;
};

struct PollResult {
  std::string status;  // "pending" | "claimed"
  std::string token;   // empty unless claimed with a non-null token
};

// Return true on a successful parse; false on invalid JSON or missing required fields.
bool parsePairStart(const std::string &json, PairStart &out);
bool parsePollResult(const std::string &json, PollResult &out);

// Build the JSON body for POST /api/devices/pair/poll.
std::string buildPollBody(const std::string &deviceCode);

}  // namespace nb
```

- [ ] **Step 4: Create `cardputer/lib/nb_json/PairingJson.cpp`**

```cpp
#include "PairingJson.h"
#include <ArduinoJson.h>

namespace nb {

bool parsePairStart(const std::string &json, PairStart &out) {
  JsonDocument doc;
  if (deserializeJson(doc, json) != DeserializationError::Ok) return false;
  if (!doc["device_code"].is<const char *>() || !doc["user_code"].is<const char *>()) return false;
  out.deviceCode = doc["device_code"].as<std::string>();
  out.userCode = doc["user_code"].as<std::string>();
  out.interval = doc["interval"].as<int>();
  out.expiresAt = doc["expires_at"].as<std::string>();
  return true;
}

bool parsePollResult(const std::string &json, PollResult &out) {
  JsonDocument doc;
  if (deserializeJson(doc, json) != DeserializationError::Ok) return false;
  if (!doc["status"].is<const char *>()) return false;
  out.status = doc["status"].as<std::string>();
  out.token = doc["token"].is<const char *>() ? doc["token"].as<std::string>() : std::string();
  return true;
}

std::string buildPollBody(const std::string &deviceCode) {
  JsonDocument doc;
  doc["device_code"] = deviceCode;
  std::string out;
  serializeJson(doc, out);
  return out;
}

}  // namespace nb
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd cardputer && pio test -e native -f test_json`
Expected: PASS (6 tests).

- [ ] **Step 6: Commit**

```bash
git add cardputer/lib/nb_json cardputer/test/test_json
git commit -m "feat(cardputer): add pairing JSON parse/build (nb_json)"
```

---

### Task 3: `nb_config` — `DeviceConfig` struct, codec, predicates

**Files:**
- Create: `cardputer/lib/nb_config/Config.h`, `cardputer/lib/nb_config/Config.cpp`, `cardputer/test/test_config/test_config.cpp`

- [ ] **Step 1: Write the failing test `cardputer/test/test_config/test_config.cpp`**

```cpp
#include <unity.h>
#include "Config.h"

using namespace nb;

void test_predicates(void) {
  DeviceConfig c;
  TEST_ASSERT_FALSE(c.hasWifi());
  TEST_ASSERT_FALSE(c.hasToken());
  TEST_ASSERT_FALSE(c.isReady());
  c.wifiSsid = "home";
  c.serverHost = "newbro.example.com";
  c.deviceToken = "tok";
  TEST_ASSERT_TRUE(c.hasWifi());
  TEST_ASSERT_TRUE(c.hasServer());
  TEST_ASSERT_TRUE(c.hasToken());
  TEST_ASSERT_TRUE(c.isReady());
}

void test_codec_roundtrip(void) {
  DeviceConfig c;
  c.serverHost = "newbro.example.com";
  c.serverPort = 8443;
  c.wifiSsid = "home";
  c.wifiPassword = "s3cret";
  c.deviceToken = "abc.def";

  DeviceConfig back;
  TEST_ASSERT_TRUE(decodeConfig(encodeConfig(c), back));
  TEST_ASSERT_EQUAL_STRING("newbro.example.com", back.serverHost.c_str());
  TEST_ASSERT_EQUAL_UINT16(8443, back.serverPort);
  TEST_ASSERT_EQUAL_STRING("home", back.wifiSsid.c_str());
  TEST_ASSERT_EQUAL_STRING("s3cret", back.wifiPassword.c_str());
  TEST_ASSERT_EQUAL_STRING("abc.def", back.deviceToken.c_str());
}

void test_decode_defaults_port_443(void) {
  DeviceConfig back;
  TEST_ASSERT_TRUE(decodeConfig(R"({"host":"h","ssid":"s"})", back));
  TEST_ASSERT_EQUAL_UINT16(443, back.serverPort);
  TEST_ASSERT_EQUAL_STRING("h", back.serverHost.c_str());
}

void test_decode_rejects_garbage(void) {
  DeviceConfig back;
  TEST_ASSERT_FALSE(decodeConfig("nope", back));
}

int main(int, char **) {
  UNITY_BEGIN();
  RUN_TEST(test_predicates);
  RUN_TEST(test_codec_roundtrip);
  RUN_TEST(test_decode_defaults_port_443);
  RUN_TEST(test_decode_rejects_garbage);
  return UNITY_END();
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd cardputer && pio test -e native -f test_config`
Expected: FAIL — `Config.h` not found.

- [ ] **Step 3: Create `cardputer/lib/nb_config/Config.h`**

```cpp
#pragma once
#include <cstdint>
#include <string>

namespace nb {

struct DeviceConfig {
  std::string serverHost;
  uint16_t serverPort = 443;
  std::string wifiSsid;
  std::string wifiPassword;
  std::string deviceToken;

  bool hasWifi() const { return !wifiSsid.empty(); }
  bool hasServer() const { return !serverHost.empty(); }
  bool hasToken() const { return !deviceToken.empty(); }
  bool isReady() const { return hasWifi() && hasServer() && hasToken(); }
};

// Serialize to / parse from a compact JSON blob (stored in NVS).
std::string encodeConfig(const DeviceConfig &c);
bool decodeConfig(const std::string &blob, DeviceConfig &out);

}  // namespace nb
```

- [ ] **Step 4: Create `cardputer/lib/nb_config/Config.cpp`**

```cpp
#include "Config.h"
#include <ArduinoJson.h>

namespace nb {

std::string encodeConfig(const DeviceConfig &c) {
  JsonDocument doc;
  doc["host"] = c.serverHost;
  doc["port"] = c.serverPort;
  doc["ssid"] = c.wifiSsid;
  doc["pass"] = c.wifiPassword;
  doc["token"] = c.deviceToken;
  std::string out;
  serializeJson(doc, out);
  return out;
}

bool decodeConfig(const std::string &blob, DeviceConfig &out) {
  JsonDocument doc;
  if (deserializeJson(doc, blob) != DeserializationError::Ok) return false;
  out.serverHost = doc["host"].as<std::string>();
  out.serverPort = doc["port"].is<uint16_t>() ? doc["port"].as<uint16_t>() : 443;
  out.wifiSsid = doc["ssid"].as<std::string>();
  out.wifiPassword = doc["pass"].as<std::string>();
  out.deviceToken = doc["token"].as<std::string>();
  return true;
}

}  // namespace nb
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd cardputer && pio test -e native -f test_config`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add cardputer/lib/nb_config cardputer/test/test_config
git commit -m "feat(cardputer): add DeviceConfig + JSON codec (nb_config)"
```

---

### Task 4: `nb_backoff` — exponential backoff

**Files:**
- Create: `cardputer/lib/nb_backoff/Backoff.h`, `cardputer/lib/nb_backoff/Backoff.cpp`, `cardputer/test/test_backoff/test_backoff.cpp`

- [ ] **Step 1: Write the failing test `cardputer/test/test_backoff/test_backoff.cpp`**

```cpp
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd cardputer && pio test -e native -f test_backoff`
Expected: FAIL — `Backoff.h` not found.

- [ ] **Step 3: Create `cardputer/lib/nb_backoff/Backoff.h`**

```cpp
#pragma once
#include <cstdint>

namespace nb {

class Backoff {
 public:
  Backoff(uint32_t baseMs, uint32_t maxMs) : base_(baseMs), max_(maxMs), cur_(baseMs) {}
  uint32_t current() const { return cur_; }
  void reset() { cur_ = base_; }
  // Return the current delay, then advance (doubling, capped at max).
  uint32_t next();

 private:
  uint32_t base_;
  uint32_t max_;
  uint32_t cur_;
};

}  // namespace nb
```

- [ ] **Step 4: Create `cardputer/lib/nb_backoff/Backoff.cpp`**

```cpp
#include "Backoff.h"

namespace nb {

uint32_t Backoff::next() {
  uint32_t value = cur_;
  uint32_t doubled = cur_ >= max_ ? max_ : cur_ * 2;
  cur_ = doubled > max_ ? max_ : doubled;
  return value;
}

}  // namespace nb
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd cardputer && pio test -e native -f test_backoff`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add cardputer/lib/nb_backoff cardputer/test/test_backoff
git commit -m "feat(cardputer): add exponential backoff (nb_backoff)"
```

---

### Task 5: `nb_pairing` — pairing state machine

**Files:**
- Create: `cardputer/lib/nb_pairing/Pairing.h`, `cardputer/lib/nb_pairing/Pairing.cpp`, `cardputer/test/test_pairing/test_pairing.cpp`

The state machine is pure: a driver performs the HTTP calls and feeds parsed results in; the machine owns the state, the code to display, and the resulting token.

- [ ] **Step 1: Write the failing test `cardputer/test/test_pairing/test_pairing.cpp`**

```cpp
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
  // A claimed poll whose token was already delivered (token empty) must not
  // be treated as success — keep polling/﻿retry rather than store an empty token.
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd cardputer && pio test -e native -f test_pairing`
Expected: FAIL — `Pairing.h` not found.

- [ ] **Step 3: Create `cardputer/lib/nb_pairing/Pairing.h`**

```cpp
#pragma once
#include <string>
#include "PairingJson.h"  // PairStart, PollResult

namespace nb {

enum class PairState { Idle, AwaitingStart, Polling, Claimed, Expired, Failed };

class PairingMachine {
 public:
  PairState state() const { return state_; }
  const std::string &userCode() const { return userCode_; }
  const std::string &deviceCode() const { return deviceCode_; }
  const std::string &token() const { return token_; }
  const std::string &error() const { return error_; }

  void begin();
  void onStart(const PairStart &s);
  void onPoll(const PollResult &r);
  void onExpired();
  void onError(const std::string &msg);

 private:
  PairState state_ = PairState::Idle;
  std::string userCode_;
  std::string deviceCode_;
  std::string token_;
  std::string error_;
};

}  // namespace nb
```

- [ ] **Step 4: Create `cardputer/lib/nb_pairing/Pairing.cpp`**

```cpp
#include "Pairing.h"

namespace nb {

void PairingMachine::begin() {
  state_ = PairState::AwaitingStart;
  userCode_.clear();
  deviceCode_.clear();
  token_.clear();
  error_.clear();
}

void PairingMachine::onStart(const PairStart &s) {
  deviceCode_ = s.deviceCode;
  userCode_ = s.userCode;
  state_ = PairState::Polling;
}

void PairingMachine::onPoll(const PollResult &r) {
  if (r.status == "claimed" && !r.token.empty()) {
    token_ = r.token;
    state_ = PairState::Claimed;
  }
  // "pending", or "claimed" with an already-delivered (empty) token: keep polling.
}

void PairingMachine::onExpired() { state_ = PairState::Expired; }

void PairingMachine::onError(const std::string &msg) {
  error_ = msg;
  state_ = PairState::Failed;
}

}  // namespace nb
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd cardputer && pio test -e native -f test_pairing`
Expected: PASS (6 tests).

- [ ] **Step 6: Commit**

```bash
git add cardputer/lib/nb_pairing cardputer/test/test_pairing
git commit -m "feat(cardputer): add pairing state machine (nb_pairing)"
```

---

### Task 6: `nb_transport` interface + `nb_client` NewbroClient

**Files:**
- Create: `cardputer/lib/nb_transport/Transport.h`
- Create: `cardputer/lib/nb_client/NewbroClient.h`, `cardputer/lib/nb_client/NewbroClient.cpp`, `cardputer/test/test_client/test_client.cpp`

- [ ] **Step 1: Create the transport interface `cardputer/lib/nb_transport/Transport.h`**

(No test of its own — it is a pure abstract interface, exercised via `NewbroClient` tests.)

```cpp
#pragma once
#include <string>

namespace nb {

struct HttpResponse {
  bool transportOk = false;  // true if a response was received at all
  int status = 0;            // HTTP status code (valid when transportOk)
  std::string body;
};

class Transport {
 public:
  virtual ~Transport() = default;
  // method: "GET" or "POST". path is server-relative, e.g. "/api/devices/pair/start".
  // body is sent for POST (ignored otherwise). cookieToken, when non-empty, is sent
  // as the header "Cookie: newbro_session=<cookieToken>".
  virtual HttpResponse request(const std::string &method, const std::string &path,
                               const std::string &body, const std::string &cookieToken) = 0;
};

}  // namespace nb
```

- [ ] **Step 2: Write the failing test `cardputer/test/test_client/test_client.cpp`**

```cpp
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
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd cardputer && pio test -e native -f test_client`
Expected: FAIL — `NewbroClient.h` not found.

- [ ] **Step 4: Create `cardputer/lib/nb_client/NewbroClient.h`**

```cpp
#pragma once
#include <string>
#include "Transport.h"
#include "PairingJson.h"

namespace nb {

class NewbroClient {
 public:
  explicit NewbroClient(Transport &transport) : t_(transport) {}

  // Each returns true on success (HTTP 200 + parseable body). On failure they
  // set lastError() and return false.
  bool startPairing(PairStart &out);
  bool pollPairing(const std::string &deviceCode, PollResult &out);

  const std::string &lastError() const { return lastError_; }

 private:
  Transport &t_;
  std::string lastError_;
};

}  // namespace nb
```

- [ ] **Step 5: Create `cardputer/lib/nb_client/NewbroClient.cpp`**

```cpp
#include "NewbroClient.h"

namespace nb {

bool NewbroClient::startPairing(PairStart &out) {
  lastError_.clear();
  HttpResponse r = t_.request("POST", "/api/devices/pair/start", "", "");
  if (!r.transportOk) { lastError_ = "network error"; return false; }
  if (r.status != 200) { lastError_ = "start failed: HTTP " + std::to_string(r.status); return false; }
  if (!parsePairStart(r.body, out)) { lastError_ = "bad start response"; return false; }
  return true;
}

bool NewbroClient::pollPairing(const std::string &deviceCode, PollResult &out) {
  lastError_.clear();
  HttpResponse r = t_.request("POST", "/api/devices/pair/poll", buildPollBody(deviceCode), "");
  if (!r.transportOk) { lastError_ = "network error"; return false; }
  if (r.status != 200) { lastError_ = "poll failed: HTTP " + std::to_string(r.status); return false; }
  if (!parsePollResult(r.body, out)) { lastError_ = "bad poll response"; return false; }
  return true;
}

}  // namespace nb
```

- [ ] **Step 6: Run to verify it passes**

Run: `cd cardputer && pio test -e native -f test_client`
Expected: PASS (5 tests).

- [ ] **Step 7: Run the full native suite to confirm everything is green**

Run: `cd cardputer && pio test -e native`
Expected: all test folders pass (`test_smoke`, `test_json`, `test_config`, `test_backoff`, `test_pairing`, `test_client`).

- [ ] **Step 8: Commit**

```bash
git add cardputer/lib/nb_transport cardputer/lib/nb_client cardputer/test/test_client
git commit -m "feat(cardputer): add Transport interface + NewbroClient pairing calls"
```

---

### Task 7: `HttpsTransport` (device glue)

**Files:**
- Create: `cardputer/src/transport/HttpsTransport.h`, `cardputer/src/transport/HttpsTransport.cpp`

This implements `nb::Transport` over TLS. It is Arduino-only and verified by device compile (Step 4) + the on-device smoke test in Task 10 — there is no native unit test (it depends on `WiFiClientSecure`).

The Arduino-ESP32 core ships a Mozilla root-CA bundle accessible via linker symbols; `WiFiClientSecure::setCACertBundle` uses it to verify public TLS certs.

- [ ] **Step 1: Create `cardputer/src/transport/HttpsTransport.h`**

```cpp
#pragma once
#include <cstdint>
#include <string>
#include "Transport.h"

namespace nb {

// TLS transport for a public HTTPS newbro deployment. Verifies the server
// certificate against the Arduino-ESP32 built-in Mozilla root-CA bundle.
class HttpsTransport : public Transport {
 public:
  HttpsTransport(std::string host, uint16_t port) : host_(std::move(host)), port_(port) {}
  HttpResponse request(const std::string &method, const std::string &path,
                       const std::string &body, const std::string &cookieToken) override;

 private:
  std::string host_;
  uint16_t port_;
};

}  // namespace nb
```

- [ ] **Step 2: Create `cardputer/src/transport/HttpsTransport.cpp`**

```cpp
#include "transport/HttpsTransport.h"

#include <HTTPClient.h>
#include <WiFiClientSecure.h>

// Arduino-ESP32 built-in Mozilla root CA bundle (linked from the core).
extern const uint8_t rootca_crt_bundle_start[] asm("_binary_data_cert_x509_crt_bundle_bin_start");

namespace nb {

HttpResponse HttpsTransport::request(const std::string &method, const std::string &path,
                                     const std::string &body, const std::string &cookieToken) {
  HttpResponse out;
  WiFiClientSecure client;
  client.setCACertBundle(rootca_crt_bundle_start);

  HTTPClient https;
  std::string url = "https://" + host_ + ":" + std::to_string(port_) + path;
  if (!https.begin(client, url.c_str())) {
    out.transportOk = false;
    return out;
  }
  https.addHeader("Content-Type", "application/json");
  if (!cookieToken.empty()) {
    https.addHeader("Cookie", ("newbro_session=" + cookieToken).c_str());
  }

  int code;
  if (method == "POST") {
    code = https.POST((uint8_t *)body.data(), body.size());
  } else {
    code = https.GET();
  }

  if (code <= 0) {
    out.transportOk = false;  // negative = client/connection error
  } else {
    out.transportOk = true;
    out.status = code;
    out.body = std::string(https.getString().c_str());
  }
  https.end();
  return out;
}

}  // namespace nb
```

- [ ] **Step 3: Add an include path build flag so `src/` can include the `nb_transport` header**

The transport header is already found via the library (LDF). No platformio.ini change is needed — `#include "Transport.h"` resolves through the `nb_transport` library. (`HttpsTransport.h` includes `"Transport.h"`.)

- [ ] **Step 4: Verify device compile**

First, temporarily reference the class so it is compiled: in `cardputer/src/main.cpp`, add at the top `#include "transport/HttpsTransport.h"` and, inside `setup()`, after the display print, add:

```cpp
  static nb::HttpsTransport probe("example.com", 443);
  (void)probe;
```

Run: `cd cardputer && pio run -e device`
Expected: compiles successfully (the cert-bundle symbol resolves against the ESP32 core).

> If the linker reports the symbol `_binary_data_cert_x509_crt_bundle_bin_start` is undefined for your core version, that means the bundle isn't auto-included; report this as a BLOCKED finding so the controller can switch the plan to the `bblanchon`/`tanakamasayuki` ESP32CertBundle approach. Do not silently fall back to `client.setInsecure()`.

- [ ] **Step 5: Commit**

```bash
git add cardputer/src/transport cardputer/src/main.cpp
git commit -m "feat(cardputer): add HTTPS transport with CA-bundle verification"
```

---

### Task 8: `ConfigStore` — persist `DeviceConfig` in NVS

**Files:**
- Create: `cardputer/src/store/ConfigStore.h`, `cardputer/src/store/ConfigStore.cpp`

Arduino-only (uses `Preferences`); verified by device compile + Task 10 smoke test. The config is stored as the single JSON blob produced by `encodeConfig`, so the testable codec (Task 3) carries all the parsing logic.

- [ ] **Step 1: Create `cardputer/src/store/ConfigStore.h`**

```cpp
#pragma once
#include "Config.h"

namespace nb {

// Loads/saves the device config as a JSON blob under one NVS key.
class ConfigStore {
 public:
  // Returns true if a config blob was present and decoded.
  bool load(DeviceConfig &out);
  void save(const DeviceConfig &c);
  void clear();
};

}  // namespace nb
```

- [ ] **Step 2: Create `cardputer/src/store/ConfigStore.cpp`**

```cpp
#include "store/ConfigStore.h"

#include <Preferences.h>

namespace nb {

static const char *kNamespace = "newbro";
static const char *kKey = "cfg";

bool ConfigStore::load(DeviceConfig &out) {
  Preferences prefs;
  prefs.begin(kNamespace, /*readOnly=*/true);
  String blob = prefs.getString(kKey, "");
  prefs.end();
  if (blob.isEmpty()) return false;
  return decodeConfig(std::string(blob.c_str()), out);
}

void ConfigStore::save(const DeviceConfig &c) {
  Preferences prefs;
  prefs.begin(kNamespace, /*readOnly=*/false);
  prefs.putString(kKey, encodeConfig(c).c_str());
  prefs.end();
}

void ConfigStore::clear() {
  Preferences prefs;
  prefs.begin(kNamespace, /*readOnly=*/false);
  prefs.remove(kKey);
  prefs.end();
}

}  // namespace nb
```

- [ ] **Step 3: Verify device compile**

In `cardputer/src/main.cpp`, add `#include "store/ConfigStore.h"` and inside `setup()` add:

```cpp
  static nb::ConfigStore store;
  (void)store;
```

Run: `cd cardputer && pio run -e device`
Expected: compiles successfully.

- [ ] **Step 4: Commit**

```bash
git add cardputer/src/store cardputer/src/main.cpp
git commit -m "feat(cardputer): persist device config in NVS (ConfigStore)"
```

---

### Task 9: `WifiManager` + `TextScreen` (device glue)

**Files:**
- Create: `cardputer/src/net/WifiManager.h`, `cardputer/src/net/WifiManager.cpp`
- Create: `cardputer/src/ui/TextScreen.h`, `cardputer/src/ui/TextScreen.cpp`

Arduino-only; verified by device compile + Task 10. (The beautiful Ink UI is Plan C — Plan A uses plain text screens to prove the flow.)

- [ ] **Step 1: Create `cardputer/src/net/WifiManager.h`**

```cpp
#pragma once
#include <string>

namespace nb {

class WifiManager {
 public:
  void begin(const std::string &ssid, const std::string &password);
  bool isConnected() const;
  // Blocks up to timeoutMs for a connection; returns connection status.
  bool waitForConnection(uint32_t timeoutMs);
};

}  // namespace nb
```

- [ ] **Step 2: Create `cardputer/src/net/WifiManager.cpp`**

```cpp
#include "net/WifiManager.h"

#include <WiFi.h>

namespace nb {

void WifiManager::begin(const std::string &ssid, const std::string &password) {
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid.c_str(), password.c_str());
}

bool WifiManager::isConnected() const { return WiFi.status() == WL_CONNECTED; }

bool WifiManager::waitForConnection(uint32_t timeoutMs) {
  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED && (millis() - start) < timeoutMs) {
    delay(100);
  }
  return WiFi.status() == WL_CONNECTED;
}

}  // namespace nb
```

- [ ] **Step 3: Create `cardputer/src/ui/TextScreen.h`**

```cpp
#pragma once
#include <string>

namespace nb {

// Minimal full-screen text helpers for Plan A (replaced by the Ink UI in Plan C).
namespace screen {
void title(const std::string &line);                         // big centered-ish title
void status(const std::string &title, const std::string &detail);  // title + small detail
void pairingCode(const std::string &code, const std::string &hint);
}  // namespace screen

}  // namespace nb
```

- [ ] **Step 4: Create `cardputer/src/ui/TextScreen.cpp`**

```cpp
#include "ui/TextScreen.h"

#include <M5Cardputer.h>

namespace nb {
namespace screen {

static void clear() {
  M5Cardputer.Display.fillScreen(TFT_BLACK);
  M5Cardputer.Display.setTextColor(TFT_WHITE, TFT_BLACK);
  M5Cardputer.Display.setCursor(8, 8);
}

void title(const std::string &line) {
  clear();
  M5Cardputer.Display.setTextSize(3);
  M5Cardputer.Display.print(line.c_str());
}

void status(const std::string &title, const std::string &detail) {
  clear();
  M5Cardputer.Display.setTextSize(2);
  M5Cardputer.Display.println(title.c_str());
  M5Cardputer.Display.setTextSize(1);
  M5Cardputer.Display.setCursor(8, 40);
  M5Cardputer.Display.print(detail.c_str());
}

void pairingCode(const std::string &code, const std::string &hint) {
  clear();
  M5Cardputer.Display.setTextSize(1);
  M5Cardputer.Display.println("PAIR THIS DEVICE");
  M5Cardputer.Display.setTextSize(4);
  M5Cardputer.Display.setCursor(8, 28);
  M5Cardputer.Display.println(code.c_str());
  M5Cardputer.Display.setTextSize(1);
  M5Cardputer.Display.setCursor(8, 86);
  M5Cardputer.Display.print(hint.c_str());
}

}  // namespace screen
}  // namespace nb
```

- [ ] **Step 5: Verify device compile**

Run: `cd cardputer && pio run -e device`
Expected: compiles successfully. (These are referenced by `main.cpp` in Task 10; if the linker drops them now, that's fine — the compile of each .cpp is what we're confirming. If PlatformIO reports "unused", ignore.)

- [ ] **Step 6: Commit**

```bash
git add cardputer/src/net cardputer/src/ui
git commit -m "feat(cardputer): add WifiManager and text screens"
```

---

### Task 10: `main.cpp` router — boot → wifi setup → pair → ready

**Files:**
- Modify: `cardputer/src/main.cpp` (replace the scaffold with the real router)

This wires everything: on boot, load config; if Wi-Fi/server unknown, prompt for SSID, password, and server host on the keyboard; connect; if no token, run the pairing flow (start → show code → poll on `interval` until claimed) and persist the token; then show "Ready". Arduino-only; verified by device compile + the on-device smoke checklist.

- [ ] **Step 1: Replace `cardputer/src/main.cpp` with the router**

```cpp
#include <M5Cardputer.h>

#include <string>

#include "Backoff.h"
#include "Config.h"
#include "NewbroClient.h"
#include "Pairing.h"
#include "net/WifiManager.h"
#include "store/ConfigStore.h"
#include "transport/HttpsTransport.h"
#include "ui/TextScreen.h"

namespace {

nb::ConfigStore g_store;
nb::WifiManager g_wifi;
nb::DeviceConfig g_config;

// Blocking on-keyboard line entry. `mask` hides characters (for passwords).
std::string promptLine(const std::string &label, bool mask) {
  std::string buffer;
  nb::screen::status(label, "type, then Enter");
  for (;;) {
    M5Cardputer.update();
    if (M5Cardputer.Keyboard.isChange() && M5Cardputer.Keyboard.isPressed()) {
      auto st = M5Cardputer.Keyboard.keysState();
      for (auto c : st.word) buffer += c;
      if (st.del && !buffer.empty()) buffer.pop_back();
      if (st.enter && !buffer.empty()) break;
      std::string shown = mask ? std::string(buffer.size(), '*') : buffer;
      nb::screen::status(label, shown.empty() ? "type, then Enter" : shown);
    }
    delay(5);
  }
  return buffer;
}

void runFirstRunSetupIfNeeded() {
  if (g_config.hasWifi() && g_config.hasServer()) return;
  g_config.wifiSsid = promptLine("Wi-Fi name", false);
  g_config.wifiPassword = promptLine("Wi-Fi password", true);
  g_config.serverHost = promptLine("Server host", false);  // e.g. newbro.example.com
  g_config.serverPort = 443;
  g_store.save(g_config);
}

// Returns true once paired (token stored), false on a terminal failure.
bool runPairing() {
  nb::HttpsTransport transport(g_config.serverHost, g_config.serverPort);
  nb::NewbroClient client(transport);
  nb::PairingMachine machine;
  nb::Backoff retry(2000, 30000);

  machine.begin();
  nb::PairStart start;
  while (!client.startPairing(start)) {
    nb::screen::status("Pairing", client.lastError());
    delay(retry.next());
  }
  machine.onStart(start);
  retry.reset();

  uint32_t intervalMs = (start.interval > 0 ? start.interval : 2) * 1000U;
  nb::screen::pairingCode(machine.userCode(),
                          "Enter this code in newbro -> Account -> Devices");

  while (machine.state() == nb::PairState::Polling) {
    delay(intervalMs);
    M5Cardputer.update();
    nb::PollResult poll;
    if (!client.pollPairing(machine.deviceCode(), poll)) {
      // Transport/HTTP error (e.g. 404 = expired): show and keep trying briefly.
      nb::screen::status("Pairing", client.lastError());
      delay(retry.next());
      continue;
    }
    machine.onPoll(poll);
  }

  if (machine.state() == nb::PairState::Claimed) {
    g_config.deviceToken = machine.token();
    g_store.save(g_config);
    return true;
  }
  return false;
}

}  // namespace

void setup() {
  auto cfg = M5.config();
  M5Cardputer.begin(cfg, true);  // enable keyboard
  M5Cardputer.Display.setRotation(1);

  nb::screen::title("newbro");
  delay(600);

  g_store.load(g_config);  // populates g_config if present
  runFirstRunSetupIfNeeded();

  nb::screen::status("Connecting", g_config.wifiSsid);
  g_wifi.begin(g_config.wifiSsid, g_config.wifiPassword);
  if (!g_wifi.waitForConnection(20000)) {
    nb::screen::status("Wi-Fi failed", "check credentials, reboot to retry");
    return;
  }

  if (!g_config.hasToken()) {
    if (!runPairing()) {
      nb::screen::status("Pairing failed", "reboot to retry");
      return;
    }
  }

  nb::screen::status("Ready", "paired - conversation UI coming in Plan B/C");
}

void loop() {
  M5Cardputer.update();
  delay(5);
}
```

- [ ] **Step 2: Verify device compile**

Run: `cd cardputer && pio run -e device`
Expected: compiles and links successfully.

- [ ] **Step 3: Confirm native tests still pass (no logic regressions)**

Run: `cd cardputer && pio test -e native`
Expected: all native tests still pass.

- [ ] **Step 4: On-device smoke checklist** (requires a physical Cardputer + the server reachable)

Flash and monitor: `cd cardputer && pio run -e device -t upload && pio device monitor`

Verify in order:
1. Boot shows "newbro", then prompts for Wi-Fi name → type SSID, Enter.
2. Prompts for Wi-Fi password (masked) → type, Enter.
3. Prompts for server host → type your deployment host (e.g. `newbro.example.com`), Enter.
4. Shows "Connecting" then advances (Wi-Fi connects).
5. Shows a 4-character pairing code.
6. In the newbro web app → account popover → **Devices**, enter the code → "Device paired."
7. Device advances to "Ready" within a couple of poll intervals.
8. Power-cycle the device → it boots straight to "Connecting" then "Ready" (config + token persisted; no re-prompt, no re-pair).

Record pass/fail for each step in the PR description.

- [ ] **Step 5: Commit**

```bash
git add cardputer/src/main.cpp
git commit -m "feat(cardputer): wire boot -> wifi setup -> pairing -> ready router"
```

---

## Self-Review

**Spec coverage (against spec §3–§5 for the Plan-A slice):**
- New top-level `cardputer/` PlatformIO project (sibling to `macos/`) → Task 1. ✓
- `store/Config` (NVS persistence: Wi-Fi creds, server URL, device token) → `nb_config` (Task 3) + `ConfigStore` (Task 8). ✓
- `net/WifiManager` (connect, status) → Task 9. ✓
- `net/NewbroClient` sets the `Cookie: newbro_session=<token>` header → header wiring in `HttpsTransport` (Task 7); `NewbroClient` pairing calls (Task 6). (Bootstrap/personas/audio/text are Plan B.) ✓
- `net/Pairing` device-flow start → poll → store token → `nb_pairing` machine (Task 5) + `runPairing()` router (Task 10). ✓
- BootScreen / WifiSetupScreen / PairScreen → text screens (Task 9) + router (Task 10); the Ink-styled versions are Plan C. ✓
- `app/Router` owns active screen + transitions → `main.cpp` (Task 10). ✓
- Public HTTPS with cert verification (per the chosen connection target) → `HttpsTransport::setCACertBundle` (Task 7), with an explicit BLOCKED escalation rather than an insecure fallback. ✓
- Host-unit-testable logic split from hardware (spec §9 testing strategy) → all logic in `lib/` with native Unity tests (Tasks 2–6); hardware glue isolated in `src/`. ✓
- Out of Plan A (deferred): `EventStream`, `MicRecorder`, `NewbroClient` bootstrap/personas/audio/text → Plan B; `Theme`, `BroGlyph`, `BroListScreen`, `ChatScreen` Ink UI → Plan C.

**Placeholder scan:** No TBD/TODO. Every code step contains complete code. Task 7's cert-bundle symbol has an explicit BLOCKED-escalation path (not a vague "handle errors"). The on-device smoke checklist (Task 10 Step 4) is a concrete numbered procedure, not a placeholder.

**Type/name consistency:** `nb::PairStart`/`PollResult` (defined in `nb_json`, reused by `nb_pairing` and `nb_client`); `nb::HttpResponse`/`Transport` (defined in `nb_transport`, implemented by `HttpsTransport`, faked in tests); `nb::DeviceConfig` + `encodeConfig`/`decodeConfig` (used by `ConfigStore`); `nb::NewbroClient::startPairing`/`pollPairing`; `nb::PairingMachine::begin`/`onStart`/`onPoll`/`onExpired`/`onError`/`state`/`userCode`/`deviceCode`/`token`. Header include names (`"Transport.h"`, `"PairingJson.h"`, `"Config.h"`, etc.) are resolved by PlatformIO's LDF from `lib/`, and `src/` sub-folder includes use the `"transport/…"`, `"store/…"`, `"net/…"`, `"ui/…"` paths consistently. Endpoint paths match the contract section. ✓
