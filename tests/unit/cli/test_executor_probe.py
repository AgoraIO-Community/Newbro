from __future__ import annotations

import json
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
