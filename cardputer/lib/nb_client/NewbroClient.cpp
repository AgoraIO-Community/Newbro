#include "NewbroClient.h"

#include <ArduinoJson.h>

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
  HttpResponse r = t_.request("GET", "/api/sessions/" + sessionId + "/bros", "", token_);
  if (!r.transportOk) { lastError_ = "network error"; return false; }
  if (r.status != 200) { lastError_ = "bros failed: HTTP " + std::to_string(r.status); return false; }
  if (!parsePersonas(r.body, out)) { lastError_ = "bad bros response"; return false; }
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

bool NewbroClient::getReply(const std::string &sessionId, const std::string &personaId,
                            const std::string &threadId, TurnView &out) {
  lastError_.clear();
  JsonDocument filter;
  buildTurnFilter(filter);
  JsonDocument doc;
  int status = 0;
  // limit=1: we only need the newest turn for the reply. A larger window can push
  // the timeline response past the 64 KB Arduino String ceiling (long codex replies)
  // -> truncated body -> parse fails every poll -> the chat is stuck "thinking".
  std::string path = "/api/sessions/" + sessionId + "/bro-threads/" + threadId +
                     "/timeline?target_persona_id=" + personaId + "&limit=1";
  if (!t_.getFiltered(path, token_, filter, doc, status)) {
    lastError_ = status == 0      ? "network error"
                 : status != 200  ? "timeline HTTP " + std::to_string(status)
                                   : "bad timeline";
    return false;
  }
  collectLatestTurn(doc, personaId, out);
  return true;
}

bool NewbroClient::getThreads(const std::string &sessionId, const std::string &personaId,
                              std::vector<ThreadInfo> &out) {
  lastError_.clear();
  JsonDocument filter;
  buildBroThreadsFilter(filter);
  JsonDocument doc;
  int status = 0;
  std::string path = "/api/sessions/" + sessionId +
                     "/bro-threads?target_persona_id=" + personaId + "&limit=15";
  if (!t_.getFiltered(path, token_, filter, doc, status)) {
    lastError_ = status == 0      ? "network error"
                 : status != 200  ? "threads HTTP " + std::to_string(status)
                                   : "bad threads";
    return false;
  }
  collectBroThreads(doc, personaId, out);
  return true;
}

}  // namespace nb
