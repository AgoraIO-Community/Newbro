#include "SessionJson.h"
#include <ArduinoJson.h>

namespace nb {

bool parseBootstrap(const std::string &json, Bootstrap &out) {
  JsonDocument doc;
  if (deserializeJson(doc, json) != DeserializationError::Ok) return false;
  if (!doc["session_id"].is<const char *>()) return false;
  out.sessionId = doc["session_id"].as<std::string>();
  out.defaultPersonaId =
      doc["default_persona_id"].is<const char *>() ? doc["default_persona_id"].as<std::string>() : std::string();
  return true;
}

bool parsePersonas(const std::string &json, std::vector<Persona> &out) {
  JsonDocument doc;
  if (deserializeJson(doc, json) != DeserializationError::Ok) return false;
  if (!doc.is<JsonArray>()) return false;
  out.clear();
  for (JsonObject item : doc.as<JsonArray>()) {
    if (!item["persona_id"].is<const char *>()) continue;  // skip malformed entries
    Persona p;
    p.id = item["persona_id"].as<std::string>();
    p.name = item["name"].is<const char *>() ? item["name"].as<std::string>() : std::string();
    p.avatar = item["avatar"].is<const char *>() ? item["avatar"].as<std::string>() : std::string();
    p.busy = item["status"].as<std::string>() == "busy";
    out.push_back(p);
  }
  return true;
}

bool extractLatestTurn(const std::string &snapshotJson, const std::string &personaId, TurnView &out) {
  JsonDocument filter;
  JsonObject t = filter["bro_timeline_turns"].add<JsonObject>();
  t["persona_id"] = true;
  t["status"] = true;
  t["created_at"] = true;
  t["user"]["text"] = true;
  t["user"]["transcript"] = true;
  t["assistant"]["text"] = true;

  JsonDocument doc;
  if (deserializeJson(doc, snapshotJson, DeserializationOption::Filter(filter)) != DeserializationError::Ok) {
    return false;
  }
  out = TurnView{};
  std::string bestCreatedAt;
  for (JsonObject turn : doc["bro_timeline_turns"].as<JsonArray>()) {
    const char *pid = turn["persona_id"].is<const char *>() ? turn["persona_id"].as<const char *>() : "";
    if (personaId != pid) continue;
    std::string createdAt = turn["created_at"].as<std::string>();
    if (out.found && createdAt < bestCreatedAt) continue;  // ISO-8601 sorts lexicographically
    bestCreatedAt = createdAt;
    out.found = true;
    out.status = turn["status"].as<std::string>();
    JsonObject user = turn["user"];
    out.userText = user["transcript"].is<const char *>() ? user["transcript"].as<std::string>()
                   : user["text"].is<const char *>()     ? user["text"].as<std::string>()
                                                          : std::string();
    JsonObject assistant = turn["assistant"];
    out.assistantText = assistant["text"].is<const char *>() ? assistant["text"].as<std::string>() : std::string();
  }
  return true;
}

std::string parseAudioTranscript(const std::string &json) {
  JsonDocument doc;
  if (deserializeJson(doc, json) != DeserializationError::Ok) return std::string();
  return doc["transcript_text"].is<const char *>() ? doc["transcript_text"].as<std::string>() : std::string();
}

std::string buildAudioQuery(const std::string &personaId, const AudioMeta &m) {
  std::string q;
  q += "target_persona_id=" + personaId;
  q += "&duration_ms=" + std::to_string(m.durationMs);
  q += "&sample_rate=" + std::to_string(m.sampleRate);
  q += "&num_channels=" + std::to_string(static_cast<unsigned>(m.numChannels));
  q += "&samples_per_channel=" + std::to_string(m.samplesPerChannel);
  return q;
}

std::string buildTextBody(const std::string &personaId, const std::string &text) {
  JsonDocument doc;
  doc["target_persona_id"] = personaId;
  doc["text"] = text;
  doc["create_new_thread"] = false;
  std::string out;
  serializeJson(doc, out);
  return out;
}

}  // namespace nb
