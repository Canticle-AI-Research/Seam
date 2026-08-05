---
handoff_id: 2026-08-05-tui-rebuild-canticle
supersedes: 2026-08-03-track-s-s5-merged-s6-next
handoff_status: current
history: HISTORY#537
---

# TUI rebuild in Canticle style — superseded the old dashboard UI

## State

The new Textual TUI is the live dashboard. Every interactive entry point
(`seam dashboard`, `seam-dash`, `seam-tui`, and the operator's `stui` wrapper)
routes through `dashboard.run_dashboard`, which now launches
`seam_runtime.tui.app.SeamTUI` against the `DashboardApp` backend. Rich
snapshot (`--snapshot`) and script (`--run`) modes are unchanged and stay on
the backend.

Branch: `feat/tui-canticle`, stacked on `fix/local-gates-match-ci` (PR #203,
HISTORY#536), which must merge first.

## Files

Added:

- `seam_runtime/config.py` — declarative registry of 115 env vars, 27 masked
  secrets, 25 provider keys, custom-key support. Persists to
  `~/.config/seam/seam.env` at 0600, **never** the repo `.env`. Process env
  always wins over the file.
- `seam_runtime/tui/` — `app.py` (shell, `/` palette, worker execution),
  `commands.py` (153 commands across 5 surfaces, all derived at runtime from
  the backend parser: dash 20 / cli 66 / mcp 19 / api 27 / sdk 21),
  `settings_screen.py`, `panels.py` (7 worker-backed DataTable/Tree panels),
  `brand.py`, `theme.tcss` (Canticle tokens: Tokyo Night + Charm pastels).
- `tests/audit/test_tui_supersedes_dashboard.py` — 29 tests.

Modified:

- `seam_runtime/dashboard.py` — `run_dashboard` launches the new TUI; `main`
  applies persisted config before the parser is built; `TextualDashboardApp`
  carries a deprecation docstring.
- `pyproject.toml` — textual pin `>=0.50,<1.0` → `>=8.0,<9.0`; added
  `seam-tui` script; `tui/*.tcss` package data.
- `MANIFEST.in` — ships `tui/*.tcss`.
- `docs/CODE_LAYOUT.md` — documents `seam_runtime/tui/`, `config.py`, and the
  narrowed role of `dashboard.py`.

## NOT mine — leave alone

Five files modified 2026-08-04 23:09 by a concurrent agent (Codex signature):
`docs/kb/memory-systems/mem0.md`, `docs/kb/memory-systems/seam-positioning.md`,
`docs/roadmap/COMPETITIVE_ROADMAP.md`,
`docs/roadmap/MEMORY_GUARANTEES_CAMPAIGN.md`,
`seam_runtime/temporal_instance_context.py`.
**Do not `git add -A`** — it would sweep these into a TUI commit.

## Resolved decisions

- **Supersession shape: Replace.** Operator chose repoint-only. The old
  `TextualDashboardApp` (`dashboard.py:496-2360`) is kept as dead code with a
  deprecation docstring, because its 28 test usages in
  `test_seam_all/test_seam.py` are the only coverage of several dashboard
  behaviours. Deleting it without porting them would trade a working UI for a
  coverage hole. Removal is deferred until the new TUI has operating time.
- **Name collision resolved.** `~/.local/bin/seam-tui` (and its `stui` symlink)
  is a bash wrapper that runs `seam dashboard`. Because the supersession
  happens inside `run_dashboard`, that wrapper now launches the new TUI with no
  change to the wrapper itself.
- **Operator venv.** `Agents/.venv-seam` is an editable install of this repo
  and is what `seam`/`stui` actually run. Its textual was 0.89.1, below the
  declared `>=8.0` floor; upgraded to 8.2.8. `pip check` clean, only textual
  moved, `seam-bridge` and `seam-deepagent` re-smoked.

## Two defects found by launching the real binary

Headless `run_test()` mounts passed while both of these were live. They were
caught only by running `seam dashboard` in a real terminal.

1. **`BadIdentifier` crash at mount.** `SettingRow._widget_id` interpolated a
   setting name straight into a Textual widget id. Textual raises at
   construction, so one bad name took down the whole app rather than degrading
   one row. Now folded through `_ID_SAFE`; `_slug` hardened the same way.
2. **The operator's `DEEPSEEK_API_KEY` silently never reached the
   environment.** `~/.config/seam/seam.env` is a pre-existing hand-written
   shell env file using `export FOO=bar`. `_parse_env_text` did not strip
   `export`, so the key parsed under the name `export DEEPSEEK_API_KEY` — not a
   legal env var name, so it was exported uselessly and the real variable
   stayed unset. `export` is now stripped, and names that cannot be env var
   names are refused on the load path (`is_env_name`), not just in the
   add-a-key UI.

## Verification performed

- Real TTY launch under tmux via `seam dashboard`, `.venv-seam/bin/seam`, and
  the operator's own `stui` against the live `seam.db`: 8 tabs mount, panels
  populate from real MIRL records, `/` palette opens and filters, Settings tab
  renders with secrets masked and `env`-sourced values badged.
- `pytest tests/audit/test_tui_supersedes_dashboard.py` — 29 passed.
- Discrimination proven: reverting each fix fails 9 of those tests; restoring
  passes all 29.
- Full suite `pytest tests/ test_seam_all/ tools/history tools/streams` —
  2586 passed, 2 xfailed, 0 skipped. `ruff check .` clean.

## Remaining work

1. PR #203 (HISTORY#536) merges, then this branch.
2. `REPO_LEDGER.md` / `PROJECT_STATUS.md` still describe one dashboard.
3. Old `TextualDashboardApp` removal, once its 28 tests are ported or retired.
4. `dashboard.py` remains on the never-audited list from two whole-repository
   audits; this change narrows its role but does not audit it.
