#pragma once
#include <cstdint>
#include <string>

namespace nb {

struct DeviceConfig {
  std::string serverHost;
  uint16_t serverPort = 443;
  std::string wifiSsid;
  std::string wifiPassword;
  std::string deviceToken;

  bool hasWifi() const { return !wifiSsid.empty(); }
  bool hasServer() const { return !serverHost.empty(); }
  bool hasToken() const { return !deviceToken.empty(); }
  bool isReady() const { return hasWifi() && hasServer() && hasToken(); }
};

// Serialize to / parse from a compact JSON blob (stored in NVS).
std::string encodeConfig(const DeviceConfig &c);
bool decodeConfig(const std::string &blob, DeviceConfig &out);

}  // namespace nb
