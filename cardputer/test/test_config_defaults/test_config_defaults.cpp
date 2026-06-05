#include <unity.h>
#include "Config.h"

using namespace nb;

static DeviceConfig stored() {
  DeviceConfig c;
  c.wifiSsid = "old-ssid";
  c.wifiPassword = "old-pass";
  c.serverHost = "old.example.com";
  c.serverPort = 8443;
  c.deviceToken = "tok-123";
  return c;
}

void test_defaults_win_when_set(void) {
  DeviceDefaults d;
  d.wifiSsid = "new-ssid";
  d.serverHost = "new.example.com";
  DeviceConfig out = mergeDefaults(stored(), d);
  TEST_ASSERT_EQUAL_STRING("new-ssid", out.wifiSsid.c_str());
  TEST_ASSERT_EQUAL_STRING("new.example.com", out.serverHost.c_str());
  TEST_ASSERT_EQUAL_STRING("old-pass", out.wifiPassword.c_str());
  TEST_ASSERT_EQUAL_UINT16(8443, out.serverPort);
}

void test_empty_defaults_keep_stored(void) {
  DeviceDefaults d;
  DeviceConfig out = mergeDefaults(stored(), d);
  TEST_ASSERT_EQUAL_STRING("old-ssid", out.wifiSsid.c_str());
  TEST_ASSERT_EQUAL_STRING("old-pass", out.wifiPassword.c_str());
  TEST_ASSERT_EQUAL_STRING("old.example.com", out.serverHost.c_str());
  TEST_ASSERT_EQUAL_UINT16(8443, out.serverPort);
}

void test_token_never_touched(void) {
  DeviceDefaults d;
  d.wifiSsid = "new-ssid";
  DeviceConfig out = mergeDefaults(stored(), d);
  TEST_ASSERT_EQUAL_STRING("tok-123", out.deviceToken.c_str());
}

void test_port_fallbacks(void) {
  DeviceDefaults d;
  d.serverPort = 9000;
  TEST_ASSERT_EQUAL_UINT16(9000, mergeDefaults(stored(), d).serverPort);

  DeviceConfig out2 = mergeDefaults(stored(), DeviceDefaults{});
  TEST_ASSERT_EQUAL_UINT16(8443, out2.serverPort);

  DeviceConfig s0 = stored();
  s0.serverPort = 0;
  TEST_ASSERT_EQUAL_UINT16(443, mergeDefaults(s0, DeviceDefaults{}).serverPort);
}

int main(int, char **) {
  UNITY_BEGIN();
  RUN_TEST(test_defaults_win_when_set);
  RUN_TEST(test_empty_defaults_keep_stored);
  RUN_TEST(test_token_never_touched);
  RUN_TEST(test_port_fallbacks);
  return UNITY_END();
}
