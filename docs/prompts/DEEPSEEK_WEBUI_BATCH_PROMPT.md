# DeepSeek execution prompt — SEAM WebUI batch hardening + quick-wins

Copy everything below the line into DeepSeek. Do not edit it. The
operator pastes DeepSeek's final report back to Claude for verification.

This prompt uses **batch sync-relay mode**: DeepSeek executes ALL items
in sequence in one session and emits one ITEM_SUCCESS block per item in a
single final paste. This overrides the "one item at a time" default of
the deep-audit prompt.

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
3. `PROJECT_STATUS.md` — current state (HISTORY#207 is the latest entry)
4. `REPO_LEDGER.md` — stable repo decisions
5. `HISTORY_INDEX.md` — history map (do NOT read full `HISTORY.md`)
6. `docs/CODE_LAYOUT.md` — active vs archived paths
7. `docs/SOP_DEEP_AUDIT_REMEDIATION_BLUEPRINT.md` — workflow guardrails
8. `docs/ledgers/agents/deepseek.md` — corrections ledger (cards C1-C5
   describe known failure modes; do not repeat them)
9. `docs/SOP_WEBUI_BATCH_HARDENING_DEEPSEEK.md` — **your canonical spec
   for this batch**

If any of these nine files are missing, STOP and emit the MISSING_FILE
report block (template at the end of this prompt).

## Mode override (batch sync-relay)

The canonical sync-relay rule is "one item at a time, never batch." This
prompt overrides it for ALL items in `SOP_WEBUI_BATCH_HARDENING_DEEPSEEK.md`:

- Execute items W1, W2, W3, W4, H1, H5, M8 in that order.
- For EACH item: write the failing test, confirm fail, apply fix,
  confirm green, run the per-item gate, move to next item.
- Do NOT stop between items unless a stop condition fires (see "Stop
  conditions").
- After all seven items complete, emit one ITEM_SUCCESS block per item,
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
  `experimental/webui/`.
- **No scope creep.** Per ledger card C4: only edit files in the item's
  `Files:` line plus the cited test path. Log adjacent issues in
  `additional_observations`; do not fix them.
- **No new docs unless the SOP item requires one.** This prompt and the
  SOP are durable; do not edit either.
- **No secrets.** If you find anything that looks like a credential,
  token, session URL, share URL, or `.env` value, STOP and emit the
  SECRET_FOUND report.
- **Stay on `main`.** Confirm with `git branch --show-current`. Expect 4
  dirty files from the WebUI in-flight batch (server.py, storage.py,
  dashboard.html, seam-api.js). Do NOT revert those.

## Pre-flight

Run BEFORE any item:

```
git branch --show-current               # expect: main
git status --short | wc -l              # expect: 4
python -m pytest test_seam_all/test_seam.py -q
python -m tools.history.verify_integrity
python -m tools.history.verify_routing
python -m tools.history.verify_continuity
python -m tools.streams.verify_streams
```

If `git status --short | wc -l` is not 4, OR any verify gate fails, OR
pytest fails on a test you did not author this session, STOP and emit
SCOPE_LIMIT_HIT (reason `pre_existing_red_tdd` per ledger card C2 if it's
a test issue; otherwise `ambiguous_owner` with the discrepancy detail).

## Stop conditions

Stop the batch and emit the appropriate report immediately when ANY of
these occur:

- The pre-fix failing test passes (CLAIM_COULD_NOT_REPRODUCE for that
  item)
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

Do not improvise around any stop condition.

## Report format — emit ONE final paste containing all blocks

After ALL items complete (or a stop condition fires), emit one block per
item, in execution order, in one paste. Use the exact field names below.
Do not add commentary outside the blocks.

### Block: ITEM_SUCCESS

```
===== DEEPSEEK REPORT: ITEM_SUCCESS =====
item_id: <W1 / W2 / W3 / W4 / H1 / H5 / M8>
item_title: <copy from SOP heading>
files_changed:
  - <repo-relative path>
  - <repo-relative path>
tests_added:
  - <repo-relative path>
focused_test_cmd: python -m pytest tests/audit/<file> -q
focused_test_before_fix: FAIL  (exit=<n>)
focused_test_after_fix: PASS  (exit=0)
full_suite_cmd: python -m pytest test_seam_all/test_seam.py -q
full_suite_result: PASS  (exit=0, <N> passed)
py_compile_result: PASS
compileall_result: PASS
diff_stat:
<paste `git diff --stat -- <files for this item>` output>
diff_preview:
<paste `git diff -- <files for this item>` full hunks for THIS item only;
 max 200 lines per item. If diff is larger, paste first 200 lines and
 write "TRUNCATED — uncommitted in working tree">
additional_observations: <free text, or "none">
ready_for_next_item: yes  (or "all_items_complete" on the last block)
===== END REPORT =====
```

### Block: CLAIM_COULD_NOT_REPRODUCE

```
===== DEEPSEEK REPORT: CLAIM_COULD_NOT_REPRODUCE =====
item_id: <e.g. W3>
focused_test_cmd: <cmd>
focused_test_result: PASS_UNEXPECTED  (exit=0)
test_source:
<paste the test file you wrote, full content>
observed_behaviour: <what the code actually does at the cited lines>
cited_lines_quoted:
<paste the cited source lines verbatim>
hypothesis: <one of: "audit_stale" / "fix_already_landed" / "misread_lines" / "other">
hypothesis_detail: <free text>
items_completed_before_this: [<comma-separated item_ids, or "none">]
ready_for_next_item: no  (waiting on Claude verdict)
===== END REPORT =====
```

### Block: REGRESSION

```
===== DEEPSEEK REPORT: REGRESSION =====
item_id: <e.g. W2>
focused_test_result: PASS
full_suite_result: FAIL  (exit=<n>, <N> failed)
failing_tests:
  - <nodeid>: <one-line reason>
diff_stat:
<paste>
diff_preview:
<paste>
suspected_cause: <free text>
rollback_status: not_rolled_back   (Claude reviews before rollback)
items_completed_before_this: [<comma-separated item_ids, or "none">]
ready_for_next_item: no
===== END REPORT =====
```

### Block: SCOPE_LIMIT_HIT

```
===== DEEPSEEK REPORT: SCOPE_LIMIT_HIT =====
item_id: <e.g. W4>
reason: <one of: "needs_file_outside_files_line" / "needs_history_edit" /
                 "needs_experimental_webui_edit" / "ambiguous_owner" /
                 "pre_existing_red_tdd" / "other">
detail: <free text — what additional file or decision is needed>
files_changed_so_far:
  - <path>
focused_test_state: <PASS / FAIL / NOT_RUN>
items_completed_before_this: [<comma-separated item_ids, or "none">]
ready_for_next_item: no
===== END REPORT =====
```

### Block: SECRET_FOUND

```
===== DEEPSEEK REPORT: SECRET_FOUND =====
item_id: <e.g. H5>
where: <repo-relative path>
pattern_kind: <one of: "bearer" / "session_url" / "share_url" / "env_value" /
                       "private_key" / "api_key" / "dsn_with_password" / "other">
do_not_quote: true   (you must NOT paste the secret value)
context: <short neutral description, no secret material>
action_taken: stopped_before_diff_produced
items_completed_before_this: [<comma-separated item_ids, or "none">]
ready_for_next_item: no
===== END REPORT =====
```

### Block: MISSING_FILE

```
===== DEEPSEEK REPORT: MISSING_FILE =====
expected: <repo-relative path>
checked_with: ls / stat output
items_completed_before_this: [<comma-separated item_ids, or "none">]
ready_for_next_item: no
===== END REPORT =====
```

## First action

After reading all nine authoritative inputs, emit a short readiness block
(this one only — not the per-item template):

```
===== DEEPSEEK READY =====
seam_repo_root: /home/terrabyte/Documents/Projects/Seam
git_branch: <output of `git branch --show-current`>
git_dirty_files_count: <output of `git status --short | wc -l`>
canonical_sop_present: <yes/no>  (check docs/SOP_WEBUI_BATCH_HARDENING_DEEPSEEK.md)
corrections_ledger_present: <yes/no>  (check docs/ledgers/agents/deepseek.md)
batch_items: [W1, W2, W3, W4, H1, H5, M8]
batch_mode_understood: <yes/no>  (you will execute ALL items in one session and emit one final paste)
plan_summary: <3-5 sentences max, in your own words, of the order and approach>
===== END READY =====
```

Then STOP and wait for Claude's "proceed with batch" reply.

After "proceed with batch", execute W1 → W2 → W3 → W4 → H1 → H5 → M8 in
order, then emit all seven ITEM_SUCCESS blocks (or whatever stop-condition
blocks apply) in one final paste.

Do not ask follow-up questions outside the block formats. If something is
genuinely unclear, use SCOPE_LIMIT_HIT with reason `ambiguous_owner` and
put the question in `detail`.

End of prompt.
