#include "ui/BroGlyph.h"

namespace nb {

static void drawEyes(lgfx::LGFXBase &g, GlyphState state, int lx, int rx, int ey, uint16_t color) {
  if (state == GlyphState::Asleep) {
    g.drawLine(lx - 2, ey, lx + 2, ey + 1, color);
    g.drawLine(rx - 2, ey, rx + 2, ey + 1, color);
  } else if (state == GlyphState::Working) {
    g.drawLine(lx - 2, ey + 1, lx + 2, ey, color);
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
      g.drawLine(cx, cy + r / 3, cx - 2, cy + r / 2, color);
      break;
    case GlyphKind::Person:
    default:
      g.drawFastHLine(cx - r / 2, cy - headR - 1, r, color);
      break;
  }

  drawEyes(g, state, lx, rx, ey, color);
  g.fillCircle(cx, cy + r / 6, 1, color);

  if (state == GlyphState::Asleep) {
    drawZzz(g, cx + headR, cy - headR, color);
  } else if (state == GlyphState::Working) {
    int pulse = (frame / 8) % 3;
    g.drawCircle(cx, cy, headR + 2 + pulse, color);
  }
}

}  // namespace nb
