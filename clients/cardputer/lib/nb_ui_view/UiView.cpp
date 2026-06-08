#include "UiView.h"

namespace nb {

GlyphKind glyphKindFor(const std::string &avatar) {
  if (avatar == "rabbit") return GlyphKind::Rabbit;
  if (avatar == "cat") return GlyphKind::Cat;
  if (avatar == "fox") return GlyphKind::Fox;
  return GlyphKind::Person;
}

bool isTurnActive(const std::string &status) {
  return status == "running" || status == "pending";
}

const char *phaseLabel(Phase phase) {
  switch (phase) {
    case Phase::Recording: return "listening";
    case Phase::Transcribing: return "transcribing";
    case Phase::Streaming: return "thinking";
    case Phase::Idle:
    default: return "hold to talk";
  }
}

}  // namespace nb
