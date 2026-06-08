#include "SessionJson.h"
#include <ArduinoJson.h>
#include <algorithm>

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
  // GET /sessions/{id}/bros -> {"bros":[{persona_id,name,avatar,status,...}]}
  JsonDocument doc;
  if (deserializeJson(doc, json) != DeserializationError::Ok) return false;
  JsonArray bros = doc["bros"].as<JsonArray>();
  if (bros.isNull()) return false;
  out.clear();
  for (JsonObject item : bros) {
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

void buildTurnFilter(JsonDocument &filter) {
  // GET /sessions/{id}/bro-threads/{tid}/timeline -> {"turns":[BroTimelineTurn]}
  JsonObject t = filter["turns"].add<JsonObject>();
  t["persona_id"] = true;
  t["status"] = true;
  t["created_at"] = true;
  t["user"]["text"] = true;
  t["user"]["transcript"] = true;
  t["assistant"]["text"] = true;
}

bool extractLatestTurn(const std::string &snapshotJson, const std::string &personaId, TurnView &out) {
  JsonDocument filter;
  buildTurnFilter(filter);
  JsonDocument doc;
  if (deserializeJson(doc, snapshotJson, DeserializationOption::Filter(filter)) != DeserializationError::Ok) {
    return false;
  }
  collectLatestTurn(doc, personaId, out);
  return true;
}

void collectLatestTurn(JsonDocument &doc, const std::string &personaId, TurnView &out) {
  out = TurnView{};
  std::string bestCreatedAt;
  for (JsonObject turn : doc["turns"].as<JsonArray>()) {
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
}

std::string parseAudioTranscript(const std::string &json) {
  JsonDocument doc;
  if (deserializeJson(doc, json) != DeserializationError::Ok) return std::string();
  return doc["transcript_text"].is<const char *>() ? doc["transcript_text"].as<std::string>() : std::string();
}

std::string buildAudioQuery(const std::string &personaId, const AudioMeta &m,
                            const std::string &targetThreadId) {
  std::string q;
  q += "target_persona_id=" + personaId;
  q += "&target_thread_id=" + targetThreadId;
  q += "&duration_ms=" + std::to_string(m.durationMs);
  q += "&sample_rate=" + std::to_string(m.sampleRate);
  q += "&num_channels=" + std::to_string(static_cast<unsigned>(m.numChannels));
  q += "&samples_per_channel=" + std::to_string(m.samplesPerChannel);
  return q;
}

std::string buildTextBody(const std::string &personaId, const std::string &text,
                          const std::string &targetThreadId) {
  JsonDocument doc;
  doc["target_persona_id"] = personaId;
  doc["target_thread_id"] = targetThreadId;
  doc["text"] = text;
  doc["create_new_thread"] = false;
  std::string out;
  serializeJson(doc, out);
  return out;
}

void buildBroThreadsFilter(JsonDocument &filter) {
  // GET /sessions/{id}/bro-threads -> {"threads":[BroThread]}
  JsonObject t = filter["threads"].add<JsonObject>();
  t["thread_id"] = true;
  t["persona_id"] = true;
  t["title"] = true;
  t["preview"] = true;
  t["status"] = true;
  t["updated_at"] = true;
}

bool parseBroThreads(const std::string &snapshotJson, const std::string &personaId,
                     std::vector<ThreadInfo> &out) {
  JsonDocument filter;
  buildBroThreadsFilter(filter);
  JsonDocument doc;
  if (deserializeJson(doc, snapshotJson, DeserializationOption::Filter(filter)) != DeserializationError::Ok) {
    return false;
  }
  collectBroThreads(doc, personaId, out);
  return true;
}

void collectBroThreads(JsonDocument &doc, const std::string &personaId,
                       std::vector<ThreadInfo> &out) {
  out.clear();
  for (JsonObject th : doc["threads"].as<JsonArray>()) {
    const char *pid = th["persona_id"].is<const char *>() ? th["persona_id"].as<const char *>() : "";
    if (personaId != pid) continue;
    if (!th["thread_id"].is<const char *>()) continue;  // skip threads with no id
    ThreadInfo info;
    info.id = th["thread_id"].as<std::string>();
    info.title = th["title"].is<const char *>() ? th["title"].as<std::string>() : std::string();
    info.preview = th["preview"].is<const char *>() ? th["preview"].as<std::string>() : std::string();
    info.status = th["status"].is<const char *>() ? th["status"].as<std::string>() : std::string();
    info.updatedAt = th["updated_at"].is<const char *>() ? th["updated_at"].as<std::string>() : std::string();
    out.push_back(info);
  }
  std::sort(out.begin(), out.end(), [](const ThreadInfo &a, const ThreadInfo &b) {
    return a.updatedAt > b.updatedAt;  // ISO-8601 desc; "" sorts last
  });
}

}  // namespace nb
