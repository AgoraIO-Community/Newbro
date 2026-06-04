#include <M5Cardputer.h>

#include <string>
#include <vector>

#include "AudioMeta.h"
#include "Backoff.h"
#include "Config.h"
#include "NewbroClient.h"
#include "Pairing.h"
#include "SessionJson.h"
#include "UiView.h"
#include "audio/MicRecorder.h"
#include "net/WifiManager.h"
#include "store/ConfigStore.h"
#include "transport/HttpsTransport.h"
#include "ui/BroListScreen.h"
#include "ui/ChatScreen.h"
#include "ui/Router.h"
#include "ui/TextScreen.h"

namespace {

nb::ConfigStore g_store;
nb::WifiManager g_wifi;
nb::DeviceConfig g_config;
nb::MicRecorder g_mic;

nb::Router g_router;
nb::BroListScreen g_listScreen;
nb::ChatScreen g_chatScreen;

nb::NewbroClient *g_clientPtr = nullptr;
std::string g_sessionId;
std::vector<nb::Persona> g_personas;
nb::Persona g_activeBro;
bool g_inChat = false;

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
  g_config.serverHost = promptLine("Server host", false);
  g_config.serverPort = 443;
  g_store.save(g_config);
}

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
  nb::screen::pairingCode(machine.userCode(), "Enter this code in newbro -> Account -> Devices");
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

void renderOnce() { g_router.tick(); }

void runVoiceTurn() {
  g_chatScreen.setPhase(nb::Phase::Recording);
  g_chatScreen.setReply("");
  renderOnce();
  if (!g_mic.beginRecording()) {
    g_chatScreen.setReply("mic unavailable");
    g_chatScreen.setPhase(nb::Phase::Idle);
    return;
  }
  while (true) {
    M5Cardputer.update();
    g_mic.poll();
    renderOnce();
    if (!M5Cardputer.Keyboard.isPressed()) break;
    delay(5);
  }
  g_mic.endRecording();
  if (g_mic.sampleCount() == 0) {
    g_chatScreen.setPhase(nb::Phase::Idle);
    return;
  }

  g_chatScreen.setPhase(nb::Phase::Transcribing);
  renderOnce();
  nb::AudioMeta meta = nb::computeAudioMeta(g_mic.sampleCount(), nb::MicRecorder::kSampleRate, 1);
  std::string transcript;
  if (!g_clientPtr->sendAudio(g_sessionId, g_activeBro.id, meta,
                              reinterpret_cast<const uint8_t *>(g_mic.data()), meta.byteLen, transcript)) {
    g_chatScreen.setReply(g_clientPtr->lastError());
    g_chatScreen.setPhase(nb::Phase::Idle);
    return;
  }
  g_chatScreen.setTranscript(transcript);

  g_chatScreen.setPhase(nb::Phase::Streaming);
  for (int i = 0; i < 60; ++i) {
    for (int f = 0; f < 20; ++f) { renderOnce(); delay(50); }
    M5Cardputer.update();
    nb::TurnView v;
    if (g_clientPtr->getReply(g_sessionId, g_activeBro.id, v) && v.found) {
      g_chatScreen.setReply(v.assistantText);
      if (!nb::isTurnActive(v.status)) break;
    }
  }
  g_chatScreen.setPhase(nb::Phase::Idle);
}

void openChat(const nb::Persona &bro) {
  g_activeBro = bro;
  g_chatScreen.setBro(bro);
  g_chatScreen.setTranscript("");
  g_chatScreen.setReply("");
  g_chatScreen.setPhase(nb::Phase::Idle);
  g_inChat = true;
  g_router.setScreen(&g_chatScreen);
}

void backToList() {
  g_inChat = false;
  g_router.setScreen(&g_listScreen);
}

}  // namespace

void setup() {
  auto cfg = M5.config();
  M5Cardputer.begin(cfg, true);
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

  static nb::HttpsTransport g_transport(g_config.serverHost, g_config.serverPort);
  static nb::NewbroClient g_client(g_transport);
  g_client.setAuthToken(g_config.deviceToken);
  g_clientPtr = &g_client;

  nb::Bootstrap boot;
  if (!g_client.bootstrap(boot)) {
    nb::screen::status("Bootstrap failed", g_client.lastError());
    return;
  }
  g_sessionId = boot.sessionId;
  if (!g_client.listPersonas(g_sessionId, g_personas) || g_personas.empty()) {
    nb::screen::status("No bros yet", "add a bro in the newbro app, then reboot");
    return;
  }

  g_router.begin();
  g_listScreen.setBros(g_personas);
  g_listScreen.onOpen(openChat);
  g_chatScreen.onBack(backToList);

  for (size_t i = 0; i < g_personas.size(); ++i) {
    if (g_personas[i].id == boot.defaultPersonaId) {
      for (size_t k = 0; k < i; ++k) g_listScreen.onKey(nb::Key::Down);
      break;
    }
  }

  g_router.setScreen(&g_listScreen);
}

void loop() {
  M5Cardputer.update();
  nb::Key key = g_router.readKey();

  if (g_inChat) {
    if (key == nb::Key::Back) {
      g_chatScreen.onKey(nb::Key::Back);
    } else if (M5Cardputer.Keyboard.isChange() && M5Cardputer.Keyboard.isPressed() && key == nb::Key::None) {
      runVoiceTurn();
    }
  } else if (key != nb::Key::None) {
    g_listScreen.onKey(key);
  }

  g_router.tick();
  delay(5);
}
