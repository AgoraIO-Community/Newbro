#include <unity.h>
#include "Config.h"

using namespace nb;

void test_predicates(void) {
  DeviceConfig c;
  TEST_ASSERT_FALSE(c.hasWifi());
  TEST_ASSERT_FALSE(c.hasToken());
  TEST_ASSERT_FALSE(c.isReady());
  c.wifiSsid = "home";
  c.serverHost = "newbro.example.com";
  c.deviceToken = "tok";
  TEST_ASSERT_TRUE(c.hasWifi());
  TEST_ASSERT_TRUE(c.hasServer());
  TEST_ASSERT_TRUE(c.hasToken());
  TEST_ASSERT_TRUE(c.isReady());
}

void test_codec_roundtrip(void) {
  DeviceConfig c;
  c.serverHost = "newbro.example.com";
  c.serverPort = 8443;
  c.wifiSsid = "home";
  c.wifiPassword = "s3cret";
  c.deviceToken = "abc.def";

  DeviceConfig back;
  TEST_ASSERT_TRUE(decodeConfig(encodeConfig(c), back));
  TEST_ASSERT_EQUAL_STRING("newbro.example.com", back.serverHost.c_str());
  TEST_ASSERT_EQUAL_UINT16(8443, back.serverPort);
  TEST_ASSERT_EQUAL_STRING("home", back.wifiSsid.c_str());
  TEST_ASSERT_EQUAL_STRING("s3cret", back.wifiPassword.c_str());
  TEST_ASSERT_EQUAL_STRING("abc.def", back.deviceToken.c_str());
}

void test_decode_defaults_port_443(void) {
  DeviceConfig back;
  TEST_ASSERT_TRUE(decodeConfig(R"({"host":"h","ssid":"s"})", back));
  TEST_ASSERT_EQUAL_UINT16(443, back.serverPort);
  TEST_ASSERT_EQUAL_STRING("h", back.serverHost.c_str());
}

void test_decode_rejects_garbage(void) {
  DeviceConfig back;
  TEST_ASSERT_FALSE(decodeConfig("nope", back));
}

int main(int, char **) {
  UNITY_BEGIN();
  RUN_TEST(test_predicates);
  RUN_TEST(test_codec_roundtrip);
  RUN_TEST(test_decode_defaults_port_443);
  RUN_TEST(test_decode_rejects_garbage);
  return UNITY_END();
}
