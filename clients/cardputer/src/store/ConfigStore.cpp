#include "store/ConfigStore.h"

#include <Preferences.h>

namespace nb {

static const char *kNamespace = "newbro";
static const char *kKey = "cfg";

bool ConfigStore::load(DeviceConfig &out) {
  Preferences prefs;
  prefs.begin(kNamespace, /*readOnly=*/true);
  String blob = prefs.getString(kKey, "");
  prefs.end();
  if (blob.isEmpty()) return false;
  return decodeConfig(std::string(blob.c_str()), out);
}

void ConfigStore::save(const DeviceConfig &c) {
  Preferences prefs;
  prefs.begin(kNamespace, /*readOnly=*/false);
  prefs.putString(kKey, encodeConfig(c).c_str());
  prefs.end();
}

void ConfigStore::clear() {
  Preferences prefs;
  prefs.begin(kNamespace, /*readOnly=*/false);
  prefs.remove(kKey);
  prefs.end();
}

}  // namespace nb
