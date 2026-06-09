from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from newbro.cli.config_files import ConnectorSetupResult


CONNECTOR_ENABLED_KEY = "SYNAPSE_CONNECTOR_ENABLED"
CONNECTOR_HOST_KEY = "SYNAPSE_CONNECTOR_HOST"
CONNECTOR_PORT_KEY = "SYNAPSE_CONNECTOR_PORT"
CONNECTOR_PUBLIC_BASE_URL_KEY = "SYNAPSE_CONNECTOR_PUBLIC_BASE_URL"
CONNECTOR_SYNAPSE_BASE_URL_KEY = "SYNAPSE_CONNECTOR_SYNAPSE_BASE_URL"
CODEX_COMMAND_KEY = "SYNAPSE_CODEX_COMMAND"
ACPX_COMMAND_KEY = "SYNAPSE_ACPX_COMMAND"
ACPX_AGENT_KEY = "SYNAPSE_ACPX_AGENT"
ACPX_PERMISSION_MODE_KEY = "SYNAPSE_ACPX_PERMISSION_MODE"
ACPX_NON_INTERACTIVE_PERMISSIONS_KEY = "SYNAPSE_ACPX_NON_INTERACTIVE_PERMISSIONS"
ACPX_TIMEOUT_SECONDS_KEY = "SYNAPSE_ACPX_TIMEOUT_SECONDS"


@dataclass(frozen=True, slots=True)
class AgoraSetupCallbacks:
    prompt_text_value: Callable[..., str]
    prompt_secret_value: Callable[..., str]
    prompt_choice_value: Callable[..., str]
    pick_env_value: Callable[[str, dict[str, str], object], str | None]
    normalize_optional_value: Callable[[str | None], str | None]
    existing_connector_block: Callable[[dict[str, object], str], dict[str, object]]
    existing_nested_value: Callable[[dict[str, object], str, str], str | None]


@dataclass(frozen=True, slots=True)
class SetupResolutionCallbacks:
    connector_config_path: Callable[[], Path]
    coerce_bool_config_value: Callable[..., bool]
    existing_yaml_value: Callable[..., str | None]
    existing_executor_node_config: Callable[[dict[str, object]], dict[str, object]]
    existing_executors_config: Callable[[dict[str, object]], dict[str, dict[str, object]]]
    existing_connector_host_config: Callable[[dict[str, object]], dict[str, object]]
    existing_connectors_config: Callable[[dict[str, object]], dict[str, dict[str, object]]]
    existing_runtime_config: Callable[[dict[str, object]], dict[str, object]]
    existing_executor_enabled_types: Callable[[dict[str, object]], list[str]]
    resolved_runtime_config: Callable[[dict[str, object], dict[str, object] | None], dict[str, object]]
    default_connector_host_config: Callable[[], dict[str, object]]
    render_connector_config: Callable[..., str]
    pick_env_value: Callable[[str, dict[str, str], object], str | None]
    parse_bool_value: Callable[[str], bool | None]
    prompt_bool_value: Callable[..., bool]
    prompt_connector_selection: Callable[[], list[str]]
    prompt_text_value: Callable[..., str]
    prompt_executor_selection: Callable[..., list[str]]
    detected_codex_command: Callable[[], str | None]
    command_available: Callable[[str], bool]
    resolve_agora_connector_setup_values: Callable[..., tuple[dict[str, object], dict[str, str | None]]]


@dataclass(slots=True)
class CodexAutoSetupResult:
    setup: ConnectorSetupResult
    command: str


