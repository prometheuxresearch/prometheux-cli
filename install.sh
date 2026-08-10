#!/usr/bin/env sh
#
# Install the Prometheux CLI (`px`) on macOS / Linux.
#
#   curl -fsSL https://raw.githubusercontent.com/prometheuxresearch/prometheux-cli/main/install.sh | sh
#
# Channel order (design §9): uv (primary) -> pipx -> pip --user.
#   * uv is the primary channel: it brings its own Python, so there is no
#     per-platform build matrix. If uv is absent we offer to bootstrap it
#     (self-serve only; skip with PROMETHEUX_NO_BOOTSTRAP=1).
#   * pipx is the isolated-env fallback for hosts that already have it.
#   * pip --user is the last resort.
#
# This is the SELF-SERVE convenience path. It is NOT the enterprise path:
# banks install the signed wheel from their internal PyPI mirror (design §9).
#
# Env:
#   PROMETHEUX_VERSION      pin a release (e.g. 0.1.0)
#   PROMETHEUX_NO_BOOTSTRAP set to 1 to never auto-install uv

set -eu

PKG="prometheux"
VERSION="${PROMETHEUX_VERSION:-}"
SPEC="$PKG"
[ -n "$VERSION" ] && SPEC="$PKG==$VERSION"

log() { printf '%s\n' "$*"; }
err() { printf '%s\n' "$*" >&2; }
have() { command -v "$1" >/dev/null 2>&1; }

install_with_uv() {
  log "Installing $SPEC with uv…"
  uv tool install "$SPEC"
}

install_with_pipx() {
  log "Installing $SPEC with pipx…"
  pipx install "$SPEC"
}

install_with_pip() {
  err "uv and pipx not found — falling back to 'pip install --user'."
  err "(Tip: install uv — https://docs.astral.sh/uv/ — for an isolated, updatable install.)"
  python3 -m pip install --user "$SPEC"
}

bootstrap_uv() {
  [ "${PROMETHEUX_NO_BOOTSTRAP:-}" = "1" ] && return 1
  have curl || return 1
  log "uv not found — bootstrapping it from https://astral.sh/uv …"
  curl -fsSL https://astral.sh/uv/install.sh | sh || return 1
  # uv installs to ~/.local/bin (or $XDG_BIN_HOME); make it visible now.
  for d in "$HOME/.local/bin" "${XDG_BIN_HOME:-}" "$HOME/.cargo/bin"; do
    [ -n "$d" ] && [ -d "$d" ] && PATH="$d:$PATH"
  done
  export PATH
  have uv
}

if have uv; then
  install_with_uv
elif have pipx; then
  install_with_pipx
elif bootstrap_uv; then
  install_with_uv
elif have python3; then
  install_with_pip
else
  err "Error: need uv, pipx, or Python 3.9+. Install one and retry."
  err "Recommended: curl -fsSL https://astral.sh/uv/install.sh | sh"
  exit 1
fi

log ""
if have px; then
  log "Installed: $(px --version 2>/dev/null || echo px)"
  log "Next: px skill install   (add the agent skill for Claude Code / Cursor)"
  log "Then: px login   (or set JARVISPY_URL + PMTX_TOKEN), then px --help"
else
  log "Installed, but 'px' is not on your PATH yet."
  log "uv:   run 'uv tool update-shell' (or add ~/.local/bin to PATH) and restart your shell."
  log "pipx: run 'pipx ensurepath' and restart your shell."
  log "pip --user: add your user bin dir (see 'python3 -m site --user-base') to PATH."
fi
