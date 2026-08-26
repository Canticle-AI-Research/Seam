#!/usr/bin/env bash
# SEAM deletion guard for Claude Code Bash tool calls.
#
# Triggered as a PreToolUse hook on the Bash tool (see .claude/settings.json).
# Reads the tool input from stdin (JSON with .tool_input.command) and BLOCKS
# (exit 2) any command that would delete, truncate, or move-out-of-tree
# anything inside this repository.
#
# Rationale (HISTORY#613, 2026-08-25): an agent deleted test_seam/ab_A..ab_D
# (~3.4 GB of LoCoMo A/B evaluation arms) during a disk-full event, without
# authorization, inferring "disposable" from git-ignore status. Written rules
# existed and were ignored. This hook makes the rule mechanical: the delete
# is not an option at all.
#
# There is NO agent-side bypass. The only deletable location is .disposable/
# and only the OPERATOR deletes from it — from their own terminal, outside
# agent tooling. An agent that believes something should be deleted asks the
# operator (Ask_user) and does nothing else.
#
# If this guard blocks something that is genuinely not a deletion (a false
# positive), the fix is to refine the pattern in this file with operator
# approval — never to weaken or remove the guard.

set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
INPUT="$(cat || true)"

CMD="$(printf '%s' "$INPUT" | python3 -c 'import json,sys
try:
    data=json.load(sys.stdin)
except Exception:
    print(""); sys.exit(0)
print((data.get("tool_input") or {}).get("command",""))' 2>/dev/null)"

[ -z "$CMD" ] && exit 0

BLOCK_MSG_PREFIX="[SEAM deletion guard] BLOCKED: agents never delete anything in this repository (HISTORY#613, AGENTS.md, .disposable/README.md). The only deletable location is .disposable/ and only the operator deletes from it. If you believe something must be deleted or moved to .disposable/, ask the operator with Ask_user and take no action yourself."

block() {
  echo "$BLOCK_MSG_PREFIX" >&2
  echo "[SEAM deletion guard] Blocked command: $CMD" >&2
  exit 2
}

# 1. Direct deletion verbs, anywhere in the command string.
#    rm / rmdir / shred / unlink / truncate are never legitimate agent
#    actions against repo content.
if printf '%s' "$CMD" | grep -Eq '(^|[;&|;( ]|&&|\|)(rm|rmdir|shred|unlink|truncate)( |$)'; then
  block
fi

# 2. git destructive subcommands.
case "$CMD" in
  *"git clean"*|*"git stash drop"*|*"git stash clear"*|\
  *"git branch -D"*|*"git push --delete"*|*"git push -d "*|\
  *"git rebase"*"--onto"*|*"git filter-branch"*|*"git reflog expire"*|\
  *"git gc --prune"*|*"git worktree remove"*)
    block
    ;;
esac

# 3. find ... -delete / -exec rm.
case "$CMD" in
  *"-delete"*|*"-exec rm "*|*"--exec rm "*)
    block
    ;;
esac

# 4. Truncating output redirection into the repo tree.
#    Block `>` (not `>>`) when its target is a repo-relative path.
#    /dev/null, /tmp, absolute paths outside the repo, and fd dupes pass.
if printf '%s' "$CMD" | grep -Eq '(^|[;&| (])[[:space:]]*>[[:space:]]*[^>&/ ]'; then
  # Extract the redirect target and check it is not an outside-repo path.
  TARGET="$(printf '%s' "$CMD" | grep -Eo '(^|[;&| (])[[:space:]]*>[[:space:]]*[^>& ]+' | head -1 | sed -E 's/.*>[[:space:]]*//' | head -1)"
  case "$TARGET" in
    ""|/dev/null*|/tmp/*|\$*) ;;  # safe or non-path targets pass
    /*) ;;                        # absolute path outside repo patterns handled below
    *) block ;;                   # repo-relative truncation target: blocked
  esac
  # Absolute targets inside the repo are blocked too.
  case "$TARGET" in
    "$REPO_ROOT"/*) block ;;
  esac
fi

# 5. Moving repo content out of the tree: `mv <src> /abs/path` or `mv ... ..`.
if printf '%s' "$CMD" | grep -Eq '(^|[;&| ])mv ([^;|]* )?(/[^ ]*|\.\.[^ ]*)($|[ ;|])'; then
  block
fi

exit 0
