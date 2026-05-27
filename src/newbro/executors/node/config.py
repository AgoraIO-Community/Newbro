from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from newbro.config_home import SYNAPSE_ENV_FILE, SYNAPSE_CONNECTOR_CONFIG_FILE
from newbro.envfile import load_env_file
from newbro.yaml_support import YAMLParseError, load_yaml_file


class ExecutorNodeConfigError(RuntimeError):
    pass


@dataclass(slots=True)
class ExecutorNodeSettings:
    synapse_base_url: str = "http://127.0.0.1:8000"
    node_id: str = ""
    token: str = ""
    enabled_executors: list[str] = field(default_factory=list)


@dataclass(slots=True)
class LoadedExecutorNodeConfig:
    node_settings: ExecutorNodeSettings
    executors: dict[str, Any] = field(default_factory=dict)
    audio: dict[str, Any] = field(default_factory=dict)
    source_path: Path | None = None


DEFAULT_ENV_FILE = SYNAPSE_ENV_FILE


def load_executor_node_config(
    *,
    env_file: Path | None = None,
    config_file: Path | None = None,
) -> LoadedExecutorNodeConfig:
    env_path = env_file or DEFAULT_ENV_FILE
    load_env_file(env_path, override=False)
    config_path = config_file or env_path.with_name(SYNAPSE_CONNECTOR_CONFIG_FILE.name)
    if not config_path.exists():
        return LoadedExecutorNodeConfig(node_settings=ExecutorNodeSettings(), executors={}, audio={}, source_path=None)
    try:
        raw = load_yaml_file(config_path)
    except YAMLParseError as exc:
        raise ExecutorNodeConfigError(f"Invalid executor node YAML at {config_path}: {exc}") from exc
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ExecutorNodeConfigError(f"Executor node config root must be a mapping: {config_path}")
    version = raw.get("version")
    if version not in (None, 1):
        raise ExecutorNodeConfigError(f"Unsupported executor node config version at {config_path}: {version}")

    node_settings = _parse_node_settings(
        _resolve_env_placeholders(raw.get("executor_node") or {}, config_path),
        config_path,
    )
    audio = _parse_audio_settings(
        _resolve_env_placeholders(raw.get("audio") or {}, config_path),
        config_path,
    )
    if not node_settings.enabled_executors:
        return LoadedExecutorNodeConfig(
            node_settings=node_settings,
            executors={},
            audio=audio,
            source_path=config_path,
        )
    raw_executors = raw.get("executors") or {}
    if not isinstance(raw_executors, dict):
        raise ExecutorNodeConfigError(f"'executors' must be a mapping in {config_path}")
    executors = {
        slug: _resolve_env_placeholders(raw_executors.get(slug), config_path)
        for slug in node_settings.enabled_executors
        if slug in raw_executors
    }
    return LoadedExecutorNodeConfig(
        node_settings=node_settings,
        executors=executors,
        audio=audio,
        source_path=config_path,
    )


def load_executor_node_settings(*, env_file: Path | None = None) -> ExecutorNodeSettings:
    return load_executor_node_config(env_file=env_file).node_settings


def generate_executor_node_id() -> str:
    return f"node-{uuid4().hex[:8]}"


def _resolve_env_placeholders(value: Any, config_path: Path) -> Any:
    if isinstance(value, dict):
        return {key: _resolve_env_placeholders(next_value, config_path) for key, next_value in value.items()}
    if isinstance(value, list):
        return [_resolve_env_placeholders(item, config_path) for item in value]
    if isinstance(value, str) and value.startswith("$") and value.count("$") == 1:
        env_name = value[1:]
        env_value = os.getenv(env_name)
        if env_value in (None, ""):
            raise ExecutorNodeConfigError(
                f"Missing environment variable {env_name} referenced by {config_path}"
            )
        return env_value
    return value


def _parse_node_settings(raw_host: Any, config_path: Path) -> ExecutorNodeSettings:
    if raw_host is None:
        raw_host = {}
    if not isinstance(raw_host, dict):
        raise ExecutorNodeConfigError(f"'executor_node' must be a mapping in {config_path}")
    enabled_executors = _parse_string_list(
        raw_host.get("enabled_executors") or [],
        field_name="executor_node.enabled_executors",
        config_path=config_path,
    )
    return ExecutorNodeSettings(
        synapse_base_url=str(raw_host.get("synapse_base_url", "http://127.0.0.1:8000")),
        node_id=str(raw_host.get("node_id", "")),
        token=str(raw_host.get("token", "")),
        enabled_executors=enabled_executors,
    )


def _parse_audio_settings(raw_audio: Any, config_path: Path) -> dict[str, Any]:
    if raw_audio is None:
        return {}
    if not isinstance(raw_audio, dict):
        raise ExecutorNodeConfigError(f"'audio' must be a mapping in {config_path}")
    return dict(raw_audio)


def _parse_string_list(value: Any, *, field_name: str, config_path: Path) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ExecutorNodeConfigError(f"'{field_name}' must be a list of strings in {config_path}")
    return [item.strip() for item in value]
