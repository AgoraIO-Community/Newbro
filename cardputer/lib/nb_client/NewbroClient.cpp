#include "NewbroClient.h"

namespace nb {

bool NewbroClient::startPairing(PairStart &out) {
  lastError_.clear();
  HttpResponse r = t_.request("POST", "/api/devices/pair/start", "", "");
  if (!r.transportOk) { lastError_ = "network error"; return false; }
  if (r.status != 200) { lastError_ = "start failed: HTTP " + std::to_string(r.status); return false; }
  if (!parsePairStart(r.body, out)) { lastError_ = "bad start response"; return false; }
  return true;
}

bool NewbroClient::pollPairing(const std::string &deviceCode, PollResult &out) {
  lastError_.clear();
  HttpResponse r = t_.request("POST", "/api/devices/pair/poll", buildPollBody(deviceCode), "");
  if (!r.transportOk) { lastError_ = "network error"; return false; }
  if (r.status != 200) { lastError_ = "poll failed: HTTP " + std::to_string(r.status); return false; }
  if (!parsePollResult(r.body, out)) { lastError_ = "bad poll response"; return false; }
  return true;
}

}  // namespace nb
