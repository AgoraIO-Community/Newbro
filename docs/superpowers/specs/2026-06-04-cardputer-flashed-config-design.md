# Cardputer Flashed Wi-Fi/Server Config — Design

**Date:** 2026-06-04
**Status:** Approved design, ready for implementation planning
**Scope:** Let the Cardputer pick up Wi-Fi and server settings from a flashed (gitignored) config header so first boot doesn't require typing them on the keyboard.

## 1. Goal

During development the Cardputer prompts for Wi-Fi SSID, Wi-Fi password, and server host on the keyboard at first boot (and after an NVS erase). This is tedious when re-flashing repeatedly. Provide an optional, gitignored compile-time config that pre-fills those three fields so a freshly flashed device boots straight to the pairing-code screen.

Out of scope: the device token (still obtained via pairing and persisted in NVS — you pair once, it survives re-flashes); any server change.

## 2. Mechanism

- A **gitignored** header `cardputer/include/DeviceSecrets.h`, alongside a committed template `cardputer/include/DeviceSecrets.example.h`. The header defines any of these macros:
  - `NB_DEFAULT_WIFI_SSID` (string)
  - `NB_DEFAULT_WIFI_PASSWORD` (string)
  - `NB_DEFAULT_SERVER_HOST` (string)
  - `NB_DEFAULT_SERVER_PORT` (integer; optional, defaults to 443)
- `main.cpp` includes it conditionally: `#if __has_include("DeviceSecrets.h")`. When the file is absent the firmware builds and behaves exactly as today (keyboard prompts). PlatformIO already adds `include/` to the include path.
- `cardputer/.gitignore` gains `include/DeviceSecrets.h`.

## 3. Merge logic (host-tested)

Add to `nb_config`:

```cpp
struct DeviceDefaults {
  std::string wifiSsid;
  std::string wifiPassword;
  std::string serverHost;
  uint16_t serverPort = 0;  // 0 = "not set"
};

DeviceConfig mergeDefaults(const DeviceConfig &stored, const DeviceDefaults &defaults);
```

Semantics:
- `wifiSsid` / `wifiPassword` / `serverHost`: the **compiled default wins when non-empty**; otherwise keep the stored value. (So editing the config file + re-flash changes them, and you can't get stuck with a stale typed value.)
- `serverPort`: use `defaults.serverPort` when non-zero; else keep `stored.serverPort` when non-zero; else `443`.
- `deviceToken`: **always taken from `stored`** — the config never sets or clears it.

`mergeDefaults` is pure (no Arduino), unit-tested on the host.

## 4. Boot flow change

In `main.cpp`, immediately after `g_store.load(g_config)`:

```cpp
nb::DeviceDefaults defaults;
#if __has_include("DeviceSecrets.h")
  #ifdef NB_DEFAULT_WIFI_SSID
    defaults.wifiSsid = NB_DEFAULT_WIFI_SSID;
  #endif
  // ... password / host / port guarded the same way ...
#endif
g_config = nb::mergeDefaults(g_config, defaults);
```

`runFirstRunSetupIfNeeded()` is unchanged: it prompts only for fields that are still empty after the merge. With SSID + host present it skips straight to "Connecting", then pairing (if no token), then the UI. The `DeviceSecrets.h` include itself lives inside the `__has_include` guard so each `NB_DEFAULT_*` is only referenced when defined.

## 5. Components & boundaries

| Unit | Responsibility | Tested by |
|---|---|---|
| `nb::DeviceDefaults` + `mergeDefaults` (`nb_config`) | pure merge of compiled defaults over stored config | native unit tests |
| `cardputer/include/DeviceSecrets.example.h` | documented template of the macros | — |
| `cardputer/.gitignore` | ignore the real `DeviceSecrets.h` | — |
| `main.cpp` boot wiring | build `DeviceDefaults` from macros, call `mergeDefaults` | device compile |

## 6. Error handling

- File absent → `__has_include` false → no defaults → existing keyboard-prompt behavior (no regression).
- Partial config (e.g. only SSID + host, no password) → those fields filled, the missing one still prompts. An open Wi-Fi network legitimately has an empty password, which simply means it's prompted; that's acceptable for a dev convenience.
- Port omitted → 443.

## 7. Testing

- Native unit tests for `mergeDefaults`: default-wins for each non-empty field; empty default keeps stored; token never altered by defaults; port fallback (default non-zero wins → stored non-zero → 443).
- Device compile with and (conceptually) without the secrets header.
- Manual: create `DeviceSecrets.h` with real values, flash, confirm the device boots past the prompts straight to the pairing-code screen; confirm the token from a prior pairing still works without re-pairing.

## 8. Out of scope (future)

- Compiling in the device token to skip pairing entirely.
- An on-device "forget/reset" key combo (tracked separately).
- A filesystem-based (LittleFS) config.
