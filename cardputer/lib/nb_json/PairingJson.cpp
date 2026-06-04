#include "PairingJson.h"
#include <ArduinoJson.h>

namespace nb {

bool parsePairStart(const std::string &json, PairStart &out) {
  JsonDocument doc;
  if (deserializeJson(doc, json) != DeserializationError::Ok) return false;
  if (!doc["device_code"].is<const char *>() || !doc["user_code"].is<const char *>()) return false;
  out.deviceCode = doc["device_code"].as<std::string>();
  out.userCode = doc["user_code"].as<std::string>();
  out.interval = doc["interval"].as<int>();
  out.expiresAt = doc["expires_at"].as<std::string>();
  return true;
}

bool parsePollResult(const std::string &json, PollResult &out) {
  JsonDocument doc;
  if (deserializeJson(doc, json) != DeserializationError::Ok) return false;
  if (!doc["status"].is<const char *>()) return false;
  out.status = doc["status"].as<std::string>();
  out.token = doc["token"].is<const char *>() ? doc["token"].as<std::string>() : std::string();
  return true;
}

std::string buildPollBody(const std::string &deviceCode) {
  JsonDocument doc;
  doc["device_code"] = deviceCode;
  std::string out;
  serializeJson(doc, out);
  return out;
}

}  // namespace nb
