#!/usr/bin/env bash
#
# Judgment CLI installer.
#
# Usage:
#   curl -fsSL https://judgmentlabs.ai/install.sh | bash
#   curl -fsSL https://judgmentlabs.ai/install.sh | VERSION=v0.1.0 bash
#
# What it does:
#   1. Downloads the requested release tarball (default: pinned APP_VERSION,
#      or latest if unpinned).
#   2. Creates an isolated venv at ~/.local/share/judgment-cli/venv.
#   3. Installs the CLI + its dependencies into that venv.
#   4. Symlinks `judgment` into ~/.local/bin (or $PREFIX if set).
#
# Re-running the script is safe: it wipes the venv and reinstalls.

set -euo pipefail

# APP_VERSION is rewritten by the release workflow to the pinned tag (e.g.
# "v0.1.4"). The in-repo copy keeps the placeholder so running it from a
# checkout falls back to resolving the latest tag via the GitHub API.
APP_VERSION="@@VERSION@@"
case "$APP_VERSION" in
  @@*@@) APP_VERSION="latest" ;;
esac

REPO="${REPO:-JudgmentLabs/cli}"
VERSION="${VERSION:-$APP_VERSION}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/.local/share/judgment-cli}"
PREFIX="${PREFIX:-$HOME/.local/bin}"

red()   { printf "\033[31m%s\033[0m\n" "$*" >&2; }
green() { printf "\033[32m%s\033[0m\n" "$*"; }
info()  { printf "==> %s\n" "$*"; }

abort() { red "error: $*"; exit 1; }

require() {
  command -v "$1" >/dev/null 2>&1 || abort "required command not found: $1"
}

require curl
require tar
require uname

# Pick a Python interpreter (>=3.9). Allow override via $PYTHON.
choose_python() {
  if [[ -n "${PYTHON:-}" ]]; then
    echo "$PYTHON"
    return
  fi
  for candidate in python3.13 python3.12 python3.11 python3.10 python3.9 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
        echo "$candidate"
        return
      fi
    fi
  done
  abort "no Python >= 3.9 found on PATH (tried python3.{9..13}); set \$PYTHON to override"
}

PY="$(choose_python)"
info "using $($PY --version 2>&1) at $(command -v "$PY")"

# Resolve VERSION to a concrete tag if "latest".
resolve_version() {
  if [[ "$VERSION" != "latest" ]]; then
    echo "$VERSION"
    return
  fi
  local tag
  tag="$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" \
    | grep -E '"tag_name"' | head -n1 | sed -E 's/.*"tag_name": *"([^"]+)".*/\1/')"
  [[ -n "$tag" ]] || abort "could not resolve latest release for ${REPO}"
  echo "$tag"
}

TAG="$(resolve_version)"
TARBALL_URL="https://github.com/${REPO}/archive/refs/tags/${TAG}.tar.gz"
info "installing ${REPO}@${TAG}"

# Download + extract into a temp dir.
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

info "downloading ${TARBALL_URL}"
curl -fsSL "$TARBALL_URL" -o "$TMP/source.tar.gz"
tar -xzf "$TMP/source.tar.gz" -C "$TMP"
SRC="$(find "$TMP" -maxdepth 1 -mindepth 1 -type d | head -n1)"
[[ -d "$SRC" ]] || abort "tarball missing source directory"

# Fresh venv install.
info "creating venv at ${INSTALL_DIR}/venv"
mkdir -p "$INSTALL_DIR"
rm -rf "$INSTALL_DIR/venv"
"$PY" -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install --quiet "$SRC"

# Symlink into PREFIX.
mkdir -p "$PREFIX"
ln -sfn "$INSTALL_DIR/venv/bin/judgment" "$PREFIX/judgment"
green "installed: $PREFIX/judgment -> $INSTALL_DIR/venv/bin/judgment"

# PATH check.
case ":$PATH:" in
  *":$PREFIX:"*) ;;
  *)
    echo
    info "$PREFIX is not on your PATH. Add this to your shell rc:"
    echo "    export PATH=\"$PREFIX:\$PATH\""
    ;;
esac

# Wire up shell completion. Render the script to a file once and source it
# from the rc -- avoids spawning a Python subprocess on every shell startup.
# Set NO_COMPLETIONS=1 to skip. Failures here are non-fatal.
install_completions() {
  [[ "${NO_COMPLETIONS:-}" = "1" ]] && return 0

  local bin="$INSTALL_DIR/venv/bin/judgment"
  local marker="# >>> judgment cli completion >>>"

  append_rc() {
    local rc="$1" body="$2"
    touch "$rc"
    grep -qF "$marker" "$rc" 2>/dev/null && return
    printf '\n%s\n%s\n# <<< judgment cli completion <<<\n' "$marker" "$body" >> "$rc"
    info "added shell completion to $rc (set NO_COMPLETIONS=1 to skip)"
  }

  case "$(basename "${SHELL:-}")" in
    zsh)
      local file="$INSTALL_DIR/_judgment.zsh"
      "$bin" completion zsh > "$file" 2>/dev/null || return 0
      append_rc "$HOME/.zshrc" "$(printf 'autoload -Uz compinit 2>/dev/null && compinit -u 2>/dev/null\n[ -s "%s" ] && source "%s"' "$file" "$file")"
      ;;
    bash)
      local file="$INSTALL_DIR/_judgment.bash" rc
      [[ "$(uname -s)" = "Darwin" ]] && rc="$HOME/.bash_profile" || rc="$HOME/.bashrc"
      "$bin" completion bash > "$file" 2>/dev/null || return 0
      append_rc "$rc" "[ -s \"$file\" ] && source \"$file\""
      ;;
    fish)
      # fish auto-loads from ~/.config/fish/completions/, no rc edit needed.
      local fd="${XDG_CONFIG_HOME:-$HOME/.config}/fish/completions"
      mkdir -p "$fd"
      "$bin" completion fish > "$fd/judgment.fish" 2>/dev/null \
        && info "installed fish completions to $fd/judgment.fish"
      ;;
  esac
}

install_completions || true

echo
green "done. Try: judgment --version"
green "restart your shell (or 'source' your rc file) to pick up tab-completion."
