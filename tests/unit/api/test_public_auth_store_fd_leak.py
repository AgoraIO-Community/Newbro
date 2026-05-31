"""Regression test: PublicAuthStore must not leak SQLite connections (file descriptors).

A `sqlite3.Connection` used as a context manager (`with conn:`) only manages the
transaction -- it does NOT close the connection. The store previously relied on
garbage collection to reap connections, but Connection/Cursor form reference
cycles, so under load file descriptors piled up until the worker hit its open-file
limit and every `sqlite3.connect()` failed with "unable to open database file".

We disable the cyclic GC during measurement so the check is deterministic: if
connections are released only via cycle collection, the descriptor count grows;
once `_connect` closes them explicitly, the count stays flat regardless of GC.
"""

from __future__ import annotations

import gc
import os

import pytest

from newbro.api.public_auth import PublicAuthStore


def _fd_dir() -> str | None:
    for path in ("/proc/self/fd", "/dev/fd"):
        if os.path.isdir(path):
            return path
    return None


def _open_fd_count(fd_dir: str) -> int:
    return len(os.listdir(fd_dir))


@pytest.mark.anyio
async def test_user_for_token_does_not_leak_connections(tmp_path):
    fd_dir = _fd_dir()
    if fd_dir is None:
        pytest.skip("no per-process fd directory available on this platform")

    store = PublicAuthStore(path=tmp_path / "public_auth.sqlite3")

    gc_was_enabled = gc.isenabled()
    gc.disable()
    try:
        # Warm up: first calls may allocate caches / steady-state descriptors.
        for _ in range(5):
            await store.user_for_token("missing-token")

        before = _open_fd_count(fd_dir)
        for _ in range(100):
            await store.user_for_token("missing-token")
        after = _open_fd_count(fd_dir)
    finally:
        if gc_was_enabled:
            gc.enable()

    grew_by = after - before
    assert grew_by <= 5, f"PublicAuthStore leaked ~{grew_by} file descriptors over 100 queries"
