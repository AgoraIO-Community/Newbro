# Cardputer Flashed Wi-Fi/Server Config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the Cardputer pre-fill Wi-Fi SSID/password and server host from an optional, gitignored compile-time header so a freshly flashed device skips the on-device keyboard setup.

**Architecture:** A pure `mergeDefaults(stored, defaults)` in `nb_config` overlays compiled defaults onto the NVS-loaded config (defaults win for non-empty Wi-Fi/server fields; the device token is never touched). `main.cpp` builds a `DeviceDefaults` from optional `NB_DEFAULT_*` macros in a gitignored `include/DeviceSecrets.h`, pulled in via `#if __has_include` so the build works with or without the file.

**Tech Stack:** C++17, PlatformIO, Arduino-ESP32 (`m5stack/M5Cardputer`), Unity (host tests). Reuses the existing `nb_config` lib and `main.cpp`.

---

## Prerequisites

- The Cardputer firmware is on `main` (all of Plans A/B/C merged): `cardputer/` PlatformIO project with `nb_config` (`DeviceConfig` + `encodeConfig`/`decodeConfig`), `ConfigStore`, and the `main.cpp` router. Run `pio` from inside `cardputer/`.
- No server changes.

## File Structure

| Path | Responsibility | Built in |
|---|---|---|
| `cardputer/lib/nb_config/Config.h` | add `DeviceDefaults` struct + `mergeDefaults` declaration | both |
| `cardputer/lib/nb_config/Config.cpp` | implement `mergeDefaults` | both |
| `cardputer/test/test_config_defaults/test_config_defaults.cpp` | native unit tests for `mergeDefaults` | native |
| `cardputer/include/DeviceSecrets.example.h` | committed template of the `NB_DEFAULT_*` macros | device |
| `cardputer/.gitignore` | ignore the real `include/DeviceSecrets.h` | — |
| `cardputer/src/main.cpp` | include secrets via `__has_include`, build defaults, call `mergeDefaults` | device |

---

### Task 1: `nb_config` — `DeviceDefaults` + `mergeDefaults`

**Files:**
- Modify: `cardputer/lib/nb_config/Config.h`, `cardputer/lib/nb_config/Config.cpp`
- Create: `cardputer/test/test_config_defaults/test_config_defaults.cpp`

- [ ] **Step 1: Write the failing test `cardputer/test/test_config_defaults/test_config_defaults.cpp`**

```cpp
#include <unity.h>
#include "Config.h"

using namespace nb;

static DeviceConfig stored() {
  DeviceConfig c;
  c.wifiSsid = "old-ssid";
  c.wifiPassword = "old-pass";
  c.serverHost = "old.example.com";
  c.serverPort = 8443;
  c.deviceToken = "tok-123";
  return c;
}

void test_defaults_win_when_set(void) {
  DeviceDefaults d;
  d.wifiSsid = "new-ssid";
  d.serverHost = "new.example.com";
  DeviceConfig out = mergeDefaults(stored(), d);
  TEST_ASSERT_EQUAL_STRING("new-ssid", out.wifiSsid.c_str());
  TEST_ASSERT_EQUAL_STRING("new.example.com", out.serverHost.c_str());
  // Untouched fields keep stored values.
  TEST_ASSERT_EQUAL_STRING("old-pass", out.wifiPassword.c_str());
  TEST_ASSERT_EQUAL_UINT16(8443, out.serverPort);
}

void test_empty_defaults_keep_stored(void) {
  DeviceDefaults d;  // all empty / port 0
  DeviceConfig out = mergeDefaults(stored(), d);
  TEST_ASSERT_EQUAL_STRING("old-ssid", out.wifiSsid.c_str());
  TEST_ASSERT_EQUAL_STRING("old-pass", out.wifiPassword.c_str());
  TEST_ASSERT_EQUAL_STRING("old.example.com", out.serverHost.c_str());
  TEST_ASSERT_EQUAL_UINT16(8443, out.serverPort);
}

void test_token_never_touched(void) {
  DeviceDefaults d;
  d.wifiSsid = "new-ssid";
  DeviceConfig out = mergeDefaults(stored(), d);
  TEST_ASSERT_EQUAL_STRING("tok-123", out.deviceToken.c_str());
}

void test_port_fallbacks(void) {
  // default non-zero wins
  DeviceDefaults d;
  d.serverPort = 9000;
  TEST_ASSERT_EQUAL_UINT16(9000, mergeDefaults(stored(), d).serverPort);

  // default 0 keeps stored non-zero
  DeviceConfig out2 = mergeDefaults(stored(), DeviceDefaults{});
  TEST_ASSERT_EQUAL_UINT16(8443, out2.serverPort);

  // default 0 and stored 0 → 443
  DeviceConfig s0 = stored();
  s0.serverPort = 0;
  TEST_ASSERT_EQUAL_UINT16(443, mergeDefaults(s0, DeviceDefaults{}).serverPort);
}

int main(int, char **) {
  UNITY_BEGIN();
  RUN_TEST(test_defaults_win_when_set);
  RUN_TEST(test_empty_defaults_keep_stored);
  RUN_TEST(test_token_never_touched);
  RUN_TEST(test_port_fallbacks);
  return UNITY_END();
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd cardputer && pio test -e native -f test_config_defaults`
Expected: FAIL — `DeviceDefaults` / `mergeDefaults` not declared.

