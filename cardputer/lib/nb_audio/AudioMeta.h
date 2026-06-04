#pragma once
#include <cstdint>

namespace nb {

struct AudioMeta {
  uint32_t sampleRate;
  uint8_t numChannels;
  uint32_t samplesPerChannel;
  uint32_t durationMs;
  uint32_t byteLen;  // samplesPerChannel * numChannels * 2
};

// Compute the metadata the server requires for an executor-audio-instruction.
AudioMeta computeAudioMeta(uint32_t samplesPerChannel, uint32_t sampleRate, uint8_t numChannels);

}  // namespace nb
