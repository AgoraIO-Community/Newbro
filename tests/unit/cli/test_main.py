from __future__ import annotations

import builtins
import importlib
from pathlib import Path

from newbro.config_home import ConfigHomeMigrationResult
from newbro.protocol import EXECUTOR_CONTROL_MAX_MESSAGE_BYTES

cli_main = importlib.import_module("newbro.cli.main")


class FakeCompletedProcess:
    def __init__(self, returncode: int = 0):
        self.returncode = returncode


def test_frontend_tool_prefers_bun(monkeypatch):
    monkeypatch.setattr(cli_main.shutil, "which", lambda name: f"/usr/bin/{name}" if name in {"bun", "npm"} else None)

    assert cli_main.preferred_frontend_tool() == "bun"


def test_frontend_tool_falls_back_to_npm(monkeypatch):
    monkeypatch.setattr(cli_main.shutil, "which", lambda name: "/usr/bin/npm" if name == "npm" else None)

    assert cli_main.preferred_frontend_tool() == "npm"


def test_frontend_dev_command_passes_explicit_vite_config_for_bun(monkeypatch):
    monkeypatch.setattr(cli_main.shutil, "which", lambda name: f"/usr/bin/{name}" if name == "bun" else None)

    assert cli_main.frontend_dev_command("0.0.0.0", 5173) == [
        "bun",
        "run",
        "dev",
        "--",
        "--host",
        "0.0.0.0",
        "--port",
        "5173",
        "--config",
        "vite.config.ts",
    ]


def test_frontend_dev_command_passes_explicit_vite_config_for_npm(monkeypatch):
    monkeypatch.setattr(cli_main.shutil, "which", lambda name: "/usr/bin/npm" if name == "npm" else None)

    assert cli_main.frontend_dev_command("127.0.0.1", 15173) == [
        "npm",
        "run",
        "dev",
        "--",
        "--host",
        "127.0.0.1",
        "--port",
        "15173",
        "--config",
        "vite.config.ts",
    ]


def test_executor_node_command_passes_audio_overrides():
    assert cli_main.executor_node_command(
        Path("/tmp/newbro/.venv/bin/python"),
        base_url="http://127.0.0.1:8000",
        node_id="node-1",
        token="token-1",
        enabled_executors=["codex"],
        audio_language="zh",
        whisper_model="small",
    ) == [
        "/tmp/newbro/.venv/bin/python",
        "-m",
        "newbro.executors.node",
        "--base-url",
        "http://127.0.0.1:8000",
        "--node-id",
        "node-1",
        "--token",
        "token-1",
        "--enabled-executor",
        "codex",
        "--audio-language",
        "zh",
        "--whisper-model",
        "small",
    ]


def test_backend_command_sets_executor_control_websocket_limit():
    assert cli_main.command_specs.backend_command(
        Path("/tmp/newbro/.venv/bin/python"),
        "127.0.0.1",
        8000,
        reload=False,
    ) == [
        "/tmp/newbro/.venv/bin/python",
        "-m",
        "uvicorn",
        "newbro.api.app:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
        "--ws-max-size",
        str(EXECUTOR_CONTROL_MAX_MESSAGE_BYTES),
    ]


def test_service_command_sets_executor_control_websocket_limit():
    assert cli_main.command_specs.service_command(
        Path("/tmp/newbro/.venv/bin/python"),
        "0.0.0.0",
        8000,
        reload=False,
    ) == [
        "/tmp/newbro/.venv/bin/python",
        "-m",
        "uvicorn",
        "newbro.service.app:app",
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
        "--ws-max-size",
        str(EXECUTOR_CONTROL_MAX_MESSAGE_BYTES),
    ]


def configure_repo_paths(monkeypatch, root: Path) -> None:
    monkeypatch.setattr(cli_main, "ROOT", root)
    monkeypatch.setattr(cli_main, "FRONTEND", root / "src" / "newbro" / "ui")
    monkeypatch.setattr(cli_main, "VENV_DIR", root / ".venv")
    monkeypatch.setattr(cli_main, "LEGACY_SYNAPSE_HOME_DIR", root / ".synapse")
    monkeypatch.setattr(cli_main, "NEWBRO_HOME_DIR", root / ".newbro")
    monkeypatch.setattr(cli_main, "ENV_LOCAL", root / ".newbro" / ".env")


def force_yaml_fallback(monkeypatch) -> None:
    original_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "yaml":
            raise ModuleNotFoundError("No module named 'yaml'")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)


def test_main_runs_newbro_home_migration_before_commands(monkeypatch, tmp_path: Path):
    configure_repo_paths(monkeypatch, tmp_path)
    migration_calls: list[dict[str, Path]] = []
    monkeypatch.setattr(
        cli_main,
        "ensure_newbro_home",
        lambda **kwargs: migration_calls.append(kwargs) or ConfigHomeMigrationResult(migrated=False),
    )
    monkeypatch.setattr(cli_main, "bootstrap_setup_files", lambda: None)

    assert cli_main.main(["setup", "--bootstrap-defaults"]) == 0
    assert migration_calls == [
        {
            "legacy_home": tmp_path / ".synapse",
            "new_home": tmp_path / ".newbro",
        }
    ]


def test_main_prints_non_fatal_newbro_home_migration_warning(
    monkeypatch,
    tmp_path: Path,
    capsys,
):
    configure_repo_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(
        cli_main,
        "ensure_newbro_home",
        lambda **_kwargs: ConfigHomeMigrationResult(
            migrated=True,
            warning="Migrated config to ~/.newbro but could not remove ~/.newbro.",
        ),
    )
    monkeypatch.setattr(cli_main, "bootstrap_setup_files", lambda: None)

    assert cli_main.main(["setup", "--bootstrap-defaults"]) == 0

    assert "[warn] Migrated config to ~/.newbro but could not remove ~/.newbro." in capsys.readouterr().err


def test_invite_create_writes_public_auth_store(monkeypatch, tmp_path: Path, capsys):
    from newbro.api import public_auth

    configure_repo_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(
        cli_main,
        "ensure_newbro_home",
        lambda **_kwargs: ConfigHomeMigrationResult(migrated=False),
    )
    monkeypatch.setattr(public_auth, "PUBLIC_AUTH_DB", tmp_path / ".newbro" / "public_auth.sqlite3")

    assert cli_main.main(["invite", "create", "friend-code", "--email", "User@Example.com"]) == 0
    assert capsys.readouterr().out.strip() == "friend-code"

    redeemed = cli_main.asyncio.run(public_auth.PublicAuthStore().redeem_invite("friend-code"))
    assert redeemed.user.email == "user@example.com"


