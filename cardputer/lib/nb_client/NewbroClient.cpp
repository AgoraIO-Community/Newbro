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

bool NewbroClient::bootstrap(Bootstrap &out) {
  lastError_.clear();
  HttpResponse r = t_.request("GET", "/api/me/bootstrap", "", token_);
  if (!r.transportOk) { lastError_ = "network error"; return false; }
  if (r.status != 200) { lastError_ = "bootstrap failed: HTTP " + std::to_string(r.status); return false; }
  if (!parseBootstrap(r.body, out)) { lastError_ = "bad bootstrap response"; return false; }
  return true;
}

bool NewbroClient::listPersonas(const std::string &sessionId, std::vector<Persona> &out) {
  lastError_.clear();
  HttpResponse r = t_.request("GET", "/api/sessions/" + sessionId + "/personas", "", token_);
  if (!r.transportOk) { lastError_ = "network error"; return false; }
  if (r.status != 200) { lastError_ = "personas failed: HTTP " + std::to_string(r.status); return false; }
  if (!parsePersonas(r.body, out)) { lastError_ = "bad personas response"; return false; }
  return true;
}

bool NewbroClient::sendText(const std::string &sessionId, const std::string &personaId, const std::string &text) {
  lastError_.clear();
  HttpResponse r = t_.request("POST", "/api/sessions/" + sessionId + "/executor-text-instructions",
                              buildTextBody(personaId, text), token_);
  if (!r.transportOk) { lastError_ = "network error"; return false; }
  if (r.status != 200) { lastError_ = "text failed: HTTP " + std::to_string(r.status); return false; }
  return true;
}

}  // namespace nb
