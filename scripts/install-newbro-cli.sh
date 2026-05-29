#!/usr/bin/env sh
set -eu

UV_INSTALL_URL="https://astral.sh/uv/install.sh"

log() {
  printf '[newbro-cli-install] %s\n' "$*"
}

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

have_cmd() {
  command -v "$1" >/dev/null 2>&1
}

prepend_path_once() {
  path_entry="$1"
  case ":$PATH:" in
    *":$path_entry:"*) ;;
    *) PATH="$path_entry:$PATH"; export PATH ;;
  esac
}

add_user_tool_paths() {
  if [ -n "${HOME:-}" ]; then
    prepend_path_once "$HOME/.local/bin"
    prepend_path_once "$HOME/.cargo/bin"
  fi
}

install_uv() {
  add_user_tool_paths
  if have_cmd uv; then
    log "Using uv at $(command -v uv)"
    return
  fi
  if ! have_cmd curl; then
    die "curl is required to install uv."
  fi
  log "Installing uv"
  curl -LsSf "$UV_INSTALL_URL" | sh
  add_user_tool_paths
  if ! have_cmd uv; then
    die "uv installation completed but uv is still not available on PATH."
  fi
}

install_newbro_cli() {
  log "Installing/updating newbro-cli"
  uv tool install --python 3.12 --upgrade --force newbro-cli
  add_user_tool_paths
  if ! have_cmd newbro; then
    die "newbro-cli installed but newbro is still not available on PATH."
  fi
}

install_uv
install_newbro_cli

if [ "$#" -gt 0 ]; then
  log "Running newbro $*"
  exec newbro "$@"
fi

log "Done. Run: newbro --help"
