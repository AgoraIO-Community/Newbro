#include <M5Cardputer.h>
#include "transport/HttpsTransport.h"

void setup() {
  auto cfg = M5.config();
  M5Cardputer.begin(cfg, true);  // true => enable keyboard
  M5Cardputer.Display.setTextSize(2);
  M5Cardputer.Display.print("newbro");
  static nb::HttpsTransport probe("example.com", 443);
  (void)probe;
}

void loop() {
  M5Cardputer.update();
  delay(5);
}