def resolve_connector_setup_values(
    *,
    existing_values: dict[str, str],
    environ: object,
    interactive: bool,
    force_prompt: bool,
    existing_config_yaml: dict[str, object],
    runtime_values: dict[str, object] | None,
    callbacks: SetupResolutionCallbacks,
) -> ConnectorSetupResult:
    if not interactive:
        return ConnectorSetupResult(env_values={})

    existing_enabled = callbacks.coerce_bool_config_value(
        callbacks.existing_yaml_value(existing_config_yaml, "connector_host", "enabled"),
        default=False,
    )
    if not existing_enabled:
        env_enabled = callbacks.pick_env_value(CONNECTOR_ENABLED_KEY, existing_values, environ)
        if env_enabled is not None:
            parsed = callbacks.parse_bool_value(env_enabled)
            if parsed is not None:
                existing_enabled = parsed
    should_configure = callbacks.prompt_bool_value(
        "Configure connector host",
        default=bool(existing_enabled or force_prompt),
    )
    if not should_configure:
        if not force_prompt:
            return ConnectorSetupResult(env_values={})
        return ConnectorSetupResult(
            env_values={},
            config_path=callbacks.connector_config_path(),
            config_text=callbacks.render_connector_config(
                runtime=callbacks.resolved_runtime_config(existing_config_yaml, runtime_values),
                connector_host=callbacks.default_connector_host_config(),
                connectors={},
                executor_node=callbacks.existing_executor_node_config(existing_config_yaml),
                executors=callbacks.existing_executors_config(existing_config_yaml),
            ),
        )

    config_path = callbacks.connector_config_path()

    connectors = callbacks.prompt_connector_selection()
    host = callbacks.prompt_text_value(
        "Connector host",
        default_value=callbacks.existing_yaml_value(existing_config_yaml, "connector_host", "host")
        or callbacks.pick_env_value(CONNECTOR_HOST_KEY, existing_values, environ)
        or "0.0.0.0",
        required=True,
    )
    port = callbacks.prompt_text_value(
        "Connector port",
        default_value=str(
            callbacks.existing_yaml_value(existing_config_yaml, "connector_host", "port")
            or callbacks.pick_env_value(CONNECTOR_PORT_KEY, existing_values, environ)
            or "8010"
        ),
        required=True,
    )
    public_base_url = callbacks.prompt_text_value(
        "Connector public base URL",
        default_value=callbacks.existing_yaml_value(existing_config_yaml, "connector_host", "public_base_url")
        or callbacks.pick_env_value(CONNECTOR_PUBLIC_BASE_URL_KEY, existing_values, environ)
        or str(callbacks.default_connector_host_config()["public_base_url"]),
        required=True,
    )
    synapse_base_url = callbacks.prompt_text_value(
        "Newbro service base URL for connector callbacks",
        default_value=callbacks.existing_yaml_value(existing_config_yaml, "connector_host", "synapse_base_url")
        or callbacks.pick_env_value(CONNECTOR_SYNAPSE_BASE_URL_KEY, existing_values, environ)
        or "http://127.0.0.1:8000",
        required=True,
    )

    resolved_env: dict[str, str | None] = {}
    connector_blocks: dict[str, dict[str, object]] = {}
    for connector in connectors:
        if connector == "agora-convoai":
            block, env_updates = callbacks.resolve_agora_connector_setup_values(
                existing_values,
                environ,
                existing_config_yaml,
            )
            connector_blocks[connector] = block
            resolved_env.update(env_updates)
    config_text = callbacks.render_connector_config(
        runtime=callbacks.resolved_runtime_config(existing_config_yaml, runtime_values),
        connector_host={
            "enabled": True,
            "host": host,
            "port": int(port),
            "public_base_url": public_base_url,
            "synapse_base_url": synapse_base_url,
            "enabled_connectors": connectors,
        },
        connectors=connector_blocks,
        executor_node=callbacks.existing_executor_node_config(existing_config_yaml),
        executors=callbacks.existing_executors_config(existing_config_yaml),
    )
    return ConnectorSetupResult(
        env_values=resolved_env,
        config_path=config_path,
        config_text=config_text,
    )


