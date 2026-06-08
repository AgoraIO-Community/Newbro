#pragma once
#include <M5GFX.h>
#include "UiColor.h"

namespace nb {
namespace theme {

constexpr uint16_t bgTop = kInkBgTop;
constexpr uint16_t bgBottom = kInkBgBottom;
constexpr uint16_t text = kInkText;
constexpr uint16_t muted = kInkMuted;
constexpr uint16_t line = kInkLine;
constexpr uint16_t coral = kInkCoral;
constexpr uint16_t coralLight = kInkCoralLight;
constexpr uint16_t green = kInkGreen;
constexpr uint16_t greenLight = kInkGreenLight;

inline const lgfx::IFont *fontName() { return &fonts::FreeSansBold9pt7b; }
inline const lgfx::IFont *fontBody() { return &fonts::FreeSans9pt7b; }
inline const lgfx::IFont *fontSmall() { return &fonts::Font0; }

// CJK-capable fonts for user/assistant text (transcripts/replies can be Chinese).
// efontCN covers Simplified Chinese + ASCII. (Traditional Chinese / Korean /
// Japanese would each need their own efont; M5GFX has no single all-CJK font.)
inline const lgfx::IFont *fontCJK() { return &fonts::efontCN_16; }
inline const lgfx::IFont *fontCJKSmall() { return &fonts::efontCN_12; }

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
