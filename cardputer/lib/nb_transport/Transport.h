#pragma once
#include <cstddef>
#include <cstdint>
#include <string>

namespace nb {

struct HttpResponse {
  bool transportOk = false;  // true if a response was received at all
  int status = 0;            // HTTP status code (valid when transportOk)
  std::string body;
};

class Transport {
 public:
  virtual ~Transport() = default;
  // method: "GET" or "POST". path is server-relative, e.g. "/api/devices/pair/start".
  // body is sent for POST (ignored otherwise). cookieToken, when non-empty, is sent
  // as the header "Cookie: newbro_session=<cookieToken>".
  virtual HttpResponse request(const std::string &method, const std::string &path,
                               const std::string &body, const std::string &cookieToken) = 0;

  // POST raw bytes with an explicit Content-Type (e.g. "audio/pcm").
  // cookieToken, when non-empty, is sent as "Cookie: newbro_session=<cookieToken>".
  virtual HttpResponse postBytes(const std::string &path, const std::string &contentType,
                                 const uint8_t *body, size_t len, const std::string &cookieToken) = 0;
};

}  // namespace nb
