from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CodexProbeResult:
    path: str
    version: str | None
    ok: bool
    error: str | None = None


CODEX_MINIMUM_SUPPORTED_VERSION = (0, 135, 0)
CODEX_MINIMUM_SUPPORTED_VERSION_TEXT = "0.135.0"


def codex_version_tuple(version: str | None) -> tuple[int, int, int] | None:
    if not version:
        return None
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", version)
    if match is None:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def codex_version_supported(version: str | None) -> bool:
    parsed = codex_version_tuple(version)
    return parsed is not None and parsed >= CODEX_MINIMUM_SUPPORTED_VERSION


def unsupported_codex_version_error(version: str | None) -> str:
    display = version or "unknown"
    return (
        f"Codex CLI {display} is below Newbro's minimum supported version "
        f"{CODEX_MINIMUM_SUPPORTED_VERSION_TEXT}."
    )


def discover_codex_commands(*, configured_command: str | None = None) -> list[str]:
    candidates: list[str] = []
    if configured_command:
        candidates.extend(_resolve_command_candidates(configured_command))
    candidates.extend(_which_all("codex"))
    candidates.extend(_login_shell_which_all("codex"))
    home = Path.home()
    candidates.extend(
        [
            str(home / ".bun/bin/codex"),
            str(home / ".local/bin/codex"),
            "/opt/homebrew/bin/codex",
            "/usr/local/bin/codex",
        ]
    )
    return _dedupe_existing_or_configured(candidates, configured_command=configured_command)


def probe_codex_command(command: str) -> CodexProbeResult:
    path = _resolve_command_path(command) or command
    try:
        completed = subprocess.run(
            [path, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except FileNotFoundError:
        return CodexProbeResult(path=path, version=None, ok=False, error="command not found")
    except subprocess.TimeoutExpired:
        return CodexProbeResult(path=path, version=None, ok=False, error="codex --version timed out")
    except Exception as exc:
        return CodexProbeResult(path=path, version=None, ok=False, error=str(exc))
    output = (completed.stdout or completed.stderr or "").strip()
    first_line = output.splitlines()[0].strip() if output else None
    if completed.returncode != 0:
        return CodexProbeResult(
            path=path,
            version=first_line,
            ok=False,
            error=first_line or f"codex --version exited {completed.returncode}",
        )
    if not codex_version_supported(first_line):
        return CodexProbeResult(
            path=path,
            version=first_line,
            ok=False,
            error=unsupported_codex_version_error(first_line),
        )
    return CodexProbeResult(path=path, version=first_line, ok=True)


def _resolve_command_candidates(command: str) -> list[str]:
    if os.path.isabs(command):
        return [command]
    return _which_all(command) or [command]


def _resolve_command_path(command: str) -> str | None:
    if os.path.isabs(command):
        return command
    return shutil.which(command)


def _which_all(command: str) -> list[str]:
    paths: list[str] = []
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if not directory:
            continue
        candidate = Path(directory) / command
        if candidate.exists() and os.access(candidate, os.X_OK):
            paths.append(str(candidate))
    return paths


def _login_shell_which_all(command: str) -> list[str]:
    try:
        completed = subprocess.run(
            ["/bin/zsh", "-lc", f"which -a {command}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except Exception:
        return []
    if completed.returncode != 0:
        return []
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def _dedupe_existing_or_configured(
    candidates: list[str],
    *,
    configured_command: str | None,
) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for candidate in candidates:
        if not candidate:
            continue
        keep = candidate == configured_command or Path(candidate).exists()
        if not keep:
            continue
        key = str(Path(candidate).expanduser())
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return result