def test_setup_interactive_updates_env_file(monkeypatch, tmp_path: Path):
    root = tmp_path
    (root / "src" / "newbro" / "ui").mkdir(parents=True)
    (root / ".newbro").mkdir(parents=True, exist_ok=True)
    (root / ".newbro" / ".env").write_text(
        "SYNAPSE_OPENAI_MODEL=gpt-4.1-mini\nEXTRA_FLAG=keep-me\n",
        encoding="utf-8",
    )

    configure_repo_paths(monkeypatch, root)
    monkeypatch.setattr(cli_main, "setup_can_prompt", lambda: True)
    monkeypatch.setattr(cli_main.getpass, "getpass", lambda _prompt: "sk-test")
    monkeypatch.setattr("builtins.input", lambda _prompt: "")

    assert cli_main.main(["setup"]) == 0

    configured = (root / ".newbro" / ".env").read_text(encoding="utf-8")
    assert "OPENAI_API_KEY=sk-test" in configured
    assert "SYNAPSE_OPENAI_MODEL=gpt-4.1-mini" in configured
    assert configured.strip().endswith("EXTRA_FLAG=keep-me")

    configured_runtime = (root / ".newbro" / "config.yaml").read_text(encoding="utf-8")
    assert "runtime: {}" in configured_runtime
    assert "detached_executor_enabled" not in configured_runtime
    assert "detached_executor_types" not in configured_runtime
    assert "executor_node:" in configured_runtime
    assert "executors: {}" in configured_runtime
    assert "host_token" not in configured_runtime
    assert "heartbeat_seconds" not in configured_runtime
    assert "enabled_executors: []" in configured_runtime


def test_setup_interactive_can_configure_connector_host(monkeypatch, tmp_path: Path):
    root = tmp_path
    (root / "src" / "newbro" / "ui").mkdir(parents=True)
    (root / ".newbro").mkdir(parents=True, exist_ok=True)

    configure_repo_paths(monkeypatch, root)
    monkeypatch.setattr(cli_main, "setup_can_prompt", lambda: True)
    monkeypatch.setattr(cli_main, "list_available_connector_modules", lambda: ["agora-convoai"])
    secret_responses = iter(["sk-test", "app-cert"])
    monkeypatch.setattr(cli_main.getpass, "getpass", lambda _prompt: next(secret_responses))

    allowed_empty_prompts = {
        "Select connectors [1]: ",
        "Connector host [0.0.0.0]: ",
        "Connector port [8010]: ",
        "Connector public base URL [http://127.0.0.1:8000]: ",
        "Newbro service base URL for connector callbacks [http://127.0.0.1:8000]: ",
        "ASR credential mode [managed]: ",
        "ASR model [nova-3]: ",
        "ASR language [en-US]: ",
        "TTS vendor [minimax]: ",
        "TTS model [speech_2_6_turbo]: ",
        "TTS voice [English_magnetic_voiced_man]: ",
    }

    def fake_input(prompt: str) -> str:
        if prompt == "Configure connector host [y/N]: ":
            return "yes"
        if prompt.startswith("Agora App ID"):
            return "agora-app"
        if prompt in allowed_empty_prompts:
            return ""
        raise AssertionError(f"Unexpected prompt: {prompt}")

    monkeypatch.setattr("builtins.input", fake_input)

    assert cli_main.main(["setup"]) == 0

    configured_runtime = (root / ".newbro" / "config.yaml").read_text(encoding="utf-8")
    assert "detached_executor_enabled" not in configured_runtime
    assert "detached_executor_types:" not in configured_runtime
    assert "enabled_connectors:" in configured_runtime
    assert "- agora-convoai" in configured_runtime
    assert "app_id: $AGORA_APP_ID" in configured_runtime


def test_executor_setup_uses_detected_codex_command_default(monkeypatch, tmp_path: Path):
    root = tmp_path
    (root / "src" / "newbro" / "ui").mkdir(parents=True)
    (root / ".newbro").mkdir(parents=True, exist_ok=True)
    (root / ".newbro" / "config.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "runtime: {}",
                "connector_host:",
                "  enabled: false",
                "  host: 0.0.0.0",
                "  port: 8010",
                '  public_base_url: "http://127.0.0.1:8000"',
                '  synapse_base_url: "http://127.0.0.1:8000"',
                "  enabled_connectors: []",
                "connectors: {}",
                "executor_node:",
                "  enabled_executors: []",
                "executors: {}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    configure_repo_paths(monkeypatch, root)
    monkeypatch.setattr(cli_main, "setup_can_prompt", lambda: True)
    monkeypatch.setattr(cli_main, "_detected_codex_command", lambda: "/detected/codex")
    monkeypatch.setattr(
        cli_main,
        "_command_available",
        lambda command: command == "/detected/codex",
    )
    responses = iter(["", "", "", ""])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))

    assert cli_main.main(["executor", "setup"]) == 0

    configured_runtime = (root / ".newbro" / "config.yaml").read_text(encoding="utf-8")
    assert "detached_executor_enabled" not in configured_runtime
    assert "detached_executor_types:" not in configured_runtime
    assert "executor_node:" in configured_runtime
    assert "command: /detected/codex" in configured_runtime
    assert "host_token" not in configured_runtime
    assert "heartbeat_seconds" not in configured_runtime
    assert "enabled_executors:" in configured_runtime
    assert "node_id:" not in configured_runtime


