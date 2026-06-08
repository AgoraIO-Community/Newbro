#pragma once
#include <string>

namespace nb {

struct PairStart {
  std::string deviceCode;
  std::string userCode;
  int interval = 0;
  std::string expiresAt;
};

struct PollResult {
  std::string status;  // "pending" | "claimed"
  std::string token;   // empty unless claimed with a non-null token
};

// Return true on a successful parse; false on invalid JSON or missing required fields.
bool parsePairStart(const std::string &json, PairStart &out);
bool parsePollResult(const std::string &json, PollResult &out);

// Build the JSON body for POST /api/devices/pair/poll.
std::string buildPollBody(const std::string &deviceCode);

}  // namespace nb
