# M5Stack Cardputer UI — Design

**Date:** 2026-06-04
**Status:** Approved design, ready for implementation planning
**Scope:** A standalone ESP32 firmware that turns an M5Stack Cardputer into a
beautiful, voice-first pocket chat client for the newbro server.

## 1. Goal & Role

Build a Cardputer firmware that lets a user talk to one of their Bros (executors)
from a pocket device. It is a **pocket chat client**, not an executor node and not
a full remote control. The UI is deliberately simplified for the device's
constraints (240×135 TFT, 56-key QWERTY, PDM mic, speaker, ESP32-S3) but should
look polished and characterful, matching the newbro brand.

Primary interaction is **voice-first push-to-talk**; keyboard text is a secondary
input path. The device reuses the existing newbro HTTP + WebSocket contract, with
one small, clean server addition for device pairing.

### Decisions (locked during brainstorming)

| Decision | Choice |
|---|---|
| Device role | Pocket chat client |
| Input model | Voice-first push-to-talk; keyboard text secondary |
| Onboarding/auth | Pair-with-code device flow (new server endpoints) |
| Navigation | Bro list + chat (two core screens) |
| Visual direction | "Ink" dark theme with coral accent and line-art Bros |
| Firmware stack | Arduino + M5Unified / M5GFX, built with PlatformIO |

## 2. Why these choices

- **Voice-first** is viable because the server's
  `POST /sessions/{id}/executor-audio-instructions` endpoint already accepts raw
  PCM16 over a plain HTTP POST (`Content-Type: audio/pcm`) and performs Whisper
  transcription server-side, returning `transcript_text` in the response. The
  device does **not** need the Agora RTC SDK — it only buffers mic PCM and POSTs it.
- **Arduino + M5Unified/M5GFX** is the standard Cardputer stack: it provides the
  keyboard and PDM mic out of the box, and M5GFX (LovyanGFX) gives double-buffered,
  anti-aliased sprite rendering needed for the Ink theme and signature animations.
  ESP-IDF was rejected as overkill; MicroPython was rejected because it fights the
  "looks nice" goal (weak simultaneous graphics + audio + WebSocket performance).
- **Pair-with-code** gives the nicest first-run UX and fits the AGENTS.md principle
  of fixing the contract rather than adding a hack. It reuses the existing token
  model, so no auth code downstream changes.

## 3. Server interaction (existing contract)

The device authenticates by sending `Cookie: newbro_session=<token>` on every
HTTP request and on the WebSocket upgrade. The server's auth resolvers
(`require_session_owner`, `user_for_websocket`) read this cookie today, so no
server change is required for authenticated calls.

Steady-state flow:

1. `GET /api/me/bootstrap` → `{ session_id, default_persona_id, default_bro_detail_session_id }`.
2. `GET /api/sessions/{session_id}/personas` → list of Bros
   (`persona_id`, `name`, `avatar`, `executor_node_id`, `bro_detail_session_id`).
3. Voice send:
   `POST /api/sessions/{session_id}/executor-audio-instructions?target_persona_id=…&duration_ms=…&sample_rate=…&num_channels=…&samples_per_channel=…`
   with body = raw PCM16 and `Content-Type: audio/pcm`. Response includes
   `transcript_text`. Server constraints: `sample_rate` 8000–96000, body length
   must equal `samples_per_channel * num_channels * 2`, duration metadata must match
   sample count within tolerance, body ≤ `MAX_EXECUTOR_AUDIO_BYTES`,
   `duration_ms` ≤ `MAX_EXECUTOR_AUDIO_DURATION_MS`.
4. Text send (secondary): `POST /api/sessions/{session_id}/executor-text-instructions`
   with JSON `{ target_persona_id, text, create_new_thread?, … }`.
5. Reply stream: WebSocket `/api/sessions/{session_id}/stream` delivers
   `assistant_response_started` / `assistant_response_delta` / `assistant_response_completed`
   (and failure variants). The device renders the deltas live.

> Open implementation detail: confirm the exact event subset for the Bro-detail
> executor reply path against the web client's `useVoiceSession`/`adapters`
> consumption during planning, and mirror only that subset on the device.

## 4. Server addition — device pairing

A small new router under `/api/devices/pair/`, reusing the existing
`browser_sessions` token store so the issued device token is an ordinary
`newbro_session` token:

- `POST /api/devices/pair/start` (unauthenticated) →
  `{ device_code, user_code, interval, expires_at }`. `device_code` is the secret
  the device polls with; `user_code` is the short human code shown on screen.
- `POST /api/devices/pair/poll` (unauthenticated, body `{ device_code }`) →
  `{ status: "pending" }` until claimed, then `{ status: "claimed", token }`.
  Codes expire; expired/invalid codes return an explicit error.
- `POST /api/devices/pair/claim` (authenticated via the web UI, body
  `{ user_code }`) → links the pending pairing to the calling user and mints the
  session token that `poll` will return.

This is a standard OAuth-style device flow. The web UI gains a minimal
"Settings · Devices" affordance to enter the `user_code`.

