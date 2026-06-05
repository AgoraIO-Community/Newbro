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

bool parseBootstrap(const std::string &json, Bootstrap &out);
bool parsePersonas(const std::string &json, std::vector<Persona> &out);

// Implemented in Task 3:
bool extractLatestTurn(const std::string &snapshotJson, const std::string &personaId, TurnView &out);
std::string parseAudioTranscript(const std::string &json);
std::string buildAudioQuery(const std::string &personaId, const AudioMeta &m);
std::string buildTextBody(const std::string &personaId, const std::string &text);

}  // namespace nb
