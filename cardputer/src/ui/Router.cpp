#include "ui/Router.h"
#include "ui/Theme.h"

namespace nb {

void Router::begin() {
  canvas_.setPsram(false);  // no PSRAM on the Cardputer; the 64 KB canvas lives in internal SRAM
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
  // NOTE: isChange() is one-shot (it resets its baseline on read), so it MUST be
  // called exactly once per loop. Callers use the returned Key, never isChange() again.
  if (!(M5Cardputer.Keyboard.isChange() && M5Cardputer.Keyboard.isPressed())) return Key::None;
  auto st = M5Cardputer.Keyboard.keysState();
  if (st.enter) return Key::Enter;
  for (auto c : st.word) {
    if (c == ';') return Key::Up;
    if (c == '.') return Key::Down;
    if (c == '`' || c == 0x1b) return Key::Back;
  }
  return Key::Other;  // fresh press of a non-nav key → push-to-talk
}

}  // namespace nb
