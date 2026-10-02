# SOP: Production Readiness Remediation

Handoff target: DeepSeek (or any contributor)
Track: cross-track maintenance (touches stream substrate, test infra, runtime, docs, CI)
Source audit: production readiness assessment, verified 2026-05-18 (see HISTORY#190 baseline).
Sequence: standalone SOP. No prereq. Follow-ups: none required.

This SOP turns the verified audit punch list into a single executable handoff. Every step starts with a `Skip if:` verify-first gate, so any item the operator has already fixed becomes a no-op. DeepSeek must run each gate before doing the work; if the gate is satisfied, record `Skipped (already done)` in the HISTORY entry and move on.

## 0. Read order (do this before changing anything)

1. `PROJECT_STATUS.md`
2. `REPO_LEDGER.md`
3. `HISTORY_INDEX.md`
4. `docs/CODE_LAYOUT.md`
5. `docs/DATA_ROUTING.md` (any phase that touches history/streams/routing)
6. This SOP

Then verify baseline before touching anything:

```bash
python3 -m tools.history.verify_integrity
python3 -m tools.history.verify_continuity
python3 -m tools.history.verify_routing
python3 -m tools.streams.verify_streams
```

If any gate is red on a clean checkout, **stop and report** — do not start remediation on top of pre-existing drift.

## 1. Scope

In:
- Phase 1: Critical correctness gaps (4 items)
- Phase 2: Runtime + roadmap + doc quick wins (6 items)
- Phase 3: Dead-code audit (1 item, gated on operator confirmation)
- Phase 4: Test coverage gaps (2 items)
- Phase 5: Test quality scrub (1 item, sample-first)
- Phase 6: Medium-priority cleanups (7 items)
- Phase 7: Low-priority backlog (catalogued only)
- Closeout: HISTORY entry + verify chain + snapshot

Out:
- Schema migration system for SQLite (suggested in audit; deferred to a separate roadmap card)
- Structured logging replacement of `print()` (deferred; needs design)
- Metrics endpoint on REST API (deferred; Track K territory)
- Property-based tests for MIRL/LX/HS roundtrip (deferred; needs hypothesis dependency decision)

## 2. Branching + PR strategy

- Branch: `deepseek/production-readiness-remediation`
- One PR per phase is preferred. Single bundled PR is acceptable if every phase passes its verify chain independently. Do **not** mix phases inside a single commit.
- Each commit message format: `prod-readiness P<phase>.<item>: <one-line summary>`
- Final commit per phase: `prod-readiness P<phase>: verify chain green` after running the four verify gates.

## 3. Phase 1 — Critical correctness gaps

### 1.1 Commit the rebuilt cross-index

**Skip if:**
```bash
git status --short .seam/cross_index.md .seam/cross_index_archive/ | grep -q . || echo "clean"
```
prints `clean`.

**Do:**
1. Confirm hot zone covers through history:190:
   ```bash
   tail -3 .seam/cross_index.md | grep -q "history:190" && echo OK
   ```
2. If not OK, regenerate:
   ```bash
   python3 -m tools.streams.rebuild_cross_index
   ```
3. Stage and commit:
   ```bash
   git add .seam/cross_index.md .seam/cross_index_archive/
   git commit -m "prod-readiness P1.1: commit rebuilt cross-index hot zone through history:190"
   ```

**Verify:** `python3 -m tools.streams.verify_streams` green; `git diff --quiet .seam/cross_index.md` clean.

### 1.2 Add file locking to `tools/history/new_entry.py`

**Skip if:**
```bash
grep -qE "fcntl|msvcrt|portalocker|flock" tools/history/new_entry.py && echo "locked"
```
prints `locked`.

**Do:**
- Wrap the read-compute-write cycle (currently lines ~58–99) with a cross-platform advisory lock.
- POSIX path: `fcntl.flock(fd, LOCK_EX)` on the index file (`HISTORY_INDEX.md`) before reading the last id, hold through the `HISTORY.md` append + index rebuild.
- Windows path: `msvcrt.locking(fileno, LK_LOCK, 1)` on the same file. Use a small wrapper `_acquire_history_lock()` selected by `os.name`.
- Lock file = `HISTORY_INDEX.md`. Do **not** introduce a new sentinel file — the index is already the canonical id source.
- Release in a `finally` block.

**Test:** add `tools/history/test_history_tools.py::test_new_entry_lock_serializes_concurrent_writes` using `concurrent.futures.ThreadPoolExecutor` with 4 workers each calling `new_entry(...)`; assert no duplicate ids in the resulting index.

**Verify:** `python3 -m pytest tools/history/test_history_tools.py -k lock` green.

### 1.3 Create `test_seam_all/conftest.py`

**Skip if:**
```bash
test -f test_seam_all/conftest.py && echo "exists"
```
prints `exists`.

**Do:** create the file with three fixtures only — do not retrofit existing tests in this SOP, just make the fixtures available for new tests:

```python
# test_seam_all/conftest.py
from __future__ import annotations
import os
from pathlib import Path
import pytest

@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    """Per-test isolated SQLite path under tmp_path; auto-cleaned."""
    return tmp_path / "seam_test.db"

@pytest.fixture
def seam_runtime(tmp_db_path: Path):
    """SeamRuntime bound to a tmp DB. Yields the runtime; closes on teardown."""
    from seam_runtime.runtime import SeamRuntime
    rt = SeamRuntime(db_path=str(tmp_db_path))
    try:
        yield rt
    finally:
        rt.close()

@pytest.fixture
def isolated_env(monkeypatch, tmp_path):
    """Strips SEAM_* env vars so tests don't inherit operator state."""
    for key in list(os.environ):
        if key.startswith("SEAM_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("SEAM_BENCH_OUT_DIR", str(tmp_path / "bench"))
    return tmp_path
```

If `SeamRuntime` import path differs, grep for the canonical import in `test_seam_all/test_seam.py` and match it exactly — do **not** invent a new import path.

**Verify:** `python3 -m pytest test_seam_all/ -q` green; same pass count as before plus zero new failures.

### 1.4 Standardize CI workflow invocations

**Skip if:** `ci.yml` and `external-memory-benchmarks.yml` already use the same invocation style and the same default scope.

**Do:**
- Read both workflows.
- Pick one canonical pattern: **`python -m <module>`** with explicit `--scope all` for benchmarks. Reason: `python -m` works identically across OS matrices; `python script.py` is path-sensitive.
- Update the diverging workflow to match. Do not introduce new steps; only rewrite the invocation lines.
- Document the canonical pattern in a one-line comment at the top of each workflow file.

**Verify:** push a no-op commit and confirm both workflows run green on GitHub Actions. If you cannot push to a fork branch with CI enabled, run the equivalent commands locally and record the outputs in the HISTORY entry.

## 4. Phase 2 — Runtime + roadmap + doc quick wins

### 2.1 Lazy-import `experimental.retrieval_orchestrator` in `seam_runtime/cli.py`

**Skip if:**
```bash
grep -n "^from experimental" seam_runtime/cli.py | grep -q . || echo "lazy"
```
prints `lazy`.

**Do:**
- Remove the top-level `from experimental.retrieval_orchestrator import RetrievalOrchestrator`.
- Inside each function that uses `RetrievalOrchestrator`, add the import as the first statement of the function body.
- Add a regression test: `test_seam_all/test_cli_import_isolation.py` that patches `sys.modules["experimental.retrieval_orchestrator"] = None` and asserts `python -m seam doctor` still exits 0. Use `subprocess.run([sys.executable, "-m", "seam", "doctor"], env={...})` to get a true module-load isolation check.

**Verify:** `python3 -m pytest test_seam_all/test_cli_import_isolation.py -q` green.

### 2.2 Re-validate `table_name` in `seam_runtime/vector_adapters.py`

**Skip if:** `table_name` is already a read-only property or `ensure_schema()` calls a validator.

**Do:**
- Audit `seam_runtime/vector_adapters.py:64–86`. Identify every method that interpolates `self.table_name` into SQL.
- Add a private `_validate_table_name(name: str) -> None` raising `ValueError` on anything outside `[A-Za-z0-9_]{1,63}`.
- Call `_validate_table_name(self.table_name)` at the top of `ensure_schema()`, `insert(...)`, and any other SQL-emitting method.
- Add a test: `test_seam_all/test_vector_adapter_table_name_validation.py` mutating `adapter.table_name = "users; DROP TABLE x"` and asserting `ensure_schema()` raises `ValueError`.

**Verify:** new test green; existing vector adapter tests still green.

### 2.3 Add `seam:item` markers for Tracks I, J, K, L in `ROADMAP.md`

**Skip if:**
```bash
python3 -m tools.streams.roadmap_parser --list | grep -E "track:[IJKL]" | wc -l
```
prints `4` (one marker per track).

**Do:** for each of Tracks I, J, K, L, add a marker immediately after the `## Track <X> — <name>` heading, following the existing pattern (see Track H4 at line ~1141 for the canonical shape):

```
<!-- seam:item
id: roadmap:track:I
status: done            # I is complete on main
status-since: 2026-05-17
status-by: history:189
supersedes: none
topics: benchmark, retrieval, comparator
priority: 1
phase: 1
-->
```

Status mapping (verify against `PROJECT_STATUS.md` before writing):
- Track I → `done` (Track I COMPLETE per PROJECT_STATUS.md line 3)
- Track J → `planned`
- Track K → `planned`
- Track L → `planned`

**Verify:**
```bash
python3 -m tools.streams.verify_streams
grep -c "seam:item" ROADMAP.md   # expect 38 (was 34)
```

### 2.4 Fix Track H mislabel at `ROADMAP.md:1280`

**Skip if:**
```bash
sed -n '1280p' ROADMAP.md | grep -q "Track L" && echo "fixed"
```
prints `fixed`.

**Do:** the line currently reads `- Track H: Agent / Skills Compiler ...`. Change `Track H` to `Track L`. Track H is Context Streams Protocol; Track L is Agent/Skills Compiler.

Also scan the surrounding "Recommended Course" block for any other Track mismatch — read lines 1260–1295 and reconcile each `Track <letter>:` reference against the canonical heading at the actual track section.

**Verify:** `grep -n "Track H:" ROADMAP.md` shows no entry pointing to Agent/Skills Compiler.

### 2.5 Delete leftover test DBs in `test_seam/locomo/`

**Skip if:**
```bash
ls test_seam/locomo/*.db 2>/dev/null | wc -l
```
prints `0`.

**Do:**
1. Delete the files:
   ```bash
   rm test_seam/locomo/conv-*.db
   ```
2. Audit the LoCoMo adapter tests (`test_seam_all/test_locomo_*adapter*.py`) for a missing `tearDown` or `tmp_path` fixture. If the tests write to `test_seam/locomo/` instead of `tmp_path`, file a follow-up TODO inline (one comment, one line) and capture it in the HISTORY entry. Do **not** rewrite the adapter tests in this SOP — that's separate work.

`test_seam/` is gitignored and documented as the test DB sink, so this is housekeeping, not a stream-substrate change.

**Verify:** `git status` does not list the deleted files (they were never tracked).

### 2.6 Delete `seam.db` at repo root

**Skip if:**
```bash
test -f seam.db && echo "present" || echo "absent"
```
prints `absent`.

**Do:**
1. Confirm it's not the active local dev DB the operator is using — check `git log -1 --format=%cd seam.db` (untracked = no log; safe to delete) and check that `pyproject.toml` / scripts do not point to `seam.db` at the root as a canonical path.
2. Delete: `rm seam.db`.
3. If you found references to the root path, do **not** delete — open a question instead and stop the phase.

**Verify:** `git status` clean for `seam.db`.

## 5. Phase 3 — Dead-code audit (gated)

### 3.1 `experimental/hybrid_orchestrator/` audit — RESOLVED

Superseded by repo history: the orchestrator was promoted to
`seam_runtime/retrieval_orchestrator/` in HISTORY#284 and the `experimental/`
tree was removed entirely in HISTORY#285. `docs/CODE_LAYOUT.md` documents the
promoted module as active runtime; no deletion decision remains for this item.
If a comparable retired directory is ever reintroduced, verify with a thorough
usage search and request operator confirmation before any removal.

## 6. Phase 4 — Test coverage gaps

### 4.1 Dedicated tests for `evals.py`, `agent_memory.py`, `transpile.py`

**Skip if:** `test_seam_all/test_evals.py`, `test_agent_memory.py`, and `test_transpile.py` all exist with non-trivial assertions (>3 test functions each).

**Do:** create one test file per module. Aim for **one test per public function plus one negative-path test**, not exhaustive coverage. Use the fixtures from Phase 1.3 conftest.

- `test_evals.py`: cover scoring entry points, malformed-input rejection, deterministic output.
- `test_agent_memory.py`: cover memory put/get roundtrip, bounded lookup behavior, eviction policy if any.
- `test_transpile.py` (21 lines of source — small): one happy-path test, one error-path test, done.

If a module's public surface is unclear, read its `__all__` or top-level `def`/`class` declarations and target each one.

**Verify:** `python3 -m pytest test_seam_all/test_evals.py test_seam_all/test_agent_memory.py test_seam_all/test_transpile.py -q` green.

### 4.2 Add Linux CI job

**Skip if:**
```bash
grep -q "ubuntu-latest" .github/workflows/ci.yml && echo "linux"
```
prints `linux`.

**Do:** convert `ci.yml`'s single-OS run into a matrix:

```yaml
jobs:
  test-and-benchmark:
    strategy:
      fail-fast: false
      matrix:
        os: [windows-latest, ubuntu-latest]
    runs-on: ${{ matrix.os }}
    steps:
      # ... existing steps unchanged ...
```

If a step is Windows-specific (e.g., PowerShell installer), gate it with `if: matrix.os == 'windows-latest'`. The Linux installer (`installers/install_seam_linux.sh`) should be exercised on `ubuntu-latest` — add one step:

```yaml
      - name: Linux installer smoke test
        if: matrix.os == 'ubuntu-latest'
        run: sh ./installers/install_seam_linux.sh --dev
```

**Verify:** push and confirm both matrix legs run; both must be green.

## 7. Phase 5 — Test quality scrub (sample-first)

### 5.1 Strengthen weak `assertTrue` patterns in `test_seam_all/test_seam.py`

**Skip if:**
```bash
grep -c "assertTrue(" test_seam_all/test_seam.py
```
prints a number under 30 (audit threshold is "many"; ≤30 means the bulk has been addressed).

**Do:**
- This is a 129-call scrub. **Do not attempt the full pass in this SOP.** Instead:
  1. Find the 15 highest-value cases: `grep -nE "assertTrue\((len\(|.+ in .+|results)" test_seam_all/test_seam.py | head -15`
  2. For each, replace with the specific assertion: `assertEqual(len(x), N)`, `assertIn(expected_id, [c.id for c in x])`, `assertGreaterEqual(score, 0.5)`, etc.
  3. Run the test after every 5 replacements to catch regressions early.
- Open a follow-up roadmap card `seam:item` for the remaining ~114 with status `planned`, topic `tests`. Place it under Track F (Docs/Setup/Error Playbooks) since it's quality-not-feature work — or wherever the operator prefers.

**Verify:** `python3 -m pytest test_seam_all/test_seam.py -q` green; the 15 touched assertions are visible in the diff.

## 8. Phase 6 — Medium-priority cleanups

Run these in order. Each has a `Skip if` gate.

### 6.1 Replace hardcoded operator paths in `REPO_LEDGER.md`

**Skip if:** `grep -q "C:\\\\Users\\\\iwana" REPO_LEDGER.md` returns non-zero.

**Do:** lines 153–155 reference `C:\Users\iwana\OneDrive\Documents\Codex\scripts\...`. Replace each with the in-repo relative reference: `scripts/run_guarded.ps1`, `scripts/run_real_adapters_guarded.ps1`, `scripts/store_benchmark.ps1`. If those repo-relative scripts don't exist, the original ledger lines were also wrong — note that in HISTORY and leave the originals annotated `(operator-local; see private Codex repo)`.

**Verify:** `grep -rn "C:\\\\Users" REPO_LEDGER.md` returns nothing.

### 6.2 Add `[tool.pytest.ini_options]` to `pyproject.toml`

**Skip if:** `grep -q "tool.pytest" pyproject.toml`.

**Do:** add a minimal block:

```toml
[tool.pytest.ini_options]
testpaths = ["test_seam_all", "tools/history"]
addopts = "-q --strict-markers"
markers = [
    "slow: marks tests that take more than 5 seconds",
    "external: tests that hit external services (pgvector, network)",
]
```

**Verify:** `python3 -m pytest --collect-only -q` enumerates the same files as before with no errors.

### 6.3 Mark unimplemented comparators in benchmark registry

**Skip if:** `letta_memgpt`, `mempalace`, `hindsight`, `memmachine` all carry `"status": "not_implemented"` in `benchmarks/registry/memory_benchmarks.json`.

**Do:** for each comparator without adapter code under `benchmarks/external/`, set `"status": "not_implemented"` (string field). Do not remove them — they're roadmap signal. Add a registry validator test asserting the field is present and one of `{implemented, not_implemented, deprecated}`.

**Verify:** `python3 -m pytest test_seam_all/test_external_memory_benchmarks.py -q` green.

### 6.4 `tools/history/build_context_pack.py` UnicodeDecodeError

**Skip if:** `grep -q 'errors="replace"' tools/history/build_context_pack.py` at the relevant decode site.

**Do:** locate the `.decode("utf-8")` call near line 183 and change to `.decode("utf-8", errors="replace")`. Add a test feeding a byte sequence with an invalid UTF-8 mid-sequence and asserting the pack builder produces output rather than raising.

**Verify:** new test green.

### 6.5 ROADMAP done-track "How" section refresh

**Skip if:** Tracks A0, A1, A5 already carry an implementation note pointing to the current dashboard stack.

**Do:** add a single line at the top of each done track's "How" section: `> Implementation note: superseded by Textual migration; see HISTORY#<id>.` Find the relevant history ids via `grep -n "textual" HISTORY_INDEX.md`. Do not rewrite the existing prose — append a one-line note.

**Verify:** `git diff ROADMAP.md` shows only additive one-liners under each track's "How" heading.

### 6.6 (Skipped — see Phase 9, deferred items.)

### 6.7 (Skipped — see Phase 9, deferred items.)

## 9. Phase 7 — Low-priority backlog (catalogue only)

Do **not** fix these in this SOP. Append them as `seam:item` cards to ROADMAP.md under Track F (or operator-chosen track) with status `planned`:

- `SECURITY.md` contact channel clarity
- `installers/install_seam_linux.sh` symlink resolution edge case
- `tools/git-hooks/install.sh` macOS `sha256sum` incompatibility
- `seam_runtime/retrieval.py` hardcoded scoring weights (0.4/0.35/0.15/0.10) — needs benchmark-driven tuning
- `seam_runtime/models.py` exponential backoff without jitter
- `seam_runtime/pack.py` JSON comparison fragility
- `scripts/*.ps1` double-backslash in `Join-Path`
- Experience stream bootstrapped but empty (0 events) — needs first real producer
- Superseded phase tree in ROADMAP.md (~37 lines of stale planning) — needs archival pass
- `test_claude_judge_does_not_import_anthropic_at_module_level` order-dependent flakiness — needs pytest-randomly investigation

**Skip if:** all 10 items already carry `seam:item` markers in ROADMAP.md.

**Verify:** `python3 -m tools.streams.verify_streams` green; new marker count = previous + (number of items not already filed).

## 10. Closeout (mandatory)

Per `AGENTS.md` Session End:

1. Run the full verify chain:
   ```bash
   python3 -m tools.history.verify_integrity
   python3 -m tools.history.verify_routing
   python3 -m tools.history.verify_continuity
   python3 -m tools.streams.verify_streams
   ```
2. Append one `HISTORY.md` entry covering **every phase executed**, with:
   - Files changed (exact paths)
   - Items skipped (with the gate output that triggered the skip)
   - Items deferred (Phase 3 confirmation request, Phase 5 backlog card, Phase 7 catalogue)
   - Verification commands run and their results
   - `supersedes: 190` (or whichever id is current at execution time)
3. Rebuild the index:
   ```bash
   python3 -m tools.history.rebuild_index
   ```
4. Rebuild the cross-index:
   ```bash
   python3 -m tools.streams.rebuild_cross_index
   ```
5. Write a snapshot:
   ```bash
   python3 -m tools.history.write_snapshot
   ```
6. Update `PROJECT_STATUS.md`:
   - Bump `Last updated` date
   - Update `Current Resume Point` to point at the new history id
   - If a phase was deferred (Phase 3 confirmation, Phase 5 backlog), note it under `Active Focus`
7. Final verify pass — same four commands as step 1; must all be green.
8. Commit message for the closeout: `prod-readiness closeout: HISTORY#<new-id>, verify chain green`.

## 11. PR description template

```
## Summary
- Production readiness remediation per docs/SOP_PRODUCTION_READINESS_REMEDIATION.md
- Phases executed: <list>
- Phases skipped (gate satisfied): <list with reason>
- Phases deferred (operator confirmation needed): <list>

## Verification
- [ ] verify_integrity
- [ ] verify_routing
- [ ] verify_continuity
- [ ] verify_streams
- [ ] full pytest pass on test_seam_all/ and tools/history/
- [ ] CI matrix green on both windows-latest and ubuntu-latest (if Phase 4.2 executed)

## HISTORY
HISTORY#<id> — supersedes #<prev>

## Awaiting operator confirmation
- <Phase 3 finding, if applicable>
```

## 12. Hard rules (do not violate)

- Never edit a committed HISTORY entry in place. Always append.
- Never delete retired directories without an explicit operator decision; the
  `experimental/` tree itself was removed in HISTORY#285 and no longer exists.
- Never bypass the pre-commit hook (`--no-verify`). If the gate fails, fix the underlying issue.
- Never commit agent-local `.claude/`, `.opencode/`, `.agents/`, or root
  OpenCode configuration paths. The narrow tracked exceptions are the exact
  root Claude memory pin documented in [`CLAUDE_MEMORY.md`](CLAUDE_MEMORY.md)
  and the validator-declared OpenCode project skill documents; do not broaden
  or work around those compatibility rules.
- Never write session links, share links, API keys, or credential-bearing DSNs into commits, HISTORY, snapshots, or docs. If found in the working tree, redact or delete.
- If a verify gate fails after a phase, **roll back that phase** (`git restore`) and re-run the gate before continuing. Do not stack work on a red gate.

## 13. Out-of-scope items (explicit non-goals)

These appeared in the production readiness assessment but are deferred to separate work:

- Schema migration system for SQLite — needs design RFC, not a remediation pass.
- Structured logging replacement of `print()` — large surface; needs operator decision on logger choice.
- Prometheus-style metrics endpoint — Track K territory.
- Property-based tests (hypothesis) for MIRL/LX/HS roundtrip — needs dependency decision.
- `test_seam.py` 3848-line split into domain files — separate refactor SOP; not safe to bundle with remediation.

If DeepSeek believes any of these become urgent during execution, file a HISTORY observation and stop — do not expand scope.
