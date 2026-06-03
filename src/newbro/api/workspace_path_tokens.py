from __future__ import annotations

import re

# An absolute-path token begins at a boundary — string start, whitespace, or an
# opening bracket/brace/angle/quote/backtick (so a path inside a markdown link
# ``](/abs/path)``, parentheses, quotes, or backticks is detected) — starts with
# ``/`` and runs until whitespace or a closing bracket/brace/angle/quote/backtick.
# A relative path (``out/x``) is not matched because its ``/`` follows a word
# character, and a URL (``https://...``) is not matched because its ``//`` follows
# ``:``.
_PATH_TOKEN_RE = re.compile(r"""(?:^|(?<=[\s(\[{<"'`]))(/[^\s()\[\]{}<>"'`]*)""")
# Sentence punctuation stripped from a token's trailing edge.
_TRAILING = ".,;:!?"


def extract_path_tokens(text: str | None) -> set[str]:
    """Absolute-path tokens present in ``text`` per the shared grammar.

    Detects absolute POSIX paths written bare, in backticks/quotes/parentheses,
    or as a markdown link target ``[label](/abs/path)``. Relative paths and URLs
    are not detected; trailing sentence punctuation is stripped; paths containing
    spaces are not detected (V1).
    """
    if not text:
        return set()
    tokens: set[str] = set()
    for match in _PATH_TOKEN_RE.finditer(text):
        token = match.group(1).rstrip(_TRAILING)
        if token and "\x00" not in token:
            tokens.add(token)
    return tokens
