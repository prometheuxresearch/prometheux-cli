#!/usr/bin/env sh
#
# Install the Prometheux CLI (`px`).
#
#   curl -fsSL https://raw.githubusercontent.com/prometheuxresearch/prometheux-cli/main/install.sh | sh
#
# Prefers pipx (installs px into its own isolated environment); falls back to
# `pip install --user`. Set PROMETHEUX_VERSION to pin a release.

set -eu

PKG="prometheux"
VERSION="${PROMETHEUX_VERSION:-}"
SPEC="$PKG"
[ -n "$VERSION" ] && SPEC="$PKG==$VERSION"

if command -v pipx >/dev/null 2>&1; then
  echo "Installing $SPEC with pipx…"
  pipx install "$SPEC"
elif command -v python3 >/dev/null 2>&1; then
  echo "pipx not found — installing $SPEC with 'pip install --user'."
  echo "(Tip: 'python3 -m pip install --user pipx' for isolated installs.)"
  python3 -m pip install --user "$SPEC"
else
  echo "Error: need Python 3.9+ (and ideally pipx). Install Python and retry." >&2
  exit 1
fi

echo
if command -v px >/dev/null 2>&1; then
  echo "Installed: $(px --version 2>/dev/null || echo px)"
  echo "Next: px login   (or set JARVISPY_URL + PMTX_TOKEN), then px --help"
else
  echo "Installed, but 'px' is not on your PATH yet."
  echo "pipx: run 'pipx ensurepath' and restart your shell."
  echo "pip --user: add your user bin dir (see 'python3 -m site --user-base') to PATH."
fi
