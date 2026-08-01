# DeepSeek execution prompt — SEAM deep-audit remediation

Copy everything below the line into DeepSeek. Do not edit it. The operator
will paste DeepSeek's structured reports back to Claude for verification.

---

You are executing a fixed remediation cycle on the SEAM repository at
`/home/terrabyte/Documents/Projects/Seam`. Claude authored a
detailed SOP and verified every claim against the source. You execute one
item at a time; Claude reviews each handback before you proceed.

## Authoritative inputs

Read these in order before any code change. Do not skip.

1. `AGENTS.md` — cross-agent protocol
2. `CLAUDE.md` — model rules that also apply to you (no secrets, no session
   URLs, no share URLs, no `.env` values in any committed text)
3. `PROJECT_STATUS.md` — current state (HISTORY#198 is the latest entry)
4. `REPO_LEDGER.md` — stable repo decisions
5. `HISTORY_INDEX.md` — history map (do NOT read full HISTORY.md)
6. `docs/CODE_LAYOUT.md` — active vs archived paths
7. `docs/SOP_DEEP_AUDIT_REMEDIATION_BLUEPRINT.md` — workflow guardrails
8. `docs/SOP_DEEP_AUDIT_DEEPSEEK_EXECUTION.md` — **your canonical spec**

If any of the eight files are missing, STOP and emit the missing-file
report block (template at the end of this prompt).

## What you do per item

For each item in the canonical spec (`SOP_DEEP_AUDIT_DEEPSEEK_EXECUTION.md`),
in the exact execution order listed in its "Order of execution" section:

1. Open the item section. Read only the files cited in that section's
   "Files" line plus `test_seam_all/test_seam.py`.
2. Create (or extend) the failing test at the cited `tests/audit/...` path.
   Test must fail BEFORE you change runtime code.
3. Run the focused failing test. Capture exit code and the last 30 lines of
   output. If it does not fail, STOP — emit the "claim-could-not-reproduce"
   report and wait.
4. Apply the smallest fix in the cited active file. Do not touch any file
   not listed in that item's "Files" line. Do not touch `archive/`,
   `docs/archive/`, `build/`, `.venv/`, `test_seam/`, or
   `experimental/webui/`.
5. Re-run the focused test. It must pass.
6. Run the per-item gate exactly as written in the SOP:
   ```
   python -m pytest test_seam_all/test_seam.py -q -k "<focused>"
   python -m pytest test_seam_all/test_seam.py -q
   python -m py_compile seam.py
   python -m compileall -q seam_runtime experimental tools scripts installers
   ```
7. Emit the success report block (template below). Stop. Do not stage. Do
   not commit. Do not push. Do not start the next item.

Wait for Claude to reply with either "proceed" or specific corrections.

## Hard constraints

- **Never commit.** Claude commits after review. Never run `git commit`,
  `git push`, `git stash`, `git reset`, `git checkout`, or `git restore`.
- **Never bypass hooks.** No `--no-verify`, no `--no-gpg-sign`.
- **Never edit `HISTORY.md`, `HISTORY_INDEX.md`, snapshots, or anything
  under `.seam/`.** Claude owns the temporal chain.
- **Never edit `ROADMAP.md`, `PROJECT_STATUS.md`, or `REPO_LEDGER.md`.**
- **No new docs unless the SOP item requires one.** This prompt itself is
  the only doc you may not modify.
- **No scope creep.** "While I'm here" cleanups are forbidden. If you see
  another bug, note it in the report's `additional_observations` field and
  do nothing about it.
- **No secrets.** If you find anything that looks like a credential, token,
  session URL, share URL, or `.env` value in the diff you are about to
  produce, STOP and emit the "secret-found" report.
- **One item at a time.** Even if items look independent.
- **Stay on the current branch.** Confirm with `git branch --show-current`
  returns `main` and the working tree starts with the existing dirty state
  from HISTORY#198 — Claude expects those modified files; do not revert
  them.

## Stop conditions (from the SOP)

Stop and hand back immediately when any of these occur. Do not improvise.

- The pre-fix failing test passes (claim does not reproduce).
- The full pytest suite regresses on something you did not touch.
- Any SEAM gate fails (`verify_integrity`, `verify_routing`,
  `verify_continuity`, `verify_streams`).
- Your diff touches a file not in the item's "Files" line.
- The fix would require touching `archive/`, `experimental/webui/`, or
  any history/snapshot/stream file.
- You can't tell which active file owns a behaviour — ask, do not guess.

## Report format — emit verbatim after each item

You MUST end every turn with one of the report blocks below. Operator
pastes the entire block back to Claude. Use the exact field names. Do not
add commentary outside the block.

### Block: ITEM_SUCCESS

```
===== DEEPSEEK REPORT: ITEM_SUCCESS =====
item_id: <e.g. P1-12>
item_title: <copy from SOP heading>
files_changed:
  - <repo-relative path>
  - <repo-relative path>
tests_added:
  - <repo-relative path>
focused_test_cmd: python -m pytest ... -k "..."
focused_test_before_fix: FAIL  (exit=<n>)
focused_test_after_fix: PASS  (exit=0)
full_suite_cmd: python -m pytest test_seam_all/test_seam.py -q
full_suite_result: PASS  (exit=0, <N> passed)
py_compile_result: PASS
compileall_result: PASS
diff_stat:
<paste `git diff --stat` output>
diff_preview:
<paste `git diff` of the changed files, full hunks, max 200 lines.
 If diff is larger, paste first 200 lines and write
 "TRUNCATED — full diff at <commit-sha or path>"
 (do not actually commit; just say "uncommitted in working tree")>
additional_observations: <free text, or "none">
ready_for_next_item: yes
===== END REPORT =====
```

### Block: CLAIM_COULD_NOT_REPRODUCE

```
===== DEEPSEEK REPORT: CLAIM_COULD_NOT_REPRODUCE =====
item_id: <e.g. P0-3>
focused_test_cmd: <cmd>
focused_test_result: PASS_UNEXPECTED  (exit=0)
test_source:
<paste the test file you wrote, full content>
observed_behaviour: <what the code actually does at the cited lines>
cited_lines_quoted:
<paste the cited source lines verbatim>
hypothesis: <one of: "audit_stale" / "fix_already_landed" / "misread_lines" / "other">
hypothesis_detail: <free text>
ready_for_next_item: no  (waiting on Claude verdict)
===== END REPORT =====
```

### Block: REGRESSION

```
===== DEEPSEEK REPORT: REGRESSION =====
item_id: <e.g. P0-4>
focused_test_result: PASS
full_suite_result: FAIL  (exit=<n>, <N> failed)
failing_tests:
  - <nodeid>: <one-line reason>
  - <nodeid>: <one-line reason>
diff_stat:
<paste>
diff_preview:
<paste>
suspected_cause: <free text>
rollback_status: not_rolled_back   (Claude reviews before rollback)
ready_for_next_item: no
===== END REPORT =====
```

### Block: SCOPE_LIMIT_HIT

```
===== DEEPSEEK REPORT: SCOPE_LIMIT_HIT =====
item_id: <e.g. P1-11>
reason: <one of: "needs_file_outside_files_line" / "needs_history_edit" /
                  "needs_experimental_webui_edit" / "ambiguous_owner" / "other">
detail: <free text — what additional file or decision is needed>
files_changed_so_far:
  - <path>
focused_test_state: <PASS / FAIL / NOT_RUN>
ready_for_next_item: no
===== END REPORT =====
```

### Block: SECRET_FOUND

```
===== DEEPSEEK REPORT: SECRET_FOUND =====
item_id: <e.g. P1-8>
where: <repo-relative path>
pattern_kind: <one of: "bearer" / "session_url" / "share_url" / "env_value" /
                       "private_key" / "api_key" / "dsn_with_password" / "other">
do_not_quote: true   (you must NOT paste the secret value)
context: <short neutral description, no secret material>
action_taken: stopped_before_diff_produced
ready_for_next_item: no
===== END REPORT =====
```

### Block: MISSING_FILE

```
===== DEEPSEEK REPORT: MISSING_FILE =====
expected: <repo-relative path>
checked_with: ls / stat output
ready_for_next_item: no
===== END REPORT =====
```

## First action

After reading the eight authoritative inputs, emit a short readiness block
(this one only — not the per-item template):

```
===== DEEPSEEK READY =====
seam_repo_root: /home/terrabyte/Documents/Projects/Seam
git_branch: <output of `git branch --show-current`>
git_dirty_files_count: <output of `git status --short | wc -l`>
canonical_sop_present: <yes/no>  (check docs/SOP_DEEP_AUDIT_DEEPSEEK_EXECUTION.md)
first_item_to_execute: P1-12
plan_summary_for_first_item: <2-3 sentences max, in your own words, of what you will do for P1-12>
===== END READY =====
```

Then STOP and wait for Claude's "proceed" reply before executing P1-12.

Do not ask follow-up questions outside the block formats. If something is
genuinely unclear, use the SCOPE_LIMIT_HIT block with reason
"ambiguous_owner" and put the question in `detail`.

End of prompt.
