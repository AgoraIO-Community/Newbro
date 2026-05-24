from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
import getpass
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import secrets
from uuid import uuid4

from newbro.config_home import (
    LEGACY_SYNAPSE_HOME_DIR,
    NEWBRO_HOME_DIR,
    SYNAPSE_ENV_FILE,
    ConfigHomeMigrationError,
    ensure_newbro_home,
    format_user_path,
)
from newbro.yaml_support import load_yaml_file


MODULE_ROOT = Path(__file__).resolve().parents[3]
ROOT = MODULE_ROOT
FRONTEND = ROOT / "src" / "newbro" / "ui"
VENV_DIR = ROOT / ".venv"
ENV_LOCAL = SYNAPSE_ENV_FILE
CLI_NAME = "newbro"
ROOT_LAUNCHER = f"./{CLI_NAME}"
ENV_LINE_RE = re.compile(r"^\s*(?P<comment>#\s*)?(?P<key>[A-Z0-9_]+)=(?P<value>.*)$")
TRUTHY_VALUES = {"1", "true", "yes", "on", "y"}
FALSY_VALUES = {"0", "false", "no", "off", "n"}
OPENAI_KEY = "OPENAI_API_KEY"
CODEX_ENABLED_KEY = "SYNAPSE_CODEX_EXECUTOR_ENABLED"
CODEX_COMMAND_KEY = "SYNAPSE_CODEX_COMMAND"
INTERACTIVE_SETUP_KEYS = {OPENAI_KEY}
CONNECTOR_ENABLED_KEY = "SYNAPSE_CONNECTOR_ENABLED"
CONNECTOR_HOST_KEY = "SYNAPSE_CONNECTOR_HOST"
CONNECTOR_PORT_KEY = "SYNAPSE_CONNECTOR_PORT"
CONNECTOR_PUBLIC_BASE_URL_KEY = "SYNAPSE_CONNECTOR_PUBLIC_BASE_URL"
CONNECTOR_SYNAPSE_BASE_URL_KEY = "SYNAPSE_CONNECTOR_SYNAPSE_BASE_URL"
CONNECTOR_MODULES_KEY = "SYNAPSE_CONNECTOR_MODULES"
ACPX_COMMAND_KEY = "SYNAPSE_ACPX_COMMAND"
ACPX_AGENT_KEY = "SYNAPSE_ACPX_AGENT"
ACPX_PERMISSION_MODE_KEY = "SYNAPSE_ACPX_PERMISSION_MODE"
ACPX_NON_INTERACTIVE_PERMISSIONS_KEY = "SYNAPSE_ACPX_NON_INTERACTIVE_PERMISSIONS"
ACPX_TIMEOUT_SECONDS_KEY = "SYNAPSE_ACPX_TIMEOUT_SECONDS"
LEGACY_REAL_EXECUTOR_ENV_KEYS = {
    CODEX_ENABLED_KEY,
    CODEX_COMMAND_KEY,
    ACPX_COMMAND_KEY,
    ACPX_AGENT_KEY,
    ACPX_PERMISSION_MODE_KEY,
    ACPX_NON_INTERACTIVE_PERMISSIONS_KEY,
    ACPX_TIMEOUT_SECONDS_KEY,
}
SYSTEMD_UNIT_NAME = "newbro.service"
SYSTEMD_SERVICE_DIR = Path("/etc/systemd/system")
REMOVED_RUNTIME_KEYS = {"executor_node_id", "executor_node_token"}
START_PUBLIC_PORT = 8000
DEFAULT_ENV_TEMPLATE_LINES = (
    "OPENAI_API_KEY=your_openai_api_key_here",
    "SYNAPSE_OPENAI_MODEL=gpt-4o-mini",
    "SYNAPSE_OPENAI_TIMEOUT_SECONDS=30",
    "# SYNAPSE_OPENAI_BASE_URL=",
    "# SYNAPSE_CORS_ALLOWED_ORIGINS=https://app.example.com,https://your-project.vercel.app",
    "",
    f"# Shared Newbro credentials written by `{CLI_NAME} setup` to {format_user_path(ENV_LOCAL)}",
    "# AGORA_APP_ID=",
    "# AGORA_APP_CERTIFICATE=",
    "# DEEPGRAM_API_KEY=",
    "# ELEVENLABS_API_KEY=",
)


@dataclass(slots=True)
class EnvTemplateLine:
    raw: str
    key: str | None = None
    value: str | None = None
    commented: bool = False


@dataclass(slots=True)
class ConnectorSetupResult:
    env_values: dict[str, str | None]
    config_path: Path | None = None
    config_text: str | None = None


@dataclass(slots=True)
class SetupValuesResult:
    env_values: dict[str, str | None]
    runtime_values: dict[str, object]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=CLI_NAME, description="Newbro developer CLI.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    setup_parser = subparsers.add_parser(
        "setup",
        help=f"Interactively configure {format_user_path(ENV_LOCAL)}.",
    )
    setup_parser.add_argument(
        "--non-interactive",
        action="store_true",
        help=f"Resolve values from {format_user_path(ENV_LOCAL)} and process env without prompting.",
    )
    setup_parser.add_argument(
        "--bootstrap-defaults",
        action="store_true",
        help=argparse.SUPPRESS,
    )

    dev_parser = subparsers.add_parser("dev", help="Run backend and frontend together.")
    _add_host_port(dev_parser, backend_port=8000, frontend_port=5173, include_frontend_port=True)

    backend_parser = subparsers.add_parser("backend", help="Run the FastAPI backend with reload.")
    _add_host_port(backend_parser, backend_port=8000)

    frontend_parser = subparsers.add_parser("frontend", help="Run the frontend dev server.")
    frontend_parser.add_argument("--host", default="0.0.0.0")
    frontend_parser.add_argument("--port", type=int, default=5173)

    doctor_parser = subparsers.add_parser("doctor", help="Check local development prerequisites.")
    doctor_parser.add_argument("--backend-port", type=int, default=8000)
    doctor_parser.add_argument("--frontend-port", type=int, default=5173)

    start_parser = subparsers.add_parser(
        "start",
        help="Run the production Newbro service without reload.",
    )
    start_parser.add_argument("--host", default="0.0.0.0")
    start_parser.add_argument("--port", type=int, default=START_PUBLIC_PORT)

    connector_parser = subparsers.add_parser("connector", help="Configure and run the connector host.")
    connector_subparsers = connector_parser.add_subparsers(dest="connector_command", required=True)
    connector_subparsers.add_parser("setup", help="Interactively configure connector modules.")
    connector_run_parser = connector_subparsers.add_parser("run", help="Run the headless connector host.")
    connector_run_parser.add_argument("--host")
    connector_run_parser.add_argument("--port", type=int)
    connector_run_parser.add_argument(
        "--reload",
        action="store_true",
        help="Run the connector host with reload enabled.",
    )

    executor_parser = subparsers.add_parser("executor", help="Configure and run the detached executor node.")
    executor_subparsers = executor_parser.add_subparsers(dest="executor_command", required=True)
    executor_subparsers.add_parser("setup", help="Interactively configure the detached executor node.")
    executor_run_parser = executor_subparsers.add_parser(
        "run",
        help="Run the detached executor node. Requires --base-url, --node-id, and --token.",
    )
    executor_run_parser.add_argument("--base-url", required=True, help="Public Newbro service base URL.")
    executor_run_parser.add_argument("--node-id", required=True, help="Executor node id issued by Newbro.")
    executor_run_parser.add_argument("--token", required=True, help="Executor node token issued by Newbro.")
    executor_run_parser.add_argument(
        "--enabled-executor",
        action="append",
        choices=["codex", "acpx"],
        help="Override the enabled executor families for this run. Repeat for multiple values.",
    )
    executor_run_parser.add_argument(
        "--acpx-agent",
        help="Override the ACPX agent for this run, for example codex or openclaw.",
    )

    service_parser = subparsers.add_parser("service", help="Install and control the Ubuntu systemd service.")
    service_subparsers = service_parser.add_subparsers(dest="service_command", required=True)
    service_install_parser = service_subparsers.add_parser(
        "install",
        help="Install or update the systemd unit for this repo checkout.",
    )
    service_install_parser.add_argument("--host", default="0.0.0.0")
    service_install_parser.add_argument("--port", type=int, default=START_PUBLIC_PORT)
    service_subparsers.add_parser("start", help="Start the installed systemd service.")
    service_subparsers.add_parser("stop", help="Stop the installed systemd service.")
    service_subparsers.add_parser("restart", help="Restart the installed systemd service.")

    invite_parser = subparsers.add_parser("invite", help="Manage public invite access.")
    invite_subparsers = invite_parser.add_subparsers(dest="invite_command", required=True)
    invite_create_parser = invite_subparsers.add_parser("create", help="Create or replace an invite code.")
    invite_create_parser.add_argument("code", nargs="?", help="Invite code to create. Generated when omitted.")
    invite_create_parser.add_argument("--email", help="Optional email label for the invite.")

    return parser


