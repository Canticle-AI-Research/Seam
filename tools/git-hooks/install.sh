#!/usr/bin/env bash
# Install the SEAM canonical git hooks into .git/hooks/.
#
# Tries a symlink first (so updates to tools/git-hooks/<hook> are picked
# up automatically). Falls back to a copy on filesystems that do not support
# symlinks (exFAT, FAT32, some Windows configurations). The copy embeds a
# CANONICAL_SHA marker so subsequent runs can detect drift and warn that
# `bash tools/git-hooks/install.sh` should be re-run.
#
# Pass --force to overwrite existing hooks (backed up to
# .git/hooks/<hook>.bak.<timestamp>).

set -u

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT" || exit 1

HOOKS=(pre-commit pre-push)

FORCE=0
for arg in "$@"; do
  case "$arg" in
    --force|-f) FORCE=1 ;;
  esac
done

install_hook() {
  local hook_name="$1"
  local src_rel="tools/git-hooks/$hook_name"
  local src="$REPO_ROOT/$src_rel"
  local dest="$REPO_ROOT/.git/hooks/$hook_name"

  if [ ! -f "$src" ]; then
    echo "Missing $src" >&2
    return 1
  fi

  chmod +x "$src"

  local src_sha
  src_sha="$(sha256sum "$src" | awk '{print $1}')"

  # Already a symlink pointing at the canonical hook?
  if [ -L "$dest" ] && [ "$(readlink "$dest")" = "../../$src_rel" ]; then
    echo "[SEAM hooks] Already installed (symlink): $dest"
    return 0
  fi

  # Already a copy with matching marker?
  if [ -f "$dest" ] && grep -q "^# CANONICAL_SHA: $src_sha\$" "$dest" 2>/dev/null; then
    echo "[SEAM hooks] Already installed (copy, sha matches): $dest"
    return 0
  fi

  # Need to overwrite — back up if anything exists.
  if [ -e "$dest" ] || [ -L "$dest" ]; then
    if [ "$FORCE" -ne 1 ]; then
      echo "[SEAM hooks] $dest already exists and does not match canonical." >&2
      echo "[SEAM hooks] Rerun with --force to replace (the existing file will be backed up)." >&2
      return 1
    fi
    local stamp
    stamp="$(date +%Y%m%d-%H%M%S)"
    mv "$dest" "$dest.bak.$stamp"
    echo "[SEAM hooks] Backed up existing hook to $dest.bak.$stamp"
  fi

  # Try symlink first.
  if ln -s "../../$src_rel" "$dest" 2>/dev/null; then
    echo "[SEAM hooks] Installed (symlink): $dest -> ../../$src_rel"
    return 0
  fi

  # Fall back to copy with embedded canonical sha marker.
  {
    head -n 1 "$src"
    echo "# CANONICAL_SHA: $src_sha"
    echo "# Installed by tools/git-hooks/install.sh (copy mode; symlink unsupported by filesystem)."
    echo "# Re-run that installer after pulling updates if the source hash changes."
    tail -n +2 "$src"
  } > "$dest"
  chmod +x "$dest"
  echo "[SEAM hooks] Installed (copy): $dest"
  echo "[SEAM hooks] Source: $src_rel  sha256=$src_sha"
}

STATUS=0
for hook in "${HOOKS[@]}"; do
  install_hook "$hook" || STATUS=1
done

exit "$STATUS"
