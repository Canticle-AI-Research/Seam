#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
INSTALLER="$SCRIPT_DIR/install_seam.py"

if command -v python3 >/dev/null 2>&1; then
  exec python3 "$INSTALLER" "$@"
fi

if command -v python >/dev/null 2>&1; then
  exec python "$INSTALLER" "$@"
fi

echo "Python 3 is required to install SEAM." >&2
exit 1
