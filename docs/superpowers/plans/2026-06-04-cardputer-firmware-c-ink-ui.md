# Cardputer Firmware Plan C — The Ink UI

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the plain text screens with the "Ink" dark UI from the design — a scrollable Bro list (line-art animal glyphs + live status) and a chat screen with push-to-talk states and signature animations — driven by a small `Router`, with multi-Bro selection.

**Architecture:** Pure presentation logic (color packing, list/scroll/wrap math, the chat-phase state machine, avatar→glyph mapping) lives in host-tested `lib/` modules. Rendering is double-buffered through a single PSRAM-backed `M5Canvas` (240×135, RGB565): each frame clears to the Ink gradient, the active screen draws into the canvas, and it's blitted in one `pushSprite`. The `Router` owns the active screen, dispatches keyboard input, and ticks an animation frame counter. This sits on top of Plan B's data layer (`NewbroClient`, `MicRecorder`, the `Persona`/`TurnView` structs) — Plan C changes presentation only, not the data path.

**Tech Stack:** C++17, PlatformIO, Arduino-ESP32, `m5stack/M5Cardputer` (M5GFX/`M5Canvas`, keyboard), `bblanchon/ArduinoJson` v7 (already used), Unity (host tests). Reuses Plan A/B libs and glue.

---

## Prerequisites

- Plan A + Plan B available on this branch: the `cardputer/` project with libs `nb_audio`, `nb_session_json` (`Persona{id,name,avatar,busy}`, `TurnView{found,userText,assistantText,status}`, `Bootstrap{sessionId,defaultPersonaId}`), `nb_client` (`NewbroClient` with `bootstrap`/`listPersonas`/`sendAudio`/`getReply`), and glue `src/audio/MicRecorder`, `src/net/WifiManager`, `src/store/ConfigStore`, `src/transport/HttpsTransport`, `src/ui/TextScreen`, `src/main.cpp`.
- Run `pio` from inside `cardputer/`. Tasks 1–3 are host-verifiable; Tasks 4–10 add device compiles; Tasks 7, 8, 10 additionally have an on-device visual smoke step (requires hardware) that is deferred to the user.

---

## Design tokens (Ink), from the spec

- Background gradient: top `#1b1d27` → bottom `#0d0e13`.
- Ink text `#e9eaf0`; muted `#7d8492`; hairline `#23252f`.
- Coral `#ff6a3d` / light `#ff8254`; live green `#10b981` / light `#34d399`.
- Screen is 240×135 landscape (rotation 1). Layout budget: header ~24 px, footer ~18 px, body fills the rest.

---

## File Structure

| Path | Responsibility | Built in |
|---|---|---|
| `cardputer/lib/nb_ui_color/UiColor.{h,cpp}` | `rgb565` packing, Ink palette constants, `lerp565` | both |
| `cardputer/lib/nb_ui_layout/UiLayout.{h,cpp}` | list scroll window, text truncation, word wrap | both |
| `cardputer/lib/nb_ui_view/UiView.{h,cpp}` | `GlyphKind` mapping, chat `Phase`, `isTurnActive`, phase labels | both |
| `cardputer/src/ui/Theme.h` | M5GFX-side palette aliases + chosen fonts + gradient fill helper | device |
| `cardputer/src/ui/BroGlyph.{h,cpp}` | draw rabbit/cat/fox/person line-art with idle/working/asleep states | device |
| `cardputer/src/ui/Screen.h` | `Screen` interface (`render`, `onKey`) + shared input enum | device |
| `cardputer/src/ui/BroListScreen.{h,cpp}` | render the Bro roster | device |
| `cardputer/src/ui/ChatScreen.{h,cpp}` | render header/body/footer + phase animations | device |
| `cardputer/src/ui/Router.{h,cpp}` | owns the canvas + active screen, input dispatch, frame tick | device |
| `cardputer/src/main.cpp` | wire Router + screens + voice turn + multi-Bro selection | device |
| `cardputer/test/test_ui_color/`, `test_ui_layout/`, `test_ui_view/` | native Unity tests | native |

---

### Task 1: `nb_ui_color` — RGB565 packing, palette, blend

**Files:**
- Create: `cardputer/lib/nb_ui_color/UiColor.h`, `cardputer/lib/nb_ui_color/UiColor.cpp`, `cardputer/test/test_ui_color/test_ui_color.cpp`

- [ ] **Step 1: Write the failing test `cardputer/test/test_ui_color/test_ui_color.cpp`**

```cpp
#include <unity.h>
#include "UiColor.h"

using namespace nb;

void test_rgb565_extremes(void) {
  TEST_ASSERT_EQUAL_HEX16(0x0000, rgb565(0, 0, 0));
  TEST_ASSERT_EQUAL_HEX16(0xFFFF, rgb565(255, 255, 255));
  TEST_ASSERT_EQUAL_HEX16(0xF800, rgb565(255, 0, 0));    // pure red
  TEST_ASSERT_EQUAL_HEX16(0x07E0, rgb565(0, 255, 0));    // pure green
  TEST_ASSERT_EQUAL_HEX16(0x001F, rgb565(0, 0, 255));    // pure blue
}

void test_palette_present(void) {
  // Coral #ff6a3d packs to a known 565 value.
  TEST_ASSERT_EQUAL_HEX16(rgb565(0xff, 0x6a, 0x3d), kInkCoral);
  TEST_ASSERT_EQUAL_HEX16(rgb565(0x10, 0xb9, 0x81), kInkGreen);
  TEST_ASSERT_EQUAL_HEX16(rgb565(0xe9, 0xea, 0xf0), kInkText);
}

void test_lerp565_endpoints_and_mid(void) {
  uint16_t black = rgb565(0, 0, 0);
  uint16_t white = rgb565(255, 255, 255);
  TEST_ASSERT_EQUAL_HEX16(black, lerp565(black, white, 0));
  TEST_ASSERT_EQUAL_HEX16(white, lerp565(black, white, 255));
  // Midpoint is grey-ish: each channel roughly half. Just assert it's between.
  uint16_t mid = lerp565(black, white, 128);
  TEST_ASSERT_NOT_EQUAL(black, mid);
  TEST_ASSERT_NOT_EQUAL(white, mid);
}

int main(int, char **) {
  UNITY_BEGIN();
  RUN_TEST(test_rgb565_extremes);
  RUN_TEST(test_palette_present);
  RUN_TEST(test_lerp565_endpoints_and_mid);
  return UNITY_END();
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd cardputer && pio test -e native -f test_ui_color`
Expected: FAIL — `UiColor.h` not found.

- [ ] **Step 3: Create `cardputer/lib/nb_ui_color/UiColor.h`**

