#pragma once
#include <cstdint>

namespace nb {

class Backoff {
 public:
  Backoff(uint32_t baseMs, uint32_t maxMs) : base_(baseMs), max_(maxMs), cur_(baseMs) {}
  uint32_t current() const { return cur_; }
  void reset() { cur_ = base_; }
  // Return the current delay, then advance (doubling, capped at max).
  uint32_t next();

 private:
  uint32_t base_;
  uint32_t max_;
  uint32_t cur_;
};

}  // namespace nb
