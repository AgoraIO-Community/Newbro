#include "Backoff.h"

namespace nb {

uint32_t Backoff::next() {
  uint32_t value = cur_;
  uint32_t doubled = cur_ >= max_ ? max_ : cur_ * 2;
  cur_ = doubled > max_ ? max_ : doubled;
  return value;
}

}  // namespace nb
