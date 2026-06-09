"""Canonical list of executor families Newbro can run as detached nodes.

Single source of truth: the node registry, both CLI argparse parsers, the
interactive setup path, and runtime settings all reference this tuple so they
cannot drift apart.
"""

from __future__ import annotations

SUPPORTED_EXECUTOR_FAMILIES: tuple[str, ...] = ("codex", "acpx", "hermes")

# Families with a meaningful local readiness probe (binary presence/version).
# ACPX is run-only: no probe, no start-readiness gate.
PROBEABLE_EXECUTOR_FAMILIES: tuple[str, ...] = ("codex", "hermes")
