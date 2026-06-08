#pragma once
#include <cstddef>
#include <cstdint>

namespace nb {

// Fixed-capacity mono PCM16 capture buffer for push-to-talk.
// The Cardputer (StampS3) has NO PSRAM, so the buffer lives in internal SRAM and
// must stay small enough to coexist with the 64 KB UI canvas + Wi-Fi/TLS. At
// 16 kHz mono int16, 5 s = 160 KB. Tune kMaxSamples from the on-device heap log.
class MicRecorder {
 public:
  static constexpr uint32_t kSampleRate = 16000;
  // 3 s cap (96 KB internal RAM). Smaller upload = less exposed to packet loss on
  // flaky Wi-Fi, and leaves more headroom before the TLS upload than 4 s did.
  static constexpr size_t kMaxSamples = kSampleRate * 3;

  bool beginRecording();   // allocate (once) + start mic + reset; false if RAM alloc failed
  void poll();             // capture available samples (call frequently while held)
  void endRecording();     // stop mic
  const int16_t *data() const { return buffer_; }
  size_t sampleCount() const { return count_; }

 private:
  int16_t *buffer_ = nullptr;
  size_t count_ = 0;
};

}  // namespace nb
