#pragma once
#include <string>

namespace nb {

class WifiManager {
 public:
  void begin(const std::string &ssid, const std::string &password);
  bool isConnected() const;
  // Blocks up to timeoutMs for a connection; returns connection status.
  bool waitForConnection(uint32_t timeoutMs);
};

}  // namespace nb