def _add_host_port(parser: argparse.ArgumentParser, backend_port: int, frontend_port: int | None = None, include_frontend_port: bool = False) -> None:
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=backend_port)
    if include_frontend_port:
        parser.add_argument("--frontend-port", type=int, default=frontend_port or 5173)


def main(argv: list[str] | None = None) -> int:
    try:
        try:
            migration_result = ensure_newbro_home(
                legacy_home=LEGACY_SYNAPSE_HOME_DIR,
                new_home=NEWBRO_HOME_DIR,
            )
        except ConfigHomeMigrationError as exc:
            raise CliError(str(exc)) from exc
        if migration_result.warning:
            print(f"[warn] {migration_result.warning}", file=sys.stderr)
        parser = build_parser()
        args = parser.parse_args(argv)

        handlers = {
            "setup": cmd_setup,
            "dev": cmd_dev,
            "backend": cmd_backend,
            "frontend": cmd_frontend,
            "doctor": cmd_doctor,
            "start": cmd_start,
            "connector": cmd_connector,
            "executor": cmd_executor,
            "service": cmd_service,
            "invite": cmd_invite,
        }
        return handlers[args.command](args)
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def cmd_setup(_args: argparse.Namespace) -> int:
    args = _args
    if args.bootstrap_defaults:
        bootstrap_setup_files()
        return 0
    if not args.non_interactive and not setup_can_prompt():
        raise CliError(f"{CLI_NAME} setup requires a TTY. Use --non-interactive for automation.")

    template_lines = load_env_template()
    existing_values, existing_order = load_env_assignments(ENV_LOCAL)
    config_path = connector_config_path()
    existing_config_yaml, config_load_error = _load_existing_connector_yaml_for_setup(config_path)
    if config_load_error is not None:
        print(
            f"[warn] ignoring invalid existing config at {format_user_path(config_path)}: {config_load_error}"
        )
    setup_values = resolve_setup_values(
        template_lines=template_lines,
        existing_values=existing_values,
        environ=os.environ,
        interactive=not args.non_interactive,
        existing_config_yaml=existing_config_yaml,
    )
    connector_setup = resolve_connector_setup_values(
        existing_values=existing_values,
        environ=os.environ,
        interactive=not args.non_interactive,
        force_prompt=False,
        existing_config_yaml=existing_config_yaml,
        runtime_values=setup_values.runtime_values,
    )
    write_env_file(
        template_lines=template_lines,
        resolved_values={**setup_values.env_values, **connector_setup.env_values},
        existing_values=existing_values,
        existing_order=existing_order,
        destination=ENV_LOCAL,
    )
    config_setup = connector_setup if connector_setup.config_text is not None else ConnectorSetupResult(env_values={})
    if config_setup.config_text is None and (config_load_error is not None or setup_values.runtime_values or not config_path.exists()):
        config_setup = ConnectorSetupResult(
            env_values={},
            config_path=config_path,
            config_text=render_connector_config(
                runtime=_resolved_runtime_config(existing_config_yaml, setup_values.runtime_values),
                connector_host=_existing_connector_host_config(existing_config_yaml),
                connectors=_existing_connectors_config(existing_config_yaml),
                executor_node=_existing_executor_node_config(existing_config_yaml),
                executors=_existing_executors_config(existing_config_yaml),
            ),
        )
    _write_connector_config_if_needed(config_setup)
    print(f"[write] configured {format_user_path(ENV_LOCAL)}")
    return 0


def cmd_dev(args: argparse.Namespace) -> int:
    venv_python = require_venv_python()
    commands = [
        ("service", service_command(venv_python, args.host, args.port, reload=True), ROOT),
        ("frontend", frontend_dev_command(args.host, args.frontend_port), FRONTEND),
    ]
    connector_settings = load_connector_settings_if_enabled()

    print("\nNewbro dev is running")
    print(f"Frontend: http://localhost:{args.frontend_port}")
    print(f"Service : http://localhost:{args.port}")
    if connector_settings is not None:
        print(f"Connector : mounted via {connector_settings.public_base_url}")
    print("Press Ctrl+C to stop\n")
    return run_managed_processes(commands)


def cmd_backend(args: argparse.Namespace) -> int:
    venv_python = require_venv_python()
    return run_checked(backend_command(venv_python, args.host, args.port, reload=True), cwd=ROOT)


def cmd_start(args: argparse.Namespace) -> int:
    runtime_python = service_runtime_python_path()
    ensure_frontend_build_ready()
    commands = [
        ("service", service_command(runtime_python, args.host, args.port, reload=False), ROOT),
    ]
    return run_managed_processes(commands)


def cmd_frontend(args: argparse.Namespace) -> int:
    require_venv_python()
    return run_checked(frontend_dev_command(args.host, args.port), cwd=FRONTEND)


def cmd_doctor(args: argparse.Namespace) -> int:
    ok = True
    ok &= report_path("python", sys.executable)
    frontend_ok = report_command("bun") or report_command("npm")
    ok &= frontend_ok
    report_command("docker", required=False)

    venv_python = venv_python_path()
    if venv_python.exists():
        print(f"[ok] virtualenv: {VENV_DIR.relative_to(ROOT)}")
        print(f"[ok] venv python: {venv_python}")
    else:
        print("[missing] virtualenv: run ./install.sh")
        ok = False

    ok &= report_port(args.backend_port)
    ok &= report_port(args.frontend_port)

    if ENV_LOCAL.exists():
        print(f"[ok] env file: {format_user_path(ENV_LOCAL)}")
    else:
        print(f"[missing] env file: run {ROOT_LAUNCHER} setup")
        ok = False

    if openai_api_key_present():
        print("[ok] env: OPENAI_API_KEY")
    else:
        print(f"[missing] env: OPENAI_API_KEY (run {ROOT_LAUNCHER} setup)")
        ok = False

    ok &= report_connector_status(args)

    return 0 if ok else 1


def cmd_connector(args: argparse.Namespace) -> int:
    if args.connector_command == "setup":
        return cmd_connector_setup(args)
    if args.connector_command == "run":
        return cmd_connector_run(args)
    raise CliError(f"Unknown connector command: {args.connector_command}")


def cmd_executor(args: argparse.Namespace) -> int:
    if args.executor_command == "setup":
        return cmd_executor_setup(args)
    if args.executor_command == "run":
        return cmd_executor_run(args)
    raise CliError(f"Unknown executor command: {args.executor_command}")


def cmd_service(args: argparse.Namespace) -> int:
    if args.service_command == "install":
        return cmd_service_install(args)
    if args.service_command in {"start", "stop", "restart"}:
        return cmd_service_lifecycle(args.service_command)
    raise CliError(f"Unknown service command: {args.service_command}")


def cmd_invite(args: argparse.Namespace) -> int:
    if args.invite_command == "create":
        return cmd_invite_create(args)
    raise CliError(f"Unknown invite command: {args.invite_command}")


def cmd_invite_create(args: argparse.Namespace) -> int:
    from newbro.api.public_auth import PublicAuthStore

    code = args.code.strip() if args.code else secrets.token_urlsafe(12)
    if not code:
        raise CliError("Invite code cannot be empty.")
    store = PublicAuthStore()
    asyncio.run(store.create_invite(code, email=args.email))
    print(code)
    return 0


