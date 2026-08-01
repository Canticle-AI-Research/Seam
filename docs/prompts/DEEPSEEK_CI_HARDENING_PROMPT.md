# DeepSeek execution prompt — SEAM CI hardening batch

Copy everything below the line into DeepSeek. Do not edit it. The
operator pastes DeepSeek's final report back to Claude for verification.

This prompt uses **batch sync-relay mode**: DeepSeek executes ALL items
in sequence in one session and emits one ITEM_SUCCESS block per item in
a single final paste.

---

You are executing a fixed remediation batch on the SEAM repository at
`/home/terrabyte/Documents/Projects/Seam`. Claude authored a
detailed SOP and verified the starting state against the source. You
execute every item in the SOP in order, in one session; Claude reviews
the entire diff at the end.

## Authoritative inputs

Read these in order before any code change. Do not skip.

1. `AGENTS.md` — cross-agent protocol
2. `CLAUDE.md` — model rules that also apply to you (no secrets, no session
   URLs, no share URLs, no `.env` values in any committed text)
3. `PROJECT_STATUS.md` — current state (HISTORY#209 is the latest entry)
4. `REPO_LEDGER.md` — stable repo decisions
5. `HISTORY_INDEX.md` — history map (do NOT read full `HISTORY.md`)
6. `docs/CODE_LAYOUT.md` — active vs archived paths
7. `docs/SOP_DEEP_AUDIT_REMEDIATION_BLUEPRINT.md` — workflow guardrails
8. `docs/ledgers/agents/deepseek.md` — corrections ledger (cards C1-C5
   describe known failure modes; do not repeat them)
9. `docs/SOP_CI_HARDENING_DEEPSEEK.md` — **your canonical spec for this batch**

If any of these nine files are missing, STOP and emit the MISSING_FILE
report block (template at the end of this prompt).

## Mode override (batch sync-relay)

- Execute items CI1, CI2, CI3 in that order.
- For EACH item: write the failing test, confirm FAIL, apply the fix,
  confirm PASS, run the per-item gate, move to next item.
- Do NOT stop between items unless a stop condition fires (see "Stop
  conditions").
- After all three items complete, emit one ITEM_SUCCESS block per item,
  in execution order, in one final paste. Then STOP.

If a stop condition fires for any item, emit ITEM_SUCCESS blocks for
items completed so far + the appropriate stop block for the failed item,
then STOP — do not attempt remaining items.

## Hard constraints

- **Never commit, push, stash, reset, checkout, restore.** Claude commits
  after review.
- **Never bypass hooks.** No `--no-verify`, no `--no-gpg-sign`.
- **Never edit forbidden paths.** Per ledger card C5: `HISTORY.md`,
  `HISTORY_INDEX.md`, `PROJECT_STATUS.md`, `REPO_LEDGER.md`,
  `ROADMAP.md`, anything under `.seam/`, anything under `archive/`,
  anything under `docs/archive/`, anything under `build/`, anything
  under `.venv/`, anything under `test_seam/`, anything under
  `experimental/webui/`. Note: `.github/workflows/` is IN scope for
  this SOP — CI1 and CI2 edit `.github/workflows/ci.yml`.
- **No scope creep.** Per ledger card C4: only edit files in the item's
  `Files:` line plus the cited test path. Log adjacent issues in
  `additional_observations`; do not fix them.
- **No new docs unless the SOP item requires one.** This prompt and the
  SOP are durable; do not edit either.
- **No secrets.** If you find anything that looks like a credential,
  token, session URL, share URL, or `.env` value, STOP and emit the
  SECRET_FOUND report.
- **Stay on `main`.** Confirm with `git branch --show-current`. Expect
  **0 dirty files** — the prior WebUI batch landed at 0fa383e. If
  there is unexpected in-flight work, STOP.

## Pre-flight

Run BEFORE any item:

```
git branch --show-current               # expect: main
git status --short | wc -l              # expect: 0
git log --oneline -1                    # expect: 0fa383e WebUI batch hardening + audit quick-wins (HISTORY#208, #209)
python -m pytest test_seam_all/test_seam.py tools/history/ tools/streams/ tests/ -q
python -m tools.history.verify_integrity
python -m tools.history.verify_routing
python -m tools.history.verify_continuity
python -m tools.streams.verify_streams
```

If `git status --short | wc -l` is not 0, OR any verify gate fails, OR
pytest fails on any test, STOP and emit SCOPE_LIMIT_HIT (reason
`pre_existing_red_tdd` if it's a test issue; otherwise `ambiguous_owner`
with the discrepancy detail).

## Stop conditions

Stop the batch and emit the appropriate report immediately when ANY of
these occur:

- The pre-fix failing test passes (CLAIM_COULD_NOT_REPRODUCE)
- The full pytest suite regresses on something you did not touch
  (REGRESSION)
- A SEAM gate fails (REGRESSION, suspected_cause names the gate)
- Your diff for an item touches a file not in that item's `Files:` line
  (SCOPE_LIMIT_HIT, reason `needs_file_outside_files_line`)
- The fix would require editing a forbidden path (SCOPE_LIMIT_HIT,
  reason `needs_history_edit` or `needs_experimental_webui_edit`)
- You can't determine the canonical owner of a behavior
  (SCOPE_LIMIT_HIT, reason `ambiguous_owner`)
- You discover a secret-shaped string (SECRET_FOUND)
- A required file is missing (MISSING_FILE)
- The MCP stdio subprocess hangs or times out (REGRESSION, paste stderr
  into `suspected_cause`)

## Report format — emit ONE final paste containing all blocks

After ALL items complete (or a stop condition fires), emit one block per
item, in execution order, in one paste. Use the exact field names below.
Do not add commentary outside the blocks.

### Block: ITEM_SUCCESS

```
===== DEEPSEEK REPORT: ITEM_SUCCESS =====
item_id: <CI1 / CI2 / CI3>
item_title: <copy from SOP heading>
files_changed:
  - <repo-relative path>
  - <repo-relative path>
tests_added:
  - <repo-relative path>
focused_test_cmd: python -m pytest tests/audit/<file> -q
focused_test_before_fix: FAIL  (exit=<n>)
focused_test_after_fix: PASS  (exit=0)
full_suite_cmd: python -m pytest test_seam_all/ tools/history/ tools/streams/ tests/ -q
full_suite_result: PASS  (exit=0, <N> passed)
py_compile_result: PASS  (or "N/A — YAML-only edit" for CI1/CI2)
compileall_result: PASS  (or "N/A — YAML-only edit" for CI1/CI2)
yaml_lint_result: PASS  (only for CI1/CI2)
diff_stat:
<paste `git diff --stat -- <files for this item>` output>
diff_preview:
<paste `git diff -- <files for this item>` full hunks for THIS item only;
 max 200 lines per item>
additional_observations: <free text, or "none">
ready_for_next_item: yes  (or "all_items_complete" on the last block)
===== END REPORT =====
```

### Block: CLAIM_COULD_NOT_REPRODUCE

```
===== DEEPSEEK REPORT: CLAIM_COULD_NOT_REPRODUCE =====
item_id: <e.g. CI1>
focused_test_cmd: <cmd>
focused_test_result: PASS_UNEXPECTED  (exit=0)
test_source:
<paste the test file you wrote, full content>
observed_behaviour: <what the code/CI YAML actually does at the cited lines>
cited_lines_quoted:
<paste the cited source lines verbatim>
hypothesis: <one of: "audit_stale" / "fix_already_landed" / "misread_lines" / "other">
hypothesis_detail: <free text>
items_completed_before_this: [<comma-separated item_ids, or "none">]
ready_for_next_item: no
===== END REPORT =====
```

### Block: REGRESSION

```
===== DEEPSEEK REPORT: REGRESSION =====
item_id: <e.g. CI3>
focused_test_result: PASS  (or FAIL)
full_suite_result: FAIL  (exit=<n>, <N> failed)
failing_tests:
  - <nodeid>: <one-line reason>
diff_stat: <paste>
diff_preview: <paste>
suspected_cause: <free text — include captured stderr for CI3 subprocess failures>
rollback_status: not_rolled_back
items_completed_before_this: [<comma-separated item_ids, or "none">]
ready_for_next_item: no
===== END REPORT =====
```

### Block: SCOPE_LIMIT_HIT

```
===== DEEPSEEK REPORT: SCOPE_LIMIT_HIT =====
item_id: <e.g. CI2>
reason: <one of: "needs_file_outside_files_line" / "needs_history_edit" /
                 "needs_experimental_webui_edit" / "ambiguous_owner" /
                 "pre_existing_red_tdd" / "other">
detail: <free text>
files_changed_so_far: [<paths>]
focused_test_state: <PASS / FAIL / NOT_RUN>
items_completed_before_this: [<comma-separated item_ids, or "none">]
ready_for_next_item: no
===== END REPORT =====
```

### Block: SECRET_FOUND, MISSING_FILE

Same schemas as in `docs/prompts/DEEPSEEK_WEBUI_BATCH_PROMPT.md` — reuse
verbatim.

## First action

After reading all nine authoritative inputs, emit a short readiness block
(this one only — not the per-item template):

```
===== DEEPSEEK READY =====
seam_repo_root: /home/terrabyte/Documents/Projects/Seam
git_branch: <output of `git branch --show-current`>
git_dirty_files_count: <output of `git status --short | wc -l`>
git_head_subject: <first line of `git log --oneline -1`>
canonical_sop_present: <yes/no>  (check docs/SOP_CI_HARDENING_DEEPSEEK.md)
corrections_ledger_present: <yes/no>  (check docs/ledgers/agents/deepseek.md)
batch_items: [CI1, CI2, CI3]
batch_mode_understood: <yes/no>
plan_summary: <3-5 sentences max, in your own words>
===== END READY =====
```

Then STOP and wait for Claude's "proceed with batch" reply.

End of prompt.
