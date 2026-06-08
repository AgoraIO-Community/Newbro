#!/usr/bin/env bash
set -euo pipefail

ROOT="${SYNAPSE_INSTALL_ROOT:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)}"
FRONTEND_DIR="$ROOT/clients/web"
MIN_PYTHON_MAJOR=3
MIN_PYTHON_MINOR=12

log() {
  printf '[install] %s\n' "$*"
}

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

have_cmd() {
  command -v "$1" >/dev/null 2>&1
}

prepend_path_once() {
  local path_entry="$1"
  case ":$PATH:" in
    *":$path_entry:"*)
      ;;
    *)
      export PATH="$path_entry:$PATH"
      ;;
  esac
}

add_user_bun_to_path() {
  local bun_dir
  [[ -n "${HOME:-}" ]] || return 0
  bun_dir="$HOME/.bun/bin"
  [[ -x "$bun_dir/bun" ]] || return 0
  prepend_path_once "$bun_dir"
}

detect_uname() {
  if [[ -n "${SYNAPSE_INSTALL_TEST_UNAME:-}" ]]; then
    printf '%s\n' "$SYNAPSE_INSTALL_TEST_UNAME"
    return
  fi
  uname -s
}

os_release_path() {
  if [[ -n "${SYNAPSE_INSTALL_TEST_OS_RELEASE:-}" ]]; then
    printf '%s\n' "$SYNAPSE_INSTALL_TEST_OS_RELEASE"
    return
  fi
  printf '/etc/os-release\n'
}

run_as_root() {
  if [[ "$(id -u)" == "0" ]]; then
    "$@"
    return
  fi
  if have_cmd sudo; then
    sudo "$@"
    return
  fi
  die "sudo is required for system package installation."
}

python_meets_minimum() {
  local python_bin="$1"
  "$python_bin" -c "import sys; raise SystemExit(0 if sys.version_info >= (${MIN_PYTHON_MAJOR}, ${MIN_PYTHON_MINOR}) else 1)" >/dev/null 2>&1
}

python_supports_venv() {
  local python_bin="$1"
  "$python_bin" -m venv --help >/dev/null 2>&1
}

python_supports_pip() {
  local python_bin="$1"
  "$python_bin" -m pip --version >/dev/null 2>&1
}

find_supported_python() {
  local candidate
  local candidate_path

  for candidate in python3.12 python3 python; do
    if ! have_cmd "$candidate"; then
      continue
    fi
    candidate_path="$(command -v "$candidate")"
    if python_meets_minimum "$candidate_path"; then
      printf '%s\n' "$candidate_path"
      return 0
    fi
  done

  return 1
}

install_macos_dependencies() {
  local python_bin

  add_user_bun_to_path
  python_bin="$(find_supported_python || true)"

  if [[ -n "$python_bin" ]] && python_supports_venv "$python_bin" && python_supports_pip "$python_bin"; then
    log "Skipping Python install; found supported interpreter at $python_bin"
  else
    if ! have_cmd brew; then
      die "Homebrew is required on macOS when Python 3.12+ is not already available. Install Homebrew first, then rerun ./install.sh."
    fi
    log "Installing Python 3.12+ with Homebrew"
    brew install python@3.12
  fi

  if have_cmd bun; then
    log "Skipping Bun install; bun already available"
    return
  fi

  if ! have_cmd curl; then
    die "curl is required to install Bun."
  fi
  log "Installing Bun"
  curl -fsSL https://bun.sh/install | bash
  add_user_bun_to_path
  if ! have_cmd bun; then
    die "Bun installation completed but bun is still not available on PATH."
  fi
}