def cmd_connector_setup(_args: argparse.Namespace) -> int:
    if not setup_can_prompt():
        raise CliError(f"{CLI_NAME} connector setup requires a TTY.")

    template_lines = load_env_template()
    existing_values, existing_order = load_env_assignments(ENV_LOCAL)
    existing_config_yaml = _load_existing_connector_yaml(connector_config_path())
    connector_setup = resolve_connector_setup_values(
        existing_values=existing_values,
        environ=os.environ,
        interactive=True,
        force_prompt=True,
        existing_config_yaml=existing_config_yaml,
        runtime_values=None,
    )
    write_env_file(
        template_lines=template_lines,
        resolved_values={**existing_values, **connector_setup.env_values},
        existing_values=existing_values,
        existing_order=existing_order,
        destination=ENV_LOCAL,
    )
    _write_connector_config_if_needed(connector_setup)
    print(f"[write] configured {format_user_path(ENV_LOCAL)}")
    return 0


def cmd_connector_run(args: argparse.Namespace) -> int:
    runtime_python = service_runtime_python_path()
    settings = load_connector_settings()
    host = args.host or settings.host
    port = args.port or settings.port
    return run_checked(connector_command(runtime_python, host, port, reload=args.reload), cwd=ROOT)


def cmd_executor_setup(_args: argparse.Namespace) -> int:
    if not setup_can_prompt():
        raise CliError(f"{CLI_NAME} executor setup requires a TTY.")
    _run_executor_setup_flow()
    return 0


def cmd_executor_run(args: argparse.Namespace) -> int:
    _ensure_executor_runtime_configured_for_run(
        enabled_executors_override=args.enabled_executor or None,
    )
    venv_python = executor_run_python_path()
    return run_checked(
        executor_node_command(
            venv_python,
            base_url=args.base_url,
            node_id=args.node_id,
            token=args.token,
            enabled_executors=args.enabled_executor or None,
            acpx_agent=args.acpx_agent,
        ),
        cwd=executor_run_cwd(),
    )


def cmd_service_install(args: argparse.Namespace) -> int:
    ensure_service_install_supported()
    ensure_service_manager_available()
    user = current_service_user()
    home = service_user_home()
    venv_python = ensure_service_runtime_ready()
    cli_bin = ensure_service_cli_ready(venv_python)
    unit_text = render_service_unit(
        user=user,
        home=home,
        workdir=ROOT,
        cli_bin=cli_bin,
        host=args.host,
        public_port=args.port,
    )
    install_service_unit(unit_text)
    print(f"[ok] installed {service_unit_path()}")
    print(f"[ok] restarted {SYSTEMD_UNIT_NAME}")
    print(f"[hint] status: systemctl status {SYSTEMD_UNIT_NAME}")
    return 0


def cmd_service_lifecycle(action: str) -> int:
    ensure_service_manager_available()
    return run_privileged_checked(["systemctl", action, SYSTEMD_UNIT_NAME], cwd=ROOT)


def backend_command(venv_python: Path, host: str, port: int, *, reload: bool) -> list[str]:
    command = [
        str(venv_python),
        "-m",
        "uvicorn",
        "newbro.api.app:app",
        "--host",
        host,
        "--port",
        str(port),
    ]
    if reload:
        command.append("--reload")
    return command


def service_command(venv_python: Path, host: str, port: int, *, reload: bool) -> list[str]:
    command = [
        str(venv_python),
        "-m",
        "uvicorn",
        "newbro.service.app:app",
        "--host",
        host,
        "--port",
        str(port),
    ]
    if reload:
        command.append("--reload")
    return command


def connector_command(venv_python: Path, host: str, port: int, *, reload: bool) -> list[str]:
    command = [
        str(venv_python),
        "-m",
        "uvicorn",
        "newbro.connectors.host.app:app",
        "--host",
        host,
        "--port",
        str(port),
    ]
    if reload:
        command.append("--reload")
    return command


def executor_node_command(
    venv_python: Path,
    *,
    base_url: str,
    node_id: str,
    token: str,
    enabled_executors: list[str] | None = None,
    acpx_agent: str | None = None,
) -> list[str]:
    command = [
        str(venv_python),
        "-m",
        "newbro.executors.node",
        "--base-url",
        base_url,
        "--node-id",
        node_id,
        "--token",
        token,
    ]
    for executor_type in enabled_executors or []:
        command.extend(["--enabled-executor", executor_type])
    if acpx_agent:
        command.extend(["--acpx-agent", acpx_agent])
    return command


def frontend_install_command() -> list[str]:
    frontend_tool = preferred_frontend_tool()
    if frontend_tool == "bun":
        return ["bun", "install"]
    return ["npm", "install"]


def frontend_build_command() -> list[str]:
    frontend_tool = preferred_frontend_tool()
    if frontend_tool == "bun":
        return ["bun", "run", "build"]
    return ["npm", "run", "build"]


def frontend_dev_command(host: str, port: int) -> list[str]:
    frontend_tool = preferred_frontend_tool()
    if frontend_tool == "bun":
        return [
            "bun",
            "run",
            "dev",
            "--",
            "--host",
            host,
            "--port",
            str(port),
            "--config",
            "vite.config.ts",
        ]
    return [
        "npm",
        "run",
        "dev",
        "--",
        "--host",
        host,
        "--port",
        str(port),
        "--config",
        "vite.config.ts",
    ]


def preferred_frontend_tool() -> str:
    if shutil.which("bun"):
        return "bun"
    if shutil.which("npm"):
        return "npm"
    raise CliError("Missing frontend package manager: install Bun or npm.")


def internal_bind_host(host: str) -> str:
    if host in {"", "0.0.0.0", "::"}:
        return "127.0.0.1"
    return host


def ensure_service_install_supported() -> None:
    if not sys.platform.startswith("linux"):
        raise CliError(f"{CLI_NAME} service install currently supports Linux/systemd hosts only.")


def ensure_service_manager_available() -> None:
    if not sys.platform.startswith("linux"):
        raise CliError("systemd service management currently supports Linux hosts only.")
    if shutil.which("systemctl") is None:
        raise CliError(f"systemctl is required for {CLI_NAME} service commands.")
    if os.geteuid() != 0 and shutil.which("sudo") is None:
        raise CliError(f"sudo is required for {CLI_NAME} service commands.")


def current_service_user() -> str:
    return getpass.getuser()


def service_user_home() -> Path:
    return ENV_LOCAL.parent.parent


def service_unit_path() -> Path:
    return SYSTEMD_SERVICE_DIR / SYSTEMD_UNIT_NAME


def frontend_dist_dir() -> Path:
    return FRONTEND / "dist"


def frontend_build_index_path() -> Path:
    return frontend_dist_dir() / "index.html"


def ensure_frontend_build_ready() -> Path:
    index_path = frontend_build_index_path()
    if index_path.exists():
        return index_path
    raise CliError(
        f"Frontend production build is missing at {index_path}. "
        f"Run `{ROOT_LAUNCHER} service install` or build the frontend first."
    )


def ensure_service_runtime_ready() -> Path:
    venv_python = require_venv_python(allow_missing=True)
    if not venv_python.exists():
        run_checked([sys.executable, "-m", "venv", str(VENV_DIR)], cwd=ROOT)

    venv_python = require_venv_python()
    run_checked([str(venv_python), "-m", "pip", "install", "--upgrade", "pip"], cwd=ROOT)
    run_checked([str(venv_python), "-m", "pip", "install", "-e", "."], cwd=ROOT)

    bootstrap_setup_files()
    if not openai_api_key_present():
        print(
            f"[warn] env: OPENAI_API_KEY is not configured in {format_user_path(ENV_LOCAL)}"
        )
    run_checked(frontend_install_command(), cwd=FRONTEND)
    run_checked(frontend_build_command(), cwd=FRONTEND)

    return venv_python


