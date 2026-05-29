from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True, slots=True)
class RunContext:
    root: Path
    frontend: Path


@dataclass(frozen=True, slots=True)
class RunCallbacks:
    require_venv_python: Callable[[], Path]
    service_runtime_python_path: Callable[[], Path]
    executor_run_python_path: Callable[[], Path]
    executor_run_cwd: Callable[[], Path]
    ensure_frontend_build_ready: Callable[[], Path]
    service_command: Callable[[Path, str, int], list[str]]
    backend_command: Callable[[Path, str, int], list[str]]
    frontend_dev_command: Callable[[str, int], list[str]]
    connector_command: Callable[[Path, str, int, bool], list[str]]
    executor_node_command: Callable[[Path], list[str]]
    load_connector_settings_if_enabled: Callable[[], object | None]
    load_connector_settings: Callable[[], object]
    ensure_executor_runtime_configured: Callable[[], None]
    run_checked: Callable[[list[str], Path], int]
    run_managed_processes: Callable[[list[tuple[str, list[str], Path]]], int]


def run_dev(args, context: RunContext, callbacks: RunCallbacks) -> int:
    venv_python = callbacks.require_venv_python()
    commands = [
        ("service", callbacks.service_command(venv_python, args.host, args.port), context.root),
        ("frontend", callbacks.frontend_dev_command(args.host, args.frontend_port), context.frontend),
    ]
    connector_settings = callbacks.load_connector_settings_if_enabled()

    print("\nNewbro dev is running")
    print(f"Frontend: http://localhost:{args.frontend_port}")
    print(f"Service : http://localhost:{args.port}")
    if connector_settings is not None:
        print(f"Connector : mounted via {connector_settings.public_base_url}")
    print("Press Ctrl+C to stop\n")
    return callbacks.run_managed_processes(commands)


def run_backend(args, context: RunContext, callbacks: RunCallbacks) -> int:
    venv_python = callbacks.require_venv_python()
    command = callbacks.backend_command(venv_python, args.host, args.port)
    return callbacks.run_checked(command, context.root)


def run_start(args, context: RunContext, callbacks: RunCallbacks) -> int:
    runtime_python = callbacks.service_runtime_python_path()
    callbacks.ensure_frontend_build_ready()
    commands = [
        ("service", callbacks.service_command(runtime_python, args.host, args.port), context.root),
    ]
    return callbacks.run_managed_processes(commands)


def run_frontend(args, context: RunContext, callbacks: RunCallbacks) -> int:
    callbacks.require_venv_python()
    return callbacks.run_checked(callbacks.frontend_dev_command(args.host, args.port), context.frontend)


def run_connector(args, context: RunContext, callbacks: RunCallbacks) -> int:
    runtime_python = callbacks.service_runtime_python_path()
    settings = callbacks.load_connector_settings()
    host = args.host or settings.host
    port = args.port or settings.port
    command = callbacks.connector_command(runtime_python, host, port, args.reload)
    return callbacks.run_checked(command, context.root)


def run_executor(args, _context: RunContext, callbacks: RunCallbacks) -> int:
    callbacks.ensure_executor_runtime_configured()
    venv_python = callbacks.executor_run_python_path()
    return callbacks.run_checked(
        callbacks.executor_node_command(venv_python),
        callbacks.executor_run_cwd(),
    )
