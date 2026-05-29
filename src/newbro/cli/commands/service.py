from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True, slots=True)
class ServiceContext:
    root: Path
    systemd_unit_name: str


@dataclass(frozen=True, slots=True)
class ServiceCallbacks:
    ensure_install_supported: Callable[[], None]
    ensure_manager_available: Callable[[], None]
    current_user: Callable[[], str]
    user_home: Callable[[], Path]
    ensure_runtime_ready: Callable[[], Path]
    ensure_cli_ready: Callable[[Path], Path]
    render_unit: Callable[[str, Path, Path, Path, str, int], str]
    install_unit: Callable[[str], None]
    service_unit_path: Callable[[], Path]
    run_privileged_checked: Callable[[list[str], Path], int]


def install_service(args, context: ServiceContext, callbacks: ServiceCallbacks) -> int:
    callbacks.ensure_install_supported()
    callbacks.ensure_manager_available()
    user = callbacks.current_user()
    home = callbacks.user_home()
    venv_python = callbacks.ensure_runtime_ready()
    cli_bin = callbacks.ensure_cli_ready(venv_python)
    unit_text = callbacks.render_unit(user, home, context.root, cli_bin, args.host, args.port)
    callbacks.install_unit(unit_text)
    print(f"[ok] installed {callbacks.service_unit_path()}")
    print(f"[ok] restarted {context.systemd_unit_name}")
    print(f"[hint] status: systemctl status {context.systemd_unit_name}")
    return 0


def lifecycle_service(action: str, context: ServiceContext, callbacks: ServiceCallbacks) -> int:
    callbacks.ensure_manager_available()
    return callbacks.run_privileged_checked(["systemctl", action, context.systemd_unit_name], context.root)
