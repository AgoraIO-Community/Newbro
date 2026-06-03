from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from newbro.config_home import SYNAPSE_ENV_FILE, SYNAPSE_CONNECTOR_CONFIG_FILE
from newbro.yaml_support import YAMLParseError, load_yaml_file


LOCAL_ENV_FILE = SYNAPSE_ENV_FILE
LOCAL_CONFIG_FILE = SYNAPSE_CONNECTOR_CONFIG_FILE
LEGACY_CODEX_COMMAND_KEY = "SYNAPSE_CODEX_COMMAND"
LEGACY_ACPX_COMMAND_KEY = "SYNAPSE_ACPX_COMMAND"
LEGACY_ACPX_AGENT_KEY = "SYNAPSE_ACPX_AGENT"
SUPPORTED_DETACHED_EXECUTOR_TYPES = ("codex", "acpx")


def load_local_env() -> None:
    load_dotenv(LOCAL_ENV_FILE, override=False)


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_csv(name: str) -> tuple[str, ...]:
    raw = os.getenv(name)
    if raw is None:
        return ()
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _parse_headers(raw: str | None) -> tuple[tuple[str, str], ...]:
    # "Authorization=Bearer x;X-Foo=bar" -> (("Authorization","Bearer x"),("X-Foo","bar"))
    if not raw:
        return ()
    pairs = []
    for part in raw.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            pairs.append((k.strip(), v.strip()))
    return tuple(pairs)


@dataclass(slots=True)
class Settings:
    app_name: str = "Newbro v2"
    communication_backend: str = "auto"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    openai_timeout_seconds: float = 30.0
    openai_base_url: str | None = None
    detached_executor_enabled: bool = False
    detached_executor_types: tuple[str, ...] = ("codex", "acpx")
    acpx_executor_enabled: bool = False
    acpx_command: str = "acpx"
    acpx_agent: str = "codex"
    acpx_permission_mode: str = "approve-all"
    acpx_non_interactive_permissions: str = "deny"
    acpx_timeout_seconds: float | None = None
    codex_executor_enabled: bool = False
    codex_command: str = "codex"
    codex_blocked_wait_timeout_seconds: float = 900.0
    log_level: str = "INFO"
    log_format: str = "auto"
    log_color: str = "auto"
    quiet_diagnostics_access_logs: bool = True
    log_llm_details: bool = False
    diagnostic_max_events: int = 500
    latency_export_enabled: bool = False
    latency_export_url: str | None = None
    latency_export_headers: tuple[tuple[str, str], ...] = ()
    latency_export_event_name: str = "turn.latency"
    latency_export_batch_size: int = 50
    latency_export_flush_seconds: float = 5.0
    latency_export_queue_max: int = 1000
    live_interaction_classifier_interval_seconds: float = 1.0
    cors_allowed_origins: tuple[str, ...] = ()
    git_sha: str | None = None
    connector_internal_token: str | None = None


def _load_shared_config() -> dict[str, Any]:
    if not LOCAL_CONFIG_FILE.exists():
        return {}
    try:
        loaded = load_yaml_file(LOCAL_CONFIG_FILE)
    except YAMLParseError as exc:
        raise RuntimeError(f"Invalid shared config YAML at {LOCAL_CONFIG_FILE}: {exc}") from exc
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise RuntimeError(f"Shared config root must be a mapping: {LOCAL_CONFIG_FILE}")
    return loaded


def _resolve_config_scalar(value: Any, *, config_path: Path) -> Any:
    if isinstance(value, str) and value.startswith("$") and value.count("$") == 1:
        env_name = value[1:]
        env_value = os.getenv(env_name)
        if env_value in (None, ""):
            raise RuntimeError(
                f"Missing environment variable {env_name} referenced by {config_path}"
            )
        return env_value
    return value


def _load_runtime_config() -> dict[str, Any]:
    raw_config = _load_shared_config()
    raw_runtime = raw_config.get("runtime") or {}
    if not isinstance(raw_runtime, dict):
        raise RuntimeError(f"'runtime' must be a mapping in {LOCAL_CONFIG_FILE}")
    return {
        key: _resolve_config_scalar(value, config_path=LOCAL_CONFIG_FILE)
        for key, value in raw_runtime.items()
    }


