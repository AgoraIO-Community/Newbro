#pragma once
#include <string>
#include <vector>
#include "AudioMeta.h"

namespace nb {

struct Bootstrap {
  std::string sessionId;
  std::string defaultPersonaId;  // empty if null
};

struct Persona {
  std::string id;
  std::string name;
  std::string avatar;
  bool busy = false;  // status == "busy"
};

struct TurnView {
  bool found = false;
  std::string userText;
  std::string assistantText;
  std::string status;
};

struct ThreadInfo {
  std::string id;
  std::string title;
  std::string preview;    // empty if null
  std::string status;
  std::string updatedAt;  // ISO-8601; empty if null
};

bool parseBootstrap(const std::string &json, Bootstrap &out);
bool parsePersonas(const std::string &json, std::vector<Persona> &out);

// Threads for one persona from a full SessionSnapshot, newest-first
// (updated_at descending; empty updated_at sorts last).
bool parseBroThreads(const std::string &snapshotJson, const std::string &personaId,
                     std::vector<ThreadInfo> &out);

// Implemented in Task 3:
bool extractLatestTurn(const std::string &snapshotJson, const std::string &personaId, TurnView &out);
std::string parseAudioTranscript(const std::string &json);
std::string buildAudioQuery(const std::string &personaId, const AudioMeta &m,
                            const std::string &targetThreadId);
std::string buildTextBody(const std::string &personaId, const std::string &text,
                          const std::string &targetThreadId);

}  // namespace nb
