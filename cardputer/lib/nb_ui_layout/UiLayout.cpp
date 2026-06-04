#include "UiLayout.h"

namespace nb {

int listScrollTop(int selected, int count, int rows) {
  if (count <= rows || selected < rows) return 0;
  int top = selected - rows + 1;
  int maxTop = count - rows;
  if (top > maxTop) top = maxTop;
  if (top < 0) top = 0;
  return top;
}

int moveSelection(int current, int count, int delta) {
  if (count <= 0) return 0;
  int next = current + delta;
  if (next < 0) next = 0;
  if (next > count - 1) next = count - 1;
  return next;
}

std::string truncate(const std::string &text, int maxChars) {
  if (static_cast<int>(text.size()) <= maxChars) return text;
  if (maxChars <= 3) return "...";
  return text.substr(0, maxChars - 3) + "...";
}

std::vector<std::string> wrapLines(const std::string &text, int maxChars, int maxLines) {
  std::vector<std::string> lines;
  std::string line;
  size_t i = 0;
  while (i < text.size()) {
    while (i < text.size() && text[i] == ' ') ++i;
    size_t start = i;
    while (i < text.size() && text[i] != ' ') ++i;
    std::string word = text.substr(start, i - start);
    if (word.empty()) continue;
    if (line.empty()) {
      line = word;
    } else if (static_cast<int>(line.size() + 1 + word.size()) <= maxChars) {
      line += " " + word;
    } else {
      lines.push_back(line);
      line = word;
      if (static_cast<int>(lines.size()) == maxLines) break;
    }
  }
  if (static_cast<int>(lines.size()) < maxLines && !line.empty()) {
    lines.push_back(line);
  }
  bool overflowed = i < text.size();
  if (overflowed && !lines.empty()) {
    std::string &last = lines.back();
    if (static_cast<int>(last.size()) > maxChars - 3 && maxChars > 3) {
      last = last.substr(0, maxChars - 3);
    }
    last += "...";
  }
  return lines;
}

}  // namespace nb