```cpp
#pragma once
#include <cstdint>

namespace nb {

// Pack 8-bit RGB into RGB565 (the M5GFX default color format).
constexpr uint16_t rgb565(uint8_t r, uint8_t g, uint8_t b) {
  return static_cast<uint16_t>(((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3));
}

// Ink palette (see spec design tokens).
constexpr uint16_t kInkBgTop = rgb565(0x1b, 0x1d, 0x27);
constexpr uint16_t kInkBgBottom = rgb565(0x0d, 0x0e, 0x13);
constexpr uint16_t kInkText = rgb565(0xe9, 0xea, 0xf0);
constexpr uint16_t kInkMuted = rgb565(0x7d, 0x84, 0x92);
constexpr uint16_t kInkLine = rgb565(0x23, 0x25, 0x2f);
constexpr uint16_t kInkCoral = rgb565(0xff, 0x6a, 0x3d);
constexpr uint16_t kInkCoralLight = rgb565(0xff, 0x82, 0x54);
constexpr uint16_t kInkGreen = rgb565(0x10, 0xb9, 0x81);
constexpr uint16_t kInkGreenLight = rgb565(0x34, 0xd3, 0x99);

// Blend two RGB565 colors. t=0 → a, t=255 → b.
uint16_t lerp565(uint16_t a, uint16_t b, uint8_t t);

}  // namespace nb
```

- [ ] **Step 4: Create `cardputer/lib/nb_ui_color/UiColor.cpp`**

```cpp
#include "UiColor.h"

namespace nb {

uint16_t lerp565(uint16_t a, uint16_t b, uint8_t t) {
  int ar = (a >> 11) & 0x1F, ag = (a >> 5) & 0x3F, ab = a & 0x1F;
  int br = (b >> 11) & 0x1F, bg = (b >> 5) & 0x3F, bb = b & 0x1F;
  int r = ar + (br - ar) * t / 255;
  int g = ag + (bg - ag) * t / 255;
  int bl = ab + (bb - ab) * t / 255;
  return static_cast<uint16_t>((r << 11) | (g << 5) | bl);
}

}  // namespace nb
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd cardputer && pio test -e native -f test_ui_color`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add cardputer/lib/nb_ui_color cardputer/test/test_ui_color
git commit -m "feat(cardputer): RGB565 packing + Ink palette + blend (nb_ui_color)"
```

---

### Task 2: `nb_ui_layout` — scroll window, truncate, wrap

**Files:**
- Create: `cardputer/lib/nb_ui_layout/UiLayout.h`, `cardputer/lib/nb_ui_layout/UiLayout.cpp`, `cardputer/test/test_ui_layout/test_ui_layout.cpp`

- [ ] **Step 1: Write the failing test `cardputer/test/test_ui_layout/test_ui_layout.cpp`**

```cpp
#include <unity.h>
#include <vector>
#include "UiLayout.h"

using namespace nb;

void test_scroll_top_keeps_selection_visible(void) {
  // 3 visible rows. Selecting within the first window keeps top at 0.
  TEST_ASSERT_EQUAL_INT(0, listScrollTop(/*selected=*/0, /*count=*/10, /*rows=*/3));
  TEST_ASSERT_EQUAL_INT(0, listScrollTop(2, 10, 3));
  // Selecting row 3 scrolls so 3 is the last visible (top=1).
  TEST_ASSERT_EQUAL_INT(1, listScrollTop(3, 10, 3));
  TEST_ASSERT_EQUAL_INT(7, listScrollTop(9, 10, 3));  // last item → top=7 (7,8,9)
}

void test_scroll_top_small_list(void) {
  TEST_ASSERT_EQUAL_INT(0, listScrollTop(0, 2, 3));  // fewer items than rows
}

void test_move_selection_clamps(void) {
  TEST_ASSERT_EQUAL_INT(0, moveSelection(0, 5, -1));  // can't go below 0
  TEST_ASSERT_EQUAL_INT(1, moveSelection(0, 5, +1));
  TEST_ASSERT_EQUAL_INT(4, moveSelection(4, 5, +1));  // can't exceed count-1
  TEST_ASSERT_EQUAL_INT(0, moveSelection(3, 0, +1));  // empty list → 0
}

void test_truncate(void) {
  TEST_ASSERT_EQUAL_STRING("hello", truncate("hello", 8).c_str());      // fits
  TEST_ASSERT_EQUAL_STRING("hello...", truncate("hello world", 8).c_str());  // 5 + "..."
  TEST_ASSERT_EQUAL_STRING("...", truncate("hello", 2).c_str());        // tiny budget
}

void test_wrap_lines(void) {
  std::vector<std::string> lines = wrapLines("the quick brown fox", /*maxChars=*/10, /*maxLines=*/3);
  TEST_ASSERT_EQUAL_INT(2, (int)lines.size());
  TEST_ASSERT_EQUAL_STRING("the quick", lines[0].c_str());
  TEST_ASSERT_EQUAL_STRING("brown fox", lines[1].c_str());
}

void test_wrap_lines_truncates_overflow(void) {
  std::vector<std::string> lines = wrapLines("aaa bbb ccc ddd eee fff", 7, 2);
  TEST_ASSERT_EQUAL_INT(2, (int)lines.size());
  // Last line ends with "..." because content overflowed maxLines.
  TEST_ASSERT_TRUE(lines[1].size() >= 3 && lines[1].substr(lines[1].size() - 3) == "...");
}

