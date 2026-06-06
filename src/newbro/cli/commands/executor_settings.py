from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from newbro.cli import config_files
from newbro.executors.adapters.codex import probe as codex_probe


SUPPORTED_EXECUTORS = ["codex"]
BUN_INSTALL_URL = "https://bun.sh/install"
COMMAND_TIMEOUT_SECONDS = 300
SYSTEM_CURL = Path("/usr/bin/curl")
SYSTEM_BASH = Path("/bin/bash")


def run_executor_install_codex(args: Any, app: Any) -> int:
    config_path = app.ENV_LOCAL.with_name("config.yaml")
    try:
        command = install_codex_cli(config_path)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"Codex is ready: {command}")
    return 0


def run_executor_probe(args: Any, app: Any) -> int:
    if args.executor != "codex":
        print(f"Unsupported executor: {args.executor}", file=sys.stderr)
        return 1
    payload = codex_probe_payload(config_path=app.ENV_LOCAL.with_name("config.yaml"))
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_human_probe(payload)
    return 0


def run_executor_use(args: Any, app: Any) -> int:
    if args.executor != "codex":
        print(f"Unsupported executor: {args.executor}", file=sys.stderr)
        return 1
    command = str(args.executor_binary_command)
    if not os.path.isabs(command):
        print("Codex command must be an absolute path.", file=sys.stderr)
        return 1
    result = codex_probe.probe_codex_command(command)
    if not result.ok:
        print(result.error or "Codex command is not usable.", file=sys.stderr)
        return 1
    config_path = app.ENV_LOCAL.with_name("config.yaml")
    set_codex_command(config_path=config_path, command=command)
    print(f"Codex command set to {command}")
    return 0


def install_codex_cli(config_path: Path) -> str:
    existing_command = _first_usable_codex_command(config_path)
    if existing_command is not None:
        set_codex_command(config_path=config_path, command=existing_command)
        return existing_command

    env = _tool_environment()
    bun = shutil.which("bun", path=env.get("PATH"))
    if bun is None:
        print("Installing required runtime...")
        _install_required_runtime()
        env = _tool_environment()
        bun = shutil.which("bun", path=env.get("PATH"))
        if bun is None:
            raise RuntimeError("Codex setup failed while installing required runtime: bun is still unavailable.")

    print("Installing Codex...")
    _run_install_step([bun, "add", "-g", "@openai/codex"], "Codex setup failed while installing Codex.", env=env)

    print("Checking Codex...")
    command = _first_usable_codex_command(config_path)
    if command is None:
        command = _probe_installed_codex_command(bun)
    if command is None:
        raise RuntimeError("Codex setup finished, but codex --version is still unavailable.")
    set_codex_command(config_path=config_path, command=command)
    return command


def _install_required_runtime() -> None:
    if not SYSTEM_CURL.exists():
        raise RuntimeError(f"Codex setup failed while installing required runtime: {SYSTEM_CURL} is unavailable.")
    if not SYSTEM_BASH.exists():
        raise RuntimeError(f"Codex setup failed while installing required runtime: {SYSTEM_BASH} is unavailable.")

    env = _bootstrap_environment()
    with tempfile.TemporaryDirectory(prefix="newbro-codex-") as directory:
        installer = str(Path(directory) / "bun-install.sh")
        failure_message = "Codex setup failed while installing required runtime"
        _run_install_step(
            [str(SYSTEM_CURL), "-fsSL", BUN_INSTALL_URL, "-o", installer],
            failure_message,
            env=env,
        )
        _run_install_step([str(SYSTEM_BASH), installer], failure_message, env=env)


def _run_install_step(argv: list[str], failure_message: str, *, env: dict[str, str] | None = None) -> None:
    try:
        returncode = _run_logged(argv, env=env)
    except RuntimeError as exc:
        raise RuntimeError(f"{failure_message}: {exc}") from exc
    if returncode != 0:
        raise RuntimeError(failure_message)


def _first_usable_codex_command(config_path: Path) -> str | None:
    raw = config_files.load_existing_connector_yaml(config_path)
    executors = config_files.existing_executors_config(raw)
    configured_command = str((executors.get("codex") or {}).get("command") or "codex")
    for candidate in codex_probe.discover_codex_commands(configured_command=configured_command):
        result = codex_probe.probe_codex_command(candidate)
        if result.ok:
            return _absolute_command_path(result.path)
    return None


