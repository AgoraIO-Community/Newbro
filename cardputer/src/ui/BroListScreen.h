#pragma once
#include <functional>
#include <vector>
#include "SessionJson.h"   // nb::Persona
#include "ui/Screen.h"

namespace nb {

class BroListScreen : public Screen {
 public:
  void setBros(const std::vector<Persona> &bros) {
    bros_ = bros;
    if (selected_ >= (int)bros_.size()) selected_ = 0;
  }
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
