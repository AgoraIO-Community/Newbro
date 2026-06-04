#pragma once
#include <string>
#include <vector>

namespace nb {

int listScrollTop(int selected, int count, int rows);
int moveSelection(int current, int count, int delta);
std::string truncate(const std::string &text, int maxChars);
std::vector<std::string> wrapLines(const std::string &text, int maxChars, int maxLines);

}  // namespace nb
