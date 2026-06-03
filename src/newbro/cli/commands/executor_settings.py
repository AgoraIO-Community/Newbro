from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from newbro.cli import config_files
from newbro.executors.adapters.codex import probe as codex_probe


SUPPORTED_EXECUTORS = ["codex"]


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
