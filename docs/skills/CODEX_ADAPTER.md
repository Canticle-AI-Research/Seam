# Codex SkillDB adapter

`seam-skills-codex` is a branch-candidate adapter for Codex 0.157.x. It reads the
enabled native skill inventory from `codex app-server`, builds the portable SEAM
SkillDB projection, resolves a policy-compatible chain, and returns the complete
selected frame to the caller. It never deletes, disables, installs, or executes a
skill.

Ordinary CLI output cannot mutate system/developer context, erase earlier context,
or inject privileged instructions. A calling model must explicitly read the
returned `frame_text` and remain subject to its existing policy and approval gates.

## Pilot profile

Print the bounded instruction block without changing configuration:

```console
uv run seam-skills-codex bootstrap \
  --executable "$(uv run which seam-skills-codex)"
```

If the package was installed into the caller's normal `PATH`, invoking
`seam-skills-codex bootstrap --executable "$(command -v seam-skills-codex)"` is
equivalent. Do not use that form until `command -v` returns an absolute path.

Save the complete printed TOML as `$CODEX_HOME/skilldb.config.toml`. It uses the
Codex 0.157.1 profile-v2 shape: top-level `developer_instructions` plus `[skills]`.
It suppresses Codex's eager full-skill injection for that profile only:

```toml
developer_instructions = """
SKILLDB_BOOTSTRAP_BEGIN
<bounded discover-and-honor instructions>
SKILLDB_BOOTSTRAP_END
"""

[skills]
include_instructions = false
```

The generated discovery command defaults to the private state path
`$HOME/.local/state/seam/skilldb/codex`. Use `bootstrap --state-dir PATH` to print
a shell-safe absolute alternative. The command embeds a verified absolute adapter
executable and uses `--cwd "$PWD"`; generation fails if no executable regular file
can be resolved. `--executable PATH` is recommended for an isolated pilot and
avoids relying on the later model shell's `PATH`.

Launch the isolated pilot with strict configuration and an explicit working tree:

```console
codex --strict-config -p skilldb -C /path/to/project
```

Rollback is removal of `$CODEX_HOME/skilldb.config.toml` (or launching without
`-p skilldb`).
The adapter does not edit `~/.codex`, `AGENTS.md`, or any native skill package.

## Commands and state

```console
seam-skills-codex refresh --cwd /path/to/project --state-dir /private/state
seam-skills-codex discover --cwd /path/to/project --task "review this change" \
  --state-dir /private/state --max-skills 8 --token-budget 16000 --max-selected 3
seam-skills-codex inspect --cwd /path/to/project --window WINDOW_ID \
  --state-dir /private/state
```

`discover` also accepts repeatable `--capability`, `--tool`, and `--permission`
constraints. It refreshes before planning, considers at most three ranked roots by
default, skips bounded candidates that cannot activate, and fails when none is
compatible. Full source instructions remain absent from refresh/search receipts and
appear only in a selected window's exact-budget frame.

State is private and separated by a SHA-256 digest of the canonical cwd:

```text
<state>/<cwd-digest>/
  current.json
  snapshots/<fingerprint>.json
  snapshots/<fingerprint>.json.index.json
  windows/<window-id>/activation.json
  windows/<window-id>/frame.md
  windows/<window-id>/graph.json
  windows/<window-id>/graph.html
  windows/<window-id>/receipt.json
```

Directories are mode `0700`; files are atomically published at mode `0600`. Raw task
text is not persisted, while its fingerprint is. `inspect` rejects current-snapshot,
frame, graph, plan, source-revision, receipt, or artifact-hash drift.

## Selection rule

Discovery uses the portable metadata-only lexical projection. Candidates must score
at least 6; at most `max(12, max_selected * 4)` ranked rows are inspected, capped at
50. Up to `max_selected` compatible roots are passed to the core planner, which
closes dependencies and enforces cycles, conflicts, tools, permissions,
capabilities, skill count, and exact tokenizer budget. Instructions are never
silently truncated.
