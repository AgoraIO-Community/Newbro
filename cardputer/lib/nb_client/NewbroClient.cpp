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

bool NewbroClient::sendText(const std::string &sessionId, const std::string &personaId,
                            const std::string &targetThreadId, const std::string &text) {
  lastError_.clear();
  HttpResponse r = t_.request("POST", "/api/sessions/" + sessionId + "/executor-text-instructions",
                              buildTextBody(personaId, text, targetThreadId), token_);
  if (!r.transportOk) { lastError_ = "network error"; return false; }
  if (r.status != 200) { lastError_ = "text HTTP " + std::to_string(r.status) + ": " + r.body; return false; }
  return true;
}

bool NewbroClient::sendAudio(const std::string &sessionId, const std::string &personaId,
                             const std::string &targetThreadId, const AudioMeta &meta,
                             const uint8_t *pcm, size_t len, std::string &transcriptOut) {
  lastError_.clear();
  transcriptOut.clear();
  std::string path = "/api/sessions/" + sessionId + "/executor-audio-instructions?" +
                     buildAudioQuery(personaId, meta, targetThreadId);
  HttpResponse r = t_.postBytes(path, "audio/pcm", pcm, len, token_);
  if (!r.transportOk) { lastError_ = "network error"; return false; }
  if (r.status != 200) {
    lastError_ = "audio HTTP " + std::to_string(r.status) + ": " + r.body;
    return false;
  }
  transcriptOut = parseAudioTranscript(r.body);
  return true;
}

bool NewbroClient::getReply(const std::string &sessionId, const std::string &personaId, TurnView &out) {
  lastError_.clear();
  HttpResponse r = t_.request("GET", "/api/sessions/" + sessionId, "", token_);
  if (!r.transportOk) { lastError_ = "network error"; return false; }
  if (r.status != 200) { lastError_ = "snapshot failed: HTTP " + std::to_string(r.status); return false; }
  if (!extractLatestTurn(r.body, personaId, out)) { lastError_ = "bad snapshot"; return false; }
  return true;
}

bool NewbroClient::getThreads(const std::string &sessionId, const std::string &personaId,
                              std::vector<ThreadInfo> &out) {
  lastError_.clear();
  HttpResponse r = t_.request("GET", "/api/sessions/" + sessionId, "", token_);
  if (!r.transportOk) { lastError_ = "network error"; return false; }
  if (r.status != 200) { lastError_ = "threads HTTP " + std::to_string(r.status) + ": " + r.body; return false; }
  if (!parseBroThreads(r.body, personaId, out)) { lastError_ = "bad snapshot"; return false; }
  return true;
}

}  // namespace nb
