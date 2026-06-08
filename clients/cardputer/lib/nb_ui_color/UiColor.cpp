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
