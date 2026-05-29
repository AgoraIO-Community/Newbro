from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from newbro.cli.checks import CheckResult, path_check


@dataclass(frozen=True, slots=True)
class StatusContext:
    root_launcher: str
    python_executable: str
    env_file: Path
    config_file: Path
    venv_python: Path
    frontend_build_index: Path
    backend_port: int
    frontend_port: int
    backend_health_url: str
    frontend_url: str
    executor_invocation: str


@dataclass(frozen=True, slots=True)
class StatusCallbacks:
    report_path: Callable[[str, str], bool]
    report_command: Callable[[str], bool]
    report_optional_command: Callable[[str], bool]
    report_port: Callable[[int], bool]
    report_reachability: Callable[[str, str], bool]
    print_check: Callable[[CheckResult], bool]
    openai_api_key_present: Callable[[], bool]
    config_parse_error: Callable[[Path], str | None]
    report_connector_status: Callable[[], bool]
    executor_enabled_families: Callable[[], list[str]]


def run_status(context: StatusContext, callbacks: StatusCallbacks) -> int:
    ok = True
    print("Newbro status")

    print("\nCore")
    ok &= callbacks.report_path("python", context.python_executable)
    ok &= callbacks.report_command("bun") or callbacks.report_command("npm")
    callbacks.report_optional_command("docker")
    ok &= callbacks.print_check(
        path_check(
            "virtualenv",
            context.venv_python,
            missing_detail="missing; run ./install.sh",
        )
    )
    ok &= callbacks.print_check(
        path_check(
            "env file",
            context.env_file,
            missing_detail=f"missing; run {context.root_launcher} setup",
        )
    )
    if callbacks.openai_api_key_present():
        print("[ok] env: OPENAI_API_KEY")
    else:
        print(f"[missing] env: OPENAI_API_KEY (run {context.root_launcher} setup)")
        ok = False

    ok &= callbacks.print_check(
        path_check(
            "config file",
            context.config_file,
            missing_detail=f"missing; run {context.root_launcher} setup",
        )
    )
    if context.config_file.exists():
        config_error = callbacks.config_parse_error(context.config_file)
        if config_error is None:
            print(f"[ok] config: {context.config_file} parsed")
        else:
            print(f"[invalid] config: {context.config_file} ({config_error})")
            ok = False

    print("\nPorts")
    ok &= callbacks.report_port(context.backend_port)
    ok &= callbacks.report_port(context.frontend_port)

    print("\nReachability")
    callbacks.report_reachability("backend health", context.backend_health_url)
    callbacks.report_reachability("frontend", context.frontend_url)

    print("\nFrontend")
    frontend_tool_ok = callbacks.report_optional_command("bun") or callbacks.report_optional_command("npm")
    ok &= frontend_tool_ok
    if context.frontend_build_index.exists():
        print(f"[ok] frontend build: {context.frontend_build_index}")
    else:
        print(
            f"[warn] frontend build: missing at {context.frontend_build_index}; "
            f"run {context.root_launcher} service install or build frontend"
        )

    print("\nConnectors")
    ok &= callbacks.report_connector_status()

    print("\nExecutor node")
    try:
        enabled = callbacks.executor_enabled_families()
    except Exception as exc:
        print(f"[warn] executor node config: {exc}")
    else:
        if enabled:
            print(f"[ok] executor node config: enabled executors {', '.join(enabled)}")
        else:
            print(
                f"[warn] executor node config: no local executor families configured; "
                f"run {context.root_launcher} executor setup"
            )
    print(
        f"[info] executor node run: use {context.executor_invocation} executor run "
        "--base-url ... --node-id ... --token ..."
    )

    return 0 if ok else 1
