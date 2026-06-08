#pragma once
#include <ArduinoJson.h>
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

  // GET `path` and deserialize the response into `out` using `filter` (so only the
  // wanted fields are kept). `status` receives the HTTP status (0 on transport
  // failure). Returns true only on a 200 that parsed cleanly.
  //
  // The default buffers the whole body via request() then parses the string —
  // fine for tests and small responses. HttpsTransport overrides this to parse
  // the chunk-decoded body directly, so the large (chunked) session snapshot is
  // never copied whole into RAM, which OOMs this no-PSRAM device.
  virtual bool getFiltered(const std::string &path, const std::string &cookieToken,
                           const JsonDocument &filter, JsonDocument &out, int &status) {
    HttpResponse r = request("GET", path, "", cookieToken);
    status = r.transportOk ? r.status : 0;
    if (!r.transportOk || r.status != 200) return false;
    return deserializeJson(out, r.body, DeserializationOption::Filter(filter)) == DeserializationError::Ok;
  }
};

}  // namespace nb
