#pragma once
#include "Config.h"

namespace nb {

// Loads/saves the device config as a JSON blob under one NVS key.
class ConfigStore {
 public:
  // Returns true if a config blob was present and decoded.
  bool load(DeviceConfig &out);
  void save(const DeviceConfig &c);
  void clear();
};

}  // namespace nb
