#include <M5Cardputer.h>

#include <string>
#include <vector>

#include "AudioMeta.h"
#include "Backoff.h"
#include "Config.h"
#include "NewbroClient.h"
#include "Pairing.h"
#include "SessionJson.h"
#include "audio/MicRecorder.h"
#include "net/WifiManager.h"
#include "store/ConfigStore.h"
#include "transport/HttpsTransport.h"
#include "ui/BroGlyph.h"
#include "ui/TextScreen.h"
#include "ui/Theme.h"

namespace {

nb::ConfigStore g_store;
nb::WifiManager g_wifi;
nb::DeviceConfig g_config;
nb::MicRecorder g_mic;
nb::NewbroClient *g_clientPtr = nullptr;
std::string g_sessionId;
std::string g_personaId;
std::string g_personaName;

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

// One push-to-talk turn: record while a key is held, upload, then poll the reply.
void runVoiceTurn(nb::NewbroClient &client) {
  nb::screen::status(g_personaName, "recording...");
  if (!g_mic.beginRecording()) {
    nb::screen::status(g_personaName, "mic unavailable");
    return;
  }
  while (true) {
    M5Cardputer.update();
    g_mic.poll();
    if (!M5Cardputer.Keyboard.isPressed()) break;
    delay(5);
  }
  g_mic.endRecording();

  if (g_mic.sampleCount() == 0) {
    nb::screen::status(g_personaName, "nothing recorded");
    return;
  }

  nb::AudioMeta meta = nb::computeAudioMeta(g_mic.sampleCount(), nb::MicRecorder::kSampleRate, 1);
  nb::screen::status(g_personaName, "transcribing...");
  std::string transcript;
  if (!client.sendAudio(g_sessionId, g_personaId, meta,
                        reinterpret_cast<const uint8_t *>(g_mic.data()), meta.byteLen, transcript)) {
    nb::screen::status("Send failed", client.lastError());
    return;
  }
  Serial.printf("you: %s\n", transcript.c_str());

  std::string lastShown;
  for (int i = 0; i < 60; ++i) {  // ~60s max at 1s intervals
    delay(1000);
    M5Cardputer.update();
    nb::TurnView v;
    if (client.getReply(g_sessionId, g_personaId, v) && v.found) {
      if (v.assistantText != lastShown) {
        lastShown = v.assistantText;
        nb::screen::status(g_personaName, v.assistantText);
        Serial.printf("%s: %s [%s]\n", g_personaName.c_str(), v.assistantText.c_str(), v.status.c_str());
      }
      if (v.status == "completed" || v.status == "failed" || v.status == "cancelled") break;
    }
  }
}

}  // namespace

void setup() {
  auto cfg = M5.config();
  M5Cardputer.begin(cfg, true);  // enable keyboard
  (void)nb::theme::coral;
  nb::drawBroGlyph(M5Cardputer.Display, nb::GlyphKind::Rabbit, nb::GlyphState::Idle, 120, 67, 16, nb::theme::coral, 0);
  M5Cardputer.Display.setRotation(1);

  nb::screen::title("newbro");
  delay(600);

  g_store.load(g_config);
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

  // --- Conversation bootstrap (Plan B) ---
  static nb::HttpsTransport g_transport(g_config.serverHost, g_config.serverPort);
  static nb::NewbroClient g_client(g_transport);
  g_client.setAuthToken(g_config.deviceToken);

  nb::Bootstrap boot;
  if (!g_client.bootstrap(boot)) {
    nb::screen::status("Bootstrap failed", g_client.lastError());
    return;
  }
  g_sessionId = boot.sessionId;

  std::vector<nb::Persona> personas;
  if (!g_client.listPersonas(g_sessionId, personas) || personas.empty()) {
    nb::screen::status("No bros yet", "add a bro in the newbro app, then reboot");
    return;
  }
  g_personaId = personas[0].id;
  g_personaName = personas[0].name;

  g_clientPtr = &g_client;
  nb::screen::status(g_personaName, "hold a key to talk");
}

void loop() {
  M5Cardputer.update();
  if (g_clientPtr && !g_sessionId.empty() && !g_personaId.empty() &&
      M5Cardputer.Keyboard.isChange() && M5Cardputer.Keyboard.isPressed()) {
    runVoiceTurn(*g_clientPtr);
    nb::screen::status(g_personaName, "hold a key to talk");
  }
  delay(5);
}