## 5. Firmware architecture

New top-level `cardputer/` PlatformIO project (sibling to `macos/`), isolated from
the Python server and web UI. Modules are split so transport/logic are
host-unit-testable and hardware concerns are localized.

| Module | Responsibility | Depends on |
|---|---|---|
| `store/Config` | NVS persistence: WiFi creds, server URL, device token | Preferences |
| `net/WifiManager` | Connect, reconnect/backoff, expose status | WiFi, Config |
| `net/NewbroClient` | `bootstrap()`, `listPersonas()`, `postAudio()`, `postText()`; sets cookie header | HTTPClient |
| `net/EventStream` | WebSocket to `/stream`; parse events → typed callbacks | WebSocket client |
| `net/Pairing` | `start`/`poll` state machine; store token | NewbroClient, Config |
| `audio/MicRecorder` | Push-to-talk PCM16 capture into a ring buffer | M5Cardputer.Mic |
| `ui/Theme` | Ink color + type tokens (device port of `tokens.css`) | M5GFX |
| `ui/BroGlyph` | Line-art rabbit/cat/fox/person glyphs with idle/working/asleep states | M5GFX |
| `ui/Screen*` | One file per screen (Boot, WifiSetup, Pair, BroList, Chat) | Theme, BroGlyph |
| `app/Router` | Owns active screen + transitions; pumps input + network events | all UI + net |

All rendering goes through an off-screen `M5Canvas` sprite and is pushed in one
blit per frame to stay flicker-free.

## 6. Screens, states & flow

```
Boot → [no WiFi creds]   → WifiSetupScreen ─┐
     → [no device token] → PairScreen ──────→ BroListScreen ⇄ ChatScreen
     → [configured]      → BroListScreen
```

- **BootScreen** — logo + line-art Bro; connection progress (`wifi… · server… · synced`).
- **WifiSetupScreen** — type SSID, then password on the keyboard; persisted to NVS.
- **PairScreen** — calls `pair/start`, shows the short `user_code`, polls until
  claimed, stores the token, advances.
- **BroListScreen** — `↑/↓` select, `↵` open chat. Row = line-art glyph + name +
  executor/run subline + status badge (working / idle / asleep) derived from the
  session snapshot and stream.
- **ChatScreen** — header (Bro glyph + name + live status dot), body (last user
  transcript in mono + the Bro's streaming reply), footer push-to-talk hint.
  `Esc` returns to the list.

**ChatScreen state machine:**
`idle` (hint "hold ↵ to talk") → `recording` (green breathing waveform + elapsed
timer) → `sending` (spinner, "transcribing…") → `streaming` (reply text fills with
a blinking cursor) → `idle`. Typing any character enters a text-compose line;
`↵` sends it as a text instruction.

## 7. Visual system

Device port of `design/tokens.css`, Ink variant:

- **Background:** radial `#1b1d27 → #0d0e13`.
- **Ink text:** `#e9eaf0`; muted `#7d8492`.
- **Coral accent:** `#ff6a3d` / lighter `#ff8254`.
- **Live green:** `#10b981` / `#34d399` (recording, "working", live dot).
- **Type:** an M5GFX sans face for names/body and a mono face for transcripts and
  sublines (closest available to Inter / JetBrains Mono).
- **Signature motion (sprite animations):** breathe (recording mic), wave
  (transcript bars), pulse (live dots), plus the Bro glyph's idle ear-twitch,
  working halo, and asleep zzz — mirroring the web character behavior.

## 8. Error handling

Errors are surfaced as small inline banners, never silent (AGENTS.md: do not hide
problems):

- WiFi lost → auto-reconnect with a top status strip.
- `401` (token invalid/expired) → drop to PairScreen to re-pair.
- Audio/text POST `4xx`/`5xx` → "couldn't send — hold ↵ to retry".
- WebSocket drop → reconnect with backoff; live status dot turns amber.
- Mic too-short / too-long → bounded to the server's duration limits with a
  gentle on-screen hint before sending.

## 9. Testing strategy

- **Host unit tests** (PlatformIO `native` env + Unity), no hardware:
  event-JSON parsing, pairing state machine, config serialize/deserialize, PCM
  metadata math (byte length ↔ sample count ↔ duration), reconnect/backoff logic.
- **Server-side tests** for the new pairing endpoints (start/poll/claim happy path,
  expiry, invalid/used codes, token issuance) following the existing route test
  patterns.
- **End-to-end audio contract check:** POST a small recorded PCM16 fixture against a
  local `newbro backend` and assert a `transcript_text` comes back.
- **On-device smoke checklist** (documented in the firmware README) for mic capture,
  rendering, and the full pair → list → talk → reply loop.

## 10. Out of scope (future)

- Speaker TTS playback of the Bro's reply (text-only reply for v1).
- Multi-thread browsing, resolving interaction requests, executor switching.
- On-device STT.
- Agora RTC transport.
- AP-based WiFi config portal (keyboard entry is used instead).
