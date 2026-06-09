from newbro.cli.commands import executor_settings


def test_supported_executors_includes_hermes():
    assert "hermes" in executor_settings.SUPPORTED_EXECUTORS


def test_set_hermes_command_writes_block(tmp_path):
    config_path = tmp_path / "config.yaml"
    executor_settings.set_hermes_command(config_path=config_path, command="/usr/local/bin/hermes")
    text = config_path.read_text()
    assert "hermes" in text
    assert "/usr/local/bin/hermes" in text
