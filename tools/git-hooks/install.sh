#!/usr/bin/env bash
# Install worktree-safe SEAM hook dispatchers in the repository common Git dir.

set -u

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || {
  echo "[SEAM hooks] cannot resolve repository root" >&2
  exit 1
}
COMMON_RAW=$(git rev-parse --git-common-dir 2>/dev/null) || {
  echo "[SEAM hooks] cannot resolve common Git directory" >&2
  exit 1
}
case "$COMMON_RAW" in
  /*) COMMON_DIR=$COMMON_RAW ;;
  *) COMMON_DIR=$(cd "$REPO_ROOT/$COMMON_RAW" 2>/dev/null && pwd -P) || {
       echo "[SEAM hooks] common Git directory is unavailable" >&2
       exit 1
     } ;;
esac

CUSTOM_HOOKS=$(git config --get core.hooksPath 2>/dev/null || true)
if [ -n "$CUSTOM_HOOKS" ]; then
  echo "[SEAM hooks] refusing custom core.hooksPath: $CUSTOM_HOOKS" >&2
  exit 1
fi

REPLACE=0
for arg in "$@"; do
  case "$arg" in
    --replace|--force|-f) REPLACE=1 ;;
    *) echo "[SEAM hooks] unsupported argument: $arg" >&2; exit 2 ;;
  esac
done

HOOK_DIR="$COMMON_DIR/hooks"
mkdir -p "$HOOK_DIR" || exit 1

write_dispatcher() {
  local output=$1
  local hook_name=$2
  local source_sha=$3
  {
    echo '#!/usr/bin/env bash'
    echo '# SEAM_HOOK_DISPATCHER: 1'
    echo 'set -u'
    printf 'HOOK_NAME=%q\n' "$hook_name"
    printf 'EXPECTED_SHA=%q\n' "$source_sha"
    cat <<'DISPATCH'
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || {
  echo "[SEAM hook dispatcher] cannot resolve invoking checkout" >&2
  exit 1
}
SOURCE="$REPO_ROOT/tools/git-hooks/$HOOK_NAME"
if [ ! -f "$SOURCE" ] || ! grep -qx '# SEAM_HOOK_PROTOCOL: 1' "$SOURCE"; then
  echo "[SEAM hook dispatcher] canonical source is absent, stale or unsupported: $SOURCE" >&2
  exit 1
fi
ACTUAL_SHA=$(sha256sum "$SOURCE" | awk '{print $1}') || exit 1
if [ "$ACTUAL_SHA" != "$EXPECTED_SHA" ]; then
  echo "[SEAM hook dispatcher] canonical source is stale or unsupported; rerun tools/git-hooks/install.sh" >&2
  exit 1
fi
exec bash "$SOURCE" "$@"
DISPATCH
  } >"$output" || return 1
  chmod 0755 "$output"
}

install_hook() {
  local hook_name=$1
  local source_path="$REPO_ROOT/tools/git-hooks/$hook_name"
  local destination="$HOOK_DIR/$hook_name"
  local source_sha temporary recognized stamp old_sha expected_old backup link_target resolved_target

  if [ ! -f "$source_path" ]; then
    echo "[SEAM hooks] missing canonical source: $source_path" >&2
    return 1
  fi
  if ! grep -qx '# SEAM_HOOK_PROTOCOL: 1' "$source_path"; then
    echo "[SEAM hooks] unsupported canonical source protocol: $source_path" >&2
    return 1
  fi
  source_sha=$(sha256sum "$source_path" | awk '{print $1}') || return 1
  temporary=$(mktemp "$HOOK_DIR/.${hook_name}.tmp.XXXXXX") || return 1
  if ! write_dispatcher "$temporary" "$hook_name" "$source_sha"; then
    rm -f "$temporary"
    return 1
  fi

  if [ -f "$destination" ] && [ ! -L "$destination" ] && cmp -s "$temporary" "$destination"; then
    rm -f "$temporary"
    echo "[SEAM hooks] already installed: $destination"
    return 0
  fi

  recognized=0
  if [ -L "$destination" ]; then
    link_target=$(readlink "$destination")
    if [ "$link_target" = "../../tools/git-hooks/$hook_name" ]; then
      resolved_target=$(readlink -f "$destination" 2>/dev/null || true)
      if [ "$resolved_target" = "$(readlink -f "$source_path")" ]; then
        recognized=1
      fi
    fi
  elif [ -f "$destination" ]; then
    old_sha=$(sed -n 's/^EXPECTED_SHA=\([0-9a-f]\{64\}\)$/\1/p' "$destination")
    if [ -n "$old_sha" ]; then
      expected_old=$(mktemp "$HOOK_DIR/.${hook_name}.expected.XXXXXX") || {
        rm -f "$temporary"
        return 1
      }
      if write_dispatcher "$expected_old" "$hook_name" "$old_sha" \
        && cmp -s "$expected_old" "$destination"; then
        recognized=1
      fi
      rm -f "$expected_old"
    fi
  fi
  if { [ -e "$destination" ] || [ -L "$destination" ]; } && [ "$recognized" -ne 1 ] && [ "$REPLACE" -ne 1 ]; then
    rm -f "$temporary"
    echo "[SEAM hooks] unknown existing hook refused: $destination (use --replace to back it up)" >&2
    return 1
  fi
  if [ -e "$destination" ] || [ -L "$destination" ]; then
    stamp=$(date +%Y%m%d-%H%M%S)-$$
    backup="$destination.bak.$stamp"
    cp -a -- "$destination" "$backup" || {
      rm -f "$temporary"
      return 1
    }
    echo "[SEAM hooks] backed up existing hook: $backup"
  fi
  mv -f "$temporary" "$destination" || {
    rm -f "$temporary"
    return 1
  }
  echo "[SEAM hooks] installed common-dir dispatcher: $destination"
}

STATUS=0
install_hook pre-commit || STATUS=1
install_hook pre-push || STATUS=1
exit "$STATUS"