def service_cli_bin_path(venv_python: Path) -> Path:
    return venv_python.with_name(CLI_NAME)


def ensure_service_cli_ready(venv_python: Path) -> Path:
    cli_bin = service_cli_bin_path(venv_python)
    if not cli_bin.exists():
        raise CliError(
            f"Installed {CLI_NAME} console script is missing at {cli_bin}. "
            f"Run `{venv_python} -m pip install -e .` or rerun `{ROOT_LAUNCHER} service install`."
        )
    if not os.access(cli_bin, os.X_OK):
        raise CliError(
            f"Installed {CLI_NAME} console script is not executable at {cli_bin}. "
            f"Run `{venv_python} -m pip install -e .` or rerun `{ROOT_LAUNCHER} service install`."
        )
    return cli_bin


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
    exec_start = _render_systemd_exec_start(
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
        _render_systemd_env("HOME", str(home)),
        _render_systemd_env("PATH", ":".join(path_entries)),
        f"ExecStart={exec_start}",
        "Restart=on-failure",
        "RestartSec=5",
        "",
        "[Install]",
        "WantedBy=multi-user.target",
        "",
    ]
    return "\n".join(lines)


def _render_systemd_env(name: str, value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'Environment="{name}={escaped}"'


def _render_systemd_exec_start(args: list[str]) -> str:
    rendered: list[str] = []
    for arg in args:
        if not arg or any(char.isspace() for char in arg):
            escaped = arg.replace("\\", "\\\\").replace('"', '\\"')
            rendered.append(f'"{escaped}"')
            continue
        rendered.append(arg)
    return " ".join(rendered)


def install_service_unit(unit_text: str) -> None:
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
                str(service_unit_path()),
            ],
            cwd=ROOT,
        )
        run_privileged_checked(["systemctl", "daemon-reload"], cwd=ROOT)
        run_privileged_checked(["systemctl", "enable", SYSTEMD_UNIT_NAME], cwd=ROOT)
        run_privileged_checked(["systemctl", "restart", SYSTEMD_UNIT_NAME], cwd=ROOT)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def run_privileged_checked(cmd: list[str], *, cwd: Path) -> int:
    if os.geteuid() == 0:
        return run_checked(cmd, cwd=cwd)
    return run_checked(["sudo", *cmd], cwd=cwd)


def require_venv_python(*, allow_missing: bool = False) -> Path:
    venv_python = venv_python_path()
    if venv_python.exists():
        return venv_python
    if allow_missing:
        return venv_python
    raise CliError("Repo virtualenv is not ready. Run ./install.sh first.")


def service_runtime_python_path() -> Path:
    venv_python = venv_python_path()
    if venv_python.exists():
        return venv_python
    if sys.executable:
        return Path(sys.executable)
    raise CliError("Python interpreter is unavailable.")


def venv_python_path() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def running_from_repo_checkout() -> bool:
    return (
        (MODULE_ROOT / "pyproject.toml").is_file()
        and (MODULE_ROOT / "install.sh").is_file()
        and (MODULE_ROOT / "src" / "newbro" / "__main__.py").is_file()
    )


def executor_run_python_path() -> Path:
    if running_from_repo_checkout():
        return require_venv_python()
    if not sys.executable:
        raise CliError("Current Python interpreter is unavailable for executor run.")
    return Path(sys.executable)


def executor_run_cwd() -> Path:
    if running_from_repo_checkout():
        return ROOT
    return Path.cwd()


def executor_cli_invocation() -> str:
    if running_from_repo_checkout():
        return ROOT_LAUNCHER
    return CLI_NAME


def run_checked(cmd: list[str], cwd: Path) -> int:
    print(f"[run] {' '.join(cmd)}")
    try:
        completed = subprocess.run(cmd, cwd=cwd, check=False)
    except KeyboardInterrupt:
        print("[stop] interrupted")
        return 130
    if completed.returncode in {130, -signal.SIGINT}:
        return 130
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)
    return completed.returncode


def run_managed_processes(commands: list[tuple[str, list[str], Path]]) -> int:
    processes: list[tuple[str, subprocess.Popen[str]]] = []

    def start_process(name: str, cmd: list[str], cwd: Path) -> subprocess.Popen[str]:
        print(f"[start] {name}: {' '.join(cmd)}")
        process = subprocess.Popen(cmd, cwd=cwd)
        processes.append((name, process))
        return process

    def stop_all() -> None:
        for name, process in reversed(processes):
            if process.poll() is None:
                print(f"[stop] {name}")
                process.terminate()
        deadline = time.time() + 5
        for _, process in processes:
            while process.poll() is None and time.time() < deadline:
                time.sleep(0.1)
        for name, process in processes:
            if process.poll() is None:
                print(f"[kill] {name}")
                process.kill()

    def handle_signal(_signum: int, _frame) -> None:
        stop_all()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    for name, cmd, cwd in commands:
        start_process(name, cmd, cwd)

    try:
        while True:
            for name, process in processes:
                code = process.poll()
                if code is not None:
                    print(f"[exit] {name} exited with code {code}")
                    stop_all()
                    return code
            time.sleep(1)
    finally:
        stop_all()


def report_command(name: str, *, required: bool = True) -> bool:
    path = shutil.which(name)
    if path:
        print(f"[ok] command: {name} -> {path}")
        return True
    status = "missing" if required else "warn"
    print(f"[{status}] command: {name}")
    return not required


def report_path(label: str, value: str) -> bool:
    print(f"[ok] {label}: {value}")
    return True


def report_port(port: int) -> bool:
    try:
        sock = socket.socket()
    except PermissionError:
        print(f"[warn] port {port} could not be checked in this environment")
        return True

    try:
        sock.bind(("127.0.0.1", port))
        print(f"[ok] port {port} is free")
        return True
    except PermissionError:
        print(f"[warn] port {port} could not be checked in this environment")
        return True
    except OSError:
        print(f"[busy] port {port} is already in use")
        return False
    finally:
        sock.close()


def openai_api_key_present() -> bool:
    if os.getenv("OPENAI_API_KEY"):
        return True
    if not ENV_LOCAL.exists():
        return False
    for line in ENV_LOCAL.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        if key.strip() == "OPENAI_API_KEY" and value.strip():
            return True
    return False


def setup_can_prompt() -> bool:
    return sys.stdin.isatty()


def load_env_template() -> list[EnvTemplateLine]:
    return _parse_env_template_lines(DEFAULT_ENV_TEMPLATE_LINES)


def _parse_env_template_lines(raw_lines: tuple[str, ...]) -> list[EnvTemplateLine]:
    lines: list[EnvTemplateLine] = []
    for raw_line in raw_lines:
        match = ENV_LINE_RE.match(raw_line)
        if not match:
            lines.append(EnvTemplateLine(raw=raw_line))
            continue
        lines.append(
            EnvTemplateLine(
                raw=raw_line,
                key=match.group("key"),
                value=match.group("value"),
                commented=match.group("comment") is not None,
            )
        )
    return lines


def bootstrap_env_template() -> list[EnvTemplateLine]:
    template_lines = load_env_template()
    bootstrapped_lines: list[EnvTemplateLine] = []
    for line in template_lines:
        if line.key == OPENAI_KEY:
            bootstrapped_lines.append(
                EnvTemplateLine(
                    raw=f"{OPENAI_KEY}=",
                    key=OPENAI_KEY,
                    value="",
                    commented=False,
                )
            )
            continue
        bootstrapped_lines.append(line)
    return bootstrapped_lines


def load_env_assignments(path: Path) -> tuple[dict[str, str], list[str]]:
    if not path.exists():
        return {}, []

    values: dict[str, str] = {}
    order: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        match = ENV_LINE_RE.match(raw_line)
        if not match or match.group("comment") is not None:
            continue
        key = match.group("key")
        if key not in values:
            order.append(key)
        values[key] = match.group("value")
    return values, order


