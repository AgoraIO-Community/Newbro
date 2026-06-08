#include "net/WifiManager.h"

#include <WiFi.h>

namespace nb {

void WifiManager::begin(const std::string &ssid, const std::string &password) {
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid.c_str(), password.c_str());
}

bool WifiManager::isConnected() const { return WiFi.status() == WL_CONNECTED; }

bool WifiManager::waitForConnection(uint32_t timeoutMs) {
  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED && (millis() - start) < timeoutMs) {
    delay(100);
  }
  return WiFi.status() == WL_CONNECTED;
}

}  // namespace nb
