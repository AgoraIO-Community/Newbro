#pragma once
#include <M5GFX.h>

namespace nb {

// Other = a fresh press of any non-navigation key (used for push-to-talk).
enum class Key { None, Up, Down, Enter, Back, Other };

class Screen {
 public:
  virtual ~Screen() = default;
  virtual void render(M5Canvas &canvas, uint32_t frame) = 0;
  virtual void onKey(Key key) = 0;
};

}  // namespace nb
