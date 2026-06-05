#include "AudioMeta.h"

namespace nb {

AudioMeta computeAudioMeta(uint32_t samplesPerChannel, uint32_t sampleRate, uint8_t numChannels) {
  AudioMeta m;
  m.sampleRate = sampleRate;
  m.numChannels = numChannels;
  m.samplesPerChannel = samplesPerChannel;
  m.byteLen = samplesPerChannel * static_cast<uint32_t>(numChannels) * 2u;
  m.durationMs = sampleRate == 0
                     ? 0
                     : static_cast<uint32_t>((static_cast<uint64_t>(samplesPerChannel) * 1000ull) / sampleRate);
  return m;
}

}  // namespace nb
