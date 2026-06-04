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
    Persona p;
    p.id = item["persona_id"].as<std::string>();
    p.name = item["name"].as<std::string>();
    p.avatar = item["avatar"].as<std::string>();
    p.busy = std::string("busy") == (item["status"].is<const char *>() ? item["status"].as<const char *>() : "");
    out.push_back(p);
  }
  return true;
}

}  // namespace nb
