#include "ui/TextScreen.h"

#include <M5Cardputer.h>

namespace nb {
namespace screen {

static void clear() {
  M5Cardputer.Display.fillScreen(TFT_BLACK);
  M5Cardputer.Display.setTextColor(TFT_WHITE, TFT_BLACK);
  M5Cardputer.Display.setCursor(8, 8);
}

void title(const std::string &line) {
  clear();
  M5Cardputer.Display.setTextSize(3);
  M5Cardputer.Display.print(line.c_str());
}

void status(const std::string &title, const std::string &detail) {
  clear();
  M5Cardputer.Display.setTextSize(2);
  M5Cardputer.Display.println(title.c_str());
  M5Cardputer.Display.setTextSize(1);
  M5Cardputer.Display.setCursor(8, 40);
  M5Cardputer.Display.print(detail.c_str());
}

void pairingCode(const std::string &code, const std::string &hint) {
  clear();
  M5Cardputer.Display.setTextSize(1);
  M5Cardputer.Display.println("PAIR THIS DEVICE");
  M5Cardputer.Display.setTextSize(4);
  M5Cardputer.Display.setCursor(8, 28);
  M5Cardputer.Display.println(code.c_str());
  M5Cardputer.Display.setTextSize(1);
  M5Cardputer.Display.setCursor(8, 86);
  M5Cardputer.Display.print(hint.c_str());
}

}  // namespace screen
}  // namespace nb
