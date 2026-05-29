from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Callable
from urllib.error import URLError


@dataclass(frozen=True, slots=True)
class CheckResult:
    label: str
    ok: bool
    status: str
    detail: str

    def render(self) -> str:
        return f"[{self.status}] {self.label}: {self.detail}"


def command_check(name: str, *, shutil_module: ModuleType, required: bool = True) -> CheckResult:
    path = shutil_module.which(name)
    if path:
        return CheckResult(label=f"command: {name}", ok=True, status="ok", detail=path)
    status = "missing" if required else "warn"
    return CheckResult(label=f"command: {name}", ok=not required, status=status, detail="")


def path_check(label: str, path: Path, *, missing_detail: str) -> CheckResult:
    if path.exists():
        return CheckResult(label=label, ok=True, status="ok", detail=str(path))
    return CheckResult(label=label, ok=False, status="missing", detail=missing_detail)


def port_check(port: int, *, socket_factory: Callable[[], object]) -> CheckResult:
    try:
        sock = socket_factory()
    except PermissionError:
        return CheckResult(label=f"port {port}", ok=True, status="warn", detail="could not be checked in this environment")

    try:
        sock.bind(("127.0.0.1", port))
        return CheckResult(label=f"port {port}", ok=True, status="ok", detail="is free")
    except PermissionError:
        return CheckResult(label=f"port {port}", ok=True, status="warn", detail="could not be checked in this environment")
    except OSError:
        return CheckResult(label=f"port {port}", ok=False, status="busy", detail="is already in use")
    finally:
        sock.close()


def env_file_has_key(path: Path, key: str) -> bool:
    if not path.exists():
        return False
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        line_key, _, value = stripped.partition("=")
        if line_key.strip() == key and value.strip():
            return True
    return False


def http_reachability_check(
    label: str,
    url: str,
    *,
    urlopen: Callable[..., object],
    timeout: float = 0.5,
) -> CheckResult:
    try:
        with urlopen(url, timeout=timeout) as response:
            status = getattr(response, "status", None)
            if status is None or 200 <= int(status) < 500:
                detail = f"reachable at {url}"
                if status is not None:
                    detail = f"{detail} ({status})"
                return CheckResult(label=label, ok=True, status="ok", detail=detail)
            return CheckResult(label=label, ok=True, status="warn", detail=f"{url} returned {status}")
    except (OSError, URLError, TimeoutError) as exc:
        return CheckResult(label=label, ok=True, status="warn", detail=f"not reachable at {url} ({exc})")