def load_settings() -> Settings:
    load_local_env()
    runtime_config = _load_runtime_config()
    yaml_codex_command = runtime_config.get("codex_command")
    yaml_acpx_command = runtime_config.get("acpx_command")
    yaml_acpx_agent = runtime_config.get("acpx_agent")
    yaml_acpx_permission_mode = runtime_config.get("acpx_permission_mode")
    yaml_acpx_non_interactive_permissions = runtime_config.get(
        "acpx_non_interactive_permissions"
    )
    yaml_acpx_timeout_seconds = runtime_config.get("acpx_timeout_seconds")
    yaml_codex_blocked_wait_timeout_seconds = runtime_config.get(
        "codex_blocked_wait_timeout_seconds"
    )
    codex_command = (
        str(yaml_codex_command)
        if yaml_codex_command not in (None, "")
        else os.getenv(LEGACY_CODEX_COMMAND_KEY, "codex")
    )
    acpx_command = (
        str(yaml_acpx_command)
        if yaml_acpx_command not in (None, "")
        else os.getenv(LEGACY_ACPX_COMMAND_KEY, "acpx")
    )
    acpx_agent = (
        str(yaml_acpx_agent)
        if yaml_acpx_agent not in (None, "")
        else os.getenv(LEGACY_ACPX_AGENT_KEY, "codex")
    )
    acpx_permission_mode = (
        str(yaml_acpx_permission_mode)
        if yaml_acpx_permission_mode not in (None, "")
        else os.getenv("SYNAPSE_ACPX_PERMISSION_MODE", "approve-all")
    )
    acpx_non_interactive_permissions = (
        str(yaml_acpx_non_interactive_permissions)
        if yaml_acpx_non_interactive_permissions not in (None, "")
        else os.getenv("SYNAPSE_ACPX_NON_INTERACTIVE_PERMISSIONS", "deny")
    )
    acpx_timeout_seconds = (
        float(yaml_acpx_timeout_seconds)
        if yaml_acpx_timeout_seconds not in (None, "")
        else float(os.getenv("SYNAPSE_ACPX_TIMEOUT_SECONDS"))
        if os.getenv("SYNAPSE_ACPX_TIMEOUT_SECONDS")
        else None
    )
    codex_blocked_wait_timeout_seconds = (
        float(yaml_codex_blocked_wait_timeout_seconds)
        if yaml_codex_blocked_wait_timeout_seconds not in (None, "")
        else float(os.getenv("SYNAPSE_CODEX_BLOCKED_WAIT_TIMEOUT_SECONDS", "900"))
    )
    return Settings(
        app_name=os.getenv("SYNAPSE_APP_NAME", "Newbro v2"),
        communication_backend=os.getenv("SYNAPSE_COMMUNICATION_BACKEND", "auto"),
        openai_api_key=os.getenv("OPENAI_API_KEY") or None,
        openai_model=os.getenv("SYNAPSE_OPENAI_MODEL", "gpt-4o-mini"),
        openai_timeout_seconds=float(os.getenv("SYNAPSE_OPENAI_TIMEOUT_SECONDS", "30")),
        openai_base_url=os.getenv("SYNAPSE_OPENAI_BASE_URL")
        or os.getenv("OPENAI_BASE_URL")
        or None,
        detached_executor_enabled=True,
        detached_executor_types=SUPPORTED_DETACHED_EXECUTOR_TYPES,
        acpx_executor_enabled=_get_bool("SYNAPSE_ACPX_EXECUTOR_ENABLED", False),
        acpx_command=acpx_command,
        acpx_agent=acpx_agent,
        acpx_permission_mode=acpx_permission_mode,
        acpx_non_interactive_permissions=acpx_non_interactive_permissions,
        acpx_timeout_seconds=acpx_timeout_seconds,
        codex_executor_enabled=_get_bool("SYNAPSE_CODEX_EXECUTOR_ENABLED", False),
        codex_command=codex_command,
        codex_blocked_wait_timeout_seconds=codex_blocked_wait_timeout_seconds,
        log_level=os.getenv("SYNAPSE_LOG_LEVEL", "INFO").upper(),
        log_format=os.getenv("SYNAPSE_LOG_FORMAT", "auto").lower(),
        log_color=os.getenv("SYNAPSE_LOG_COLOR", "auto").lower(),
        quiet_diagnostics_access_logs=_get_bool("SYNAPSE_QUIET_DIAGNOSTICS_ACCESS_LOGS", True),
        log_llm_details=_get_bool("SYNAPSE_LOG_LLM_DETAILS", False),
        diagnostic_max_events=int(os.getenv("SYNAPSE_DIAGNOSTIC_MAX_EVENTS", "500")),
        latency_export_enabled=os.getenv("SYNAPSE_LATENCY_EXPORT_ENABLED", "false").lower() == "true",
        latency_export_url=os.getenv("SYNAPSE_LATENCY_EXPORT_URL") or None,
        latency_export_headers=_parse_headers(os.getenv("SYNAPSE_LATENCY_EXPORT_HEADERS")),
        latency_export_event_name=os.getenv("SYNAPSE_LATENCY_EXPORT_EVENT_NAME", "turn.latency"),
        latency_export_batch_size=int(os.getenv("SYNAPSE_LATENCY_EXPORT_BATCH_SIZE", "50")),
        latency_export_flush_seconds=float(os.getenv("SYNAPSE_LATENCY_EXPORT_FLUSH_SECONDS", "5")),
        latency_export_queue_max=int(os.getenv("SYNAPSE_LATENCY_EXPORT_QUEUE_MAX", "1000")),
        live_interaction_classifier_interval_seconds=float(
            os.getenv("SYNAPSE_LIVE_INTERACTION_CLASSIFIER_INTERVAL_SECONDS", "1.0")
        ),
        cors_allowed_origins=_get_csv("SYNAPSE_CORS_ALLOWED_ORIGINS"),
        git_sha=os.getenv("SYNAPSE_GIT_SHA") or None,
        connector_internal_token=os.getenv("SYNAPSE_CONNECTOR_INTERNAL_TOKEN") or None,
    )


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise RuntimeError(f"Invalid boolean value in runtime config: {value!r}")


def _parse_string_list(value: Any, *, field_name: str) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(part.strip() for part in value.split(",") if part.strip())
    if isinstance(value, list):
        if any(not isinstance(item, str) or not item.strip() for item in value):
            raise RuntimeError(f"{field_name} must be a list of strings.")
        return tuple(item.strip() for item in value)
    if value in (None, ""):
        return ()
    raise RuntimeError(f"Invalid string-list value in runtime config: {value!r}")