def test_executor_setup_migrates_legacy_codex_command_over_detected_default(
    monkeypatch,
    tmp_path: Path,
):
    root = tmp_path
    (root / "src" / "newbro" / "ui").mkdir(parents=True)
    (root / ".newbro").mkdir(parents=True, exist_ok=True)
    (root / ".newbro" / ".env").write_text(
        "\n".join(
            [
                "OPENAI_API_KEY=sk-existing",
                "SYNAPSE_CODEX_EXECUTOR_ENABLED=true",
                "SYNAPSE_CODEX_COMMAND=/legacy/codex",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (root / ".newbro" / "config.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "runtime: {}",
                "connector_host:",
                "  enabled: false",
                "  host: 0.0.0.0",
                "  port: 8010",
                '  public_base_url: "http://127.0.0.1:8000"',
                '  synapse_base_url: "http://127.0.0.1:8000"',
                "  enabled_connectors: []",
                "connectors: {}",
                "executor_node:",
                "  enabled_executors: []",
                "executors: {}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    configure_repo_paths(monkeypatch, root)
    monkeypatch.setattr(cli_main, "setup_can_prompt", lambda: True)
    monkeypatch.setattr(cli_main, "_detected_codex_command", lambda: "/detected/codex")
    monkeypatch.setattr(
        cli_main,
        "_command_available",
        lambda command: command in {"/legacy/codex", "/detected/codex"},
    )
    responses = iter(["", "", "", ""])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))

    assert cli_main.main(["executor", "setup"]) == 0

    configured_env = (root / ".newbro" / ".env").read_text(encoding="utf-8")
    configured_runtime = (root / ".newbro" / "config.yaml").read_text(encoding="utf-8")
    assert "command: /legacy/codex" in configured_runtime
    assert "command: /detected/codex" not in configured_runtime
    assert "SYNAPSE_CODEX_COMMAND=/legacy/codex" not in configured_env
    assert "host_token" not in configured_runtime
    assert "heartbeat_seconds" not in configured_runtime


def test_connector_setup_writes_connector_module_env(monkeypatch, tmp_path: Path):
    root = tmp_path
    (root / "src" / "newbro" / "ui").mkdir(parents=True)

    configure_repo_paths(monkeypatch, root)
    monkeypatch.setattr(cli_main, "setup_can_prompt", lambda: True)
    monkeypatch.setattr(cli_main, "list_available_connector_modules", lambda: ["agora-convoai"])
    secret_responses = iter(["app-cert"])
    monkeypatch.setattr(cli_main.getpass, "getpass", lambda _prompt: next(secret_responses))

    allowed_empty_prompts = {
        "Configure connector host [y/N]: ",
        "Configure connector host [Y/n]: ",
        "Select connectors [1]: ",
        "Connector host [0.0.0.0]: ",
        "Connector port [8010]: ",
        "Connector public base URL [http://127.0.0.1:8000]: ",
        "Newbro service base URL for connector callbacks [http://127.0.0.1:8000]: ",
        "ASR credential mode [managed]: ",
        "ASR model [nova-3]: ",
        "ASR language [en-US]: ",
        "TTS vendor [minimax]: ",
        "TTS model [speech_2_6_turbo]: ",
        "TTS voice [English_magnetic_voiced_man]: ",
    }

    def fake_input(prompt: str) -> str:
        if prompt.startswith("Agora App ID"):
            return "agora-app"
        if prompt in allowed_empty_prompts:
            return ""
        raise AssertionError(f"Unexpected prompt: {prompt}")

    monkeypatch.setattr("builtins.input", fake_input)

    assert cli_main.main(["connector", "setup"]) == 0

    configured = (root / ".newbro" / ".env").read_text(encoding="utf-8")
    assert "AGORA_APP_ID=agora-app" in configured
    assert "AGORA_APP_CERTIFICATE=app-cert" in configured

    connector_config = (root / ".newbro" / "config.yaml").read_text(encoding="utf-8")
    assert "runtime: {}" in connector_config
    assert "enabled_connectors:" in connector_config
    assert "- agora-convoai" in connector_config
    assert "app_id: $AGORA_APP_ID" in connector_config
    assert "convoai_area: US" in connector_config
    assert "credential_mode: managed" in connector_config
    assert "vendor: minimax" in connector_config
    assert "voice: English_magnetic_voiced_man" in connector_config


def test_connector_setup_decline_disables_existing_connector_config(monkeypatch, tmp_path: Path):
    root = tmp_path
    (root / "src" / "newbro" / "ui").mkdir(parents=True)
    configure_repo_paths(monkeypatch, root)
    monkeypatch.setattr(cli_main, "setup_can_prompt", lambda: True)
    (root / ".newbro").mkdir(parents=True, exist_ok=True)
    (root / ".newbro" / "config.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "runtime:",
                "  codex_command: /existing/codex",
                "connector_host:",
                "  enabled: true",
                "  enabled_connectors:",
                "    - agora-convoai",
                "connectors:",
                "  agora-convoai:",
                "    app_id: $AGORA_APP_ID",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: "no")

    assert cli_main.main(["connector", "setup"]) == 0

    configured = (root / ".newbro" / "config.yaml").read_text(encoding="utf-8")
    assert "codex_command: /existing/codex" in configured
    assert "enabled: false" in configured
    assert "enabled_connectors:" in configured


def test_connector_setup_reads_existing_legacy_empty_connectors_config_with_yaml_fallback(
    monkeypatch,
    tmp_path: Path,
):
    root = tmp_path
    (root / "src" / "newbro" / "ui").mkdir(parents=True)
    (root / ".newbro").mkdir(parents=True, exist_ok=True)
    (root / ".newbro" / "config.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "connector_host:",
                "  enabled: false",
                "  host: 0.0.0.0",
                "  port: 8010",
                '  public_base_url: "http://127.0.0.1:8000"',
                '  synapse_base_url: "http://127.0.0.1:8000"',
                "  enabled_connectors:",
                "connectors:",
                "  {}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    configure_repo_paths(monkeypatch, root)
    monkeypatch.setattr(cli_main, "setup_can_prompt", lambda: True)
    monkeypatch.setattr(cli_main, "list_available_connector_modules", lambda: ["agora-convoai"])
    force_yaml_fallback(monkeypatch)

    secret_responses = iter(["app-cert"])
    monkeypatch.setattr(cli_main.getpass, "getpass", lambda _prompt: next(secret_responses))

    allowed_empty_prompts = {
        "Select connectors [1]: ",
        "Connector host [0.0.0.0]: ",
        "Connector port [8010]: ",
        "Connector public base URL [http://127.0.0.1:8000]: ",
        "Newbro service base URL for connector callbacks [http://127.0.0.1:8000]: ",
        "ASR credential mode [managed]: ",
        "ASR model [nova-3]: ",
        "ASR language [en-US]: ",
        "TTS vendor [minimax]: ",
        "TTS model [speech_2_6_turbo]: ",
        "TTS voice [English_magnetic_voiced_man]: ",
    }

    def fake_input(prompt: str) -> str:
        if prompt in {"Configure connector host [y/N]: ", "Configure connector host [Y/n]: "}:
            return "y"
        if prompt.startswith("Agora App ID"):
            return "agora-app"
        if prompt in allowed_empty_prompts:
            return ""
        raise AssertionError(f"Unexpected prompt: {prompt}")

    monkeypatch.setattr("builtins.input", fake_input)

    assert cli_main.main(["connector", "setup"]) == 0

    configured = (root / ".newbro" / "config.yaml").read_text(encoding="utf-8")
    assert "connectors:\n  {}" not in configured
    assert "connectors:" in configured
    assert "app_id: $AGORA_APP_ID" in configured


def test_connector_listing_and_settings_do_not_require_fastapi(monkeypatch, tmp_path: Path):
    root = tmp_path
    (root / "src" / "newbro" / "ui").mkdir(parents=True)
    (root / ".newbro").mkdir(parents=True, exist_ok=True)
    (root / ".newbro" / ".env").write_text(
        "\n".join(
            [
                "OPENAI_API_KEY=test-key",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (root / ".newbro" / "config.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "connector_host:",
                "  enabled: true",
                "  enabled_connectors:",
                "    - agora-convoai",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    configure_repo_paths(monkeypatch, root)

    original_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name.startswith("fastapi"):
            raise ModuleNotFoundError("No module named 'fastapi'")
        if name.startswith("dotenv"):
            raise ModuleNotFoundError("No module named 'dotenv'")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    assert cli_main.list_available_connector_modules() == ["agora-convoai"]
    settings = cli_main.load_connector_settings()
    assert settings.enabled is True
    assert settings.enabled_connectors == ["agora-convoai"]


def test_setup_non_interactive_uses_existing_and_env(monkeypatch, tmp_path: Path):
    root = tmp_path
    (root / "src" / "newbro" / "ui").mkdir(parents=True)

    configure_repo_paths(monkeypatch, root)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")

    assert cli_main.main(["setup", "--non-interactive"]) == 0

    configured = (root / ".newbro" / ".env").read_text(encoding="utf-8")
    assert "OPENAI_API_KEY=sk-env" in configured
    assert "SYNAPSE_CODEX_EXECUTOR_ENABLED" not in configured
    assert "SYNAPSE_CODEX_COMMAND" not in configured
    configured_runtime = (root / ".newbro" / "config.yaml").read_text(encoding="utf-8")
    assert "runtime: {}" in configured_runtime
    assert "executor_node:" in configured_runtime
    assert "executors: {}" in configured_runtime


def test_executor_setup_migrates_legacy_codex_command_to_config(monkeypatch, tmp_path: Path):
    root = tmp_path
    (root / "src" / "newbro" / "ui").mkdir(parents=True)
    (root / ".newbro").mkdir(parents=True, exist_ok=True)
    (root / ".newbro" / ".env").write_text(
        "\n".join(
            [
                "OPENAI_API_KEY=test-key",
                "SYNAPSE_CODEX_EXECUTOR_ENABLED=true",
                "SYNAPSE_CODEX_COMMAND=/legacy/codex",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (root / ".newbro" / "config.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "runtime: {}",
                "connector_host:",
                "  enabled: false",
                "  host: 0.0.0.0",
                "  port: 8010",
                '  public_base_url: "http://127.0.0.1:8000"',
                '  synapse_base_url: "http://127.0.0.1:8000"',
                "  enabled_connectors: []",
                "connectors: {}",
                "executor_node:",
                "  enabled_executors: []",
                "executors: {}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    configure_repo_paths(monkeypatch, root)
    monkeypatch.setattr(cli_main, "setup_can_prompt", lambda: True)
    monkeypatch.setattr(cli_main, "_command_available", lambda command: command == "/legacy/codex")
    responses = iter(["", "", "", ""])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))

    assert cli_main.main(["executor", "setup"]) == 0

    configured_env = (root / ".newbro" / ".env").read_text(encoding="utf-8")
    assert "SYNAPSE_CODEX_COMMAND=/legacy/codex" not in configured_env
    assert "SYNAPSE_CODEX_EXECUTOR_ENABLED=true" not in configured_env

    configured_runtime = (root / ".newbro" / "config.yaml").read_text(encoding="utf-8")
    assert "command: /legacy/codex" in configured_runtime
    assert "host_token" not in configured_runtime
    assert "heartbeat_seconds" not in configured_runtime
    assert "enabled_executors:" in configured_runtime
    assert "node_id:" not in configured_runtime


def test_executor_setup_works_without_runtime_config(monkeypatch, tmp_path: Path):
    root = tmp_path
    (root / "src" / "newbro" / "ui").mkdir(parents=True)
    (root / ".newbro").mkdir(parents=True, exist_ok=True)

    configure_repo_paths(monkeypatch, root)
    monkeypatch.setattr(cli_main, "setup_can_prompt", lambda: True)
    monkeypatch.setattr(cli_main, "_detected_codex_command", lambda: "/detected/codex")
    monkeypatch.setattr(cli_main, "_command_available", lambda command: command == "/detected/codex")
    responses = iter(["", ""])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))

    assert cli_main.main(["executor", "setup"]) == 0
    configured_runtime = (root / ".newbro" / "config.yaml").read_text(encoding="utf-8")
    assert "executor_node:" in configured_runtime
    assert "enabled_executors:" in configured_runtime
    assert "command: /detected/codex" in configured_runtime


def test_setup_non_interactive_tolerates_malformed_existing_config(monkeypatch, tmp_path: Path, capsys):
    root = tmp_path
    (root / "src" / "newbro" / "ui").mkdir(parents=True)
    (root / ".newbro").mkdir(parents=True, exist_ok=True)
    (root / ".newbro" / ".env").write_text(
        "\n".join(
            [
                "OPENAI_API_KEY=test-key",
                "SYNAPSE_CODEX_EXECUTOR_ENABLED=true",
                "SYNAPSE_CODEX_COMMAND=/legacy/codex",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (root / ".newbro" / "config.yaml").write_text("version: [\n", encoding="utf-8")

    configure_repo_paths(monkeypatch, root)

    assert cli_main.main(["setup", "--non-interactive"]) == 0

    output = capsys.readouterr().out
    assert "ignoring invalid existing config" in output

    configured_runtime = (root / ".newbro" / "config.yaml").read_text(encoding="utf-8")
    assert "runtime:" in configured_runtime
    assert "executor_node:" in configured_runtime
    assert "executors: {}" in configured_runtime


def test_setup_non_interactive_requires_openai(monkeypatch, tmp_path: Path, capsys):
    root = tmp_path
    (root / "src" / "newbro" / "ui").mkdir(parents=True)

    configure_repo_paths(monkeypatch, root)

    assert cli_main.main(["setup", "--non-interactive"]) == 1
    assert "OPENAI_API_KEY is required for non-interactive setup" in capsys.readouterr().err


def test_setup_bootstrap_defaults_creates_env_and_connector_config(monkeypatch, tmp_path: Path):
    root = tmp_path
    (root / "src" / "newbro" / "ui").mkdir(parents=True)

    configure_repo_paths(monkeypatch, root)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-shell-secret")
    monkeypatch.setenv("AGORA_APP_ID", "agora-shell-app")
    monkeypatch.setenv("SYNAPSE_CODEX_EXECUTOR_ENABLED", "true")
    monkeypatch.setenv("SYNAPSE_CODEX_COMMAND", "/shell/codex")

    assert cli_main.main(["setup", "--bootstrap-defaults"]) == 0

    configured_env = (root / ".newbro" / ".env").read_text(encoding="utf-8")
    assert "OPENAI_API_KEY=\n" in configured_env
    assert "SYNAPSE_OPENAI_MODEL=gpt-4o-mini" in configured_env
    assert "sk-shell-secret" not in configured_env
    assert "agora-shell-app" not in configured_env
    assert "/shell/codex" not in configured_env

    configured_connector = (root / ".newbro" / "config.yaml").read_text(encoding="utf-8")
    assert "runtime: {}" in configured_connector
    assert "enabled: false" in configured_connector
    assert 'public_base_url: "http://127.0.0.1:8000"' in configured_connector
    assert "enabled_connectors: []" in configured_connector
    assert "connectors: {}" in configured_connector
    assert "connectors:\n  {}" not in configured_connector
    assert "executor_node:" in configured_connector
    assert "enabled_executors: []" in configured_connector
    assert "host_token" not in configured_connector
    assert "heartbeat_seconds" not in configured_connector
    assert "node_id:" not in configured_connector
    assert "executors: {}" in configured_connector


def test_setup_bootstrap_defaults_preserves_existing_files(monkeypatch, tmp_path: Path):
    root = tmp_path
    (root / "src" / "newbro" / "ui").mkdir(parents=True)
    (root / ".newbro").mkdir(parents=True, exist_ok=True)
    (root / ".newbro" / ".env").write_text("OPENAI_API_KEY=existing\n", encoding="utf-8")
    (root / ".newbro" / "config.yaml").write_text("version: 1\n", encoding="utf-8")

    configure_repo_paths(monkeypatch, root)

    assert cli_main.main(["setup", "--bootstrap-defaults"]) == 0
    assert (root / ".newbro" / ".env").read_text(encoding="utf-8") == "OPENAI_API_KEY=existing\n"
    assert (root / ".newbro" / "config.yaml").read_text(encoding="utf-8") == "version: 1\n"


def test_setup_bootstrap_defaults_ignores_malformed_codex_shell_env(monkeypatch, tmp_path: Path):
    root = tmp_path
    (root / "src" / "newbro" / "ui").mkdir(parents=True)

    configure_repo_paths(monkeypatch, root)
    monkeypatch.setenv("SYNAPSE_CODEX_EXECUTOR_ENABLED", "not-a-bool")

    assert cli_main.main(["setup", "--bootstrap-defaults"]) == 0

    configured_env = (root / ".newbro" / ".env").read_text(encoding="utf-8")
    assert "SYNAPSE_CODEX_EXECUTOR_ENABLED" not in configured_env


def test_backend_requires_setup(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(cli_main, "VENV_DIR", tmp_path / ".venv")

    assert cli_main.main(["backend"]) == 1


def test_doctor_reads_openai_key_from_env_file(monkeypatch, tmp_path: Path, capsys):
    env_local = tmp_path / ".newbro" / ".env"
    env_local.parent.mkdir(parents=True, exist_ok=True)
    env_local.write_text("OPENAI_API_KEY=test-key\n", encoding="utf-8")
    venv_python = tmp_path / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True, exist_ok=True)
    venv_python.write_text("", encoding="utf-8")

    configure_repo_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(cli_main, "report_port", lambda _port: True)
    monkeypatch.setattr(cli_main, "report_command", lambda _name, required=True: True)

    assert cli_main.main(["doctor"]) == 0
    assert "[ok] env: OPENAI_API_KEY" in capsys.readouterr().out


def test_doctor_points_to_install_and_setup(monkeypatch, tmp_path: Path, capsys):
    configure_repo_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(cli_main, "report_port", lambda _port: True)
    monkeypatch.setattr(cli_main, "report_command", lambda _name, required=True: True)

    assert cli_main.main(["doctor"]) == 1
    output = capsys.readouterr().out
    assert "[missing] virtualenv: run ./install.sh" in output
    assert "[missing] env file: run ./newbro setup" in output


def test_status_reports_readiness_without_starting_services(monkeypatch, tmp_path: Path, capsys):
    env_local = tmp_path / ".newbro" / ".env"
    env_local.parent.mkdir(parents=True, exist_ok=True)
    env_local.write_text("OPENAI_API_KEY=test-key\n", encoding="utf-8")
    (tmp_path / ".newbro" / "config.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "connector_host:",
                "  enabled: false",
                "  enabled_connectors: []",
                "connectors: {}",
                "executor_node:",
                "  enabled_executors:",
                "    - codex",
                "executors:",
                "  codex:",
                "    command: codex",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    venv_python = tmp_path / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True, exist_ok=True)
    venv_python.write_text("", encoding="utf-8")

    configure_repo_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(cli_main, "report_command", lambda name, required=True: print(f"[ok] command: {name}") or True)
    monkeypatch.setattr(cli_main, "report_port", lambda port: print(f"[ok] port {port} is free") or True)
    monkeypatch.setattr(
        cli_main,
        "report_reachability",
        lambda label, url: print(f"[ok] {label}: {url}") or True,
    )

    assert cli_main.main(["status"]) == 0

    output = capsys.readouterr().out
    assert "Newbro status" in output
    assert "[ok] env: OPENAI_API_KEY" in output
    assert "[ok] config:" in output
    assert "[ok] connector: disabled" in output
    assert "[ok] backend health: http://127.0.0.1:8000/api/health" in output
    assert "[ok] frontend: http://127.0.0.1:5173/" in output
    assert "[ok] executor node config: enabled executors codex" in output
    assert "executor run --base-url ... --node-id ... --token ..." in output


def test_report_port_tolerates_permission_error(monkeypatch, capsys):
    class DeniedSocket:
        def bind(self, _address):
            raise PermissionError

        def close(self):
            return None

    monkeypatch.setattr(cli_main.socket, "socket", lambda: DeniedSocket())

    assert cli_main.report_port(8000) is True
    assert "[warn] port 8000 could not be checked in this environment" in capsys.readouterr().out


def test_dev_uses_repo_venv_and_frontend_command(monkeypatch, tmp_path: Path):
    venv_python = tmp_path / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True, exist_ok=True)
    venv_python.write_text("", encoding="utf-8")

    class FakeProcess:
        def __init__(self, returncode: int | None = None):
            self._returncode = returncode

        def poll(self):
            return self._returncode

        def terminate(self):
            self._returncode = 0

        def kill(self):
            self._returncode = -9

    spawned: list[tuple[list[str], Path]] = []
    processes = [FakeProcess(0), FakeProcess(None), FakeProcess(None)]

    def fake_popen(cmd: list[str], cwd: Path):
        spawned.append((cmd, cwd))
        return processes[len(spawned) - 1]

    configure_repo_paths(monkeypatch, tmp_path)
    (tmp_path / ".newbro").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".newbro" / ".env").write_text(
        "\n".join(
            [
                "OPENAI_API_KEY=test-key",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / ".newbro" / "config.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "connector_host:",
                "  enabled: true",
                "  port: 8010",
                "  public_base_url: http://127.0.0.1:8000",
                "  enabled_connectors:",
                "    - agora-convoai",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cli_main.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(cli_main.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(cli_main.signal, "signal", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cli_main, "frontend_dev_command", lambda host, port: ["npm", "run", "dev", "--", "--host", host, "--port", str(port)])

    assert cli_main.main(["dev"]) == 0
    assert spawned[0][0][:4] == [str(venv_python), "-m", "uvicorn", "newbro.service.app:app"]
    assert spawned[1][0] == ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
    assert len(spawned) == 2


def test_start_runs_single_service_process(monkeypatch, tmp_path: Path):
    venv_python = tmp_path / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True, exist_ok=True)
    venv_python.write_text("", encoding="utf-8")
    dist_dir = tmp_path / "src" / "newbro" / "ui" / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    (dist_dir / "index.html").write_text("<html>ok</html>", encoding="utf-8")

    configure_repo_paths(monkeypatch, tmp_path)
    (tmp_path / ".newbro").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".newbro" / ".env").write_text("OPENAI_API_KEY=test-key\n", encoding="utf-8")
    (tmp_path / ".newbro" / "config.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "connector_host:",
                "  enabled: true",
                "  host: 0.0.0.0",
                "  port: 8010",
                '  public_base_url: "http://127.0.0.1:8000"',
                "  enabled_connectors:",
                "    - agora-convoai",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    captured: dict[str, object] = {}

    def fake_run_managed_processes(commands):
        captured["commands"] = commands
        return 0

    monkeypatch.setattr(cli_main, "run_managed_processes", fake_run_managed_processes)

    assert cli_main.main(["start"]) == 0

    commands = captured["commands"]
    assert commands == [
        (
            "service",
            [
                str(venv_python),
                "-m",
                "uvicorn",
                "newbro.service.app:app",
                "--host",
                "0.0.0.0",
                "--port",
                "8000",
                "--ws-max-size",
                str(EXECUTOR_CONTROL_MAX_MESSAGE_BYTES),
            ],
            tmp_path,
        )
    ]


def test_start_uses_current_python_when_no_repo_venv(monkeypatch, tmp_path: Path):
    dist_dir = tmp_path / "src" / "newbro" / "ui" / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    (dist_dir / "index.html").write_text("<html>ok</html>", encoding="utf-8")

    configure_repo_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(cli_main.sys, "executable", "/usr/local/bin/python")

    captured: dict[str, object] = {}

    def fake_run_managed_processes(commands):
        captured["commands"] = commands
        return 0

    monkeypatch.setattr(cli_main, "run_managed_processes", fake_run_managed_processes)

    assert cli_main.main(["start"]) == 0

    commands = captured["commands"]
    assert commands == [
        (
            "service",
            [
                "/usr/local/bin/python",
                "-m",
                "uvicorn",
                "newbro.service.app:app",
                "--host",
                "0.0.0.0",
                "--port",
                "8000",
                "--ws-max-size",
                str(EXECUTOR_CONTROL_MAX_MESSAGE_BYTES),
            ],
            tmp_path,
        )
    ]


def configure_service_environment(monkeypatch, tmp_path: Path) -> None:
    configure_repo_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(cli_main.sys, "platform", "linux")
    monkeypatch.setattr(cli_main.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(cli_main.getpass, "getuser", lambda: "deploy")
    monkeypatch.setattr(
        cli_main.shutil,
        "which",
        lambda name: f"/usr/bin/{name}" if name in {"sudo", "systemctl", "bun"} else None,
    )


def configure_root_service_environment(monkeypatch, tmp_path: Path) -> None:
    configure_repo_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(cli_main.sys, "platform", "linux")
    monkeypatch.setattr(cli_main.os, "geteuid", lambda: 0)
    monkeypatch.setattr(cli_main.getpass, "getuser", lambda: "root")
    monkeypatch.setattr(
        cli_main.shutil,
        "which",
        lambda name: f"/usr/bin/{name}" if name in {"systemctl", "bun"} else None,
    )


def write_fake_service_console_script(root: Path, *, executable: bool = True) -> Path:
    cli_bin = root / ".venv" / "bin" / "newbro"
    cli_bin.parent.mkdir(parents=True, exist_ok=True)
    cli_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    cli_bin.chmod(0o755 if executable else 0o644)
    return cli_bin


def bootstrap_fake_service_artifacts(cmd: list[str], root: Path, *, install_console_script: bool) -> None:
    if len(cmd) >= 3 and cmd[1:3] == ["-m", "venv"]:
        venv_python = root / ".venv" / "bin" / "python"
        venv_python.parent.mkdir(parents=True, exist_ok=True)
        venv_python.write_text("", encoding="utf-8")
    if (
        install_console_script
        and len(cmd) >= 6
        and cmd[1:4] == ["-m", "pip", "install"]
        and cmd[-2:] == ["-e", "."]
    ):
        write_fake_service_console_script(root)


def test_service_install_bootstraps_runtime_and_enables_unit(monkeypatch, tmp_path: Path, capsys):
    configure_service_environment(monkeypatch, tmp_path)

    commands: list[tuple[list[str], Path]] = []

    def fake_run_checked(cmd: list[str], cwd: Path) -> int:
        commands.append((cmd, cwd))
        bootstrap_fake_service_artifacts(cmd, tmp_path, install_console_script=True)
        return 0

    monkeypatch.setattr(cli_main, "run_checked", fake_run_checked)

    assert cli_main.main(["service", "install", "--host", "0.0.0.0", "--port", "9000"]) == 0

    venv_python = tmp_path / ".venv" / "bin" / "python"
    assert commands[0] == ([cli_main.sys.executable, "-m", "venv", str(tmp_path / ".venv")], tmp_path)
    assert commands[1] == ([str(venv_python), "-m", "pip", "install", "--upgrade", "pip"], tmp_path)
    assert commands[2] == ([str(venv_python), "-m", "pip", "install", "-e", "."], tmp_path)
    assert commands[3] == (["bun", "install"], tmp_path / "src" / "newbro" / "ui")
    assert commands[4] == (["bun", "run", "build"], tmp_path / "src" / "newbro" / "ui")
    assert commands[5][0][0:8] == ["sudo", "install", "-o", "root", "-g", "root", "-m", "0644"]
    assert commands[5][0][-1] == str(cli_main.service_unit_path())
    assert commands[6] == (["sudo", "systemctl", "daemon-reload"], tmp_path)
    assert commands[7] == (["sudo", "systemctl", "enable", "newbro.service"], tmp_path)
    assert commands[8] == (["sudo", "systemctl", "restart", "newbro.service"], tmp_path)
    assert (tmp_path / ".newbro" / ".env").exists()
    assert (tmp_path / ".newbro" / "config.yaml").exists()
    assert "[warn] env: OPENAI_API_KEY is not configured" in capsys.readouterr().out


def test_service_install_skips_venv_creation_when_existing(monkeypatch, tmp_path: Path):
    configure_service_environment(monkeypatch, tmp_path)
    venv_python = tmp_path / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True, exist_ok=True)
    venv_python.write_text("", encoding="utf-8")
    write_fake_service_console_script(tmp_path)
    (tmp_path / ".newbro").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".newbro" / ".env").write_text("OPENAI_API_KEY=test-key\n", encoding="utf-8")

    commands: list[list[str]] = []
    monkeypatch.setattr(cli_main, "run_checked", lambda cmd, cwd: commands.append(cmd) or 0)

    assert cli_main.main(["service", "install"]) == 0
    assert all(cmd[1:3] != ["-m", "venv"] for cmd in commands if len(cmd) >= 3)
    assert commands[0] == [str(venv_python), "-m", "pip", "install", "--upgrade", "pip"]
    assert ["bun", "install"] in commands
    assert ["bun", "run", "build"] in commands


def test_service_install_allows_root_and_uses_direct_systemctl(monkeypatch, tmp_path: Path, capsys):
    configure_root_service_environment(monkeypatch, tmp_path)

    commands: list[tuple[list[str], Path]] = []

    def fake_run_checked(cmd: list[str], cwd: Path) -> int:
        commands.append((cmd, cwd))
        bootstrap_fake_service_artifacts(cmd, tmp_path, install_console_script=True)
        return 0

    monkeypatch.setattr(cli_main, "run_checked", fake_run_checked)

    assert cli_main.main(["service", "install", "--host", "0.0.0.0", "--port", "9000"]) == 0

    venv_python = tmp_path / ".venv" / "bin" / "python"
    assert commands[0] == ([cli_main.sys.executable, "-m", "venv", str(tmp_path / ".venv")], tmp_path)
    assert commands[1] == ([str(venv_python), "-m", "pip", "install", "--upgrade", "pip"], tmp_path)
    assert commands[2] == ([str(venv_python), "-m", "pip", "install", "-e", "."], tmp_path)
    assert commands[3] == (["bun", "install"], tmp_path / "src" / "newbro" / "ui")
    assert commands[4] == (["bun", "run", "build"], tmp_path / "src" / "newbro" / "ui")
    assert commands[5][0][0:7] == ["install", "-o", "root", "-g", "root", "-m", "0644"]
    assert commands[5][0][-1] == str(cli_main.service_unit_path())
    assert commands[6] == (["systemctl", "daemon-reload"], tmp_path)
    assert commands[7] == (["systemctl", "enable", "newbro.service"], tmp_path)
    assert commands[8] == (["systemctl", "restart", "newbro.service"], tmp_path)
    assert (tmp_path / ".newbro" / ".env").exists()
    assert (tmp_path / ".newbro" / "config.yaml").exists()
    assert "[warn] env: OPENAI_API_KEY is not configured" in capsys.readouterr().out


def test_service_install_fails_before_unit_install_when_newbro_script_missing(
    monkeypatch,
    tmp_path: Path,
    capsys,
):
    configure_service_environment(monkeypatch, tmp_path)

    commands: list[tuple[list[str], Path]] = []

    def fake_run_checked(cmd: list[str], cwd: Path) -> int:
        commands.append((cmd, cwd))
        bootstrap_fake_service_artifacts(cmd, tmp_path, install_console_script=False)
        return 0

    monkeypatch.setattr(cli_main, "run_checked", fake_run_checked)

    assert cli_main.main(["service", "install"]) == 1

    assert "Installed newbro console script is missing" in capsys.readouterr().err
    assert all("systemctl" not in cmd for cmd, _cwd in commands)
    assert all(
        cmd[:2] != ["sudo", "install"] and cmd[:1] != ["install"]
        for cmd, _cwd in commands
    )


def test_service_install_fails_before_unit_install_when_newbro_script_not_executable(
    monkeypatch,
    tmp_path: Path,
    capsys,
):
    configure_service_environment(monkeypatch, tmp_path)

    commands: list[tuple[list[str], Path]] = []

    def fake_run_checked(cmd: list[str], cwd: Path) -> int:
        commands.append((cmd, cwd))
        bootstrap_fake_service_artifacts(cmd, tmp_path, install_console_script=False)
        if (
            len(cmd) >= 6
            and cmd[1:4] == ["-m", "pip", "install"]
            and cmd[-2:] == ["-e", "."]
        ):
            write_fake_service_console_script(tmp_path, executable=False)
        return 0

    monkeypatch.setattr(cli_main, "run_checked", fake_run_checked)

    assert cli_main.main(["service", "install"]) == 1

    assert "Installed newbro console script is not executable" in capsys.readouterr().err
    assert all("systemctl" not in cmd for cmd, _cwd in commands)
    assert all(
        cmd[:2] != ["sudo", "install"] and cmd[:1] != ["install"]
        for cmd, _cwd in commands
    )


def test_service_install_requires_systemctl(monkeypatch, tmp_path: Path, capsys):
    configure_repo_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(cli_main.sys, "platform", "linux")
    monkeypatch.setattr(cli_main.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(cli_main.shutil, "which", lambda _name: None)

    assert cli_main.main(["service", "install"]) == 1
    assert "systemctl is required" in capsys.readouterr().err


def test_service_install_rejects_non_linux(monkeypatch, tmp_path: Path, capsys):
    configure_repo_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(cli_main.sys, "platform", "darwin")
    monkeypatch.setattr(cli_main.os, "geteuid", lambda: 1000)

    assert cli_main.main(["service", "install"]) == 1
    assert "supports Linux/systemd hosts only" in capsys.readouterr().err


def test_render_service_unit_includes_expected_values():
    unit = cli_main.render_service_unit(
        user="deploy",
        home=Path("/home/deploy"),
        workdir=Path("/srv/newbro"),
        cli_bin=Path("/srv/newbro/.venv/bin/newbro"),
        host="0.0.0.0",
        public_port=8000,
    )

    assert "User=deploy" in unit
    assert "WorkingDirectory=/srv/newbro" in unit
    assert 'Environment="HOME=/home/deploy"' in unit
    assert 'Environment="PATH=/srv/newbro/.venv/bin:/home/deploy/.local/bin:/home/deploy/.bun/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"' in unit
    assert "Description=Newbro service" in unit
    assert (
        "ExecStart=/srv/newbro/.venv/bin/newbro start --host 0.0.0.0 --port 8000"
        in unit
    )
    assert "Restart=on-failure" in unit
    assert "WantedBy=multi-user.target" in unit


def test_render_service_unit_supports_root_values():
    unit = cli_main.render_service_unit(
        user="root",
        home=Path("/root"),
        workdir=Path("/srv/newbro"),
        cli_bin=Path("/srv/newbro/.venv/bin/newbro"),
        host="0.0.0.0",
        public_port=8000,
    )

    assert "User=root" in unit
    assert 'Environment="HOME=/root"' in unit
    assert 'Environment="PATH=/srv/newbro/.venv/bin:/root/.local/bin:/root/.bun/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"' in unit


def test_start_requires_production_frontend_build(monkeypatch, tmp_path: Path, capsys):
    configure_repo_paths(monkeypatch, tmp_path)
    venv_python = tmp_path / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True, exist_ok=True)
    venv_python.write_text("", encoding="utf-8")

    assert cli_main.main(["start"]) == 1
    assert "Frontend production build is missing" in capsys.readouterr().err


def test_service_lifecycle_commands_use_sudo(monkeypatch, tmp_path: Path):
    configure_service_environment(monkeypatch, tmp_path)
    commands: list[list[str]] = []
    monkeypatch.setattr(cli_main, "run_checked", lambda cmd, cwd: commands.append(cmd) or 0)

    assert cli_main.main(["service", "start"]) == 0
    assert cli_main.main(["service", "stop"]) == 0
    assert cli_main.main(["service", "restart"]) == 0

    assert commands == [
        ["sudo", "systemctl", "start", "newbro.service"],
        ["sudo", "systemctl", "stop", "newbro.service"],
        ["sudo", "systemctl", "restart", "newbro.service"],
    ]


def test_run_checked_returns_130_on_keyboard_interrupt(monkeypatch, tmp_path: Path, capsys):
    monkeypatch.setattr(
        cli_main.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    assert cli_main.run_checked(["echo", "hello"], cwd=tmp_path) == 130
    output = capsys.readouterr().out
    assert "[run] echo hello" in output
    assert "[stop] interrupted" in output


def test_executor_run_returns_130_when_child_interrupts(monkeypatch, tmp_path: Path):
    venv_python = tmp_path / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True, exist_ok=True)
    venv_python.write_text("", encoding="utf-8")

    configure_repo_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(cli_main, "_executor_runtime_config_complete", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        cli_main.subprocess,
        "run",
        lambda *_args, **_kwargs: FakeCompletedProcess(returncode=130),
    )

    assert (
        cli_main.main(
            [
                "executor",
                "run",
                "--base-url",
                "http://127.0.0.1:8000",
                "--node-id",
                "node-1",
                "--token",
                "token-1",
            ]
        )
        == 130
    )


def test_executor_run_uses_current_python_when_installed_from_package(monkeypatch, tmp_path: Path):
    configure_repo_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(cli_main, "running_from_repo_checkout", lambda: False)
    monkeypatch.setattr(cli_main, "_executor_runtime_config_complete", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(cli_main.sys, "executable", "/opt/newbro/bin/python3")

    run_calls: list[tuple[list[str], Path, bool]] = []

    def fake_run(cmd, cwd, check=False):
        run_calls.append((cmd, cwd, check))
        return FakeCompletedProcess(returncode=0)

    monkeypatch.setattr(cli_main.subprocess, "run", fake_run)

    assert (
        cli_main.main(
            [
                "executor",
                "run",
                "--base-url",
                "https://newbro.plutoless.com",
                "--node-id",
                "node-faa287f7",
                "--token",
                "token-1",
            ]
        )
        == 0
    )
    assert run_calls == [
        (
            [
                "/opt/newbro/bin/python3",
                "-m",
                "newbro.executors.node",
                "--base-url",
                "https://newbro.plutoless.com",
                "--node-id",
                "node-faa287f7",
                "--token",
                "token-1",
            ],
            Path.cwd(),
            False,
        )
    ]


def test_executor_run_triggers_setup_when_local_runtime_config_missing(monkeypatch, tmp_path: Path):
    venv_python = tmp_path / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True, exist_ok=True)
    venv_python.write_text("", encoding="utf-8")

    configure_repo_paths(monkeypatch, tmp_path)
    completion_states = iter([False, True])
    monkeypatch.setattr(cli_main, "_executor_runtime_config_complete", lambda *_args, **_kwargs: next(completion_states))
    monkeypatch.setattr(cli_main, "setup_can_prompt", lambda: True)
    setup_calls: list[str] = []
    monkeypatch.setattr(cli_main, "_run_executor_setup_flow", lambda: setup_calls.append("called"))
    monkeypatch.setattr(
        cli_main.subprocess,
        "run",
        lambda *_args, **_kwargs: FakeCompletedProcess(returncode=130),
    )

    assert (
        cli_main.main(
            [
                "executor",
                "run",
                "--base-url",
                "http://127.0.0.1:8000",
                "--node-id",
                "node-1",
                "--token",
                "token-1",
            ]
        )
        == 130
    )
    assert setup_calls == ["called"]


def test_executor_run_requires_tty_when_local_runtime_config_missing(monkeypatch, tmp_path: Path, capsys):
    venv_python = tmp_path / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True, exist_ok=True)
    venv_python.write_text("", encoding="utf-8")

    configure_repo_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(cli_main, "_executor_runtime_config_complete", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(cli_main, "setup_can_prompt", lambda: False)

    assert (
        cli_main.main(
            [
                "executor",
                "run",
                "--base-url",
                "http://127.0.0.1:8000",
                "--node-id",
                "node-1",
                "--token",
                "token-1",
            ]
        )
        == 1
    )
    assert "Local executor runtime config is incomplete." in capsys.readouterr().err
