from __future__ import annotations

import argparse
from importlib import metadata
from pathlib import Path

from newbro.config_home import format_user_path
from newbro.executors.families import SUPPORTED_EXECUTOR_FAMILIES


def add_host_port(
    parser: argparse.ArgumentParser,
    *,
    backend_port: int,
    frontend_port: int | None = None,
    include_frontend_port: bool = False,
) -> None:
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=backend_port)
    if include_frontend_port:
        parser.add_argument("--frontend-port", type=int, default=frontend_port or 5173)


def build_parser(
    *,
    cli_name: str,
    env_file: Path,
    start_public_port: int,
) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=cli_name, description="Newbro developer CLI.")
    try:
        _version = metadata.version("newbro-cli")
    except metadata.PackageNotFoundError:
        _version = "0+unknown"
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {_version}",
        help="Show the installed newbro-cli version and exit.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    setup_parser = subparsers.add_parser(
        "setup",
        help=f"Interactively configure {format_user_path(env_file)}.",
    )
    setup_parser.add_argument(
        "--non-interactive",
        action="store_true",
        help=f"Resolve values from {format_user_path(env_file)} and process env without prompting.",
    )
    setup_parser.add_argument(
        "--bootstrap-defaults",
        action="store_true",
        help=argparse.SUPPRESS,
    )

    dev_parser = subparsers.add_parser("dev", help="Run backend and frontend together.")
    add_host_port(dev_parser, backend_port=8000, frontend_port=5173, include_frontend_port=True)

    backend_parser = subparsers.add_parser("backend", help="Run the FastAPI backend with reload.")
    add_host_port(backend_parser, backend_port=8000)

    frontend_parser = subparsers.add_parser("frontend", help="Run the frontend dev server.")
    frontend_parser.add_argument("--host", default="0.0.0.0")
    frontend_parser.add_argument("--port", type=int, default=5173)

    doctor_parser = subparsers.add_parser("doctor", help="Check local development prerequisites.")
    doctor_parser.add_argument("--backend-port", type=int, default=8000)
    doctor_parser.add_argument("--frontend-port", type=int, default=5173)

    status_parser = subparsers.add_parser("status", help="Inspect local Newbro startup readiness.")
    status_parser.add_argument("--backend-port", type=int, default=8000)
    status_parser.add_argument("--frontend-port", type=int, default=5173)

    start_parser = subparsers.add_parser(
        "start",
        help="Run the production Newbro service without reload.",
    )
    start_parser.add_argument("--host", default="0.0.0.0")
    start_parser.add_argument("--port", type=int, default=start_public_port)

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
    executor_subparsers.add_parser(
        "install-codex",
        help="Install or repair the local Codex CLI used by executor nodes.",
    )
    executor_subparsers.add_parser(
        "install-hermes",
        help="Install or repair the local Hermes CLI used by executor nodes.",
    )
    executor_probe_parser = executor_subparsers.add_parser(
        "probe",
        help="Probe local executor binaries.",
    )
    executor_probe_parser.add_argument("--executor", choices=list(SUPPORTED_EXECUTOR_FAMILIES), required=True)
    executor_probe_parser.add_argument("--json", action="store_true", help="Print machine-readable probe JSON.")
    executor_use_parser = executor_subparsers.add_parser(
        "use",
        help="Select a local executor binary.",
    )
    executor_use_parser.add_argument("--executor", choices=list(SUPPORTED_EXECUTOR_FAMILIES), required=True)
    executor_use_parser.add_argument(
        "--command",
        dest="executor_binary_command",
        required=True,
        help="Absolute path to the executor binary.",
    )
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
        choices=list(SUPPORTED_EXECUTOR_FAMILIES),
        help="Override the enabled executor families for this run. Repeat for multiple values.",
    )
    executor_run_parser.add_argument(
        "--acpx-agent",
        help="Override the ACPX agent for this run, for example codex or openclaw.",
    )
    executor_run_parser.add_argument(
        "--audio-language",
        help="Override local Whisper language for executor-node audio transcription, for example auto, en, or zh.",
    )
    executor_run_parser.add_argument(
        "--whisper-model",
        help="Override local Whisper model for executor-node audio transcription, for example base or small.",
    )

    service_parser = subparsers.add_parser("service", help="Install and control the Ubuntu systemd service.")
    service_subparsers = service_parser.add_subparsers(dest="service_command", required=True)
    service_install_parser = service_subparsers.add_parser(
        "install",
        help="Install or update the systemd unit for this repo checkout.",
    )
    service_install_parser.add_argument("--host", default="0.0.0.0")
    service_install_parser.add_argument("--port", type=int, default=start_public_port)
    service_subparsers.add_parser("start", help="Start the installed systemd service.")
    service_subparsers.add_parser("stop", help="Stop the installed systemd service.")
    service_subparsers.add_parser("restart", help="Restart the installed systemd service.")

    invite_parser = subparsers.add_parser("invite", help="Manage public invite access.")
    invite_subparsers = invite_parser.add_subparsers(dest="invite_command", required=True)
    invite_create_parser = invite_subparsers.add_parser("create", help="Create or replace an invite code.")
    invite_create_parser.add_argument("code", nargs="?", help="Invite code to create. Generated when omitted.")
    invite_create_parser.add_argument("--email", help="Optional email label for the invite.")

    return parser