install_linux_dependencies() {
  local python_bin
  local needs_apt=0

  add_user_bun_to_path
  python_bin="$(find_supported_python || true)"

  if [[ -n "$python_bin" ]] && python_supports_venv "$python_bin" && python_supports_pip "$python_bin"; then
    log "Skipping Python install; found supported interpreter at $python_bin"
  else
    needs_apt=1
  fi

  if have_cmd bun; then
    log "Skipping Bun install; bun already available"
  elif ! have_cmd curl; then
    needs_apt=1
  fi

  if (( needs_apt )); then
    ensure_supported_linux
    if ! have_cmd apt-get; then
      die "Only Ubuntu/Debian apt-get environments are supported by install.sh for automatic dependency installation."
    fi

    log "Installing missing apt prerequisites"
    run_as_root apt-get update
    run_as_root apt-get install -y python3 python3-venv python3-pip curl ca-certificates
  fi

  python_bin="$(choose_python)"
  if ! python_supports_venv "$python_bin"; then
    die "Selected Python interpreter at $python_bin does not support python -m venv."
  fi
  if ! python_supports_pip "$python_bin"; then
    die "Selected Python interpreter at $python_bin does not support python -m pip."
  fi

  if have_cmd bun; then
    return
  fi

  if ! have_cmd curl; then
    die "curl is required to install Bun."
  fi
  log "Installing Bun"
  curl -fsSL https://bun.sh/install | bash
  add_user_bun_to_path
  if ! have_cmd bun; then
    die "Bun installation completed but bun is still not available on PATH."
  fi
}

ensure_supported_linux() {
  local os_release
  os_release="$(os_release_path)"
  [[ -f "$os_release" ]] || die "Cannot detect Linux distribution: missing $os_release"

  # shellcheck disable=SC1090
  source "$os_release"
  case "${ID:-}" in
    ubuntu|debian)
      ;;
    *)
      die "install.sh supports Ubuntu and Debian on Linux right now."
      ;;
  esac
}

choose_python() {
  local python_bin

  python_bin="$(find_supported_python || true)"
  if [[ -n "$python_bin" ]]; then
    printf '%s\n' "$python_bin"
    return
  fi
  die "Python 3.12 or newer is required but was not found after dependency installation."
}

bootstrap_repo_dependencies() {
  local python_bin="$1"
  local venv_python
  venv_python="$ROOT/.venv/bin/python"

  [[ -d "$FRONTEND_DIR" ]] || die "Expected frontend directory at $FRONTEND_DIR"

  log "Creating repo virtualenv"
  "$python_bin" -m venv "$ROOT/.venv"
  [[ -x "$venv_python" ]] || die "Virtualenv bootstrap did not create $venv_python"

  log "Installing editable Python dependencies"
  "$venv_python" -m pip install --upgrade pip
  "$venv_python" -m pip install -e '.[dev]'

  if have_cmd bun; then
    log "Installing frontend dependencies with Bun"
    (
      cd "$FRONTEND_DIR"
      bun install
    )
    return
  fi

  if have_cmd npm; then
    log "Installing frontend dependencies with npm"
    (
      cd "$FRONTEND_DIR"
      npm install
    )
    return
  fi

  die "Need Bun or npm to install frontend dependencies."
}

bootstrap_config_files() {
  local venv_python="$ROOT/.venv/bin/python"
  local venv_newbro="$ROOT/.venv/bin/newbro"

  [[ -x "$venv_python" ]] || die "Expected virtualenv python at $venv_python"
  [[ -x "$venv_newbro" ]] || die "Expected installed newbro console script at $venv_newbro"

  log "Creating starter Newbro config files"
  "$venv_newbro" setup --bootstrap-defaults
}

main() {
  local uname_out
  local python_bin

  add_user_bun_to_path
  uname_out="$(detect_uname)"
  case "$uname_out" in
    Darwin)
      install_macos_dependencies
      ;;
    Linux)
      install_linux_dependencies
      ;;
    *)
      die "install.sh supports macOS and Ubuntu/Debian right now."
      ;;
  esac

  add_user_bun_to_path
  python_bin="$(choose_python)"
  bootstrap_repo_dependencies "$python_bin"
  bootstrap_config_files

  printf '\nNext:\n'
  printf '  ./newbro setup\n'
  printf '  ./newbro doctor\n'
  printf '  ./newbro dev\n'
}

main "$@"
