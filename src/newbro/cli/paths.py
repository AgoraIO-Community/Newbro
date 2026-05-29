from __future__ import annotations

import os
import sys
from pathlib import Path


def internal_bind_host(host: str) -> str:
    if host in {"", "0.0.0.0", "::"}:
        return "127.0.0.1"
    return host


def frontend_dist_dir(frontend_root: Path) -> Path:
    return frontend_root / "dist"


def frontend_build_index_path(frontend_root: Path) -> Path:
    return frontend_dist_dir(frontend_root) / "index.html"


def venv_python_path(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def running_from_repo_checkout(root: Path) -> bool:
    return (
        (root / "pyproject.toml").is_file()
        and (root / "install.sh").is_file()
        and (root / "src" / "newbro" / "__main__.py").is_file()
    )


def current_python_path() -> Path:
    if not sys.executable:
        raise RuntimeError("Current Python interpreter is unavailable.")
    return Path(sys.executable)