def _tool_environment() -> dict[str, str]:
    env = dict(os.environ)
    current_path = env.get("PATH", "")
    home = Path.home()
    preferred_paths = [
        str(home / ".bun" / "bin"),
        str(home / ".local" / "bin"),
    ]
    path_parts = preferred_paths + [part for part in current_path.split(os.pathsep) if part]
    env["PATH"] = os.pathsep.join(_dedupe_path_parts(path_parts))
    return env


def _bootstrap_environment() -> dict[str, str]:
    env = dict(os.environ)
    env["PATH"] = os.environ.get("PATH", "")
    return env


def _run_logged(
    argv: list[str],
    *,
    env: dict[str, str] | None = None,
    timeout_seconds: float = COMMAND_TIMEOUT_SECONDS,
) -> int:
    try:
        completed = subprocess.run(argv, check=False, env=env, timeout=timeout_seconds)
    except FileNotFoundError as exc:
        raise RuntimeError(f"Command not found: {argv[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Command timed out: {' '.join(argv)}") from exc
    return completed.returncode


def _probe_installed_codex_command(bun: str) -> str | None:
    candidates = [
        str(Path(bun).with_name("codex")),
        str(Path.home() / ".local" / "bin" / "codex"),
    ]
    for candidate in candidates:
        result = codex_probe.probe_codex_command(candidate)
        if result.ok:
            return _absolute_command_path(result.path)
    return None


def _absolute_command_path(command: str) -> str:
    path = Path(command).expanduser()
    if path.is_absolute():
        return str(path)
    resolved = shutil.which(command)
    if resolved:
        return resolved
    return str(path.resolve())


def _dedupe_path_parts(path_parts: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for part in path_parts:
        if part in seen:
            continue
        seen.add(part)
        result.append(part)
    return result


def codex_probe_payload(*, config_path: Path) -> dict[str, object]:
    raw = config_files.load_existing_connector_yaml(config_path)
    executors = config_files.existing_executors_config(raw)
    configured_command = str((executors.get("codex") or {}).get("command") or "codex")
    current_result = codex_probe.probe_codex_command(configured_command)
    candidates: list[dict[str, object]] = []
    current_path = current_result.path
    for candidate in codex_probe.discover_codex_commands(configured_command=configured_command):
        result = codex_probe.probe_codex_command(candidate)
        candidates.append(
            {
                "path": result.path,
                "version": result.version,
                "ok": result.ok,
                "source": "configured" if result.path == current_path else "discovered",
                "error": result.error,
                "is_current": result.path == current_path,
            }
        )
    return {
        "supported_executors": list(SUPPORTED_EXECUTORS),
        "current": {
            "executor": "codex",
            "command": configured_command,
            "resolved_path": current_result.path,
            "version": current_result.version,
            "ok": current_result.ok,
            "error": current_result.error,
        },
        "candidates": candidates,
    }


def set_codex_command(*, config_path: Path, command: str) -> None:
    raw = config_files.load_existing_connector_yaml(config_path)
    runtime = config_files.existing_runtime_config(raw, removed_keys=set())
    connector_host = config_files.existing_connector_host_config(raw)
    connectors = config_files.existing_connectors_config(raw)
    executor_node = config_files.existing_executor_node_config(raw)
    enabled = list(executor_node.get("enabled_executors") or [])
    if "codex" not in enabled:
        enabled.append("codex")
    executor_node["enabled_executors"] = enabled
    executors = config_files.existing_executors_config(raw)
    codex_config = dict(executors.get("codex") or {})
    codex_config["command"] = command
    executors["codex"] = codex_config
    rendered = config_files.render_connector_config(
        runtime=runtime,
        connector_host=connector_host,
        connectors=connectors,
        executor_node=executor_node,
        executors=executors,
    )
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(rendered, encoding="utf-8")


def _print_human_probe(payload: dict[str, object]) -> None:
    current = payload["current"]
    if isinstance(current, dict):
        status = "ok" if current.get("ok") else "broken"
        print(
            f"Codex current: {status} "
            f"{current.get('version') or ''} {current.get('resolved_path') or current.get('command')}"
        )
    print("Candidates:")
    for candidate in payload.get("candidates") or []:
        if not isinstance(candidate, dict):
            continue
        status = "ok" if candidate.get("ok") else "broken"
        selected = " *" if candidate.get("is_current") else ""
        detail = candidate.get("version") or candidate.get("error") or ""
        print(f"  [{status}]{selected} {candidate.get('path')} {detail}")