def resolve_executor_setup_values(
    *,
    existing_values: dict[str, str],
    environ: object,
    existing_config_yaml: dict[str, object],
    callbacks: SetupResolutionCallbacks,
) -> ConnectorSetupResult:
    del environ
    config_path = callbacks.connector_config_path()
    enabled_executors = callbacks.prompt_executor_selection(
        default_selected=callbacks.existing_executor_enabled_types(existing_config_yaml) or None
    )
    executors_block = callbacks.existing_executors_config(existing_config_yaml)
    for executor_type in enabled_executors:
        existing_block = executors_block.get(executor_type, {})
        if executor_type == "codex":
            command = callbacks.prompt_text_value(
                "Codex command",
                default_value=str(
                    existing_block.get("command")
                    or existing_values.get(CODEX_COMMAND_KEY)
                    or callbacks.detected_codex_command()
                    or "codex"
                ),
                required=True,
            )
            if not callbacks.command_available(command):
                print(f"[warn] command '{command}' is not currently available on PATH")
            executors_block["codex"] = {
                "command": command,
                "blocked_wait_timeout_seconds": float(
                    existing_block.get("blocked_wait_timeout_seconds") or 900.0
                ),
            }
        elif executor_type == "hermes":
            command = callbacks.prompt_text_value(
                "Hermes command",
                default_value=str(existing_block.get("command") or "hermes"),
                required=True,
            )
            if not callbacks.command_available(command):
                print(f"[warn] command '{command}' is not currently available on PATH")
            executors_block["hermes"] = {"command": command}
        elif executor_type == "acpx":
            executors_block["acpx"] = {
                "command": callbacks.prompt_text_value(
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

    config_text = callbacks.render_connector_config(
        runtime=callbacks.existing_runtime_config(existing_config_yaml),
        connector_host=callbacks.existing_connector_host_config(existing_config_yaml),
        connectors=callbacks.existing_connectors_config(existing_config_yaml),
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


def resolve_codex_auto_setup_values(
    *,
    existing_config_yaml: dict[str, object],
    callbacks: SetupResolutionCallbacks,
) -> CodexAutoSetupResult | None:
    command = callbacks.detected_codex_command()
    if not command or not callbacks.command_available(command):
        return None
    configured_command = "codex" if Path(command).name == "codex" else command

    executors_block = callbacks.existing_executors_config(existing_config_yaml)
    codex_block = dict(executors_block.get("codex", {}))
    codex_block["command"] = configured_command
    codex_block.setdefault("blocked_wait_timeout_seconds", 900.0)
    executors_block["codex"] = codex_block

    return CodexAutoSetupResult(
        command=configured_command,
        setup=ConnectorSetupResult(
            env_values={},
            config_path=callbacks.connector_config_path(),
            config_text=callbacks.render_connector_config(
                runtime=callbacks.existing_runtime_config(existing_config_yaml),
                connector_host=callbacks.existing_connector_host_config(existing_config_yaml),
                connectors=callbacks.existing_connectors_config(existing_config_yaml),
                executor_node={"enabled_executors": ["codex"]},
                executors=executors_block,
            ),
        ),
    )


def executor_runtime_config_complete(
    existing_config_yaml: dict[str, object],
    existing_values: dict[str, str],
    *,
    enabled_executors_override: list[str] | None = None,
    callbacks: SetupResolutionCallbacks,
) -> bool:
    enabled_executors = enabled_executors_override or callbacks.existing_executor_enabled_types(existing_config_yaml)
    if not enabled_executors:
        return False
    executors_block = callbacks.existing_executors_config(existing_config_yaml)
    return all(
        executor_runtime_ready(
            executor_type,
            existing_block=executors_block.get(executor_type, {}),
            existing_values=existing_values,
            callbacks=callbacks,
        )
        for executor_type in enabled_executors
    )


def executor_runtime_ready(
    executor_type: str,
    *,
    existing_block: dict[str, object],
    existing_values: dict[str, str],
    callbacks: SetupResolutionCallbacks,
) -> bool:
    if executor_type == "codex":
        command = str(
            existing_block.get("command")
            or existing_values.get(CODEX_COMMAND_KEY)
            or callbacks.detected_codex_command()
            or ""
        ).strip()
        return bool(command) and callbacks.command_available(command)
    if executor_type == "acpx":
        command = str(
            existing_block.get("command")
            or existing_values.get(ACPX_COMMAND_KEY)
            or "acpx"
        ).strip()
        return bool(command) and callbacks.command_available(command)
    # Generic families (e.g. hermes): default the command to the family name and
    # PATH-check it, matching what the executor node's _build_executors already does.
    command = str(existing_block.get("command") or executor_type).strip()
    return bool(command) and callbacks.command_available(command)


def resolve_agora_connector_setup_values(
    existing_values: dict[str, str],
    environ: object,
    existing_connector_yaml: dict[str, object],
    callbacks: AgoraSetupCallbacks,
) -> tuple[dict[str, object], dict[str, str | None]]:
    env_updates: dict[str, str | None] = {}
    existing_connector = callbacks.existing_connector_block(existing_connector_yaml, "agora-convoai")

    app_id = callbacks.prompt_text_value(
        "Agora App ID",
        default_value=callbacks.pick_env_value("AGORA_APP_ID", existing_values, environ) or "",
        required=True,
    )
    app_certificate = callbacks.prompt_secret_value(
        "Agora App Certificate",
        default_value=callbacks.pick_env_value("AGORA_APP_CERTIFICATE", existing_values, environ),
    )
    env_updates["AGORA_APP_ID"] = app_id
    env_updates["AGORA_APP_CERTIFICATE"] = app_certificate

    asr_mode = callbacks.prompt_choice_value(
        "ASR credential mode",
        choices=["managed", "byok"],
        default_value=str(
            callbacks.existing_nested_value(existing_connector, "asr", "credential_mode") or "managed"
        ),
    )
    asr_model = callbacks.prompt_choice_value(
        "ASR model",
        choices=["nova-3", "nova-2"],
        default_value=str(callbacks.existing_nested_value(existing_connector, "asr", "model") or "nova-3"),
    )
    asr_language = callbacks.prompt_text_value(
        "ASR language",
        default_value=str(callbacks.existing_nested_value(existing_connector, "asr", "language") or "en-US"),
        required=True,
    )
    asr_block: dict[str, object] = {
        "vendor": "deepgram",
        "credential_mode": asr_mode,
        "model": asr_model,
        "language": asr_language,
    }
    if asr_mode == "byok":
        deepgram_api_key = callbacks.prompt_secret_value(
            "Deepgram API Key",
            default_value=callbacks.pick_env_value("DEEPGRAM_API_KEY", existing_values, environ),
        )
        env_updates["DEEPGRAM_API_KEY"] = deepgram_api_key
        asr_block["api_key"] = "$DEEPGRAM_API_KEY"

    tts_vendor = callbacks.prompt_choice_value(
        "TTS vendor",
        choices=["minimax", "openai", "elevenlabs"],
        default_value=str(callbacks.existing_nested_value(existing_connector, "tts", "vendor") or "minimax"),
    )
    if tts_vendor == "minimax":
        tts_block: dict[str, object] = {
            "vendor": "minimax",
            "credential_mode": "managed",
            "model": callbacks.prompt_choice_value(
                "TTS model",
                choices=["speech_2_6_turbo", "speech_2_8_turbo"],
                default_value=str(
                    callbacks.existing_nested_value(existing_connector, "tts", "model")
                    or "speech_2_6_turbo"
                ),
            ),
            "voice": callbacks.normalize_optional_value(
                callbacks.prompt_text_value(
                    "TTS voice",
                    default_value=(
                        callbacks.existing_nested_value(existing_connector, "tts", "voice")
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
            "voice": callbacks.normalize_optional_value(
                callbacks.prompt_text_value(
                    "TTS voice",
                    default_value=callbacks.existing_nested_value(existing_connector, "tts", "voice") or "alloy",
                )
            )
            or "alloy",
            "sample_rate": None,
        }
    else:
        elevenlabs_api_key = callbacks.prompt_secret_value(
            "ElevenLabs API Key",
            default_value=callbacks.pick_env_value("ELEVENLABS_API_KEY", existing_values, environ),
        )
        env_updates["ELEVENLABS_API_KEY"] = elevenlabs_api_key
        tts_block = {
            "vendor": "elevenlabs",
            "credential_mode": "byok",
            "model": callbacks.prompt_text_value(
                "TTS model",
                default_value=str(
                    callbacks.existing_nested_value(existing_connector, "tts", "model")
                    or "eleven_flash_v2_5"
                ),
                required=True,
            ),
            "voice": callbacks.normalize_optional_value(
                callbacks.prompt_text_value(
                    "TTS voice",
                    default_value=callbacks.existing_nested_value(existing_connector, "tts", "voice"),
                    required=True,
                )
            ),
            "api_key": "$ELEVENLABS_API_KEY",
            "sample_rate": int(
                callbacks.prompt_text_value(
                    "TTS sample rate",
                    default_value=str(
                        callbacks.existing_nested_value(existing_connector, "tts", "sample_rate") or "24000"
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
