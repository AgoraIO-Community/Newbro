from pathlib import Path

import pytest

from newbro.cli.parser import build_parser


def _parser():
    return build_parser(cli_name="newbro", env_file=Path("/tmp/.env"), start_public_port=8000)


def test_version_flag_prints_package_version(capsys):
    parser = _parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    # argparse prints "newbro <version>"; version is a non-empty dotted string.
    parts = out.split()
    assert parts[0] == "newbro"
    assert parts[1][0].isdigit()
