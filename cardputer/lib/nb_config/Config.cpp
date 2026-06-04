#include "Config.h"
#include <ArduinoJson.h>

namespace nb {

std::string encodeConfig(const DeviceConfig &c) {
  JsonDocument doc;
  doc["host"] = c.serverHost;
  doc["port"] = c.serverPort;
  doc["ssid"] = c.wifiSsid;
  doc["pass"] = c.wifiPassword;
  doc["token"] = c.deviceToken;
  std::string out;
  serializeJson(doc, out);
  return out;
}

bool decodeConfig(const std::string &blob, DeviceConfig &out) {
  JsonDocument doc;
  if (deserializeJson(doc, blob) != DeserializationError::Ok) return false;
  out.serverHost = doc["host"].as<std::string>();
  out.serverPort = doc["port"].is<uint16_t>() ? doc["port"].as<uint16_t>() : 443;
  out.wifiSsid = doc["ssid"].as<std::string>();
  out.wifiPassword = doc["pass"].as<std::string>();
  out.deviceToken = doc["token"].as<std::string>();
  return true;
}

}  // namespace nb
