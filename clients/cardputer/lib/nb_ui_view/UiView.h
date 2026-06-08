#pragma once
#include <string>

namespace nb {

enum class GlyphKind { Rabbit, Cat, Fox, Person };
enum class Phase { Idle, Recording, Transcribing, Streaming };

GlyphKind glyphKindFor(const std::string &avatar);
bool isTurnActive(const std::string &status);
const char *phaseLabel(Phase phase);

}  // namespace nb
