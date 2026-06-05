#include <M5Cardputer.h>

#include <string>

#include "Backoff.h"
#include "Config.h"
#include "NewbroClient.h"
#include "Pairing.h"
#include "net/WifiManager.h"
#include "store/ConfigStore.h"
#include "transport/HttpsTransport.h"
#include "ui/TextScreen.h"

namespace {

nb::ConfigStore g_store;
nb::WifiManager g_wifi;
nb::DeviceConfig g_config;

// Blocking on-keyboard line entry. `mask` hides characters (for passwords).
std::string promptLine(const std::string &label, bool mask) {
  std::string buffer;
  nb::screen::status(label, "type, then Enter");
  for (;;) {
    M5Cardputer.update();
    if (M5Cardputer.Keyboard.isChange() && M5Cardputer.Keyboard.isPressed()) {
      auto st = M5Cardputer.Keyboard.keysState();
      for (auto c : st.word) buffer += c;
      if (st.del && !buffer.empty()) buffer.pop_back();
      if (st.enter && !buffer.empty()) break;
      std::string shown = mask ? std::string(buffer.size(), '*') : buffer;
      nb::screen::status(label, shown.empty() ? "type, then Enter" : shown);
    }
    delay(5);
  }
  return buffer;
}

void runFirstRunSetupIfNeeded() {
  if (g_config.hasWifi() && g_config.hasServer()) return;
  g_config.wifiSsid = promptLine("Wi-Fi name", false);
  g_config.wifiPassword = promptLine("Wi-Fi password", true);
  g_config.serverHost = promptLine("Server host", false);  // e.g. newbro.example.com
  g_config.serverPort = 443;
  g_store.save(g_config);
}

// Returns true once paired (token stored), false on a terminal failure.
bool runPairing() {
  nb::HttpsTransport transport(g_config.serverHost, g_config.serverPort);
  nb::NewbroClient client(transport);
  nb::PairingMachine machine;
  nb::Backoff retry(2000, 30000);

  machine.begin();
  nb::PairStart start;
  while (!client.startPairing(start)) {
    nb::screen::status("Pairing", client.lastError());
    delay(retry.next());
  }
  machine.onStart(start);
  retry.reset();

  uint32_t intervalMs = (start.interval > 0 ? start.interval : 2) * 1000U;
  nb::screen::pairingCode(machine.userCode(),
                          "Enter this code in newbro -> Account -> Devices");

  while (machine.state() == nb::PairState::Polling) {
    delay(intervalMs);
    M5Cardputer.update();
    nb::PollResult poll;
    if (!client.pollPairing(machine.deviceCode(), poll)) {
      nb::screen::status("Pairing", client.lastError());
      delay(retry.next());
      continue;
    }
    machine.onPoll(poll);
  }

  if (machine.state() == nb::PairState::Claimed) {
    g_config.deviceToken = machine.token();
    g_store.save(g_config);
    return true;
  }
  return false;
}

}  // namespace

void setup() {
  auto cfg = M5.config();
  M5Cardputer.begin(cfg, true);  // enable keyboard
  M5Cardputer.Display.setRotation(1);

  nb::screen::title("newbro");
  delay(600);

  g_store.load(g_config);  // populates g_config if present
  runFirstRunSetupIfNeeded();

  nb::screen::status("Connecting", g_config.wifiSsid);
  g_wifi.begin(g_config.wifiSsid, g_config.wifiPassword);
  if (!g_wifi.waitForConnection(20000)) {
    nb::screen::status("Wi-Fi failed", "check credentials, reboot to retry");
    return;
  }

  if (!g_config.hasToken()) {
    if (!runPairing()) {
      nb::screen::status("Pairing failed", "reboot to retry");
      return;
    }
  }

  nb::screen::status("Ready", "paired - conversation UI coming in Plan B/C");
}

void loop() {
  M5Cardputer.update();
  delay(5);
}