int main(int, char **) {
  UNITY_BEGIN();
  RUN_TEST(test_scroll_top_keeps_selection_visible);
  RUN_TEST(test_scroll_top_small_list);
  RUN_TEST(test_move_selection_clamps);
  RUN_TEST(test_truncate);
  RUN_TEST(test_wrap_lines);
  RUN_TEST(test_wrap_lines_truncates_overflow);
  return UNITY_END();
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd cardputer && pio test -e native -f test_ui_layout`
Expected: FAIL — `UiLayout.h` not found.

- [ ] **Step 3: Create `cardputer/lib/nb_ui_layout/UiLayout.h`**

```cpp
#pragma once
#include <string>
#include <vector>

namespace nb {

// First visible index so that `selected` stays within a window of `rows`.
int listScrollTop(int selected, int count, int rows);

// Clamp selection movement to [0, count-1]; returns 0 for an empty list.
int moveSelection(int current, int count, int delta);

// Truncate to at most maxChars, appending "..." when shortened.
std::string truncate(const std::string &text, int maxChars);

// Greedy word-wrap to lines of at most maxChars; if it overflows maxLines,
// the last kept line ends with "...".
std::vector<std::string> wrapLines(const std::string &text, int maxChars, int maxLines);

}  // namespace nb
```

- [ ] **Step 4: Create `cardputer/lib/nb_ui_layout/UiLayout.cpp`**

```cpp
#include "UiLayout.h"

namespace nb {

int listScrollTop(int selected, int count, int rows) {
  if (count <= rows || selected < rows) return 0;
  int top = selected - rows + 1;        // selected is the last visible row
  int maxTop = count - rows;
  if (top > maxTop) top = maxTop;
  if (top < 0) top = 0;
  return top;
}

int moveSelection(int current, int count, int delta) {
  if (count <= 0) return 0;
  int next = current + delta;
  if (next < 0) next = 0;
  if (next > count - 1) next = count - 1;
  return next;
}

std::string truncate(const std::string &text, int maxChars) {
  if (static_cast<int>(text.size()) <= maxChars) return text;
  if (maxChars <= 3) return "...";
  return text.substr(0, maxChars - 3) + "...";
}

std::vector<std::string> wrapLines(const std::string &text, int maxChars, int maxLines) {
  std::vector<std::string> lines;
  std::string line;
  size_t i = 0;
  while (i < text.size()) {
    // Extract next word.
    while (i < text.size() && text[i] == ' ') ++i;
    size_t start = i;
    while (i < text.size() && text[i] != ' ') ++i;
    std::string word = text.substr(start, i - start);
    if (word.empty()) continue;
    if (line.empty()) {
      line = word;
    } else if (static_cast<int>(line.size() + 1 + word.size()) <= maxChars) {
      line += " " + word;
    } else {
      lines.push_back(line);
      line = word;
      if (static_cast<int>(lines.size()) == maxLines) break;
    }
  }
  if (static_cast<int>(lines.size()) < maxLines && !line.empty()) {
    lines.push_back(line);
  }
  // If content remains beyond maxLines, mark the last line as truncated.
  bool overflowed = i < text.size();
  if (overflowed && !lines.empty()) {
    std::string &last = lines.back();
    if (static_cast<int>(last.size()) > maxChars - 3 && maxChars > 3) {
      last = last.substr(0, maxChars - 3);
    }
    last += "...";
  }
  return lines;
}

}  // namespace nb
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd cardputer && pio test -e native -f test_ui_layout`
Expected: PASS (6 tests).

- [ ] **Step 6: Commit**

```bash
git add cardputer/lib/nb_ui_layout cardputer/test/test_ui_layout
git commit -m "feat(cardputer): list scroll + truncate + wrap (nb_ui_layout)"
```

---

### Task 3: `nb_ui_view` — glyph mapping + chat phase

**Files:**
- Create: `cardputer/lib/nb_ui_view/UiView.h`, `cardputer/lib/nb_ui_view/UiView.cpp`, `cardputer/test/test_ui_view/test_ui_view.cpp`

- [ ] **Step 1: Write the failing test `cardputer/test/test_ui_view/test_ui_view.cpp`**

```cpp
#include <unity.h>
#include "UiView.h"

using namespace nb;

void test_glyph_kind_for_avatar(void) {
  TEST_ASSERT_TRUE(glyphKindFor("rabbit") == GlyphKind::Rabbit);
  TEST_ASSERT_TRUE(glyphKindFor("cat") == GlyphKind::Cat);
  TEST_ASSERT_TRUE(glyphKindFor("fox") == GlyphKind::Fox);
  TEST_ASSERT_TRUE(glyphKindFor("person") == GlyphKind::Person);
  TEST_ASSERT_TRUE(glyphKindFor("bro") == GlyphKind::Person);   // default family
  TEST_ASSERT_TRUE(glyphKindFor("") == GlyphKind::Person);      // default
}

void test_is_turn_active(void) {
  TEST_ASSERT_TRUE(isTurnActive("running"));
  TEST_ASSERT_TRUE(isTurnActive("pending"));
  TEST_ASSERT_FALSE(isTurnActive("completed"));
  TEST_ASSERT_FALSE(isTurnActive("failed"));
  TEST_ASSERT_FALSE(isTurnActive(""));
}

void test_phase_label(void) {
  TEST_ASSERT_EQUAL_STRING("hold to talk", phaseLabel(Phase::Idle));
  TEST_ASSERT_EQUAL_STRING("listening", phaseLabel(Phase::Recording));
  TEST_ASSERT_EQUAL_STRING("transcribing", phaseLabel(Phase::Transcribing));
  TEST_ASSERT_EQUAL_STRING("thinking", phaseLabel(Phase::Streaming));
}

int main(int, char **) {
  UNITY_BEGIN();
  RUN_TEST(test_glyph_kind_for_avatar);
  RUN_TEST(test_is_turn_active);
  RUN_TEST(test_phase_label);
  return UNITY_END();
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd cardputer && pio test -e native -f test_ui_view`
Expected: FAIL — `UiView.h` not found.

- [ ] **Step 3: Create `cardputer/lib/nb_ui_view/UiView.h`**

```cpp
#pragma once
#include <string>

namespace nb {

enum class GlyphKind { Rabbit, Cat, Fox, Person };

// Chat screen phases (push-to-talk lifecycle).
enum class Phase { Idle, Recording, Transcribing, Streaming };

GlyphKind glyphKindFor(const std::string &avatar);

// True while a Bro turn is still in progress.
bool isTurnActive(const std::string &status);

// Footer hint text for a phase. Returns a static C-string.
const char *phaseLabel(Phase phase);

}  // namespace nb
```

- [ ] **Step 4: Create `cardputer/lib/nb_ui_view/UiView.cpp`**

```cpp
#include "UiView.h"

namespace nb {

GlyphKind glyphKindFor(const std::string &avatar) {
  if (avatar == "rabbit") return GlyphKind::Rabbit;
  if (avatar == "cat") return GlyphKind::Cat;
  if (avatar == "fox") return GlyphKind::Fox;
  return GlyphKind::Person;  // "person", "bro", and anything else
}

bool isTurnActive(const std::string &status) {
  return status == "running" || status == "pending";
}

const char *phaseLabel(Phase phase) {
  switch (phase) {
    case Phase::Recording: return "listening";
    case Phase::Transcribing: return "transcribing";
    case Phase::Streaming: return "thinking";
    case Phase::Idle:
    default: return "hold to talk";
  }
}

}  // namespace nb
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd cardputer && pio test -e native -f test_ui_view`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add cardputer/lib/nb_ui_view cardputer/test/test_ui_view
git commit -m "feat(cardputer): glyph mapping + chat phase model (nb_ui_view)"
```

---

### Task 4: `Theme.h` — M5GFX palette + fonts + gradient fill

**Files:**
- Create: `cardputer/src/ui/Theme.h`

Device-only header that re-exports the `nb_ui_color` constants for M5GFX use, picks the bundled fonts closest to the brand (Inter→FreeSans, JetBrains Mono→a bundled mono), and provides an inline vertical-gradient fill (the Ink background). Verified by device compile (Task 6 references it).

- [ ] **Step 1: Create `cardputer/src/ui/Theme.h`**

```cpp
#pragma once
#include <M5GFX.h>
#include "UiColor.h"

namespace nb {
namespace theme {

// Color aliases (RGB565) from nb_ui_color.
constexpr uint16_t bgTop = kInkBgTop;
constexpr uint16_t bgBottom = kInkBgBottom;
constexpr uint16_t text = kInkText;
constexpr uint16_t muted = kInkMuted;
constexpr uint16_t line = kInkLine;
constexpr uint16_t coral = kInkCoral;
constexpr uint16_t coralLight = kInkCoralLight;
constexpr uint16_t green = kInkGreen;
constexpr uint16_t greenLight = kInkGreenLight;

// Bundled M5GFX fonts (closest available to Inter / JetBrains Mono).
inline const lgfx::IFont *fontName() { return &fonts::FreeSansBold9pt7b; }
inline const lgfx::IFont *fontBody() { return &fonts::FreeSans9pt7b; }
inline const lgfx::IFont *fontSmall() { return &fonts::Font0; }   // 6x8, for captions/mono

// Fill a canvas with the vertical Ink gradient (top→bottom).
template <typename Gfx>
void fillInkBackground(Gfx &g) {
  int h = g.height();
  for (int y = 0; y < h; ++y) {
    uint8_t t = static_cast<uint8_t>(h <= 1 ? 0 : (y * 255) / (h - 1));
    g.drawFastHLine(0, y, g.width(), lerp565(bgTop, bgBottom, t));
  }
}

}  // namespace theme
}  // namespace nb
```

- [ ] **Step 2: Verify device compile**

`Theme.h` is header-only and not yet referenced; it is compiled when included by the Renderer (Task 6). To confirm it compiles now, temporarily add `#include "ui/Theme.h"` near the top of `cardputer/src/main.cpp` and, inside `setup()` after `M5Cardputer.begin(...)`, add:
```cpp
  (void)nb::theme::coral;
```
Run: `cd cardputer && pio run -e device`
Expected: compiles. (Leave that temporary line; it's removed when `main.cpp` is rewritten in Task 10. Do NOT remove other code.)

> If a bundled font name (`fonts::FreeSansBold9pt7b`, `fonts::FreeSans9pt7b`, `fonts::Font0`) is not present in this M5GFX version and the compile fails, report the exact error; the controller will substitute a font that exists (e.g. `fonts::Font2`).

- [ ] **Step 3: Commit**

```bash
git add cardputer/src/ui/Theme.h cardputer/src/main.cpp
git commit -m "feat(cardputer): Ink theme palette, fonts, gradient (Theme.h)"
```

---

### Task 5: `BroGlyph` — line-art animal characters

**Files:**
- Create: `cardputer/src/ui/BroGlyph.h`, `cardputer/src/ui/BroGlyph.cpp`

Device-only. Draws a `GlyphKind` into a canvas at (cx, cy) with a given radius and color, plus a state (idle/working/asleep) that changes the eyes and adds a subtle marker. The drawing is a simplified line-art port of the web `bro-characters.jsx`. Verified by device compile + on-device visual smoke (Task 7).

- [ ] **Step 1: Create `cardputer/src/ui/BroGlyph.h`**

```cpp
#pragma once
#include <M5GFX.h>
#include "UiView.h"  // GlyphKind

namespace nb {

enum class GlyphState { Idle, Working, Asleep };

// Draw a line-art Bro centered at (cx,cy) fitting roughly within `r` pixels,
// stroked in `color`. `frame` drives subtle motion (ear twitch / zzz).
void drawBroGlyph(M5GFX &g, GlyphKind kind, GlyphState state, int cx, int cy, int r,
                  uint16_t color, uint32_t frame);

// Canvas overload (M5Canvas is an LGFX_Sprite, not an M5GFX) — declared separately
// so screens can draw into the off-screen buffer.
void drawBroGlyph(lgfx::LGFXBase &g, GlyphKind kind, GlyphState state, int cx, int cy, int r,
                  uint16_t color, uint32_t frame);

}  // namespace nb
```

- [ ] **Step 2: Create `cardputer/src/ui/BroGlyph.cpp`**

```cpp
#include "ui/BroGlyph.h"

namespace nb {

// All drawing goes through lgfx::LGFXBase, the common base of M5GFX and M5Canvas.
static void drawEyes(lgfx::LGFXBase &g, GlyphState state, int lx, int rx, int ey, uint16_t color) {
  if (state == GlyphState::Asleep) {
    g.drawLine(lx - 2, ey, lx + 2, ey + 1, color);
    g.drawLine(rx - 2, ey, rx + 2, ey + 1, color);
  } else if (state == GlyphState::Working) {
    g.drawLine(lx - 2, ey + 1, lx + 2, ey, color);  // focused squint
    g.drawLine(rx - 2, ey + 1, rx + 2, ey, color);
  } else {
    g.fillCircle(lx, ey, 1, color);
    g.fillCircle(rx, ey, 1, color);
  }
}

static void drawZzz(lgfx::LGFXBase &g, int x, int y, uint16_t color) {
  g.drawLine(x, y, x + 4, y, color);
  g.drawLine(x + 4, y, x, y + 4, color);
  g.drawLine(x, y + 4, x + 4, y + 4, color);
}

void drawBroGlyph(lgfx::LGFXBase &g, GlyphKind kind, GlyphState state, int cx, int cy, int r,
                  uint16_t color, uint32_t frame) {
  int headR = r;
  int ey = cy - r / 4;
  int lx = cx - r / 3, rx = cx + r / 3;
  int twitch = (state == GlyphState::Working && (frame / 30) % 2 == 0) ? -1 : 0;

  // Head outline.
  g.drawCircle(cx, cy, headR, color);

  switch (kind) {
    case GlyphKind::Rabbit:
      g.drawLine(cx - r / 3, cy - headR, cx - r / 3 - 1, cy - headR - r, color);
      g.drawLine(cx - r / 3, cy - headR, cx - r / 6, cy - headR - r + 2, color);
      g.drawLine(cx + r / 3, cy - headR, cx + r / 3 + 1 + twitch, cy - headR - r, color);
      g.drawLine(cx + r / 3, cy - headR, cx + r / 6, cy - headR - r + 2, color);
      break;
    case GlyphKind::Cat:
      g.fillTriangle(cx - r / 2, cy - headR, cx - r / 6, cy - headR, cx - r / 3, cy - headR - r / 2, color);
      g.fillTriangle(cx + r / 2, cy - headR, cx + r / 6, cy - headR, cx + r / 3 + twitch, cy - headR - r / 2, color);
      break;
    case GlyphKind::Fox:
      g.fillTriangle(cx - r / 2, cy - headR + 2, cx - r / 8, cy - headR, cx - r / 3, cy - headR - r / 2, color);
      g.fillTriangle(cx + r / 2, cy - headR + 2, cx + r / 8, cy - headR, cx + r / 3 + twitch, cy - headR - r / 2, color);
      g.drawLine(cx, cy + r / 3, cx - 2, cy + r / 2, color);  // snout hint
      break;
    case GlyphKind::Person:
    default:
      g.drawFastHLine(cx - r / 2, cy - headR - 1, r, color);  // simple cap line
      break;
  }

  drawEyes(g, state, lx, rx, ey, color);
  // Nose / mouth hint.
  g.fillCircle(cx, cy + r / 6, 1, color);

  if (state == GlyphState::Asleep) {
    drawZzz(g, cx + headR, cy - headR, color);
  } else if (state == GlyphState::Working) {
    // Breathing halo: a faint ring whose radius pulses with the frame.
    int pulse = (frame / 8) % 3;
    g.drawCircle(cx, cy, headR + 2 + pulse, color);
  }
}

void drawBroGlyph(M5GFX &g, GlyphKind kind, GlyphState state, int cx, int cy, int r,
                  uint16_t color, uint32_t frame) {
  drawBroGlyph(static_cast<lgfx::LGFXBase &>(g), kind, state, cx, cy, r, color, frame);
}

}  // namespace nb
```

- [ ] **Step 3: Verify device compile**

Temporarily, in `cardputer/src/main.cpp`, add `#include "ui/BroGlyph.h"` and inside `setup()` after the Theme probe line add:
```cpp
  nb::drawBroGlyph(M5Cardputer.Display, nb::GlyphKind::Rabbit, nb::GlyphState::Idle, 120, 67, 16, nb::theme::coral, 0);
```
Run: `cd cardputer && pio run -e device`
Expected: compiles + links. (These temporary probe lines are removed in Task 10.)

> If `lgfx::LGFXBase` is not the correct common base name in this M5GFX version (compile error on the canvas overload), report the exact error; the controller will adjust the base type.

- [ ] **Step 4: Commit**

```bash
git add cardputer/src/ui/BroGlyph.h cardputer/src/ui/BroGlyph.cpp cardputer/src/main.cpp
git commit -m "feat(cardputer): line-art Bro glyphs (BroGlyph)"
```

---

### Task 6: `Screen` interface + `Router` canvas scaffold

**Files:**
- Create: `cardputer/src/ui/Screen.h`, `cardputer/src/ui/Router.h`, `cardputer/src/ui/Router.cpp`

The `Router` owns a single PSRAM-backed `M5Canvas` (240×135) and the active screen, and per frame: fills the Ink background, asks the active screen to render, and pushes the sprite. Input is normalized to a `Key` enum. Screens are registered by the app (Task 10). Verified by device compile.

- [ ] **Step 1: Create `cardputer/src/ui/Screen.h`**

```cpp
#pragma once
#include <M5GFX.h>

namespace nb {

enum class Key { None, Up, Down, Enter, Back };

class Screen {
 public:
  virtual ~Screen() = default;
  // Draw into the off-screen canvas. `frame` is a monotonically increasing tick.
  virtual void render(M5Canvas &canvas, uint32_t frame) = 0;
  // Handle a normalized key press.
  virtual void onKey(Key key) = 0;
};

}  // namespace nb
```

- [ ] **Step 2: Create `cardputer/src/ui/Router.h`**

```cpp
#pragma once
#include <M5Cardputer.h>
#include "ui/Screen.h"

namespace nb {

class Router {
 public:
  void begin();                 // create the PSRAM canvas
  void setScreen(Screen *s);    // switch active screen
  void tick();                  // render one frame (call from loop)
  Key readKey();                // map the keyboard to a normalized Key (edge-triggered)

 private:
  M5Canvas canvas_{&M5Cardputer.Display};
  Screen *active_ = nullptr;
  uint32_t frame_ = 0;
};

}  // namespace nb
```

- [ ] **Step 3: Create `cardputer/src/ui/Router.cpp`**

```cpp
#include "ui/Router.h"
#include "ui/Theme.h"

namespace nb {

void Router::begin() {
  canvas_.setPsram(true);          // 240x135x16bpp (~64KB) lives in PSRAM
  canvas_.setColorDepth(16);
  canvas_.createSprite(M5Cardputer.Display.width(), M5Cardputer.Display.height());
}

void Router::setScreen(Screen *s) { active_ = s; }

void Router::tick() {
  ++frame_;
  theme::fillInkBackground(canvas_);
  if (active_) active_->render(canvas_, frame_);
  canvas_.pushSprite(0, 0);
}

Key Router::readKey() {
  if (!(M5Cardputer.Keyboard.isChange() && M5Cardputer.Keyboard.isPressed())) return Key::None;
  auto st = M5Cardputer.Keyboard.keysState();
  if (st.enter) return Key::Enter;
  for (auto c : st.word) {
    if (c == ';') return Key::Up;       // Cardputer arrow cluster: ; = up
    if (c == '.') return Key::Down;     // . = down
    if (c == '`' || c == 0x1b) return Key::Back;  // backtick / ESC = back
  }
  return Key::None;
}

}  // namespace nb
```

- [ ] **Step 4: Verify device compile**

In `cardputer/src/main.cpp`, add `#include "ui/Router.h"` and inside `setup()` add:
```cpp
  static nb::Router router;
  router.begin();
  (void)router;
```
Run: `cd cardputer && pio run -e device`
Expected: compiles + links (report flash/RAM — the canvas is in PSRAM so DRAM should stay low).

