#include "transport/HttpsTransport.h"

#include <HTTPClient.h>
#include <WiFiClientSecure.h>

#include "transport/RootCa.h"

namespace nb {

namespace {
// On flaky Wi-Fi the TLS handshake intermittently stalls; the peer then closes
// (~18 s) with EOF. Abandon a stalled handshake fast so retries cycle quickly.
constexpr unsigned long kHandshakeTimeoutS = 6;
constexpr int kConnectTimeoutMs = 7000;
constexpr int kGetRetries = 5;

void configClient(WiFiClientSecure &client) {
  client.setCACert(kRootCaPem);
  client.setHandshakeTimeout(kHandshakeTimeoutS);
}
}  // namespace

HttpResponse HttpsTransport::request(const std::string &method, const std::string &path,
                                     const std::string &body, const std::string &cookieToken) {
  // Retry idempotent GETs; POSTs run once (side effects; pairing retries higher up).
  const int attempts = (method == "GET") ? kGetRetries : 1;
  HttpResponse out;
  for (int attempt = 0; attempt < attempts; ++attempt) {
    if (attempt) delay(250);
    out = HttpResponse{};
    WiFiClientSecure client;
    configClient(client);

    HTTPClient https;
    std::string url = "https://" + host_ + ":" + std::to_string(port_) + path;
    if (!https.begin(client, url.c_str())) {
      out.transportOk = false;
      continue;
    }
    https.setConnectTimeout(kConnectTimeoutMs);
    https.addHeader("Content-Type", "application/json");
    if (!cookieToken.empty()) {
      https.addHeader("Cookie", ("newbro_session=" + cookieToken).c_str());
    }

    int code = (method == "POST") ? https.POST((uint8_t *)body.data(), body.size()) : https.GET();
    if (code <= 0) {
      out.transportOk = false;  // negative = client/connection error -> retry (GET)
      https.end();
      continue;
    }
    out.transportOk = true;
    out.status = code;
    out.body = std::string(https.getString().c_str());
    https.end();
    return out;
  }
  return out;
}

HttpResponse HttpsTransport::postBytes(const std::string &path, const std::string &contentType,
                                       const uint8_t *body, size_t len, const std::string &cookieToken) {
  // Retry on code<=0 only: that is a connect/handshake/upload-drop failure (the
  // request never completed at the server), so re-sending the audio can't create a
  // duplicate turn. Audio is the largest transfer and the most exposed to flaky
  // Wi-Fi, so retry more with growing backoff to ride out brief bad windows.
  const int kAudioRetries = 8;
  HttpResponse out;
  for (int attempt = 0; attempt < kAudioRetries; ++attempt) {
    if (attempt) delay(300 * attempt);  // linear backoff: 0.3s, 0.6s, ...
    out = HttpResponse{};
    WiFiClientSecure client;
    configClient(client);

    HTTPClient https;
    std::string url = "https://" + host_ + ":" + std::to_string(port_) + path;
    if (!https.begin(client, url.c_str())) {
      out.transportOk = false;
      continue;
    }
    https.setConnectTimeout(kConnectTimeoutMs);
    https.setTimeout(20000);  // allow a slow 96 KB upload + server processing
    https.addHeader("Content-Type", contentType.c_str());
    if (!cookieToken.empty()) {
      https.addHeader("Cookie", ("newbro_session=" + cookieToken).c_str());
    }
    int code = https.POST(const_cast<uint8_t *>(body), len);
    if (code <= 0) {
      out.transportOk = false;  // connection failed before reaching server -> safe to retry
      https.end();
      continue;
    }
    out.transportOk = true;
    out.status = code;
    out.body = std::string(https.getString().c_str());
    https.end();
    return out;
  }
  return out;
}

bool HttpsTransport::getFiltered(const std::string &path, const std::string &cookieToken,
                                 const JsonDocument &filter, JsonDocument &out, int &status) {
  status = 0;
  for (int attempt = 0; attempt < kGetRetries; ++attempt) {  // GET is idempotent -> retry
    if (attempt) delay(250);
    WiFiClientSecure client;
    configClient(client);

    HTTPClient https;
    std::string url = "https://" + host_ + ":" + std::to_string(port_) + path;
    if (!https.begin(client, url.c_str())) continue;
    https.setConnectTimeout(kConnectTimeoutMs);
    https.addHeader("Content-Type", "application/json");
    if (!cookieToken.empty()) {
      https.addHeader("Cookie", ("newbro_session=" + cookieToken).c_str());
    }

    int code = https.GET();
    if (code <= 0) {
      https.end();
      continue;  // transient connect/handshake failure -> retry
    }
    status = code;
    if (code != 200) {
      https.end();
      return false;
    }

    // Parse the chunk-decoded body through the filter so only the small wanted
    // fields are kept (the response may contain large fields the device skips).
    // NestingLimit must exceed the payload depth: the parser still traverses (and
    // skips) the whole nested document, and the default limit of 10 fails (TooDeep).
    DeserializationError err =
        deserializeJson(out, https.getString(), DeserializationOption::Filter(filter),
                        DeserializationOption::NestingLimit(64));
    https.end();
    return err == DeserializationError::Ok;
  }
  return false;  // status stays 0 -> caller reports "network error"
}

}  // namespace nb