def resolve_setup_values(
    *,
    template_lines: list[EnvTemplateLine],
    existing_values: dict[str, str],
    environ: os._Environ[str],
    interactive: bool,
    existing_config_yaml: dict[str, object],
) -> SetupValuesResult:
    resolved: dict[str, str | None] = {}

    for line in template_lines:
        if line.key is None or line.key in INTERACTIVE_SETUP_KEYS:
            continue
        current_value = pick_env_value(line.key, existing_values, environ)
        if current_value is None and not line.commented:
            current_value = line.value
        resolved[line.key] = normalize_optional_value(current_value)

    openai_default = normalize_required_value(
        pick_env_value(OPENAI_KEY, existing_values, environ),
        placeholder="your_openai_api_key_here",
    )
    if interactive:
        resolved[OPENAI_KEY] = prompt_secret_value(OPENAI_KEY, default_value=openai_default)
    else:
        if openai_default is None:
            raise CliError(
                f"OPENAI_API_KEY is required for non-interactive setup. Set it in {format_user_path(ENV_LOCAL)} or the shell environment."
            )
        resolved[OPENAI_KEY] = openai_default

    return SetupValuesResult(env_values=resolved, runtime_values={})


def resolve_bootstrap_values(
    *,
    template_lines: list[EnvTemplateLine],
    existing_values: dict[str, str],
) -> dict[str, str | None]:
    resolved: dict[str, str | None] = {}

    for line in template_lines:
        if line.key is None or line.key in INTERACTIVE_SETUP_KEYS:
            continue
        current_value = existing_values.get(line.key)
        if current_value is None and not line.commented:
            current_value = line.value
        resolved[line.key] = normalize_optional_value(current_value)

    resolved[OPENAI_KEY] = normalize_optional_value(existing_values.get(OPENAI_KEY))
    return resolved


def resolve_connector_setup_values(
    *,
    existing_values: dict[str, str],
    environ: os._Environ[str],
    interactive: bool,
    force_prompt: bool,
    existing_config_yaml: dict[str, object],
    runtime_values: dict[str, object] | None,
) -> ConnectorSetupResult:
    if not interactive:
        return ConnectorSetupResult(env_values={})

    existing_enabled = _coerce_bool_config_value(
        _existing_yaml_value(existing_config_yaml, "connector_host", "enabled"),
        default=False,
    )
    if not existing_enabled:
        env_enabled = pick_env_value(CONNECTOR_ENABLED_KEY, existing_values, environ)
        if env_enabled is not None:
            parsed = parse_bool_value(env_enabled)
            if parsed is not None:
                existing_enabled = parsed
    should_configure = prompt_bool_value(
        "Configure connector host",
        default=bool(existing_enabled or force_prompt),
    )
    if not should_configure:
        if not force_prompt:
            return ConnectorSetupResult(env_values={})
        return ConnectorSetupResult(
            env_values={},
            config_path=connector_config_path(),
            config_text=render_connector_config(
                runtime=_resolved_runtime_config(existing_config_yaml, runtime_values),
                connector_host=_default_connector_host_config(),
                connectors={},
                executor_node=_existing_executor_node_config(existing_config_yaml),
                executors=_existing_executors_config(existing_config_yaml),
            ),
        )

    config_path = connector_config_path()

    connectors = prompt_connector_selection()
    host = prompt_text_value(
        "Connector host",
        default_value=_existing_yaml_value(existing_config_yaml, "connector_host", "host")
        or pick_env_value(CONNECTOR_HOST_KEY, existing_values, environ)
        or "0.0.0.0",
        required=True,
    )
    port = prompt_text_value(
        "Connector port",
        default_value=str(
            _existing_yaml_value(existing_config_yaml, "connector_host", "port")
            or pick_env_value(CONNECTOR_PORT_KEY, existing_values, environ)
            or "8010"
        ),
        required=True,
    )
    public_base_url = prompt_text_value(
        "Connector public base URL",
        default_value=_existing_yaml_value(existing_config_yaml, "connector_host", "public_base_url")
        or pick_env_value(CONNECTOR_PUBLIC_BASE_URL_KEY, existing_values, environ)
        or str(_default_connector_host_config()["public_base_url"]),
        required=True,
    )
    synapse_base_url = prompt_text_value(
        "Newbro service base URL for connector callbacks",
        default_value=_existing_yaml_value(existing_config_yaml, "connector_host", "synapse_base_url")
        or pick_env_value(CONNECTOR_SYNAPSE_BASE_URL_KEY, existing_values, environ)
        or "http://127.0.0.1:8000",
        required=True,
    )

    resolved_env: dict[str, str | None] = {}
    connector_blocks: dict[str, dict[str, object]] = {}
    for connector in connectors:
        if connector == "agora-convoai":
            block, env_updates = resolve_agora_connector_setup_values(
                existing_values,
                environ,
                existing_config_yaml,
            )
            connector_blocks[connector] = block
            resolved_env.update(env_updates)
    config_text = render_connector_config(
        runtime=_resolved_runtime_config(existing_config_yaml, runtime_values),
        connector_host={
            "enabled": True,
            "host": host,
            "port": int(port),
            "public_base_url": public_base_url,
            "synapse_base_url": synapse_base_url,
            "enabled_connectors": connectors,
        },
        connectors=connector_blocks,
        executor_node=_existing_executor_node_config(existing_config_yaml),
        executors=_existing_executors_config(existing_config_yaml),
    )
    return ConnectorSetupResult(
        env_values=resolved_env,
        config_path=config_path,
        config_text=config_text,
    )


def resolve_executor_setup_values(
    *,
    existing_values: dict[str, str],
    environ: os._Environ[str],
    existing_config_yaml: dict[str, object],
) -> ConnectorSetupResult:
    del environ  # reserved for future env-backed defaults
    config_path = connector_config_path()
    enabled_executors = prompt_executor_selection(
        default_selected=_existing_executor_enabled_types(existing_config_yaml) or None
    )
    executors_block = _existing_executors_config(existing_config_yaml)
    for executor_type in enabled_executors:
        existing_block = executors_block.get(executor_type, {})
        if executor_type == "codex":
            command = prompt_text_value(
                "Codex command",
                default_value=str(
                    existing_block.get("command")
                    or existing_values.get(CODEX_COMMAND_KEY)
                    or _detected_codex_command()
                    or "codex"
                ),
                required=True,
            )
            if not _command_available(command):
                print(f"[warn] command '{command}' is not currently available on PATH")
            executors_block["codex"] = {
                "command": command,
                "blocked_wait_timeout_seconds": float(
                    existing_block.get("blocked_wait_timeout_seconds") or 900.0
                ),
            }
        elif executor_type == "acpx":
            executors_block["acpx"] = {
                "command": prompt_text_value(
                    "ACPX command",
                    default_value=str(existing_block.get("command") or existing_values.get(ACPX_COMMAND_KEY) or "acpx"),
                    required=True,
                ),
                "agent": str(existing_block.get("agent") or existing_values.get(ACPX_AGENT_KEY) or "codex"),
                "permission_mode": str(
                    existing_block.get("permission_mode")
                    or existing_values.get(ACPX_PERMISSION_MODE_KEY)
                    or "approve-all"
                ),
                "non_interactive_permissions": str(
                    existing_block.get("non_interactive_permissions")
                    or existing_values.get(ACPX_NON_INTERACTIVE_PERMISSIONS_KEY)
                    or "deny"
                ),
                "timeout_seconds": existing_block.get("timeout_seconds") or existing_values.get(ACPX_TIMEOUT_SECONDS_KEY),
            }

    config_text = render_connector_config(
        runtime=_existing_runtime_config(existing_config_yaml),
        connector_host=_existing_connector_host_config(existing_config_yaml),
        connectors=_existing_connectors_config(existing_config_yaml),
        executor_node={
            "enabled_executors": enabled_executors,
        },
        executors={
            key: value
            for key, value in executors_block.items()
            if key in enabled_executors
        },
    )
    return ConnectorSetupResult(
        env_values={},
        config_path=config_path,
        config_text=config_text,
    )


