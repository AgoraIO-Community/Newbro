#include "Backoff.h"

namespace nb {

uint32_t Backoff::next() {
  uint32_t value = cur_;
  cur_ = cur_ > max_ / 2 ? max_ : cur_ * 2;
  if (cur_ > max_) cur_ = max_;
  return value;
}

}  // namespace nb
