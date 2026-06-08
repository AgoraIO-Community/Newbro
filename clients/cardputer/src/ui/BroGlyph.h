#pragma once
#include <M5GFX.h>
#include "UiView.h"  // GlyphKind

namespace nb {

enum class GlyphState { Idle, Working, Asleep };

// Draw into the common LGFX base (works for both M5GFX display and M5Canvas).
void drawBroGlyph(lgfx::LGFXBase &g, GlyphKind kind, GlyphState state, int cx, int cy, int r,
                  uint16_t color, uint32_t frame);

}  // namespace nb