def _run_executor_setup_flow() -> None:
    template_lines = load_env_template()
    existing_values, existing_order = load_env_assignments(ENV_LOCAL)
    existing_config_yaml = _load_existing_connector_yaml(connector_config_path())
    executor_setup = resolve_executor_setup_values(
        existing_values=existing_values,
        environ=os.environ,
        existing_config_yaml=existing_config_yaml,
    )
    filtered_existing_values = {
        key: value
        for key, value in existing_values.items()
        if key not in LEGACY_REAL_EXECUTOR_ENV_KEYS
    }
    filtered_existing_order = [
        key for key in existing_order if key not in LEGACY_REAL_EXECUTOR_ENV_KEYS
    ]
    write_env_file(
        template_lines=template_lines,
        resolved_values={**filtered_existing_values, **executor_setup.env_values},
        existing_values=filtered_existing_values,
        existing_order=filtered_existing_order,
        destination=ENV_LOCAL,
    )
    _write_connector_config_if_needed(executor_setup)
    print(f"[write] configured {format_user_path(ENV_LOCAL)}")


def _ensure_executor_runtime_configured_for_run(
    *,
    enabled_executors_override: list[str] | None = None,
) -> None:
    cli_invocation = executor_cli_invocation()
    existing_values, _ = load_env_assignments(ENV_LOCAL)
    existing_config_yaml = _load_existing_connector_yaml(connector_config_path())
    if _executor_runtime_config_complete(
        existing_config_yaml,
        existing_values,
        enabled_executors_override=enabled_executors_override,
    ):
        return
    if not setup_can_prompt():
        raise CliError(
            f"Local executor runtime config is incomplete. Run `{cli_invocation} executor setup` "
            f"or rerun `{cli_invocation} executor run ...` in a TTY."
        )
    print("[setup] executor run is missing local executor runtime config; launching setup.")
    _run_executor_setup_flow()
    refreshed_values, _ = load_env_assignments(ENV_LOCAL)
    refreshed_config_yaml = _load_existing_connector_yaml(connector_config_path())
    if not _executor_runtime_config_complete(
        refreshed_config_yaml,
        refreshed_values,
        enabled_executors_override=enabled_executors_override,
    ):
        raise CliError(
            "Local executor runtime config is still incomplete after setup. "
            f"Check the configured executor command paths and rerun `{cli_invocation} executor setup`."
        )


def _executor_runtime_config_complete(
    existing_config_yaml: dict[str, object],
    existing_values: dict[str, str],
    *,
    enabled_executors_override: list[str] | None = None,
) -> bool:
    enabled_executors = enabled_executors_override or _existing_executor_enabled_types(existing_config_yaml)
    if not enabled_executors:
        return False
    executors_block = _existing_executors_config(existing_config_yaml)
    return all(
        _executor_runtime_ready(
            executor_type,
            existing_block=executors_block.get(executor_type, {}),
            existing_values=existing_values,
        )
        for executor_type in enabled_executors
    )


def _executor_runtime_ready(
    executor_type: str,
    *,
    existing_block: dict[str, object],
    existing_values: dict[str, str],
) -> bool:
    if executor_type == "codex":
        command = str(
            existing_block.get("command")
            or existing_values.get(CODEX_COMMAND_KEY)
            or _detected_codex_command()
            or ""
        ).strip()
        return bool(command) and _command_available(command)
    if executor_type == "acpx":
        command = str(
            existing_block.get("command")
            or existing_values.get(ACPX_COMMAND_KEY)
            or "acpx"
        ).strip()
        return bool(command) and _command_available(command)
    command = str(existing_block.get("command") or "").strip()
    return bool(command) and _command_available(command)


def bootstrap_setup_files() -> None:
    existing_values, existing_order = load_env_assignments(ENV_LOCAL)
    if not ENV_LOCAL.exists():
        template_lines = bootstrap_env_template()
        resolved_values = resolve_bootstrap_values(
            template_lines=template_lines,
            existing_values=existing_values,
        )
        write_env_file(
            template_lines=template_lines,
            resolved_values=resolved_values,
            existing_values=existing_values,
            existing_order=existing_order,
            destination=ENV_LOCAL,
        )
        print(f"[write] configured {format_user_path(ENV_LOCAL)}")

    config_path = connector_config_path()
    if not config_path.exists():
        _write_connector_config_if_needed(
            ConnectorSetupResult(
                env_values={},
                config_path=config_path,
                config_text=render_connector_config(
                    runtime=resolve_bootstrap_runtime_values(existing_values),
                    connector_host=_default_connector_host_config(),
                    connectors={},
                    executor_node=_default_executor_node_config(),
                    executors={},
                ),
            )
        )


def resolve_agora_connector_setup_values(
    existing_values: dict[str, str],
    environ: os._Environ[str],
    existing_connector_yaml: dict[str, object],
) -> tuple[dict[str, object], dict[str, str | None]]:
    env_updates: dict[str, str | None] = {}
    existing_connector = _existing_connector_block(existing_connector_yaml, "agora-convoai")

    app_id = prompt_text_value(
        "Agora App ID",
        default_value=pick_env_value("AGORA_APP_ID", existing_values, environ) or "",
        required=True,
    )
    app_certificate = prompt_secret_value(
        "Agora App Certificate",
        default_value=pick_env_value("AGORA_APP_CERTIFICATE", existing_values, environ),
    )
    env_updates["AGORA_APP_ID"] = app_id
    env_updates["AGORA_APP_CERTIFICATE"] = app_certificate

    asr_mode = prompt_choice_value(
        "ASR credential mode",
        choices=["managed", "byok"],
        default_value=str(
            _existing_nested_value(existing_connector, "asr", "credential_mode") or "managed"
        ),
    )
    asr_model = prompt_choice_value(
        "ASR model",
        choices=["nova-3", "nova-2"],
        default_value=str(_existing_nested_value(existing_connector, "asr", "model") or "nova-3"),
    )
    asr_language = prompt_text_value(
        "ASR language",
        default_value=str(_existing_nested_value(existing_connector, "asr", "language") or "en-US"),
        required=True,
    )
    asr_block: dict[str, object] = {
        "vendor": "deepgram",
        "credential_mode": asr_mode,
        "model": asr_model,
        "language": asr_language,
    }
    if asr_mode == "byok":
        deepgram_api_key = prompt_secret_value(
            "Deepgram API Key",
            default_value=pick_env_value("DEEPGRAM_API_KEY", existing_values, environ),
        )
        env_updates["DEEPGRAM_API_KEY"] = deepgram_api_key
        asr_block["api_key"] = "$DEEPGRAM_API_KEY"

    tts_vendor = prompt_choice_value(
        "TTS vendor",
        choices=["minimax", "openai", "elevenlabs"],
        default_value=str(_existing_nested_value(existing_connector, "tts", "vendor") or "minimax"),
    )
    if tts_vendor == "minimax":
        tts_block: dict[str, object] = {
            "vendor": "minimax",
            "credential_mode": "managed",
            "model": prompt_choice_value(
                "TTS model",
                choices=["speech_2_6_turbo", "speech_2_8_turbo"],
                default_value=str(
                    _existing_nested_value(existing_connector, "tts", "model")
                    or "speech_2_6_turbo"
                ),
            ),
            "voice": normalize_optional_value(
                prompt_text_value(
                    "TTS voice",
                    default_value=(
                        _existing_nested_value(existing_connector, "tts", "voice")
                        or "English_magnetic_voiced_man"
                    ),
                )
            ),
            "sample_rate": None,
        }
    elif tts_vendor == "openai":
        tts_block = {
            "vendor": "openai",
            "credential_mode": "managed",
            "model": "tts-1",
            "voice": normalize_optional_value(
                prompt_text_value(
                    "TTS voice",
                    default_value=_existing_nested_value(existing_connector, "tts", "voice") or "alloy",
                )
            )
            or "alloy",
            "sample_rate": None,
        }
    else:
        elevenlabs_api_key = prompt_secret_value(
            "ElevenLabs API Key",
            default_value=pick_env_value("ELEVENLABS_API_KEY", existing_values, environ),
        )
        env_updates["ELEVENLABS_API_KEY"] = elevenlabs_api_key
        tts_block = {
            "vendor": "elevenlabs",
            "credential_mode": "byok",
            "model": prompt_text_value(
                "TTS model",
                default_value=str(
                    _existing_nested_value(existing_connector, "tts", "model")
                    or "eleven_flash_v2_5"
                ),
                required=True,
            ),
            "voice": normalize_optional_value(
                prompt_text_value(
                    "TTS voice",
                    default_value=_existing_nested_value(existing_connector, "tts", "voice"),
                    required=True,
                )
            ),
            "api_key": "$ELEVENLABS_API_KEY",
            "sample_rate": int(
                prompt_text_value(
                    "TTS sample rate",
                    default_value=str(
                        _existing_nested_value(existing_connector, "tts", "sample_rate") or "24000"
                    ),
                    required=True,
                )
            ),
        }

    return (
        {
            "app_id": "$AGORA_APP_ID",
            "app_certificate": "$AGORA_APP_CERTIFICATE",
            "convoai_area": "US",
            "client_token_ttl_seconds": int(existing_connector.get("client_token_ttl_seconds") or 3600),
            "speak_priority": str(existing_connector.get("speak_priority") or "APPEND").upper(),
            "speak_interruptable": bool(existing_connector.get("speak_interruptable", True)),
            "request_timeout_seconds": float(existing_connector.get("request_timeout_seconds") or 10.0),
            "asr": asr_block,
            "tts": tts_block,
        },
        env_updates,
    )


