#include <unity.h>
#include "AudioMeta.h"

using namespace nb;

void test_mono_one_second(void) {
  AudioMeta m = computeAudioMeta(/*samplesPerChannel=*/16000, /*sampleRate=*/16000, /*numChannels=*/1);
  TEST_ASSERT_EQUAL_UINT32(16000, m.samplesPerChannel);
  TEST_ASSERT_EQUAL_UINT32(16000, m.sampleRate);
  TEST_ASSERT_EQUAL_UINT8(1, m.numChannels);
  TEST_ASSERT_EQUAL_UINT32(1000, m.durationMs);
  TEST_ASSERT_EQUAL_UINT32(32000, m.byteLen);  // 16000 * 1 * 2
}

void test_half_second(void) {
  AudioMeta m = computeAudioMeta(8000, 16000, 1);
  TEST_ASSERT_EQUAL_UINT32(500, m.durationMs);
  TEST_ASSERT_EQUAL_UINT32(16000, m.byteLen);
}

void test_duration_rounds(void) {
  AudioMeta m = computeAudioMeta(17000, 16000, 1);
  TEST_ASSERT_EQUAL_UINT32(1062, m.durationMs);
  TEST_ASSERT_EQUAL_UINT32(34000, m.byteLen);
}

int main(int, char **) {
  UNITY_BEGIN();
  RUN_TEST(test_mono_one_second);
  RUN_TEST(test_half_second);
  RUN_TEST(test_duration_rounds);
  return UNITY_END();
}
