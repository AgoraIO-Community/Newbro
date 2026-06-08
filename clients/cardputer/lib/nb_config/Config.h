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

// Optional compile-time defaults (from a flashed DeviceSecrets.h). An empty
// string / zero port means "not set" and leaves the stored value in place.
struct DeviceDefaults {
  std::string wifiSsid;
  std::string wifiPassword;
  std::string serverHost;
  uint16_t serverPort = 0;
};

// Overlay defaults onto a stored config: defaults win for non-empty Wi-Fi/server
// fields; the device token is always kept from `stored`.
DeviceConfig mergeDefaults(const DeviceConfig &stored, const DeviceDefaults &defaults);

}  // namespace nb
