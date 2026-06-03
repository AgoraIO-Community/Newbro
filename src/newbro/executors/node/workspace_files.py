from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

DEFAULT_MAX_BYTES = 100 * 1024 * 1024  # 100 MB
CHUNK_BYTES = 256 * 1024  # 256 KB


class WorkspaceFileAccessError(Exception):
    """Raised when a workspace file cannot be released. ``code`` is one of
    'denied' | 'not_found' | 'too_large' | 'read_error'."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def resolve_within_workspace(path: str, workspace_root: str) -> Path:
    """Resolve ``path`` and assert it is a regular file inside ``workspace_root``.

    Symlinks are resolved before the containment check, so a symlink inside the
    workspace that points outside is denied. ``..`` traversal and absolute
    escapes are denied.
    """
    root = Path(os.path.realpath(workspace_root))
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    real = Path(os.path.realpath(candidate))

    if real != root and root not in real.parents:
        raise WorkspaceFileAccessError("denied", "path resolves outside the workspace")
    if not real.exists():
        raise WorkspaceFileAccessError("not_found", "file does not exist")
    if not real.is_file():
        raise WorkspaceFileAccessError("denied", "path is not a regular file")
    return real


def iter_file_bytes(
    real: Path,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    chunk_bytes: int = CHUNK_BYTES,
) -> Iterator[bytes]:
    """Yield ``real`` in ``chunk_bytes`` blocks, raising 'too_large' if it
    exceeds ``max_bytes``."""
    size = real.stat().st_size
    if size > max_bytes:
        raise WorkspaceFileAccessError("too_large", f"file exceeds {max_bytes} bytes")
    try:
        with real.open("rb") as handle:
            while True:
                block = handle.read(chunk_bytes)
                if not block:
                    break
                yield block
    except OSError as exc:  # pragma: no cover - surfaced as read_error
        raise WorkspaceFileAccessError("read_error", str(exc)) from exc
