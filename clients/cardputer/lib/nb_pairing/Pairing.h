#pragma once
#include <string>
#include "PairingJson.h"  // PairStart, PollResult

namespace nb {

enum class PairState { Idle, AwaitingStart, Polling, Claimed, Expired, Failed };

class PairingMachine {
 public:
  PairState state() const { return state_; }
  const std::string &userCode() const { return userCode_; }
  const std::string &deviceCode() const { return deviceCode_; }
  const std::string &token() const { return token_; }
  const std::string &error() const { return error_; }

  void begin();
  void onStart(const PairStart &s);
  void onPoll(const PollResult &r);
  void onExpired();
  void onError(const std::string &msg);

 private:
  PairState state_ = PairState::Idle;
  std::string userCode_;
  std::string deviceCode_;
  std::string token_;
  std::string error_;
};

}  // namespace nb
