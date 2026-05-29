from __future__ import annotations

from pathlib import Path
import tempfile
from typing import Callable


SYSTEMD_UNIT_NAME = "newbro.service"
SYSTEMD_SERVICE_DIR = Path("/etc/systemd/system")


def service_unit_path() -> Path:
    return SYSTEMD_SERVICE_DIR / SYSTEMD_UNIT_NAME


def render_service_unit(
    *,
    user: str,
    home: Path,
    workdir: Path,
    cli_bin: Path,
    host: str,
    public_port: int,
) -> str:
    path_entries = [
        str(workdir / ".venv" / "bin"),
        str(home / ".local" / "bin"),
        str(home / ".bun" / "bin"),
        "/usr/local/sbin",
        "/usr/local/bin",
        "/usr/sbin",
        "/usr/bin",
        "/sbin",
        "/bin",
    ]
    exec_start = render_systemd_exec_start(
        [
            str(cli_bin),
            "start",
            "--host",
            host,
            "--port",
            str(public_port),
        ]
    )
    lines = [
        "[Unit]",
        "Description=Newbro service",
        "After=network-online.target",
        "Wants=network-online.target",
        "",
        "[Service]",
        "Type=simple",
        f"User={user}",
        f"WorkingDirectory={workdir}",
        render_systemd_env("HOME", str(home)),
        render_systemd_env("PATH", ":".join(path_entries)),
        f"ExecStart={exec_start}",
        "Restart=on-failure",
        "RestartSec=5",
        "",
        "[Install]",
        "WantedBy=multi-user.target",
        "",
    ]
    return "\n".join(lines)


def render_systemd_env(name: str, value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'Environment="{name}={escaped}"'


def render_systemd_exec_start(args: list[str]) -> str:
    rendered: list[str] = []
    for arg in args:
        if not arg or any(char.isspace() for char in arg):
            escaped = arg.replace("\\", "\\\\").replace('"', '\\"')
            rendered.append(f'"{escaped}"')
            continue
        rendered.append(arg)
    return " ".join(rendered)


def install_service_unit(
    unit_text: str,
    *,
    root: Path,
    service_unit_path: Path,
    systemd_unit_name: str,
    run_privileged_checked: Callable[[list[str], Path], int],
) -> None:
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            handle.write(unit_text)
            temp_path = Path(handle.name)
        run_privileged_checked(
            [
                "install",
                "-o",
                "root",
                "-g",
                "root",
                "-m",
                "0644",
                str(temp_path),
                str(service_unit_path),
            ],
            root,
        )
        run_privileged_checked(["systemctl", "daemon-reload"], root)
        run_privileged_checked(["systemctl", "enable", systemd_unit_name], root)
        run_privileged_checked(["systemctl", "restart", systemd_unit_name], root)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
