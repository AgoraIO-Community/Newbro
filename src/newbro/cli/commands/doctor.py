from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from newbro.cli.checks import CheckResult, path_check


@dataclass(frozen=True, slots=True)
class DoctorContext:
    root_launcher: str
    python_executable: str
    env_file: Path
    venv_dir: Path
    venv_python: Path
    backend_port: int
    frontend_port: int


@dataclass(frozen=True, slots=True)
class DoctorCallbacks:
    report_path: Callable[[str, str], bool]
    report_command: Callable[[str], bool]
    report_optional_command: Callable[[str], bool]
    report_port: Callable[[int], bool]
    print_check: Callable[[CheckResult], bool]
    openai_api_key_present: Callable[[], bool]
    report_connector_status: Callable[[], bool]


def run_doctor(context: DoctorContext, callbacks: DoctorCallbacks) -> int:
    ok = True
    ok &= callbacks.report_path("python", context.python_executable)
    ok &= callbacks.report_command("bun") or callbacks.report_command("npm")
    callbacks.report_optional_command("docker")

    venv_result = path_check(
        "virtualenv",
        context.venv_python,
        missing_detail="missing; run ./install.sh",
    )
    if venv_result.ok:
        print(f"[ok] virtualenv: {context.venv_dir.name}")
        print(f"[ok] venv python: {context.venv_python}")
    else:
        print("[missing] virtualenv: run ./install.sh")
        ok = False

    ok &= callbacks.report_port(context.backend_port)
    ok &= callbacks.report_port(context.frontend_port)

    env_result = path_check(
        "env file",
        context.env_file,
        missing_detail=f"run {context.root_launcher} setup",
    )
    ok &= callbacks.print_check(env_result)

    if callbacks.openai_api_key_present():
        print("[ok] env: OPENAI_API_KEY")
    else:
        print(f"[missing] env: OPENAI_API_KEY (run {context.root_launcher} setup)")
        ok = False

    ok &= callbacks.report_connector_status()

    return 0 if ok else 1
