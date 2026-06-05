#pragma once
#include <cstdint>
#include <string>
#include "Transport.h"

namespace nb {

// TLS transport for a public HTTPS newbro deployment. Verifies the server
// certificate against the Arduino-ESP32 built-in Mozilla root-CA bundle.
class HttpsTransport : public Transport {
 public:
  HttpsTransport(std::string host, uint16_t port) : host_(std::move(host)), port_(port) {}
  HttpResponse request(const std::string &method, const std::string &path,
                       const std::string &body, const std::string &cookieToken) override;

 private:
  std::string host_;
  uint16_t port_;
};

}  // namespace nb
