#pragma once
#include <M5GFX.h>

namespace nb {

enum class Key { None, Up, Down, Enter, Back };

class Screen {
 public:
  virtual ~Screen() = default;
  virtual void render(M5Canvas &canvas, uint32_t frame) = 0;
  virtual void onKey(Key key) = 0;
};

}  // namespace nb
