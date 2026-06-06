from __future__ import annotations

import json
import os
from pathlib import Path

from newbro.config_home import ConfigHomeMigrationResult

from tests.unit.cli.test_main import cli_main, configure_repo_paths


def _write_config(root: Path, *, codex_command: str) -> None:
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
                "  enabled_executors:",
                "    - codex",
                "executors:",
                "  codex:",
                f"    command: {codex_command}",
                "    blocked_wait_timeout_seconds: 900.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_executor_probe_json_reports_current_and_candidates(monkeypatch, tmp_path: Path, capsys):
    good = tmp_path / "bin" / "codex"
    bad = tmp_path / "broken" / "codex"
    _write_config(tmp_path, codex_command=str(bad))
    configure_repo_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(
        cli_main,
        "ensure_newbro_home",
        lambda **_kwargs: ConfigHomeMigrationResult(migrated=False),
    )

    from newbro.executors.adapters.codex import probe as codex_probe

    def fake_probe(command: str):
        path = Path(command)
        ok = path == good
        return codex_probe.CodexProbeResult(
            path=str(path),
            version="codex-cli 0.136.0" if ok else None,
            ok=ok,
            error=None if ok else "vendor executable missing",
        )

    monkeypatch.setattr(codex_probe, "discover_codex_commands", lambda configured_command=None: [str(bad), str(good)])
    monkeypatch.setattr(codex_probe, "probe_codex_command", fake_probe)

    assert cli_main.main(["executor", "probe", "--executor", "codex", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["supported_executors"] == ["codex"]
    assert payload["current"]["command"] == str(bad)
    assert payload["current"]["ok"] is False
    assert payload["current"]["error"] == "vendor executable missing"
    assert payload["candidates"] == [
        {
            "path": str(bad),
            "version": None,
            "ok": False,
            "source": "configured",
            "error": "vendor executable missing",
            "is_current": True,
        },
        {
            "path": str(good),
            "version": "codex-cli 0.136.0",
            "ok": True,
            "source": "discovered",
            "error": None,
            "is_current": False,
        },
    ]


def test_executor_use_validates_and_writes_codex_command(monkeypatch, tmp_path: Path):
    selected = tmp_path / "bin" / "codex"
    _write_config(tmp_path, codex_command="codex")
    configure_repo_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(
        cli_main,
        "ensure_newbro_home",
        lambda **_kwargs: ConfigHomeMigrationResult(migrated=False),
    )

    from newbro.executors.adapters.codex import probe as codex_probe

    monkeypatch.setattr(
        codex_probe,
        "probe_codex_command",
        lambda command: codex_probe.CodexProbeResult(
            path=str(selected),
            version="codex-cli 0.136.0",
            ok=True,
            error=None,
        ),
    )

    assert cli_main.main(["executor", "use", "--executor", "codex", "--command", str(selected)]) == 0

    configured = (tmp_path / ".newbro" / "config.yaml").read_text(encoding="utf-8")
    assert f"command: {selected}" in configured
    assert "blocked_wait_timeout_seconds: 900.0" in configured
    assert "enabled_executors:\n    - codex" in configured


def test_executor_use_rejects_broken_codex_command(monkeypatch, tmp_path: Path, capsys):
    broken = tmp_path / "broken" / "codex"
    _write_config(tmp_path, codex_command="codex")
    configure_repo_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(
        cli_main,
        "ensure_newbro_home",
        lambda **_kwargs: ConfigHomeMigrationResult(migrated=False),
    )

    from newbro.executors.adapters.codex import probe as codex_probe

    monkeypatch.setattr(
        codex_probe,
        "probe_codex_command",
        lambda command: codex_probe.CodexProbeResult(
            path=str(broken),
            version=None,
            ok=False,
            error="vendor executable missing",
        ),
    )

    assert cli_main.main(["executor", "use", "--executor", "codex", "--command", str(broken)]) == 1

    assert "vendor executable missing" in capsys.readouterr().err
    configured = (tmp_path / ".newbro" / "config.yaml").read_text(encoding="utf-8")
    assert "command: codex" in configured


def test_executor_install_codex_uses_existing_usable_codex(monkeypatch, tmp_path: Path, capsys):
    selected = tmp_path / "bin" / "codex"
    _write_config(tmp_path, codex_command="codex")
    configure_repo_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(
        cli_main,
        "ensure_newbro_home",
        lambda **_kwargs: ConfigHomeMigrationResult(migrated=False),
    )

    from newbro.cli.commands import executor_settings
    from newbro.executors.adapters.codex import probe as codex_probe

    run_calls: list[list[str]] = []
    monkeypatch.setattr(executor_settings, "_run_logged", lambda argv, *, env=None: run_calls.append(argv) or 0)
    monkeypatch.setattr(executor_settings, "_tool_environment", lambda: {"PATH": str(tmp_path / "bin")})
    monkeypatch.setattr(executor_settings.shutil, "which", lambda command, path=None: None)
    monkeypatch.setattr(codex_probe, "discover_codex_commands", lambda configured_command=None: [str(selected)])
    monkeypatch.setattr(
        codex_probe,
        "probe_codex_command",
        lambda command: codex_probe.CodexProbeResult(
            path=str(selected),
            version="codex-cli 0.136.0",
            ok=True,
            error=None,
        ),
    )

    assert cli_main.main(["executor", "install-codex"]) == 0

    assert run_calls == []
    assert "Codex is ready" in capsys.readouterr().out
    configured = (tmp_path / ".newbro" / "config.yaml").read_text(encoding="utf-8")
    assert f"command: {selected}" in configured
    assert "enabled_executors:\n    - codex" in configured


def test_executor_install_codex_bootstraps_missing_codex(monkeypatch, tmp_path: Path, capsys):
    bun = tmp_path / "home" / ".bun" / "bin" / "bun"
    codex = tmp_path / "home" / ".bun" / "bin" / "codex"
    _write_config(tmp_path, codex_command="codex")
    configure_repo_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(
        cli_main,
        "ensure_newbro_home",
        lambda **_kwargs: ConfigHomeMigrationResult(migrated=False),
    )

    from newbro.cli.commands import executor_settings
    from newbro.executors.adapters.codex import probe as codex_probe

    run_calls: list[tuple[list[str], dict[str, str] | None]] = []
    env_calls = iter(
        [
            {"PATH": os.pathsep.join([str(tmp_path / "home" / ".bun" / "bin"), "/usr/bin"])},
            {"PATH": os.pathsep.join([str(tmp_path / "home" / ".bun" / "bin"), "/usr/bin"])},
        ]
    )
    monkeypatch.setattr(executor_settings, "_tool_environment", lambda: next(env_calls))

    which_results = iter([None, str(bun)])
    monkeypatch.setattr(executor_settings.shutil, "which", lambda command, path=None: next(which_results))
    monkeypatch.setattr(
        executor_settings,
        "_run_logged",
        lambda argv, *, env=None: run_calls.append((argv, env)) or 0,
    )
    monkeypatch.setattr(codex_probe, "discover_codex_commands", lambda configured_command=None: [])
    probe_results = iter(
        [
            codex_probe.CodexProbeResult(
                path=str(codex),
                version="codex-cli 0.136.0",
                ok=True,
                error=None,
            )
        ]
    )
    monkeypatch.setattr(codex_probe, "probe_codex_command", lambda command: next(probe_results))

    assert cli_main.main(["executor", "install-codex"]) == 0

    assert run_calls == [
        (["sh", "-c", "curl -fsSL https://bun.sh/install | bash"], {"PATH": f"{bun.parent}{os.pathsep}/usr/bin"}),
        ([str(bun), "add", "-g", "@openai/codex"], {"PATH": f"{bun.parent}{os.pathsep}/usr/bin"}),
    ]
    out = capsys.readouterr().out
    assert "Installing required runtime..." in out
    assert "Installing Codex..." in out
    assert "Checking Codex..." in out
    assert "Codex is ready" in out
    configured = (tmp_path / ".newbro" / "config.yaml").read_text(encoding="utf-8")
    assert f"command: {codex}" in configured
    assert "enabled_executors:\n    - codex" in configured


def test_executor_install_codex_runtime_bootstrap_failure(monkeypatch, tmp_path: Path, capsys):
    _write_config(tmp_path, codex_command="codex")
    configure_repo_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(
        cli_main,
        "ensure_newbro_home",
        lambda **_kwargs: ConfigHomeMigrationResult(migrated=False),
    )

    from newbro.cli.commands import executor_settings
    from newbro.executors.adapters.codex import probe as codex_probe

    monkeypatch.setattr(codex_probe, "discover_codex_commands", lambda configured_command=None: [])
    monkeypatch.setattr(executor_settings, "_tool_environment", lambda: {"PATH": "/usr/bin"})
    monkeypatch.setattr(executor_settings.shutil, "which", lambda command, path=None: None)
    monkeypatch.setattr(executor_settings, "_run_logged", lambda argv, *, env=None: 1)

    assert cli_main.main(["executor", "install-codex"]) == 1

    assert "Codex setup failed while installing required runtime" in capsys.readouterr().err
    configured = (tmp_path / ".newbro" / "config.yaml").read_text(encoding="utf-8")
    assert "command: codex" in configured