> The Cardputer arrow keys are the `;`/`.`/`,`/`/` cluster (up/down/left/right) accessed via the Fn layer; this plan uses `;`=Up and `.`=Down for list navigation and backtick/ESC for Back. If `keysState()` reports these differently on the hardware, adjust the mapping in `readKey()` during the on-device smoke (Task 7) and note it.

- [ ] **Step 5: Commit**

```bash
git add cardputer/src/ui/Screen.h cardputer/src/ui/Router.h cardputer/src/ui/Router.cpp cardputer/src/main.cpp
git commit -m "feat(cardputer): Router + PSRAM canvas + Screen interface"
```

---

### Task 7: `BroListScreen`

**Files:**
- Create: `cardputer/src/ui/BroListScreen.h`, `cardputer/src/ui/BroListScreen.cpp`

Renders the roster: a title header, up to 3 visible rows (glyph + name + executor/status), a selection highlight, and a footer hint. Uses `nb_ui_layout` for scrolling and `nb_ui_view`/`BroGlyph` for glyphs. Selection state lives here; `onKey` moves it and invokes an `onOpen` callback on Enter. Verified by device compile + on-device visual smoke.

- [ ] **Step 1: Create `cardputer/src/ui/BroListScreen.h`**

```cpp
#pragma once
#include <functional>
#include <vector>
#include "SessionJson.h"   // nb::Persona
#include "ui/Screen.h"

namespace nb {

class BroListScreen : public Screen {
 public:
  void setBros(const std::vector<Persona> &bros) { bros_ = bros; if (selected_ >= (int)bros_.size()) selected_ = 0; }
  void onOpen(std::function<void(const Persona &)> cb) { onOpen_ = std::move(cb); }
  int selectedIndex() const { return selected_; }

  void render(M5Canvas &canvas, uint32_t frame) override;
  void onKey(Key key) override;

 private:
  std::vector<Persona> bros_;
  int selected_ = 0;
  std::function<void(const Persona &)> onOpen_;
};

}  // namespace nb
```