- [ ] **Step 3: Add the declarations to `cardputer/lib/nb_config/Config.h`**

Insert, immediately after the `decodeConfig` declaration and before the closing `}  // namespace nb`:

```cpp
// Optional compile-time defaults (from a flashed DeviceSecrets.h). An empty
// string / zero port means "not set" and leaves the stored value in place.
struct DeviceDefaults {
  std::string wifiSsid;
  std::string wifiPassword;
  std::string serverHost;
  uint16_t serverPort = 0;
};

// Overlay defaults onto a stored config: defaults win for non-empty Wi-Fi/server
// fields; the device token is always kept from `stored`.
DeviceConfig mergeDefaults(const DeviceConfig &stored, const DeviceDefaults &defaults);
```

- [ ] **Step 4: Implement `mergeDefaults` in `cardputer/lib/nb_config/Config.cpp`**

Add before the closing `}  // namespace nb`:

```cpp
DeviceConfig mergeDefaults(const DeviceConfig &stored, const DeviceDefaults &defaults) {
  DeviceConfig out = stored;  // deviceToken (and everything else) preserved by default
  if (!defaults.wifiSsid.empty()) out.wifiSsid = defaults.wifiSsid;
  if (!defaults.wifiPassword.empty()) out.wifiPassword = defaults.wifiPassword;
  if (!defaults.serverHost.empty()) out.serverHost = defaults.serverHost;
  if (defaults.serverPort != 0) {
    out.serverPort = defaults.serverPort;
  } else if (out.serverPort == 0) {
    out.serverPort = 443;
  }
  return out;
}
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd cardputer && pio test -e native -f test_config_defaults`
Expected: PASS (4 tests).

- [ ] **Step 6: Run the full native suite (no regressions)**

Run: `cd cardputer && pio test -e native`
Expected: all suites green (the existing `test_config` plus the new `test_config_defaults`).

- [ ] **Step 7: Commit**

```bash
git add cardputer/lib/nb_config/Config.h cardputer/lib/nb_config/Config.cpp cardputer/test/test_config_defaults
git commit -m "feat(cardputer): add DeviceDefaults + mergeDefaults (nb_config)"
```

---

### Task 2: Wire flashed defaults into the boot flow

**Files:**
- Create: `cardputer/include/DeviceSecrets.example.h`
- Modify: `cardputer/.gitignore`, `cardputer/src/main.cpp`

- [ ] **Step 1: Create the committed template `cardputer/include/DeviceSecrets.example.h`**

```cpp
// Flashed Wi-Fi/server defaults for the Cardputer (development convenience).
//
// Copy this file to `DeviceSecrets.h` in the same directory and fill in your
// values. `DeviceSecrets.h` is gitignored, so your credentials are not committed.
// Any macro you leave commented out falls back to the on-device keyboard prompt.
// The device token is NOT set here — you still pair once; it persists in NVS.
#pragma once

// #define NB_DEFAULT_WIFI_SSID     "my-2g-ssid"
// #define NB_DEFAULT_WIFI_PASSWORD "my-password"
// #define NB_DEFAULT_SERVER_HOST   "xxxx.trycloudflare.com"
// #define NB_DEFAULT_SERVER_PORT   443
```

- [ ] **Step 2: Ignore the real secrets header — edit `cardputer/.gitignore`**

The file currently contains only `.pio/`. Make it:

```gitignore
.pio/
include/DeviceSecrets.h
```

- [ ] **Step 3: Include the secrets header conditionally in `cardputer/src/main.cpp`**

Immediately after the last `#include "ui/..."` line (the include block ends with `#include "ui/TextScreen.h"`), add:

