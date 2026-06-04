#pragma once
#include <cstdint>

namespace nb {

// Pack 8-bit RGB into RGB565 (the M5GFX default color format).
constexpr uint16_t rgb565(uint8_t r, uint8_t g, uint8_t b) {
  return static_cast<uint16_t>(((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3));
}

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