- [ ] **Step 2: Create `cardputer/src/ui/BroListScreen.cpp`**

```cpp
#include "ui/BroListScreen.h"
#include "ui/BroGlyph.h"
#include "ui/Theme.h"
#include "UiLayout.h"
#include "UiView.h"

namespace nb {

static constexpr int kRows = 3;
static constexpr int kRowH = 32;
static constexpr int kHeaderH = 26;

void BroListScreen::render(M5Canvas &canvas, uint32_t frame) {
  // Header.
  canvas.setFont(theme::fontName());
  canvas.setTextColor(theme::text);
  canvas.setCursor(8, 6);
  canvas.print("Your Bros");
  canvas.setFont(theme::fontSmall());
  canvas.setTextColor(theme::muted);
  canvas.setCursor(180, 10);
  canvas.printf("%d", (int)bros_.size());
  canvas.drawFastHLine(0, kHeaderH, canvas.width(), theme::line);

  if (bros_.empty()) {
    canvas.setFont(theme::fontBody());
    canvas.setTextColor(theme::muted);
    canvas.setCursor(8, 60);
    canvas.print("No bros yet");
    return;
  }

  int top = listScrollTop(selected_, (int)bros_.size(), kRows);
  for (int row = 0; row < kRows && top + row < (int)bros_.size(); ++row) {
    int idx = top + row;
    const Persona &b = bros_[idx];
    int y = kHeaderH + 4 + row * kRowH;
    bool sel = (idx == selected_);

    if (sel) {
      canvas.fillRoundRect(4, y, canvas.width() - 8, kRowH - 4, 6, theme::line);
      canvas.fillRect(4, y, 3, kRowH - 4, theme::coral);  // selection bar
    }

    GlyphState gs = b.busy ? GlyphState::Working : GlyphState::Idle;
    uint16_t glyphColor = b.busy ? theme::coralLight : theme::muted;
    drawBroGlyph(canvas, glyphKindFor(b.avatar), gs, 24, y + (kRowH - 4) / 2, 11, glyphColor, frame);

    canvas.setFont(theme::fontName());
    canvas.setTextColor(theme::text);
    canvas.setCursor(44, y + 4);
    canvas.print(truncate(b.name, 16).c_str());

    canvas.setFont(theme::fontSmall());
    canvas.setTextColor(b.busy ? theme::greenLight : theme::muted);
    canvas.setCursor(44, y + 20);
    canvas.print(b.busy ? "working" : "idle");
  }

  // Footer.
  canvas.setFont(theme::fontSmall());
  canvas.setTextColor(theme::muted);
  canvas.setCursor(8, canvas.height() - 12);
  canvas.print("; / .  pick     enter  open");
}

void BroListScreen::onKey(Key key) {
  if (bros_.empty()) return;
  if (key == Key::Up) selected_ = moveSelection(selected_, (int)bros_.size(), -1);
  else if (key == Key::Down) selected_ = moveSelection(selected_, (int)bros_.size(), +1);
  else if (key == Key::Enter && onOpen_) onOpen_(bros_[selected_]);
}

}  // namespace nb
```

