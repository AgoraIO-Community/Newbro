#include "transport/HttpsTransport.h"

#include <HTTPClient.h>
#include <WiFiClientSecure.h>

// Arduino-ESP32 built-in Mozilla root CA bundle (linked from the core).
extern const uint8_t rootca_crt_bundle_start[] asm("_binary_data_cert_x509_crt_bundle_bin_start");

namespace nb {

HttpResponse HttpsTransport::request(const std::string &method, const std::string &path,
                                     const std::string &body, const std::string &cookieToken) {
  HttpResponse out;
  WiFiClientSecure client;
  client.setCACertBundle(rootca_crt_bundle_start);

  HTTPClient https;
  std::string url = "https://" + host_ + ":" + std::to_string(port_) + path;
  if (!https.begin(client, url.c_str())) {
    out.transportOk = false;
    return out;
  }
  https.addHeader("Content-Type", "application/json");
  if (!cookieToken.empty()) {
    https.addHeader("Cookie", ("newbro_session=" + cookieToken).c_str());
  }

  int code;
  if (method == "POST") {
    code = https.POST((uint8_t *)body.data(), body.size());
  } else {
    code = https.GET();
  }

  if (code <= 0) {
    out.transportOk = false;  // negative = client/connection error
  } else {
    out.transportOk = true;
    out.status = code;
    out.body = std::string(https.getString().c_str());
  }
  https.end();
  return out;
}

}  // namespace nb
