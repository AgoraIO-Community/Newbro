from __future__ import annotations

from pathlib import Path

from newbro.protocol import EXECUTOR_CONTROL_MAX_MESSAGE_BYTES


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
        "--ws-max-size",
        str(EXECUTOR_CONTROL_MAX_MESSAGE_BYTES),
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
        "--ws-max-size",
        str(EXECUTOR_CONTROL_MAX_MESSAGE_BYTES),
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
    audio_language: str | None = None,
    whisper_model: str | None = None,
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
    if audio_language:
        command.extend(["--audio-language", audio_language])
    if whisper_model:
        command.extend(["--whisper-model", whisper_model])
    return command


def frontend_install_command(frontend_tool: str) -> list[str]:
    if frontend_tool == "bun":
        return ["bun", "install"]
    return ["npm", "install"]


def frontend_build_command(frontend_tool: str) -> list[str]:
    if frontend_tool == "bun":
        return ["bun", "run", "build"]
    return ["npm", "run", "build"]


def frontend_dev_command(frontend_tool: str, host: str, port: int) -> list[str]:
    command = [
        frontend_tool,
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
    return command
