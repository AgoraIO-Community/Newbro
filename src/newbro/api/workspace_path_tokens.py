from __future__ import annotations

# Wrapping markdown/quote characters stripped from a token's leading edge.
_LEADING = "(<\"'`["
# Sentence punctuation / wrappers stripped from a token's trailing edge.
_TRAILING = ".,;:!?)]}>\"'`"


def extract_path_tokens(text: str | None) -> set[str]:
    """Absolute-path tokens present in ``text`` per the shared grammar.

    A token is a maximal whitespace-delimited run with wrapping
    markdown/quote/punctuation stripped from each edge, that is an absolute
    POSIX path (starts with ``/`` and contains no NUL). Relative paths and
    paths containing spaces are intentionally not detected (V1).
    """
    if not text:
        return set()
    tokens: set[str] = set()
    for raw in text.split():
        token = raw.lstrip(_LEADING).rstrip(_TRAILING)
        if not token or "\x00" in token:
            continue
        if not token.startswith("/"):
            continue
        tokens.add(token)
    return tokens