def write_env_file(
    *,
    template_lines: list[EnvTemplateLine],
    resolved_values: dict[str, str | None],
    existing_values: dict[str, str],
    existing_order: list[str],
    destination: Path,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    known_keys = [line.key for line in template_lines if line.key is not None]
    rendered_lines: list[str] = []

    for line in template_lines:
        if line.key is None:
            rendered_lines.append(line.raw)
            continue

        resolved_value = resolved_values.get(line.key)
        if resolved_value is None or resolved_value == "":
            if line.commented:
                rendered_lines.append(line.raw)
            elif line.value is not None:
                rendered_lines.append(f"{line.key}={line.value}")
            else:
                rendered_lines.append(f"{line.key}=")
            continue

        rendered_lines.append(f"{line.key}={resolved_value}")

    unknown_keys = [key for key in existing_order if key not in known_keys]
    additional_resolved_keys = [
        key
        for key, value in resolved_values.items()
        if key not in known_keys and key not in unknown_keys and value not in (None, "")
    ]
    if unknown_keys:
        if rendered_lines and rendered_lines[-1] != "":
            rendered_lines.append("")
        for key in unknown_keys:
            rendered_lines.append(f"{key}={existing_values[key]}")
    if additional_resolved_keys:
        if rendered_lines and rendered_lines[-1] != "":
            rendered_lines.append("")
        for key in additional_resolved_keys:
            rendered_lines.append(f"{key}={resolved_values[key]}")

    destination.write_text("\n".join(rendered_lines) + "\n", encoding="utf-8")


def pick_env_value(name: str, existing_values: dict[str, str], environ: os._Environ[str]) -> str | None:
    if name in existing_values:
        return existing_values[name]
    return environ.get(name)


def normalize_optional_value(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    return value


def normalize_required_value(value: str | None, *, placeholder: str | None) -> str | None:
    if value is None or value == "" or value == placeholder:
        return None
    return value


def _detected_codex_command() -> str | None:
    return shutil.which("codex")


def _command_available(command: str) -> bool:
    return shutil.which(command) is not None


def resolve_codex_enabled(explicit_value: str | None, *, interactive: bool) -> bool:
    if explicit_value is not None:
        parsed = parse_bool_value(explicit_value)
        if parsed is None:
            raise CliError(
                f"{CODEX_ENABLED_KEY} must be one of true/false/yes/no/1/0, got '{explicit_value}'."
            )
        explicit_default = parsed
    else:
        explicit_default = None

    if not interactive:
        return explicit_default if explicit_default is not None else False

    default_value = explicit_default if explicit_default is not None else _command_available("codex")
    return prompt_bool_value("Enable Codex executor", default=default_value)


def parse_bool_value(raw_value: str) -> bool | None:
    normalized = raw_value.strip().lower()
    if normalized in TRUTHY_VALUES:
        return True
    if normalized in FALSY_VALUES:
        return False
    return None


def format_bool(value: bool) -> str:
    return "true" if value else "false"


def prompt_secret_value(name: str, *, default_value: str | None) -> str:
    while True:
        suffix = " [configured]" if default_value else ""
        entered = getpass.getpass(f"{name}{suffix}: ")
        if entered:
            return entered
        if default_value:
            return default_value
        print(f"{name} is required.")


def prompt_bool_value(label: str, *, default: bool) -> bool:
    prompt = "Y/n" if default else "y/N"
    while True:
        entered = input(f"{label} [{prompt}]: ").strip()
        if not entered:
            return default
        parsed = parse_bool_value(entered)
        if parsed is not None:
            return parsed
        print("Please answer yes or no.")


def prompt_connector_module_selection() -> list[str]:
    return prompt_connector_selection()


def prompt_connector_selection() -> list[str]:
    connectors = list_available_connector_modules()
    if not connectors:
        raise CliError("No connectors are currently registered.")

    print("Available connectors:")
    for index, connector in enumerate(connectors, start=1):
        print(f"  {index}. {connector}")

    while True:
        entered = input("Select connectors [1]: ").strip()
        if not entered:
            return [connectors[0]]
        selected: list[str] = []
        try:
            for part in entered.split(","):
                index = int(part.strip())
                selected.append(connectors[index - 1])
        except (ValueError, IndexError):
            print("Enter one or more numeric choices separated by commas.")
            continue
        deduped: list[str] = []
        for connector in selected:
            if connector not in deduped:
                deduped.append(connector)
        return deduped


def prompt_executor_selection(*, default_selected: list[str] | None = None) -> list[str]:
    executors = ["codex", "acpx"]
    print("Available detached executors:")
    for index, executor_type in enumerate(executors, start=1):
        print(f"  {index}. {executor_type}")
    default_selected = [item for item in (default_selected or [executors[0]]) if item in executors]
    if not default_selected:
        default_selected = [executors[0]]
    default_index = str(executors.index(default_selected[0]) + 1)

    while True:
        entered = input(f"Select detached executor [{default_index}]: ").strip()
        if not entered:
            return [default_selected[0]]
        try:
            index = int(entered.strip())
            return [executors[index - 1]]
        except (ValueError, IndexError):
            print("Enter one numeric choice.")


def prompt_text_value(label: str, *, default_value: str | None, required: bool = False) -> str:
    while True:
        suffix = f" [{default_value}]" if default_value else ""
        entered = input(f"{label}{suffix}: ").strip()
        if entered:
            return entered
        if default_value:
            return default_value
        if not required:
            return ""
        print(f"{label} is required.")


def prompt_choice_value(label: str, *, choices: list[str], default_value: str) -> str:
    normalized_choices = {choice.lower(): choice for choice in choices}
    while True:
        entered = input(f"{label} [{default_value}]: ").strip()
        value = (entered or default_value).lower()
        if value in normalized_choices:
            return normalized_choices[value]
        print(f"Choose one of: {', '.join(choices)}")


def list_available_connector_modules() -> list[str]:
    from newbro.connectors.host.catalog import list_connector_module_specs

    return [spec.slug for spec in list_connector_module_specs()]


def load_connector_settings():
    import importlib
    connector_config_module = importlib.import_module("newbro.connectors.host.config")
    return connector_config_module.load_connector_host_settings(env_file=ENV_LOCAL)


def load_executor_node_settings():
    import importlib

    executor_node_config_module = importlib.import_module("newbro.executors.node.config")
    return executor_node_config_module.load_executor_node_settings(env_file=ENV_LOCAL)


def load_connector_settings_if_enabled():
    settings = load_connector_settings()
    if not settings.enabled or not settings.enabled_connectors:
        return None
    return settings


def report_connector_status(args: argparse.Namespace) -> bool:
    del args
    try:
        settings = load_connector_settings()
    except Exception as exc:
        print(f"[missing] connector config: {exc}")
        return False
    if not settings.enabled:
        print("[ok] connector: disabled")
        return True

    ok = True
    connectors = ", ".join(settings.enabled_connectors) or "(none)"
    print(f"[ok] connector: enabled -> {connectors}")
    print(f"[ok] connector public URL: {settings.public_base_url}")
    print(f"[ok] connector standalone listener: {settings.host}:{settings.port}")

    return ok


def report_required_env_keys(keys: list[str]) -> bool:
    ok = True
    existing_values, _ = load_env_assignments(ENV_LOCAL)
    for key in keys:
        value = pick_env_value(key, existing_values, os.environ)
        if value:
            print(f"[ok] env: {key}")
        else:
            print(f"[missing] env: {key} (run {ROOT_LAUNCHER} connector setup)")
            ok = False
    return ok


class CliError(Exception):
    pass


def connector_config_path() -> Path:
    return ENV_LOCAL.with_name("config.yaml")


def _load_existing_connector_yaml(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    loaded = load_yaml_file(path)
    if isinstance(loaded, dict):
        return loaded
    return {}


def _load_existing_connector_yaml_for_setup(path: Path) -> tuple[dict[str, object], str | None]:
    try:
        return _load_existing_connector_yaml(path), None
    except Exception as exc:
        return {}, str(exc)


def _existing_yaml_value(raw_connector_yaml: dict[str, object], *path: str) -> str | None:
    value: object = raw_connector_yaml
    for part in path:
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    if value in (None, ""):
        return None
    return str(value)


def _existing_connector_block(raw_connector_yaml: dict[str, object], connector: str) -> dict[str, object]:
    raw_connectors = raw_connector_yaml.get("connectors")
    if not isinstance(raw_connectors, dict):
        return {}
    raw_connector = raw_connectors.get(connector)
    if not isinstance(raw_connector, dict):
        return {}
    return raw_connector


def _existing_nested_value(raw_connector: dict[str, object], *path: str) -> str | None:
    value: object = raw_connector
    for part in path:
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    if value in (None, ""):
        return None
    return str(value)


def _generated_executor_node_id() -> str:
    return f"node-{uuid4().hex[:8]}"


def _existing_executor_enabled_types(raw_connector_yaml: dict[str, object]) -> list[str]:
    raw_executor_node = raw_connector_yaml.get("executor_node")
    if not isinstance(raw_executor_node, dict):
        return []
    raw_types = raw_executor_node.get("enabled_executors")
    if not isinstance(raw_types, list):
        return []
    return [
        item.strip()
        for item in raw_types
        if isinstance(item, str) and item.strip()
    ]


def _executor_node_id_default(raw_connector_yaml: dict[str, object]) -> str:
    existing = _existing_yaml_value(raw_connector_yaml, "executor_node", "node_id")
    if existing and existing != "default-node":
        return existing
    return _generated_executor_node_id()


def _coerce_bool_config_value(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        parsed = parse_bool_value(value)
        if parsed is not None:
            return parsed
    return default


def _existing_runtime_config(raw_connector_yaml: dict[str, object]) -> dict[str, object]:
    raw_runtime = raw_connector_yaml.get("runtime")
    if not isinstance(raw_runtime, dict):
        return {}
    return {
        key: value
        for key, value in raw_runtime.items()
        if key not in REMOVED_RUNTIME_KEYS
    }


def _existing_connector_host_config(raw_connector_yaml: dict[str, object]) -> dict[str, object]:
    raw_host = raw_connector_yaml.get("connector_host")
    if isinstance(raw_host, dict):
        return dict(raw_host)
    return _default_connector_host_config()


def _existing_connectors_config(raw_connector_yaml: dict[str, object]) -> dict[str, dict[str, object]]:
    raw_connectors = raw_connector_yaml.get("connectors")
    if not isinstance(raw_connectors, dict):
        return {}
    return {
        key: value
        for key, value in raw_connectors.items()
        if isinstance(key, str) and isinstance(value, dict)
    }


def _existing_executor_node_config(raw_connector_yaml: dict[str, object]) -> dict[str, object]:
    raw_executor_node = raw_connector_yaml.get("executor_node")
    if isinstance(raw_executor_node, dict):
        return {
            "enabled_executors": _existing_executor_enabled_types(raw_connector_yaml),
        }
    return _default_executor_node_config()


def _existing_executors_config(raw_connector_yaml: dict[str, object]) -> dict[str, dict[str, object]]:
    raw_executors = raw_connector_yaml.get("executors")
    if not isinstance(raw_executors, dict):
        return {}
    return {
        key: value
        for key, value in raw_executors.items()
        if isinstance(key, str) and isinstance(value, dict)
    }


def _resolved_runtime_config(
    raw_connector_yaml: dict[str, object],
    runtime_values: dict[str, object] | None,
) -> dict[str, object]:
    resolved = _existing_runtime_config(raw_connector_yaml)
    for key, value in (runtime_values or {}).items():
        if value in (None, ""):
            resolved.pop(key, None)
            continue
        resolved[key] = value
    return resolved


def _default_connector_host_config() -> dict[str, object]:
    return {
        "enabled": False,
        "host": "0.0.0.0",
        "port": 8010,
        "public_base_url": "http://127.0.0.1:8000",
        "synapse_base_url": "http://127.0.0.1:8000",
        "enabled_connectors": [],
    }


def _default_executor_node_config() -> dict[str, object]:
    return {
        "enabled_executors": [],
    }


def resolve_bootstrap_runtime_values(existing_values: dict[str, str]) -> dict[str, object]:
    del existing_values
    return {}


def render_connector_config(
    *,
    runtime: dict[str, object],
    connector_host: dict[str, object],
    connectors: dict[str, dict[str, object]],
    executor_node: dict[str, object] | None = None,
    executors: dict[str, dict[str, object]] | None = None,
) -> str:
    lines = ["version: 1", ""]
    if runtime:
        lines.append("runtime:")
        lines.extend(_render_yaml_mapping(runtime, indent=2))
    else:
        lines.append("runtime: {}")
    lines.extend(["", "connector_host:"])
    lines.extend(_render_yaml_mapping(connector_host, indent=2))
    lines.append("")
    if connectors:
        lines.append("connectors:")
        lines.extend(_render_yaml_mapping(connectors, indent=2))
    else:
        lines.append("connectors: {}")
    lines.extend(["", "executor_node:"])
    lines.extend(_render_yaml_mapping(executor_node or _default_executor_node_config(), indent=2))
    lines.append("")
    if executors:
        lines.append("executors:")
        lines.extend(_render_yaml_mapping(executors, indent=2))
    else:
        lines.append("executors: {}")
    return "\n".join(lines) + "\n"


def _render_yaml_mapping(mapping: dict[str, object], *, indent: int) -> list[str]:
    lines: list[str] = []
    prefix = " " * indent
    for key, value in mapping.items():
        if isinstance(value, dict):
            if not value:
                lines.append(f"{prefix}{key}: {{}}")
                continue
            lines.append(f"{prefix}{key}:")
            lines.extend(_render_yaml_mapping(value, indent=indent + 2))
            continue
        if isinstance(value, list):
            if not value:
                lines.append(f"{prefix}{key}: []")
                continue
            lines.append(f"{prefix}{key}:")
            for item in value:
                lines.append(f"{prefix}  - {_render_yaml_scalar(item)}")
            continue
        lines.append(f"{prefix}{key}: {_render_yaml_scalar(value)}")
    return lines


def _render_yaml_scalar(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if re.search(r"[:#\n]", text):
        return f'"{text}"'
    return text


def _write_connector_config_if_needed(result: ConnectorSetupResult) -> None:
    if result.config_path is None or result.config_text is None:
        return
    result.config_path.parent.mkdir(parents=True, exist_ok=True)
    result.config_path.write_text(result.config_text, encoding="utf-8")
    print(f"[write] configured {format_user_path(result.config_path)}")


if __name__ == "__main__":
    raise SystemExit(main())