- [ ] **Step 3: Verify device compile**

`cd cardputer && pio run -e device`
Expected: compiles + links. (Not wired into the flow until Task 10; PlatformIO compiles all of `src/`.)

- [ ] **Step 4: On-device visual smoke** (requires hardware) — DEFERRED to the user. Note in your report. Do not flash.

- [ ] **Step 5: Commit**

```bash
git add cardputer/src/ui/BroListScreen.h cardputer/src/ui/BroListScreen.cpp
git commit -m "feat(cardputer): Ink Bro list screen (BroListScreen)"
```

---

### Task 8: `ChatScreen`

**Files:**
- Create: `cardputer/src/ui/ChatScreen.h`, `cardputer/src/ui/ChatScreen.cpp`

Renders the conversation with the selected Bro: header (glyph + name + live dot), body (your last transcript in small text + the Bro's wrapped reply), footer (phase hint + animation — a green breathing waveform while recording, pulsing dots while thinking). The app sets the Bro, transcript, reply, and phase; the screen renders them. `onKey(Back)` invokes an `onBack` callback. Verified by device compile + on-device visual smoke.

- [ ] **Step 1: Create `cardputer/src/ui/ChatScreen.h`**

```cpp
#pragma once
#include <functional>
#include <string>
#include "SessionJson.h"  // nb::Persona
#include "UiView.h"       // nb::Phase
#include "ui/Screen.h"

namespace nb {

class ChatScreen : public Screen {
 public:
  void setBro(const Persona &bro) { bro_ = bro; }
  void setTranscript(const std::string &t) { transcript_ = t; }
  void setReply(const std::string &r) { reply_ = r; }
  void setPhase(Phase p) { phase_ = p; }
  void onBack(std::function<void()> cb) { onBack_ = std::move(cb); }

  void render(M5Canvas &canvas, uint32_t frame) override;
  void onKey(Key key) override;

 private:
  Persona bro_;
  std::string transcript_;
  std::string reply_;
  Phase phase_ = Phase::Idle;
  std::function<void()> onBack_;
};

}  // namespace nb
```

- [ ] **Step 2: Create `cardputer/src/ui/ChatScreen.cpp`**

```cpp
#include "ui/ChatScreen.h"
#include "ui/BroGlyph.h"
#include "ui/Theme.h"
#include "UiLayout.h"
#include "UiView.h"

namespace nb {

static void drawWave(M5Canvas &canvas, int x, int y, uint32_t frame) {
  for (int i = 0; i < 5; ++i) {
    int phase = (frame + i * 3) % 16;
    int h = 4 + (phase < 8 ? phase : 16 - phase) * 2;  // 4..18 triangle wave
    canvas.fillRoundRect(x + i * 5, y - h, 3, h, 1, theme::greenLight);
  }
}

static void drawThinkingDots(M5Canvas &canvas, int x, int y, uint32_t frame) {
  for (int i = 0; i < 3; ++i) {
    bool on = ((frame / 8) % 3) == (uint32_t)i;
    canvas.fillCircle(x + i * 8, y, on ? 3 : 2, on ? theme::coral : theme::muted);
  }
}

void ChatScreen::render(M5Canvas &canvas, uint32_t frame) {
  // Header.
  GlyphState gs = (phase_ == Phase::Streaming) ? GlyphState::Working : GlyphState::Idle;
  drawBroGlyph(canvas, glyphKindFor(bro_.avatar), gs, 16, 14, 10,
               phase_ == Phase::Streaming ? theme::coralLight : theme::text, frame);
  canvas.setFont(theme::fontName());
  canvas.setTextColor(theme::text);
  canvas.setCursor(34, 6);
  canvas.print(truncate(bro_.name, 14).c_str());
  // Live dot.
  uint16_t dot = (phase_ == Phase::Idle) ? theme::muted : theme::greenLight;
  canvas.fillCircle(canvas.width() - 12, 12, 4, dot);
  canvas.drawFastHLine(0, 26, canvas.width(), theme::line);

  // Body: your transcript (small) + the reply (wrapped body).
  int y = 34;
  if (!transcript_.empty()) {
    canvas.setFont(theme::fontSmall());
    canvas.setTextColor(theme::muted);
    canvas.setCursor(8, y);
    canvas.print(("> " + truncate(transcript_, 36)).c_str());
    y += 12;
  }
  canvas.setFont(theme::fontBody());
  canvas.setTextColor(theme::text);
  for (const auto &lineStr : wrapLines(reply_, 30, 3)) {
    canvas.setCursor(8, y);
    canvas.print(lineStr.c_str());
    y += 16;
  }

  // Footer.
  int fy = canvas.height() - 6;
  if (phase_ == Phase::Recording) {
    drawWave(canvas, 8, fy, frame);
  } else if (phase_ == Phase::Streaming) {
    drawThinkingDots(canvas, 12, fy - 4, frame);
  }
  canvas.setFont(theme::fontSmall());
  canvas.setTextColor(phase_ == Phase::Idle ? theme::muted : theme::greenLight);
  canvas.setCursor(70, canvas.height() - 12);
  canvas.print(phaseLabel(phase_));
}

void ChatScreen::onKey(Key key) {
  if (key == Key::Back && onBack_) onBack_();
}

}  // namespace nb
```

- [ ] **Step 3: Verify device compile**

`cd cardputer && pio run -e device`
Expected: compiles + links.

- [ ] **Step 4: On-device visual smoke** — DEFERRED to the user. Note in report; do not flash.

- [ ] **Step 5: Commit**

```bash
git add cardputer/src/ui/ChatScreen.h cardputer/src/ui/ChatScreen.cpp
git commit -m "feat(cardputer): Ink chat screen with phase animations (ChatScreen)"
```

---

### Task 9: Native test sweep + animation tick wiring sanity

**Files:**
- Modify: none (verification task) — confirms the three logic libs still pass together and the device build is green before the main rewrite.

- [ ] **Step 1: Run the full native suite**

Run: `cd cardputer && pio test -e native`
Expected: all suites pass, including `test_ui_color`, `test_ui_layout`, `test_ui_view` plus the Plan A/B suites.

- [ ] **Step 2: Run the device build**

Run: `cd cardputer && pio run -e device`
Expected: compiles + links (report flash/RAM).

- [ ] **Step 3: No commit** (nothing changed). If either gate fails, STOP and report — do not proceed to Task 10.

---

### Task 10: Wire the Router + screens into `main.cpp`

**Files:**
- Modify: `cardputer/src/main.cpp`

Replace the post-pairing flow: instead of `TextScreen` status lines and the single hard-coded persona, drive a `Router` between a `BroListScreen` and a `ChatScreen`. Boot/WiFi/Pair keep `TextScreen`. Multi-Bro selection: the list shows all personas; opening one starts a chat; the default persona (`bootstrap.defaultPersonaId`) is pre-selected. The voice turn updates the `ChatScreen` (transcript, reply, phase) instead of `TextScreen`.

- [ ] **Step 1: Replace `cardputer/src/main.cpp` entirely with:**

```cpp
#include <M5Cardputer.h>

#include <string>
#include <vector>

#include "AudioMeta.h"
#include "Backoff.h"
#include "Config.h"
#include "NewbroClient.h"
#include "Pairing.h"
#include "SessionJson.h"
#include "UiView.h"
#include "audio/MicRecorder.h"
#include "net/WifiManager.h"
#include "store/ConfigStore.h"
#include "transport/HttpsTransport.h"
#include "ui/BroListScreen.h"
#include "ui/ChatScreen.h"
#include "ui/Router.h"
#include "ui/TextScreen.h"

namespace {

nb::ConfigStore g_store;
nb::WifiManager g_wifi;
nb::DeviceConfig g_config;
nb::MicRecorder g_mic;

nb::Router g_router;
nb::BroListScreen g_listScreen;
nb::ChatScreen g_chatScreen;

nb::NewbroClient *g_clientPtr = nullptr;
std::string g_sessionId;
std::vector<nb::Persona> g_personas;
nb::Persona g_activeBro;
bool g_inChat = false;

// --- first-run keyboard entry (unchanged from Plan B; still uses TextScreen) ---
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
  g_config.serverHost = promptLine("Server host", false);
  g_config.serverPort = 443;
  g_store.save(g_config);
}

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
  nb::screen::pairingCode(machine.userCode(), "Enter this code in newbro -> Account -> Devices");
  while (machine.state() == nb::PairState::Polling) {
    delay(intervalMs);
    M5Cardputer.update();
    nb::PollResult poll;
    if (!client.pollPairing(machine.deviceCode(), poll)) {
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

// --- voice turn, now driving the ChatScreen ---
void renderOnce() { g_router.tick(); }

void runVoiceTurn() {
  g_chatScreen.setPhase(nb::Phase::Recording);
  g_chatScreen.setReply("");
  renderOnce();
  if (!g_mic.beginRecording()) {
    g_chatScreen.setReply("mic unavailable");
    g_chatScreen.setPhase(nb::Phase::Idle);
    return;
  }
  while (true) {
    M5Cardputer.update();
    g_mic.poll();
    renderOnce();
    if (!M5Cardputer.Keyboard.isPressed()) break;
    delay(5);
  }
  g_mic.endRecording();
  if (g_mic.sampleCount() == 0) {
    g_chatScreen.setPhase(nb::Phase::Idle);
    return;
  }

  g_chatScreen.setPhase(nb::Phase::Transcribing);
  renderOnce();
  nb::AudioMeta meta = nb::computeAudioMeta(g_mic.sampleCount(), nb::MicRecorder::kSampleRate, 1);
  std::string transcript;
  if (!g_clientPtr->sendAudio(g_sessionId, g_activeBro.id, meta,
                              reinterpret_cast<const uint8_t *>(g_mic.data()), meta.byteLen, transcript)) {
    g_chatScreen.setReply(g_clientPtr->lastError());
    g_chatScreen.setPhase(nb::Phase::Idle);
    return;
  }
  g_chatScreen.setTranscript(transcript);

  g_chatScreen.setPhase(nb::Phase::Streaming);
  for (int i = 0; i < 60; ++i) {
    for (int f = 0; f < 20; ++f) { renderOnce(); delay(50); }  // ~1s of animation per poll
    M5Cardputer.update();
    nb::TurnView v;
    if (g_clientPtr->getReply(g_sessionId, g_activeBro.id, v) && v.found) {
      g_chatScreen.setReply(v.assistantText);
      if (!nb::isTurnActive(v.status)) break;
    }
  }
  g_chatScreen.setPhase(nb::Phase::Idle);
}

void openChat(const nb::Persona &bro) {
  g_activeBro = bro;
  g_chatScreen.setBro(bro);
  g_chatScreen.setTranscript("");
  g_chatScreen.setReply("");
  g_chatScreen.setPhase(nb::Phase::Idle);
  g_inChat = true;
  g_router.setScreen(&g_chatScreen);
}

void backToList() {
  g_inChat = false;
  g_router.setScreen(&g_listScreen);
}

}  // namespace

void setup() {
  auto cfg = M5.config();
  M5Cardputer.begin(cfg, true);
  M5Cardputer.Display.setRotation(1);

  nb::screen::title("newbro");
  delay(600);

  g_store.load(g_config);
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

  static nb::HttpsTransport g_transport(g_config.serverHost, g_config.serverPort);
  static nb::NewbroClient g_client(g_transport);
  g_client.setAuthToken(g_config.deviceToken);
  g_clientPtr = &g_client;

  nb::Bootstrap boot;
  if (!g_client.bootstrap(boot)) {
    nb::screen::status("Bootstrap failed", g_client.lastError());
    return;
  }
  g_sessionId = boot.sessionId;
  if (!g_client.listPersonas(g_sessionId, g_personas) || g_personas.empty()) {
    nb::screen::status("No bros yet", "add a bro in the newbro app, then reboot");
    return;
  }

  // Build the Ink UI.
  g_router.begin();
  g_listScreen.setBros(g_personas);
  g_listScreen.onOpen(openChat);
  g_chatScreen.onBack(backToList);

  // Pre-select the default persona if present.
  for (size_t i = 0; i < g_personas.size(); ++i) {
    if (g_personas[i].id == boot.defaultPersonaId) {
      for (size_t k = 0; k < i; ++k) g_listScreen.onKey(nb::Key::Down);  // advance selection to i
      break;
    }
  }

  g_router.setScreen(&g_listScreen);
}

void loop() {
  M5Cardputer.update();
  nb::Key key = g_router.readKey();

  if (g_inChat) {
    // Hold any key (other than Back) to talk; Back returns to the list.
    if (key == nb::Key::Back) {
      g_chatScreen.onKey(nb::Key::Back);
    } else if (M5Cardputer.Keyboard.isChange() && M5Cardputer.Keyboard.isPressed() && key == nb::Key::None) {
      runVoiceTurn();
    }
  } else if (key != nb::Key::None) {
    g_listScreen.onKey(key);
  }

  g_router.tick();
  delay(5);
}
```

- [ ] **Step 2: Verify device compile**

`cd cardputer && pio run -e device`
Expected: compiles + links (report flash/RAM).

- [ ] **Step 3: Confirm native tests still pass**

`cd cardputer && pio test -e native`
Expected: all suites green.

- [ ] **Step 4: On-device smoke** (requires hardware + reachable server + a paired device + ≥1 Bro) — DEFERRED to the user. Verify:
  1. After connect, the Ink **Bro list** appears with the default Bro pre-selected; `;`/`.` move the selection; line-art glyphs + working/idle status render.
  2. Press Enter → the **chat screen** opens (header glyph + name + live dot).
  3. Hold a key and speak → green breathing waveform + "listening"; release → "transcribing"; your transcript appears; "thinking" with pulsing dots; the Bro's reply fills in wrapped text.
  4. Press backtick/ESC → back to the list.
  5. If the `;`/`.`/backtick key mapping doesn't match the hardware, adjust `Router::readKey()` and note it.

  Record pass/fail per step in the PR; do not flash from this task.

- [ ] **Step 5: Commit**

```bash
git add cardputer/src/main.cpp
git commit -m "feat(cardputer): drive Ink Router + Bro list + chat screens"
```

---

## Self-Review

**Spec coverage (against spec §5–§7, Plan-C slice):**
- `Theme` (device port of design tokens) → `nb_ui_color` (Task 1) + `Theme.h` (Task 4). ✓
- `BroGlyph` (line-art rabbit/cat/fox/person with idle/working/asleep) → Task 5; avatar→kind mapping host-tested in `nb_ui_view` (Task 3). ✓
- `BroListScreen` (roster, selection, status badges, scrolling) → Task 7; scroll/selection math host-tested in `nb_ui_layout` (Task 2). ✓
- `ChatScreen` (header + transcript + reply + footer; idle/recording/transcribing/streaming states; breathe/wave/pulse animations) → Task 8; phase model + labels host-tested in `nb_ui_view` (Task 3); text wrap host-tested in `nb_ui_layout`. ✓
- `Router` (owns active screen + transitions + animation tick; normalized input) → Task 6; wired in Task 10. ✓
- Double-buffered rendering via off-screen `M5Canvas` (PSRAM) → Task 6. ✓
- Multi-Bro selection (use `defaultPersonaId`) → Task 10 pre-selection + list selection. ✓
- Host-testable logic split from hardware (spec §9) → all color/layout/view logic in `lib/` with native tests (Tasks 1–3); glyph/screens/router/canvas are device glue verified by compile + on-device visual smoke (Tasks 4–10). ✓
- Deferred (noted): Boot/WiFi/Pair keep `TextScreen` (a light Ink restyle is optional follow-up); speaker TTS remains out of scope per spec; WebSocket push (vs Plan B's polling) remains a possible later optimization.

**Placeholder scan:** No TBD/TODO. Every code step contains complete code. The two genuinely hardware-dependent unknowns — bundled font names (Task 4) and the Cardputer arrow-key mapping (Task 6/10) — carry explicit "report the exact error / adjust during smoke" escalations, not vague instructions. On-device visual smoke steps are concrete numbered procedures and are explicitly deferred (not faked).

**Type/name consistency:** `rgb565`/`lerp565` + `kInk*` (Task 1) feed `theme::*` aliases + `fillInkBackground` (Task 4). `listScrollTop`/`moveSelection`/`truncate`/`wrapLines` (Task 2) are used by `BroListScreen` (Task 7) and `ChatScreen` (Task 8). `GlyphKind`/`glyphKindFor`/`Phase`/`isTurnActive`/`phaseLabel` (Task 3) are used by `BroGlyph` (Task 5), both screens, and `main.cpp`. `GlyphState` (Task 5) is set by the screens. The `Screen` interface (`render(M5Canvas&, uint32_t)`, `onKey(Key)`) + `Key` enum (Task 6) are implemented by `BroListScreen`/`ChatScreen` and driven by `Router`/`main.cpp`. `BroListScreen::setBros/onOpen/onKey` and `ChatScreen::setBro/setTranscript/setReply/setPhase/onBack` (Tasks 7–8) match their call sites in Task 10. `Router::begin/setScreen/tick/readKey` (Task 6) match Task 10 usage. Reuses Plan B's `nb::Persona`, `nb::TurnView`, `NewbroClient::{bootstrap,listPersonas,sendAudio,getReply}`, `MicRecorder`, and `nb::screen::*` (TextScreen) unchanged. ✓
