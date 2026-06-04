#pragma once
#include <string>

namespace nb {

// Minimal full-screen text helpers for Plan A (replaced by the Ink UI in Plan C).
namespace screen {
void title(const std::string &line);                               // big title
void status(const std::string &title, const std::string &detail);  // title + small detail
void pairingCode(const std::string &code, const std::string &hint);
}  // namespace screen

}  // namespace nb
