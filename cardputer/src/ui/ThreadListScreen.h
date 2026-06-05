#pragma once
#include <functional>
#include <string>
#include <vector>
#include "SessionJson.h"  // nb::ThreadInfo
#include "ui/Screen.h"

namespace nb {

class ThreadListScreen : public Screen {
 public:
  void setBroName(const std::string &name) { broName_ = name; }
  void setThreads(const std::vector<ThreadInfo> &threads) {
    threads_ = threads;
    if (selected_ >= (int)threads_.size()) selected_ = 0;
  }
  void onPick(std::function<void(const ThreadInfo &)> cb) { onPick_ = std::move(cb); }
  void onBack(std::function<void()> cb) { onBack_ = std::move(cb); }

  void render(M5Canvas &canvas, uint32_t frame) override;
  void onKey(Key key) override;

 private:
  std::string broName_;
  std::vector<ThreadInfo> threads_;
  int selected_ = 0;
  std::function<void(const ThreadInfo &)> onPick_;
  std::function<void()> onBack_;
};

}  // namespace nb
