import pytest
from pathlib import Path
from types import SimpleNamespace

from newbro.cli.commands import executor_settings
from newbro.cli import config_files
from newbro.cli import dispatch as cli_dispatch
from newbro.executors.adapters.hermes import probe as hermes_probe


def _enabled(config_path):
    raw = config_files.load_existing_connector_yaml(config_path)
    return config_files.existing_executor_node_config(raw).get("enabled_executors")


def test_set_hermes_command_replaces_enabled_with_single_family(tmp_path):
    config_path = tmp_path / "config.yaml"
    executor_settings.set_codex_command(config_path=config_path, command="/usr/local/bin/codex")
    executor_settings.set_hermes_command(config_path=config_path, command="/usr/local/bin/hermes")
    assert _enabled(config_path) == ["hermes"]


def test_set_codex_command_writes_single_family(tmp_path):
    config_path = tmp_path / "config.yaml"
    executor_settings.set_hermes_command(config_path=config_path, command="/usr/local/bin/hermes")
    executor_settings.set_codex_command(config_path=config_path, command="/usr/local/bin/codex")
    assert _enabled(config_path) == ["codex"]


def test_supported_executors_includes_hermes():
    assert "hermes" in executor_settings.SUPPORTED_EXECUTORS


def test_set_hermes_command_writes_block(tmp_path):
    config_path = tmp_path / "config.yaml"
    executor_settings.set_hermes_command(config_path=config_path, command="/usr/local/bin/hermes")
    text = config_path.read_text()
    assert "hermes" in text
    assert "/usr/local/bin/hermes" in text


def test_print_human_probe_uses_executor_name_from_payload(capsys):
    payload = {
        "current": {
            "executor": "hermes",
            "command": "hermes",
            "resolved_path": "/usr/local/bin/hermes",
            "version": "1.2.3",
            "ok": True,
            "error": None,
        },
        "candidates": [],
    }
    executor_settings._print_human_probe(payload)
    out = capsys.readouterr().out
    assert "hermes current:" in out
    assert "Codex current:" not in out


def test_hermes_probe_payload_has_authenticated_key(tmp_path, monkeypatch):
    from newbro.cli.commands import executor_settings
    from newbro.executors.adapters.hermes import probe as hermes_probe
    monkeypatch.setattr(hermes_probe, "probe_hermes_command", lambda cmd: hermes_probe.HermesProbeResult(path="/h", version="0.12.0", ok=True))
    monkeypatch.setattr(hermes_probe, "probe_hermes_authenticated", lambda cmd: True)
    payload = executor_settings.hermes_probe_payload(config_path=tmp_path / "config.yaml")
    assert payload["current"]["authenticated"] is True


def test_install_hermes_runs_vendor_script_then_sets_command(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(executor_settings, "_run_install_step", lambda argv, msg, env=None: calls.append(argv))
    seq = iter([
        hermes_probe.HermesProbeResult(path="hermes", version=None, ok=False, error="command not found"),
        hermes_probe.HermesProbeResult(path="/Users/me/.local/bin/hermes", version="0.12.0", ok=True),
    ])
    monkeypatch.setattr(hermes_probe, "probe_hermes_command", lambda cmd: next(seq))
    command = executor_settings.install_hermes_cli(tmp_path / "config.yaml")
    assert command.endswith("/hermes")
    assert any("install.sh" in " ".join(argv) for argv in calls)


def test_install_hermes_raises_when_still_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(executor_settings, "_run_install_step", lambda argv, msg, env=None: None)
    monkeypatch.setattr(hermes_probe, "probe_hermes_command",
                        lambda cmd: hermes_probe.HermesProbeResult(path="hermes", version=None, ok=False, error="command not found"))
    with pytest.raises(RuntimeError, match="hermes setup --portal"):
        executor_settings.install_hermes_cli(tmp_path / "config.yaml")


def test_install_hermes_finds_local_bin_when_which_misses(tmp_path, monkeypatch):
    """After install, resolution falls back to ~/.local/bin/hermes even when
    ``which("hermes")`` (bare name PATH probe) returns nothing."""
    local_bin_hermes = str(Path.home() / ".local" / "bin" / "hermes")

    monkeypatch.setattr(executor_settings, "_run_install_step", lambda argv, msg, env=None: None)

    def fake_probe(cmd):
        if cmd == "hermes":
            return hermes_probe.HermesProbeResult(path="hermes", version=None, ok=False, error="command not found")
        if cmd == local_bin_hermes:
            return hermes_probe.HermesProbeResult(path=local_bin_hermes, version="0.12.0", ok=True)
        return hermes_probe.HermesProbeResult(path=cmd, version=None, ok=False, error="command not found")

    monkeypatch.setattr(hermes_probe, "probe_hermes_command", fake_probe)

    config_path = tmp_path / "config.yaml"
    command = executor_settings.install_hermes_cli(config_path)
    assert command == local_bin_hermes
    raw = config_files.load_existing_connector_yaml(config_path)
    executors = config_files.existing_executors_config(raw)
    assert executors["hermes"]["command"] == local_bin_hermes


def test_cmd_executor_routes_install_hermes_to_run_executor_install_hermes(monkeypatch):
    called_with: list[tuple[object, object]] = []

    def fake_run_executor_install_hermes(args, app):
        called_with.append((args, app))
        return 0

    monkeypatch.setattr(
        cli_dispatch.executor_settings_command,
        "run_executor_install_hermes",
        fake_run_executor_install_hermes,
    )

    args = SimpleNamespace(executor_command="install-hermes")
    app = object()
    result = cli_dispatch.cmd_executor(args, app)

    assert result == 0
    assert len(called_with) == 1
    assert called_with[0] == (args, app)
