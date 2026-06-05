#pragma once
#include <string>
#include "Transport.h"
#include "PairingJson.h"

namespace nb {

class NewbroClient {
 public:
  explicit NewbroClient(Transport &transport) : t_(transport) {}

  // Each returns true on success (HTTP 200 + parseable body). On failure they
  // set lastError() and return false.
  bool startPairing(PairStart &out);
  bool pollPairing(const std::string &deviceCode, PollResult &out);

  const std::string &lastError() const { return lastError_; }

 private:
  Transport &t_;
  std::string lastError_;
};

}  // namespace nb
