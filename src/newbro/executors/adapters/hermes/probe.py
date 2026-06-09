from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HermesProbeResult:
    path: str
    version: str | None
    ok: bool
    error: str | None = None


def parse_hermes_version(output: str | None) -> str | None:
    if not output:
        return None
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", output)
    return match.group(0) if match else None


def probe_hermes_command(command: str) -> HermesProbeResult:
    path = command if os.path.isabs(command) else (shutil.which(command) or command)
    try:
        completed = subprocess.run(
            [path, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except FileNotFoundError:
        return HermesProbeResult(path=path, version=None, ok=False, error="command not found")
    except subprocess.TimeoutExpired:
        return HermesProbeResult(path=path, version=None, ok=False, error="hermes --version timed out")
    except Exception as exc:  # noqa: BLE001 - surface any spawn failure as a probe error
        return HermesProbeResult(path=path, version=None, ok=False, error=str(exc))
    output = (completed.stdout or completed.stderr or "").strip()
    version = parse_hermes_version(output)
    if completed.returncode != 0:
        first_line = output.splitlines()[0].strip() if output else None
        return HermesProbeResult(
            path=path,
            version=version,
            ok=False,
            error=first_line or f"hermes --version exited {completed.returncode}",
        )
    return HermesProbeResult(path=path, version=version, ok=True)