```cpp

// Optional flashed Wi-Fi/server defaults (gitignored; absent by default).
#if __has_include("DeviceSecrets.h")
#include "DeviceSecrets.h"
#endif
```

- [ ] **Step 4: Build the defaults and merge, right after the config is loaded**

In `setup()`, the lines currently read:

```cpp
  g_store.load(g_config);
  runFirstRunSetupIfNeeded();
```

Replace them with:

```cpp
  g_store.load(g_config);

  nb::DeviceDefaults defaults;
#ifdef NB_DEFAULT_WIFI_SSID
  defaults.wifiSsid = NB_DEFAULT_WIFI_SSID;
#endif
#ifdef NB_DEFAULT_WIFI_PASSWORD
  defaults.wifiPassword = NB_DEFAULT_WIFI_PASSWORD;
#endif
#ifdef NB_DEFAULT_SERVER_HOST
  defaults.serverHost = NB_DEFAULT_SERVER_HOST;
#endif
#ifdef NB_DEFAULT_SERVER_PORT
  defaults.serverPort = NB_DEFAULT_SERVER_PORT;
#endif
  g_config = nb::mergeDefaults(g_config, defaults);

  runFirstRunSetupIfNeeded();
```

- [ ] **Step 5: Verify the default build (secrets absent) compiles unchanged**

Run: `cd cardputer && pio run -e device`
Expected: compiles + links (report flash/RAM). With no `DeviceSecrets.h`, `__has_include` is false and `defaults` stays empty — `mergeDefaults` only applies the port fallback, so behavior is identical to before.

- [ ] **Step 6: Verify the secrets-present path compiles**

Create a throwaway `cardputer/include/DeviceSecrets.h` (gitignored, so it won't be committed):

```cpp
#pragma once
#define NB_DEFAULT_WIFI_SSID     "test-ssid"
#define NB_DEFAULT_WIFI_PASSWORD "test-pass"
#define NB_DEFAULT_SERVER_HOST   "test.example.com"
#define NB_DEFAULT_SERVER_PORT   443
```

Run: `cd cardputer && pio run -e device`
Expected: compiles + links (the `NB_DEFAULT_*` macros are picked up).

Then delete the throwaway file so it doesn't linger:

```bash
rm cardputer/include/DeviceSecrets.h
```

- [ ] **Step 7: Confirm native tests still pass**

Run: `cd cardputer && pio test -e native`
Expected: all suites green.

- [ ] **Step 8: Commit**

```bash
git add cardputer/include/DeviceSecrets.example.h cardputer/.gitignore cardputer/src/main.cpp
git commit -m "feat(cardputer): pre-fill wifi/server from flashed DeviceSecrets.h"
```

---

## Self-Review

**Spec coverage:**
- Gitignored `DeviceSecrets.h` + committed `.example.h` template + `__has_include` guard (spec §2) → Task 2 Steps 1–3.
- `NB_DEFAULT_WIFI_SSID/PASSWORD/SERVER_HOST/SERVER_PORT` macros → Task 2 Step 4 (each `#ifdef`-guarded).
- `DeviceDefaults` + `mergeDefaults` semantics: defaults win for non-empty Wi-Fi/server, token always from stored, port fallback default→stored→443 (spec §3) → Task 1 Steps 3–4 + tests (Step 1).
- Boot flow: merge right after `g_store.load`, `runFirstRunSetupIfNeeded` unchanged (spec §4) → Task 2 Step 4.
- `.gitignore` entry (spec §2) → Task 2 Step 2.
- Testing: native unit tests for all four merge behaviors + device compile with/without the header (spec §7) → Task 1 Step 1, Task 2 Steps 5–6.
- Error handling: file absent → no defaults (no regression); partial config → remaining fields prompt; port omitted → 443 (spec §6) → covered by the `#ifdef` guards + `mergeDefaults` port fallback (tested).

**Placeholder scan:** No TBD/TODO; every code step is complete. The `__has_include`/`#ifdef` guards are exact. The throwaway-file verification (Task 2 Step 6) has explicit create + delete steps.

**Type/name consistency:** `nb::DeviceDefaults` (fields `wifiSsid`/`wifiPassword`/`serverHost`/`serverPort`) and `nb::mergeDefaults(const DeviceConfig&, const DeviceDefaults&) -> DeviceConfig` are defined in Task 1 and used identically in Task 2 Step 4 and the Task 1 tests. The `NB_DEFAULT_*` macro names match between the `.example.h` template, the throwaway test header, and the `#ifdef` guards in `main.cpp`. Reuses the existing `nb::DeviceConfig` fields unchanged. ✓
