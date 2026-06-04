#include "audio/MicRecorder.h"

#include <M5Cardputer.h>
#include <esp_heap_caps.h>

namespace nb {

bool MicRecorder::beginRecording() {
  count_ = 0;
  if (buffer_ == nullptr) {
    buffer_ = static_cast<int16_t *>(
        heap_caps_malloc(kMaxSamples * sizeof(int16_t), MALLOC_CAP_SPIRAM));
    if (buffer_ == nullptr) return false;  // no PSRAM available
  }
  M5Cardputer.Speaker.end();  // mic and speaker can't run together
  M5Cardputer.Mic.begin();
  return true;
}

void MicRecorder::poll() {
  if (buffer_ == nullptr || !M5Cardputer.Mic.isEnabled() || count_ >= kMaxSamples) return;
  static constexpr size_t kChunk = 256;
  size_t room = kMaxSamples - count_;
  size_t want = room < kChunk ? room : kChunk;
  if (M5Cardputer.Mic.record(buffer_ + count_, want, kSampleRate)) {
    count_ += want;
  }
}

void MicRecorder::endRecording() { M5Cardputer.Mic.end(); }

}  // namespace nb
