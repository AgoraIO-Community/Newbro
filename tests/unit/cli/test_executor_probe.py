from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

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
    assert "codex" in payload["supported_executors"]
    assert "hermes" in payload["supported_executors"]
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


def test_codex_probe_rejects_version_below_minimum():
    from newbro.executors.adapters.codex import probe as codex_probe

    assert codex_probe.codex_version_tuple("codex-cli 0.134.9") == (0, 134, 9)
    assert codex_probe.codex_version_supported("codex-cli 0.134.9") is False
    assert codex_probe.codex_version_supported("codex-cli 0.135.0") is True
    assert codex_probe.codex_version_supported("codex-cli 0.137.0") is True


def test_codex_probe_marks_old_version_unavailable(monkeypatch):
    from newbro.executors.adapters.codex import probe as codex_probe

    class Completed:
        returncode = 0
        stdout = "codex-cli 0.134.9\n"
        stderr = ""

    monkeypatch.setattr(codex_probe, "_resolve_command_path", lambda command: command)
    monkeypatch.setattr(codex_probe.subprocess, "run", lambda *_args, **_kwargs: Completed())

    result = codex_probe.probe_codex_command("codex")

    assert result.ok is False
    assert result.version == "codex-cli 0.134.9"
    assert result.error == "Codex CLI codex-cli 0.134.9 is below Newbro's minimum supported version 0.135.0."


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
    monkeypatch.setattr(executor_settings, "_run_logged", lambda argv, **kwargs: run_calls.append(argv) or 0)
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
        lambda argv, **kwargs: run_calls.append((argv, kwargs.get("env"))) or 0,
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

    assert len(run_calls) == 3
    assert run_calls[0][0][:4] == ["/usr/bin/curl", "-fsSL", "https://bun.sh/install", "-o"]
    assert run_calls[0][1]["PATH"] == os.environ.get("PATH", "")
    assert run_calls[1][0][0] == "/bin/bash"
    assert run_calls[1][0][1] == run_calls[0][0][4]
    assert run_calls[1][1]["PATH"] == os.environ.get("PATH", "")
    assert run_calls[2] == ([str(bun), "add", "-g", "@openai/codex"], {"PATH": f"{bun.parent}{os.pathsep}/usr/bin"})
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
    monkeypatch.setattr(executor_settings, "_run_logged", lambda argv, **kwargs: 22)

    assert cli_main.main(["executor", "install-codex"]) == 1

    err = capsys.readouterr().err
    assert "Codex setup failed while installing required runtime" in err
    assert "/usr/bin/curl -fsSL https://bun.sh/install -o" in err
    assert "exited with code 22" in err
    configured = (tmp_path / ".newbro" / "config.yaml").read_text(encoding="utf-8")
    assert "command: codex" in configured


def test_executor_install_codex_package_install_failure(monkeypatch, tmp_path: Path, capsys):
    bun = tmp_path / "home" / ".bun" / "bin" / "bun"
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
    monkeypatch.setattr(executor_settings, "_tool_environment", lambda: {"PATH": f"{bun.parent}{os.pathsep}/usr/bin"})
    monkeypatch.setattr(executor_settings.shutil, "which", lambda command, path=None: str(bun))
    monkeypatch.setattr(executor_settings, "_run_logged", lambda argv, **kwargs: 127)

    assert cli_main.main(["executor", "install-codex"]) == 1

    err = capsys.readouterr().err
    assert "Codex setup failed while installing Codex." in err
    assert f"{bun} add -g @openai/codex" in err
    assert "exited with code 127" in err
    configured = (tmp_path / ".newbro" / "config.yaml").read_text(encoding="utf-8")
    assert "command: codex" in configured


def test_executor_install_codex_post_install_probe_failure(monkeypatch, tmp_path: Path, capsys):
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

    monkeypatch.setattr(codex_probe, "discover_codex_commands", lambda configured_command=None: [])
    monkeypatch.setattr(executor_settings, "_tool_environment", lambda: {"PATH": f"{bun.parent}{os.pathsep}/usr/bin"})
    monkeypatch.setattr(executor_settings.shutil, "which", lambda command, path=None: str(bun))
    monkeypatch.setattr(executor_settings, "_run_logged", lambda argv, **kwargs: 0)
    monkeypatch.setattr(
        codex_probe,
        "probe_codex_command",
        lambda command: codex_probe.CodexProbeResult(
            path=str(codex),
            version=None,
            ok=False,
            error="command not found",
        ),
    )

    assert cli_main.main(["executor", "install-codex"]) == 1

    assert "Codex setup finished, but codex --version is still unavailable." in capsys.readouterr().err
    configured = (tmp_path / ".newbro" / "config.yaml").read_text(encoding="utf-8")
    assert "command: codex" in configured


def test_run_logged_translates_missing_command_and_timeout(monkeypatch):
    from newbro.cli.commands import executor_settings

    def missing_command(*_args, **_kwargs):
        raise FileNotFoundError("missing")

    monkeypatch.setattr(executor_settings.subprocess, "run", missing_command)
    with pytest.raises(RuntimeError, match="Command not found: /missing/tool"):
        executor_settings._run_logged(["/missing/tool"], timeout_seconds=1)

    def timed_out(*_args, **_kwargs):
        raise executor_settings.subprocess.TimeoutExpired(["/slow/tool"], 1)

    monkeypatch.setattr(executor_settings.subprocess, "run", timed_out)
    with pytest.raises(RuntimeError, match="Command timed out: /slow/tool"):
        executor_settings._run_logged(["/slow/tool"], timeout_seconds=1)
