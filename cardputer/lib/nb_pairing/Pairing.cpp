#include "Pairing.h"

namespace nb {

void PairingMachine::begin() {
  state_ = PairState::AwaitingStart;
  userCode_.clear();
  deviceCode_.clear();
  token_.clear();
  error_.clear();
}

void PairingMachine::onStart(const PairStart &s) {
  deviceCode_ = s.deviceCode;
  userCode_ = s.userCode;
  state_ = PairState::Polling;
}

void PairingMachine::onPoll(const PollResult &r) {
  if (r.status == "claimed" && !r.token.empty()) {
    token_ = r.token;
    state_ = PairState::Claimed;
  }
  // "pending", or "claimed" with an already-delivered (empty) token: keep polling.
}

void PairingMachine::onExpired() { state_ = PairState::Expired; }

void PairingMachine::onError(const std::string &msg) {
  error_ = msg;
  state_ = PairState::Failed;
}

}  // namespace nb
