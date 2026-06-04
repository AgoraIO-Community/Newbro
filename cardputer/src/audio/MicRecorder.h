#pragma once
#include <cstddef>
#include <cstdint>

namespace nb {

// Fixed-capacity mono PCM16 capture buffer for push-to-talk.
class MicRecorder {
 public:
  static constexpr uint32_t kSampleRate = 16000;
  static constexpr size_t kMaxSamples = kSampleRate * 10;  // 10 s cap

  void beginRecording();   // start mic, reset buffer
  void poll();             // capture available samples (call frequently while held)
  void endRecording();     // stop mic
  const int16_t *data() const { return buffer_; }
  size_t sampleCount() const { return count_; }

 private:
  int16_t buffer_[kMaxSamples];
  size_t count_ = 0;
};

}  // namespace nb
