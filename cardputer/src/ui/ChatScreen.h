#pragma once
#include <functional>
#include <string>
#include "SessionJson.h"  // nb::Persona
#include "UiView.h"       // nb::Phase
#include "ui/Screen.h"

namespace nb {

class ChatScreen : public Screen {
 public:
  void setBro(const Persona &bro) { bro_ = bro; }
  void setTranscript(const std::string &t) { transcript_ = t; }
  void setReply(const std::string &r) { reply_ = r; }
  void setPhase(Phase p) { phase_ = p; }
  void onBack(std::function<void()> cb) { onBack_ = std::move(cb); }

  void render(M5Canvas &canvas, uint32_t frame) override;
  void onKey(Key key) override;

 private:
  Persona bro_;
  std::string transcript_;
  std::string reply_;
  Phase phase_ = Phase::Idle;
  std::function<void()> onBack_;
};

}  // namespace nb
