#pragma once
#include <string>
#include <vector>
#include "Transport.h"
#include "PairingJson.h"
#include "SessionJson.h"
#include "AudioMeta.h"

namespace nb {

class NewbroClient {
 public:
  explicit NewbroClient(Transport &transport) : t_(transport) {}

  void setAuthToken(const std::string &token) { token_ = token; }

  // Pairing (Plan A)
  bool startPairing(PairStart &out);
  bool pollPairing(const std::string &deviceCode, PollResult &out);

  // Conversation (Plan B)
  bool bootstrap(Bootstrap &out);
  bool listPersonas(const std::string &sessionId, std::vector<Persona> &out);
  bool sendText(const std::string &sessionId, const std::string &personaId,
                const std::string &targetThreadId, const std::string &text);
  bool sendAudio(const std::string &sessionId, const std::string &personaId,
                 const std::string &targetThreadId, const AudioMeta &meta,
                 const uint8_t *pcm, size_t len, std::string &transcriptOut);
  bool getReply(const std::string &sessionId, const std::string &personaId,
                const std::string &threadId, TurnView &out);
  bool getThreads(const std::string &sessionId, const std::string &personaId,
                  std::vector<ThreadInfo> &out);

  const std::string &lastError() const { return lastError_; }

 private:
  Transport &t_;
  std::string lastError_;
  std::string token_;
};

}  // namespace nb
