# tests/unit/cli/test_executor_parser.py
from pathlib import Path

from newbro.cli.parser import build_parser


def _parser():
    return build_parser(cli_name="newbro", env_file=Path("/tmp/.env"), start_public_port=8000)


def test_probe_accepts_hermes():
    args = _parser().parse_args(["executor", "probe", "--executor", "hermes"])
    assert args.executor == "hermes"


def test_enabled_executor_accepts_hermes():
    args = _parser().parse_args(
        ["executor", "run", "--base-url", "u", "--node-id", "n", "--token", "t", "--enabled-executor", "hermes"]
    )
    assert args.enabled_executor == ["hermes"]


def test_install_hermes_subcommand_parses():
    args = _parser().parse_args(["executor", "install-hermes"])
    assert args.executor_command == "install-hermes"


def _p():
    return build_parser(cli_name="newbro", env_file=Path("/tmp/.env"), start_public_port=8000)


def test_probe_rejects_acpx():
    import pytest
    with pytest.raises(SystemExit):
        _p().parse_args(["executor", "probe", "--executor", "acpx"])


def test_probe_still_accepts_hermes_and_codex():
    assert _p().parse_args(["executor", "probe", "--executor", "hermes"]).executor == "hermes"
    assert _p().parse_args(["executor", "use", "--executor", "codex", "--command", "/x"]).executor == "codex"
