#pragma once
#include <M5Cardputer.h>
#include "ui/Screen.h"

namespace nb {

class Router {
 public:
  void begin();
  void setScreen(Screen *s);
  void tick();
  Key readKey();

 private:
  M5Canvas canvas_{&M5Cardputer.Display};
  Screen *active_ = nullptr;
  uint32_t frame_ = 0;
};

}  // namespace nb
