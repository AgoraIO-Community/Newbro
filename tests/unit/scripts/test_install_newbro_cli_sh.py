from __future__ import annotations

from pathlib import Path
import os
import stat
import subprocess
import textwrap


REPO_ROOT = Path(__file__).resolve().parents[3]
INSTALL_SCRIPT = REPO_ROOT / "scripts" / "install-newbro-cli.sh"


def write_executable(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def fake_uv_script() -> str:
    return """#!/usr/bin/env sh
set -eu
echo "uv $*" >> "$FAKE_LOG"
"""


def fake_uv_requiring_force_script() -> str:
    return """#!/usr/bin/env sh
set -eu
echo "uv $*" >> "$FAKE_LOG"
case " $* " in
  *" --force "*) ;;
  *) echo "missing --force" >&2; exit 42 ;;
esac
"""


def fake_newbro_script() -> str:
    return """#!/usr/bin/env sh
set -eu
echo "newbro $*" >> "$FAKE_LOG"
"""


def fake_curl_installing_uv_script() -> str:
    return """#!/usr/bin/env sh
set -eu
echo "curl $*" >> "$FAKE_LOG"
cat <<'INNER'
set -eu
mkdir -p "$HOME/.local/bin"
cat > "$HOME/.local/bin/uv" <<'UV'
#!/usr/bin/env sh
set -eu
echo "uv $*" >> "$FAKE_LOG"
cat > "$HOME/.local/bin/newbro" <<'NEWBRO'
#!/usr/bin/env sh
set -eu
echo "newbro $*" >> "$FAKE_LOG"
NEWBRO
chmod +x "$HOME/.local/bin/newbro"
UV
chmod +x "$HOME/.local/bin/uv"
INNER
"""


def test_install_newbro_cli_uses_existing_uv_and_runs_forwarded_args(tmp_path: Path):
    fake_bin = tmp_path / "bin"
    home = tmp_path / "home"
    log_file = tmp_path / "install.log"
    fake_bin.mkdir()
    home.mkdir()
    write_executable(fake_bin / "uv", fake_uv_script())
    write_executable(fake_bin / "newbro", fake_newbro_script())

    env = os.environ.copy()
    env.update(
        {
            "FAKE_LOG": str(log_file),
            "HOME": str(home),
            "PATH": f"{fake_bin}:/usr/bin:/bin",
        }
    )

    completed = subprocess.run(
        [
            "sh",
            str(INSTALL_SCRIPT),
            "executor",
            "run",
            "--base-url",
            "https://newbro.example.com",
            "--node-id",
            "node-1",
            "--token",
            "secret",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert log_file.read_text(encoding="utf-8").splitlines() == [
        "uv tool install --python 3.12 --upgrade --force newbro-cli",
        "newbro executor run --base-url https://newbro.example.com --node-id node-1 --token secret",
    ]
    assert "Using uv at" in completed.stdout


def test_install_newbro_cli_forces_over_existing_newbro_executable(tmp_path: Path):
    fake_bin = tmp_path / "bin"
    home = tmp_path / "home"
    log_file = tmp_path / "install.log"
    fake_bin.mkdir()
    home.mkdir()
    write_executable(fake_bin / "uv", fake_uv_requiring_force_script())
    write_executable(fake_bin / "newbro", fake_newbro_script())

    env = os.environ.copy()
    env.update(
        {
            "FAKE_LOG": str(log_file),
            "HOME": str(home),
            "PATH": f"{fake_bin}:/usr/bin:/bin",
        }
    )

    completed = subprocess.run(
        ["sh", str(INSTALL_SCRIPT), "--version"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert log_file.read_text(encoding="utf-8").splitlines() == [
        "uv tool install --python 3.12 --upgrade --force newbro-cli",
        "newbro --version",
    ]


def test_install_newbro_cli_installs_uv_when_missing(tmp_path: Path):
    fake_bin = tmp_path / "bin"
    home = tmp_path / "home"
    log_file = tmp_path / "install.log"
    fake_bin.mkdir()
    home.mkdir()
    write_executable(fake_bin / "curl", fake_curl_installing_uv_script())

    env = os.environ.copy()
    env.update(
        {
            "FAKE_LOG": str(log_file),
            "HOME": str(home),
            "PATH": f"{fake_bin}:/usr/bin:/bin",
        }
    )

    completed = subprocess.run(
        ["sh", str(INSTALL_SCRIPT), "--help"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert log_file.read_text(encoding="utf-8").splitlines() == [
        "curl -LsSf https://astral.sh/uv/install.sh",
        "uv tool install --python 3.12 --upgrade --force newbro-cli",
        "newbro --help",
    ]
    assert "Installing uv" in completed.stdout


def test_install_newbro_cli_without_args_installs_only(tmp_path: Path):
    fake_bin = tmp_path / "bin"
    home = tmp_path / "home"
    log_file = tmp_path / "install.log"
    fake_bin.mkdir()
    home.mkdir()
    write_executable(fake_bin / "uv", fake_uv_script())
    write_executable(fake_bin / "newbro", fake_newbro_script())

    env = os.environ.copy()
    env.update(
        {
            "FAKE_LOG": str(log_file),
            "HOME": str(home),
            "PATH": f"{fake_bin}:/usr/bin:/bin",
        }
    )

    completed = subprocess.run(
        ["sh", str(INSTALL_SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert log_file.read_text(encoding="utf-8").splitlines() == [
        "uv tool install --python 3.12 --upgrade --force newbro-cli",
    ]
    assert "Done. Run: newbro --help" in completed.stdout
