from __future__ import annotations

from pathlib import Path
import os
import pytest
import stat
import subprocess
import textwrap


REPO_ROOT = Path(__file__).resolve().parents[3]
INSTALL_SCRIPT = REPO_ROOT / "install.sh"
BOOTSTRAP_COMMAND = "venv-newbro setup --bootstrap-defaults"
LEGACY_BOOTSTRAP_COMMAND = "venv-python -m newbro setup --bootstrap-defaults"


def write_executable(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def prepare_repo_root(root: Path) -> None:
    frontend_dir = root / "clients" / "web"
    frontend_dir.mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname='newbro-cli'\n", encoding="utf-8")
    (frontend_dir / "package.json").write_text(
        '{"name":"newbro-frontend"}\n',
        encoding="utf-8",
    )


def read_bootstrap_outputs(home: Path) -> tuple[str, str]:
    env_path = home / ".newbro" / ".env"
    config_path = home / ".newbro" / "config.yaml"

    assert env_path.exists()
    assert config_path.exists()

    env_text = env_path.read_text(encoding="utf-8")
    config_text = config_path.read_text(encoding="utf-8")

    assert "SYNAPSE_CODEX_EXECUTOR_ENABLED" not in env_text
    assert '# Shared Newbro credentials written by `newbro setup` to ~/.newbro/.env' in env_text
    assert 'public_base_url: "http://127.0.0.1:8000"' in config_text
    assert "executor_node:" in config_text
    assert "node_id: node-bootstrap" in config_text
    assert "executors: {}" in config_text

    return env_text, config_text


def assert_bootstrap_command(log_text: str) -> None:
    assert BOOTSTRAP_COMMAND in log_text
    assert LEGACY_BOOTSTRAP_COMMAND not in log_text


def fake_bun_script() -> str:
    return """#!/usr/bin/env bash
set -euo pipefail
echo "bun $*" >> "$FAKE_LOG"
"""


def fake_curl_installing_bun_script() -> str:
    return """#!/usr/bin/env bash
set -euo pipefail
echo "curl $*" >> "$FAKE_LOG"
cat <<'INNER'
set -euo pipefail
mkdir -p "$HOME/.bun/bin"
cat > "$HOME/.bun/bin/bun" <<'BUN'
#!/usr/bin/env bash
set -euo pipefail
echo "bun $*" >> "$FAKE_LOG"
BUN
chmod +x "$HOME/.bun/bin/bun"
INNER
"""


def fake_python_script(*, version_ok: bool = True, venv_ok: bool = True, pip_ok: bool = True) -> str:
    version_exit = "0" if version_ok else "1"
    venv_exit = "0" if venv_ok else "1"
    pip_exit = "0" if pip_ok else "1"
    return f"""#!/usr/bin/env bash
set -euo pipefail
echo "$(basename "$0") $*" >> "$FAKE_LOG"
if [[ "${{1-}}" == "-c" ]]; then
  exit {version_exit}
fi
if [[ "${{1-}}" == "-m" && "${{2-}}" == "venv" && "${{3-}}" == "--help" ]]; then
  exit {venv_exit}
fi
if [[ "${{1-}}" == "-m" && "${{2-}}" == "pip" && "${{3-}}" == "--version" ]]; then
  exit {pip_exit}
fi
if [[ "${{1-}}" == "-m" && "${{2-}}" == "venv" ]]; then
  if [[ {venv_exit} -ne 0 ]]; then
    exit {venv_exit}
  fi
  target="${{3:?}}"
  mkdir -p "$target/bin"
  cat > "$target/bin/python" <<'INNER'
#!/usr/bin/env bash
set -euo pipefail
echo "venv-python $*" >> "$FAKE_LOG"
if [[ "${{1-}}" == "-m" && "${{2-}}" == "pip" && "${{3-}}" == "install" && "${{4-}}" == "-e" ]]; then
  cat > "${{0%/*}}/newbro" <<'NEWBRO'
#!/usr/bin/env bash
set -euo pipefail
echo "venv-newbro $*" >> "$FAKE_LOG"
if [[ "${{1-}}" == "setup" && "${{2-}}" == "--bootstrap-defaults" ]]; then
  mkdir -p "$HOME/.newbro"
  cat > "$HOME/.newbro/.env" <<'BOOTSTRAP_ENV'
OPENAI_API_KEY=
SYNAPSE_OPENAI_MODEL=gpt-4o-mini
SYNAPSE_OPENAI_TIMEOUT_SECONDS=30
# SYNAPSE_OPENAI_BASE_URL=
# Shared Newbro credentials written by `newbro setup` to ~/.newbro/.env
# AGORA_APP_ID=
# AGORA_APP_CERTIFICATE=
# DEEPGRAM_API_KEY=
# ELEVENLABS_API_KEY=
BOOTSTRAP_ENV
  cat > "$HOME/.newbro/config.yaml" <<'BOOTSTRAP_CONFIG'
version: 1

runtime: {{}}

connector_host:
  enabled: false
  host: 0.0.0.0
  port: 8010
  public_base_url: "http://127.0.0.1:8000"
  synapse_base_url: "http://127.0.0.1:8000"
  enabled_connectors: []

connectors: {{}}

executor_node:
  enabled: false
  synapse_base_url: "http://127.0.0.1:8000"
  node_id: node-bootstrap
  enabled_executors: []

executors: {{}}
BOOTSTRAP_CONFIG
fi
NEWBRO
  chmod +x "${{0%/*}}/newbro"
fi
exit 0
INNER
  chmod +x "$target/bin/python"
fi
"""


def fake_brew_installing_python_script() -> str:
    return """#!/usr/bin/env bash
set -euo pipefail
echo "brew $*" >> "$FAKE_LOG"
if [[ "${1-}" == "install" && "${2-}" == "python@3.12" ]]; then
  cp "$FAKE_PYTHON_REPLACEMENT" "$FAKE_PYTHON_TARGET"
  chmod +x "$FAKE_PYTHON_TARGET"
fi
"""


def test_install_sh_macos_skips_existing_system_dependencies(tmp_path: Path):
    repo_root = tmp_path / "repo"
    fake_bin = tmp_path / "bin"
    home = tmp_path / "home"
    log_file = tmp_path / "install.log"
    prepare_repo_root(repo_root)
    fake_bin.mkdir()
    home.mkdir()

    write_executable(fake_bin / "python3.12", fake_python_script())
    write_executable(fake_bin / "bun", fake_bun_script())

    env = os.environ.copy()
    env.update(
        {
            "FAKE_LOG": str(log_file),
            "HOME": str(home),
            "PATH": f"{fake_bin}:/usr/bin:/bin",
            "OPENAI_API_KEY": "sk-shell-secret",
            "AGORA_APP_ID": "agora-shell-app",
            "SYNAPSE_CODEX_EXECUTOR_ENABLED": "not-a-bool",
            "SYNAPSE_CODEX_COMMAND": "/shell/codex",
            "SYNAPSE_INSTALL_ROOT": str(repo_root),
            "SYNAPSE_INSTALL_TEST_UNAME": "Darwin",
        }
    )

    completed = subprocess.run(
        ["bash", str(INSTALL_SCRIPT)],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    log_text = log_file.read_text(encoding="utf-8")
    assert "brew install python@3.12" not in log_text
    assert "curl -fsSL https://bun.sh/install" not in log_text
    assert f"python3.12 -m venv {repo_root / '.venv'}" in log_text
    assert "venv-python -m pip install --upgrade pip" in log_text
    assert "venv-python -m pip install -e .[dev]" in log_text
    assert "bun install" in log_text
    assert_bootstrap_command(log_text)
    env_text, _ = read_bootstrap_outputs(home)
    assert "sk-shell-secret" not in env_text
    assert "agora-shell-app" not in env_text
    assert "/shell/codex" not in env_text
    assert "[install] Skipping Python install;" in completed.stdout
    assert "[install] Skipping Bun install;" in completed.stdout
    assert "./newbro setup" in completed.stdout


def test_install_sh_macos_installs_only_missing_bun(tmp_path: Path):
    repo_root = tmp_path / "repo"
    fake_bin = tmp_path / "bin"
    home = tmp_path / "home"
    log_file = tmp_path / "install.log"
    prepare_repo_root(repo_root)
    fake_bin.mkdir()
    home.mkdir()

    write_executable(fake_bin / "python3.12", fake_python_script())
    write_executable(fake_bin / "curl", fake_curl_installing_bun_script())

    env = os.environ.copy()
    env.update(
        {
            "FAKE_LOG": str(log_file),
            "HOME": str(home),
            "PATH": f"{fake_bin}:/usr/bin:/bin",
            "SYNAPSE_INSTALL_ROOT": str(repo_root),
            "SYNAPSE_INSTALL_TEST_UNAME": "Darwin",
        }
    )

    completed = subprocess.run(
        ["bash", str(INSTALL_SCRIPT)],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    log_text = log_file.read_text(encoding="utf-8")
    assert "brew install python@3.12" not in log_text
    assert "curl -fsSL https://bun.sh/install" in log_text
    assert "bun install" in log_text
    assert_bootstrap_command(log_text)
    read_bootstrap_outputs(home)
    assert "[install] Skipping Python install;" in completed.stdout
    assert "[install] Installing Bun" in completed.stdout


@pytest.mark.parametrize(
    ("venv_ok", "pip_ok"),
    [
        (False, True),
        (True, False),
    ],
)
def test_install_sh_macos_reinstalls_python_when_capabilities_missing(
    tmp_path: Path,
    venv_ok: bool,
    pip_ok: bool,
):
    repo_root = tmp_path / "repo"
    fake_bin = tmp_path / "bin"
    home = tmp_path / "home"
    log_file = tmp_path / "install.log"
    replacement_python = tmp_path / "python3.12.good"
    prepare_repo_root(repo_root)
    fake_bin.mkdir()
    home.mkdir()

    write_executable(
        fake_bin / "brew",
        fake_brew_installing_python_script(),
    )
    write_executable(
        fake_bin / "python3.12",
        fake_python_script(venv_ok=venv_ok, pip_ok=pip_ok),
    )
    write_executable(replacement_python, fake_python_script())
    write_executable(fake_bin / "bun", fake_bun_script())

    env = os.environ.copy()
    env.update(
        {
            "FAKE_LOG": str(log_file),
            "HOME": str(home),
            "PATH": f"{fake_bin}:/usr/bin:/bin",
            "FAKE_PYTHON_REPLACEMENT": str(replacement_python),
            "FAKE_PYTHON_TARGET": str(fake_bin / "python3.12"),
            "SYNAPSE_INSTALL_ROOT": str(repo_root),
            "SYNAPSE_INSTALL_TEST_UNAME": "Darwin",
        }
    )

    completed = subprocess.run(
        ["bash", str(INSTALL_SCRIPT)],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    log_text = log_file.read_text(encoding="utf-8")
    assert "brew install python@3.12" in log_text
    assert f"python3.12 -m venv {repo_root / '.venv'}" in log_text
    assert "venv-python -m pip install --upgrade pip" in log_text
    assert_bootstrap_command(log_text)
    read_bootstrap_outputs(home)
    assert "[install] Installing Python 3.12+ with Homebrew" in completed.stdout
    assert "[install] Skipping Python install;" not in completed.stdout
    assert "[install] Skipping Bun install;" in completed.stdout


def test_install_sh_ubuntu_skips_existing_system_dependencies(tmp_path: Path):
    repo_root = tmp_path / "repo"
    fake_bin = tmp_path / "bin"
    home = tmp_path / "home"
    log_file = tmp_path / "install.log"
    prepare_repo_root(repo_root)
    fake_bin.mkdir()
    home.mkdir()

    write_executable(fake_bin / "python3.12", fake_python_script())
    write_executable(fake_bin / "bun", fake_bun_script())

    env = os.environ.copy()
    env.update(
        {
            "FAKE_LOG": str(log_file),
            "HOME": str(home),
            "PATH": f"{fake_bin}:/usr/bin:/bin",
            "SYNAPSE_INSTALL_ROOT": str(repo_root),
            "SYNAPSE_INSTALL_TEST_UNAME": "Linux",
            "SYNAPSE_INSTALL_TEST_OS_RELEASE": str(tmp_path / "missing-os-release"),
        }
    )

    completed = subprocess.run(
        ["bash", str(INSTALL_SCRIPT)],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    log_text = log_file.read_text(encoding="utf-8")
    assert "apt-get" not in log_text
    assert "curl -fsSL https://bun.sh/install" not in log_text
    assert f"python3.12 -m venv {repo_root / '.venv'}" in log_text
    assert "bun install" in log_text
    assert_bootstrap_command(log_text)
    read_bootstrap_outputs(home)
    assert "[install] Skipping Python install;" in completed.stdout
    assert "[install] Skipping Bun install;" in completed.stdout


def test_install_sh_ubuntu_reinstalls_python_prerequisites_when_venv_missing(tmp_path: Path):
    repo_root = tmp_path / "repo"
    fake_bin = tmp_path / "bin"
    home = tmp_path / "home"
    log_file = tmp_path / "install.log"
    os_release = tmp_path / "os-release"
    replacement_python = tmp_path / "python3.12.good"
    prepare_repo_root(repo_root)
    fake_bin.mkdir()
    home.mkdir()
    os_release.write_text("ID=ubuntu\n", encoding="utf-8")

    write_executable(
        fake_bin / "id",
        """#!/usr/bin/env bash
echo "1000"
""",
    )
    write_executable(
        fake_bin / "sudo",
        """#!/usr/bin/env bash
echo "sudo $*" >> "$FAKE_LOG"
"$@"
""",
    )
    write_executable(
        fake_bin / "apt-get",
        """#!/usr/bin/env bash
echo "apt-get $*" >> "$FAKE_LOG"
if [[ "${1-}" == "install" ]]; then
  cp "$FAKE_PYTHON_REPLACEMENT" "$FAKE_PYTHON_TARGET"
  chmod +x "$FAKE_PYTHON_TARGET"
fi
""",
    )
    write_executable(fake_bin / "python3.12", fake_python_script(venv_ok=False))
    write_executable(replacement_python, fake_python_script())
    write_executable(fake_bin / "bun", fake_bun_script())

    env = os.environ.copy()
    env.update(
        {
            "FAKE_LOG": str(log_file),
            "HOME": str(home),
            "PATH": f"{fake_bin}:/usr/bin:/bin",
            "FAKE_PYTHON_REPLACEMENT": str(replacement_python),
            "FAKE_PYTHON_TARGET": str(fake_bin / "python3.12"),
            "SYNAPSE_INSTALL_ROOT": str(repo_root),
            "SYNAPSE_INSTALL_TEST_UNAME": "Linux",
            "SYNAPSE_INSTALL_TEST_OS_RELEASE": str(os_release),
        }
    )

    completed = subprocess.run(
        ["bash", str(INSTALL_SCRIPT)],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    log_text = log_file.read_text(encoding="utf-8")
    assert "sudo apt-get update" in log_text
    assert "apt-get install -y python3 python3-venv python3-pip curl ca-certificates" in log_text
    assert f"python3.12 -m venv {repo_root / '.venv'}" in log_text
    assert "venv-python -m pip install --upgrade pip" in log_text
    assert "bun install" in log_text
    assert_bootstrap_command(log_text)
    assert "curl -fsSL https://bun.sh/install" not in log_text
    read_bootstrap_outputs(home)
    assert "[install] Installing missing apt prerequisites" in completed.stdout
    assert "[install] Installing Ubuntu/Debian dependencies with apt-get" not in completed.stdout
    assert "[install] Skipping Bun install;" in completed.stdout


def test_install_sh_ubuntu_installs_curl_before_bun_when_curl_missing(tmp_path: Path):
    repo_root = tmp_path / "repo"
    fake_bin = tmp_path / "bin"
    home = tmp_path / "home"
    log_file = tmp_path / "install.log"
    os_release = tmp_path / "os-release"
    replacement_curl = tmp_path / "curl.good"
    prepare_repo_root(repo_root)
    fake_bin.mkdir()
    home.mkdir()
    os_release.write_text("ID=ubuntu\n", encoding="utf-8")
    for command_name, target in {
        "bash": "/bin/bash",
        "basename": "/usr/bin/basename",
        "cat": "/bin/cat",
        "chmod": "/bin/chmod",
        "cp": "/bin/cp",
        "mkdir": "/bin/mkdir",
    }.items():
        (fake_bin / command_name).symlink_to(target)

    write_executable(
        fake_bin / "id",
        """#!/usr/bin/env bash
echo "1000"
""",
    )
    write_executable(
        fake_bin / "sudo",
        """#!/usr/bin/env bash
echo "sudo $*" >> "$FAKE_LOG"
"$@"
""",
    )
    write_executable(
        fake_bin / "apt-get",
        """#!/usr/bin/env bash
echo "apt-get $*" >> "$FAKE_LOG"
if [[ "${1-}" == "install" ]]; then
  cp "$FAKE_CURL_REPLACEMENT" "$FAKE_CURL_TARGET"
  chmod +x "$FAKE_CURL_TARGET"
fi
""",
    )
    write_executable(fake_bin / "python3.12", fake_python_script())
    write_executable(replacement_curl, fake_curl_installing_bun_script())

    env = os.environ.copy()
    env.update(
        {
            "FAKE_LOG": str(log_file),
            "HOME": str(home),
            "PATH": str(fake_bin),
            "FAKE_CURL_REPLACEMENT": str(replacement_curl),
            "FAKE_CURL_TARGET": str(fake_bin / "curl"),
            "SYNAPSE_INSTALL_ROOT": str(repo_root),
            "SYNAPSE_INSTALL_TEST_UNAME": "Linux",
            "SYNAPSE_INSTALL_TEST_OS_RELEASE": str(os_release),
        }
    )

    completed = subprocess.run(
        ["bash", str(INSTALL_SCRIPT)],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    log_text = log_file.read_text(encoding="utf-8")
    assert "sudo apt-get update" in log_text
    assert "apt-get install -y python3 python3-venv python3-pip curl ca-certificates" in log_text
    assert "curl -fsSL https://bun.sh/install" in log_text
    assert f"python3.12 -m venv {repo_root / '.venv'}" in log_text
    assert "bun install" in log_text
    assert_bootstrap_command(log_text)
    read_bootstrap_outputs(home)
    assert "[install] Skipping Python install;" in completed.stdout
    assert "[install] Installing missing apt prerequisites" in completed.stdout
    assert "[install] Installing Ubuntu/Debian dependencies with apt-get" not in completed.stdout
    assert "[install] Installing Bun" in completed.stdout
