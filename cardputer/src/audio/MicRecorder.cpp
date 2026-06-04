#include "audio/MicRecorder.h"

#include <M5Cardputer.h>

namespace nb {

void MicRecorder::beginRecording() {
  count_ = 0;
  M5Cardputer.Speaker.end();  // mic and speaker can't run together
  M5Cardputer.Mic.begin();
}

void MicRecorder::poll() {
  if (!M5Cardputer.Mic.isEnabled() || count_ >= kMaxSamples) return;
  static constexpr size_t kChunk = 256;
  size_t room = kMaxSamples - count_;
  size_t want = room < kChunk ? room : kChunk;
  if (M5Cardputer.Mic.record(buffer_ + count_, want, kSampleRate)) {
    count_ += want;
  }
}

void MicRecorder::endRecording() { M5Cardputer.Mic.end(); }

}  // namespace nb
