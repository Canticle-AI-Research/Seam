# SEAM Full-Repository Audit — 2026-08-01

**Scope:** whole repository, read-only. **Branch:** `feat/track-s-s2-migration-spine`.
**Base:** `origin/main@94375e8`. **History:** HISTORY#525.
**Method:** `/deep-audit` skill (see "Repeating this audit" below).
**Cost boundary:** no provider-paid benchmark, retrieval measurement, publish, or
deploy was run. No repository state was changed during the audit itself; the
remediation recorded at the end was a separate, subsequent step.

**Follow-up (2026-08-02):** `OPEN` below records audit-time state. Findings
2-5 have a local, unmerged repair candidate recorded in HISTORY#526 and draft
PR #193; findings 7-10 and 12 remain open. The original reproducers and verdict
are preserved rather than rewritten after the fact.

## Verdict

The security posture is layered and deliberate, the protocol machinery is real
(all five continuity verifiers green), the connection pool is well built, and
the status streams are unusually honest about their own gaps. S2 is rigorous
work. Two things stood in the way, both invisible from inside the campaign:
the entire S2 spine was uncommitted, and the primary write path silently
corrupts entity identity under concurrency.

## Confirmed findings

Ordered by the sequence in which they should be resolved — dependency and
leverage, not calendar. Severity: CRITICAL (data loss / breach / silent wrong
answers), HIGH (breaks a core guarantee), MEDIUM (bounded blast radius), LOW.

| # | Finding | Area | Sev | Evidence | Status |
|---|---|---|---|---|---|
| 1 | Entire S2 spine uncommitted, unpushed, no PR | ops | CRITICAL | `HEAD` == `origin/main` == `94375e8` | see closeout |
| 2 | Concurrent `persist_ir` defeats entity coreference | persistence | CRITICAL | `storage.py:926-931` | **OPEN** |
| 3 | Unauthenticated `/chat` reads any env var and forwards it | security | CRITICAL | `server.py:1053-1059`, `:386-387`, `:458` | **OPEN** |
| 4 | Projection registry detects but cannot migrate | architecture | HIGH | `migrations.py:172-176`, `:271-279` | **OPEN** |
| 5 | Trust gate silently mis-dates non-ISO timestamps | correctness | HIGH | `knowledge_graph.py:2259-2266` | **OPEN** |
| 6 | Full suite advisory; 13/23 external tests ran nowhere | ci | HIGH | live ruleset; `ci.yml:154` | **FIXED** |
| 7 | Graph traversal nondeterministic (no id tiebreak) | correctness | MEDIUM | `knowledge_graph.py:1116` | **OPEN** |
| 8 | Unbounded SQL variable expansion in `query_graph` | correctness | MEDIUM | `knowledge_graph.py:1105`, `:1159`, `:2074-2085` | **OPEN** |
| 9 | `/v1` public API has zero test coverage | tests | MEDIUM | 1 ref in whole test tree | **OPEN** |
| 10 | Retrieval adapters bypass the connection pool | architecture | MEDIUM | `adapters.py`, 11 sites | **OPEN** |
| 11 | Release docs describe a PyPI job that does not exist | drift | MEDIUM | `README.md` vs workflow | **FIXED** |
| 12 | 3 dirty worktrees, 5 total, against AGENTS.md:39 | ops | LOW | `git worktree list` | **OPEN** |
| 13 | Configured linter never ran in any CI lane | ci | LOW | no `ruff` in workflows | **FIXED** |

### 2 — Concurrent ingest silently fragments entity identity

`persist_ir` (`storage.py:926-931`) checks out a pooled connection and calls
`_persist_ir_on_connection` with no explicit transaction. Python's `sqlite3`
opens its implicit transaction at the first DML statement, not the first
`SELECT`, so `_reconcile_entities`' coreference read (`storage.py:828`) runs on
an unprotected snapshot. The two other callers of the same helper —
`apply_reasoning_promotion` (`:2536`) and `reverse_reasoning_promotion`
(`:2589`) — both open with `connection.execute("begin immediate")`.
`workspace.py:472-475` documents this exact hazard in a comment.

**Reproduced, 3/3 runs.** Eight threads each ingest a sentence naming the same
entity into one namespace. Sequential control: **1** canonical `ENT` record.
Concurrent: **8 distinct `ENT` ids**, zero errors, zero warnings. Every
subsequent claim and relation splits across eight disconnected nodes. WAL does
not help — the writes touch different primary keys, so there is no conflict to
detect. This defeats the entity-coreference work landed in HISTORY#321/#323.

**Resolution.** Move the transaction into `_persist_ir_on_connection` guarded by
`if not connection.in_transaction: connection.execute("begin immediate")`, so
all three call sites are covered by construction rather than patching one.
Mirror the idiom at `workspace.py:474-475`. Add a concurrency test asserting one
canonical `ENT` after N concurrent `ingest_text` calls — no such test exists.

**Not affected:** MIRL record and knowledge-graph projection *are* atomic with
each other (`project_knowledge_records` runs on the same connection before the
single `commit()` at `storage.py:930`). They cannot diverge.

### 3 — Unauthenticated `/chat` env-var read

`server.py:1053-1059` resolves `api_key` from `os.environ.get(env_key)` with
`env_key` taken from the request body and no allowlist.
`_validate_provider_base_url` (`:386-387`) exempts any loopback host from the
provider allowlist. `_call_chat_provider` (`:458`) then sends the value as an
`Authorization` header to that URL. `SEAM_API_TOKEN` is unset by default
(`:567`; guard at `:594` is `if token:`), so no auth is required.

**Verified with a canary**, not asserted: a loopback listener received the
canary environment variable's value as a bearer credential, HTTP 200.

**Scope, honestly.** Browser-driven CSRF is mitigated (CORS origin-restricted,
`allow_credentials=False`); non-loopback binds are refused without a token.
SEAM does **not** auto-load `.env`/`.env.local` into `os.environ` — only
`pgvector_bootstrap` reads them, for compose — so the blast radius is whatever
the operator exported into the serving shell. The attacker is a local process,
not the open internet.

**Resolution.** Allowlist `env_key` against the provider key names backing
`_BUILTIN_CHAT_HOSTS` (`server.py:322-334`), **and** refuse `env_key`
resolution when `base_url` is loopback — a local Ollama already falls through
to the literal `"local"` at `:1068`. Separately, generate and persist
`SEAM_API_TOKEN` on first `seam serve`.

### 4 — The migration spine is a detector, not a migrator

`_validate_projection_rows` (`migrations.py:271-279`) compares the stored
registry against `STORE_PROJECTION_VERSIONS` with exact dict equality and
refuses on any difference. `_STEPS` (`:172-176`) is a static 2-tuple and
`_apply_step` (`:413-439`) is a hardcoded `if to_version == 1 / elif == 2`.
No mechanism exists to reconcile a projection version change.

**Verified on a populated store, all three axes.** Bump a projection version →
`UnsupportedDatabaseVersionError … changed=['workspace']`. Add a projection →
`missing=[...]`. Remove one → `extra=[...]`. In every case the database becomes
permanently unopenable; data is intact but unreachable, and the only recovery
is reverting the constant. There are **13** such constants, each a release
tripwire.

**Why it is invisible.** F17 was scoped as *"there is no central
schema/migration version governing all durable projections."* S2 delivered that
governance and satisfied the finding literally. The campaign never asked the
follow-up — *how does a projection version change get applied?* — so no exit
gate in S3–S10 covers forward migration. Every S3 gate is phrased as refusal or
non-destruction ("leaves all relevant table hashes unchanged").

**Resolution.** Extend the step registry so `_apply_step` dispatches to a
registered per-projection upgrade callable rather than a hardcoded version
branch. Add a campaign exit gate: *a projection version bump upgrades an
existing populated store without data loss.* Keep byte-unchanged refusal as the
fallback for genuinely unknown states.

### 5 — Trust gate lexicographic date fallback

`_time_reached` (`knowledge_graph.py:2259-2266`) falls back to
`str(value) <= horizon` when `datetime.fromisoformat` raises, with no log. It
feeds node visibility (`:2249`) and `trust_state = "stale"` (`:2446`).

**Reproduced.** With horizon `2026-08-01`: `"2020-01-01T00:00:00+00:00"` →
`True` (correctly expired); `"Jan 1 2020"` → **`False`** — six years expired,
not marked stale, returned as established knowledge. `"01/01/2020"` returns
`True` only by lexicographic accident. The fallback is arbitrary, not
conservative.

**Resolution.** `LOGGER.warning` and return `True` — fail toward "expired"
rather than the current fail-open `False`.

### 7, 8, 10 — graph and retrieval path

- **7** `knowledge_graph.py:1116` is the only ordered-and-limited query in the
  file without a terminal id tiebreak (`:1018` has `n.id`, `:1082` has `ep.id`).
  `confidence` defaults to `0`, so ties are the common case; admitted rows
  determine `next_frontier` and therefore the returned node *set*. This
  propagates into `candidate_set_sha256`, making the advertised reproducibility
  fingerprint unreproducible. Fix: append `, e.id`.
- **8** `knowledge_graph.py:1105`, `:1159`, `:2074-2085` expand caller-controlled
  collections into `IN (...)` unchunked, while `adapters.py:29-36` sets
  `_GRAPH_REPEATED_ID_CHUNK = 400` citing SQLite's 999-variable floor.
  `GET /knowledge-graph?limit=1000&hops=5` reaches thousands of variables.
  Latent on this host (SQLite 3.45.1, limit 250,000); breaks on any host with
  the legacy 999 default. Fix: chunk at 400, or lower the API bound.
- **10** Eleven sites in `adapters.py` call `self.store._connect()` directly, so
  the pool built at `storage.py:272` is inert for the entire read path. Not a
  leak (`closing()` closes them), but each leg gets its own WAL snapshot — a
  `mix` search with `hops=3` opens ~8 connections and can return edges whose
  episodes a concurrent write already deleted.

### 12 — worktree hygiene

Five worktrees exist; three are dirty (3, 1, and 12 files). AGENTS.md:39
forbids this, citing a real regression (HISTORY#223). Left for operator
decision — no worktree was removed by this audit.

## Structural observations (not defects)

**The graph is built but unfed.** Track R delivered G1–G7. Then
`docs/status/retrieval.md:41-47` records that on the default-ingest LoCoMo
snapshot there were zero admissible semantic relation edges, so `mix` and
`hybrid` produced byte-identical results, and the graph leg cost −0.023854 while
contributing nothing. REL coverage is 27/419, "insufficient and
scorer-ineligible." The bottleneck is relation extraction at ingest, not graph
algorithms. Further graph investment compounds against a leg with no edges to
traverse.

**The campaign's exit gates are all phrased as refusal.** S3 through S10 read
"leaves all relevant table hashes unchanged," "remains byte-unchanged after
refusal," "detected and repaired," "fail-closed." Excellent discipline for
defending integrity, and the reason S2 is good work. But no gate anywhere says
*"an existing populated store successfully moves forward to a new layout."*
That asymmetry produced finding 4 and will reproduce in S3, S4, and S5.

**`storage.py` is 3,602 lines with no dedicated test file.** Covered by
`test_storage_lifecycle.py` (25 lines, 2 tests) and
`test_storage_stats_max_degree.py` (2 tests), otherwise only indirectly. This is
why finding 2 survived — there is no place a `persist_ir` concurrency test
would naturally live — and why the `begin immediate` asymmetry between three
call sites in one file went unnoticed.

**The verification machinery is stronger than what it verifies.** Five
verifiers pass, the handoff registry is a clean linear chain, routing is
auditable. At audit time all of it attested to a HISTORY entry that existed in
no commit. The protocol proves internal consistency of the record; nothing
proved the record was durable.

## Corrections to prior belief

- `docs/status/retrieval.md:92` states "Retrieval **mutates** the SQLite store."
  Under default flags a `retrieve()` left the database and WAL byte-identical.
  The claim presumably holds only when retrieval-event writing is enabled, as in
  the benchmark path. The A/B cloning methodology it justifies is sound, but as
  written it implies the read path is impure by default, which is not true.
- An fd leak in `inspect_database` (`with _readonly_connection(...)` does not
  close) is real but **GC-reclaimed and bounded** — one fd per store open.
  Measured, then downgraded from the initially suspected severity to LOW.
- Migration backups accumulate only per schema *upgrade*, not per open (early
  return at `migrations.py:457`). Smaller than first assumed. Still unpruned by
  design, and each is a full database copy.
- `fsync` on an `O_RDONLY` fd in `restore_database_backup` **succeeds on Linux**.
  Portability nit, not a defect on the target platform.
- No real API key has ever been committed. All four `sk-proj-` occurrences in
  git history are detection regexes and synthetic `"a"*24` fixtures. `.env` and
  `.env.local` are untracked, gitignored, mode 0600.

## Verifications performed

Every check run, including clean results.

- [x] Read `AGENTS.md`, `PROJECT_STATUS.md`, `docs/CODE_LAYOUT.md`, handoff
      registry + current handoff, `docs/SQLITE_MIGRATIONS.md`,
      `docs/status/retrieval.md`, `MEMORY_GUARANTEES_CAMPAIGN.md` (S2–S5 + F1–F22)
- [x] `git rev-parse HEAD` == `origin/main` == `94375e8`; branch had 0 commits
- [x] `git cat-file -e HEAD:seam_runtime/migrations.py` → failed (in no commit)
- [x] HISTORY#523 present 1× in working tree, 0× in committed `HISTORY.md`
- [x] `git ls-remote --heads origin <branch>` → empty; `gh pr list` → none
- [x] `git stash list` → empty; `git worktree list` → 5, dirty counts 3/1/12
- [x] `pytest tests/audit/test_sqlite_migration_spine.py` → **17 passed**
- [x] Projection change / add / remove on a populated store → all three refused
- [x] Counted 13 projection version constants; `_STEPS` static; `_apply_step` hardcoded
- [x] Live `seam.db`: schema v2, 13 projections, 28 `ir_records`, 1 backup (956K)
- [x] fd leak measured under GC enabled and disabled → bounded, reclaimed
- [x] `fsync` on `O_RDONLY` fd → succeeds on Linux
- [x] **Entity race reproduced 3/3**: 8 concurrent → 8 `ENT`; sequential → 1
- [x] `_time_reached("Jan 1 2020", now)` → `False` (expired fact not stale)
- [x] `knowledge_graph.py:1116` lacks the tiebreak `:1018`/`:1082` have
- [x] Local SQLite 3.45.1, variable limit 250,000 (finding 8 latent here)
- [x] `retrieve()` left db+WAL sha unchanged — falsified the mutation claim
- [x] **`/chat` exfiltration executed live with a canary** → value received
- [x] Traced all three links of the exfiltration chain in source
- [x] No real key in any commit (rebuilt the filter after a false positive)
- [x] `.env`/`.env.local` untracked, gitignored, 0600; `.env.example` placeholders
- [x] SEAM does not auto-load `.env` into `os.environ`
- [x] `pytest tests/audit/test_secret_scan.py test_public_safe_gate.py` → **52 passed**
- [x] `pytest --collect-only` → **2153 collected, 0 errors**; `-m "not external"` → 2130
- [x] External arithmetic: 23 total, **10 in CI, 13 in no lane**
- [x] **Live GitHub ruleset queried**: required checks are exactly `repo-hygiene`,
      `chroma-real-smoke`, `locomo-quickstart-bil2`; full suite not required
- [x] `test_ci_enforces_no_silent_skips` asserted 2 filenames vs "every external test"
- [x] `/v1` route coverage: 1 reference in the entire test tree
- [x] `ruff check` → 1 error (pre-existing); no `ruff` in any workflow
- [x] `verify_continuity`, `verify_handoffs`, `verify_streams`, `verify_routing`,
      `verify_integrity` → **all 5 exit 0**
- [x] `SEAM_STRICT_NO_SKIP=0` bypass → exit 0 with no warning (confirmed silent)

**Not verified:**

- [ ] Full 2,130-test suite not run; collection verified clean instead
- [ ] Multi-*process* form of finding 2 (reproduced across threads only)
- [ ] Whether `test_baseline_policy.py:64` skips in CI under `fetch-depth: 1`
- [ ] `dashboard.py` (3,160 lines), benchmarks, webui JS — outside this sweep
- [ ] Any paid benchmark or retrieval measurement — none run

## Remediation applied in the same session

Findings 6, 11, 13 were closed, plus the silent strict-no-skip bypass:

- `.github/workflows/ci.yml` — pgvector `0.8.2` → `0.8.6-pg18-trixie` (matches
  compose); pgvector job now runs all five external files; `repo-hygiene` (a
  required check) now runs `ruff check`.
- `tests/audit/test_github_pr_gates.py` — `test_ci_enforces_no_silent_skips`
  now derives the required file set from the test tree and fails if the pgvector
  job omits any; verified against a deliberately broken workflow. Added
  `test_repo_hygiene_runs_the_configured_linter`. Made the file CWD-independent.
- `tests/conftest.py` — `SEAM_STRICT_NO_SKIP=0` now prints a banner naming every
  unenforced skip instead of passing silently.
- `seam_runtime/retrieval_orchestrator/__init__.py` — ruff I001 fixed;
  re-exports verified intact.
- Docs corrected to match the real workflow: `README.md`, `docs/CODE_LAYOUT.md`,
  `ROADMAP.md` (also `2.3.0` → `2.4.0`, `seam-client` `0.1.0` → `2.0.0`),
  `docs/status/surfaces.md` (16 → 19 MCP tools), `docs/status/deferred.md`
  (113 → 133 `assertTrue`), pgvector tag in `PGVECTOR_LOCAL.md`, `MACOS.md`,
  `SEAM_OPERATOR_GUIDE.md`; SUPERSEDED banner on
  `SOP_SEAM_SELF_HOST_WHEEL.md`; `docs/README.md` no longer lists superseded
  docs as Active.

Verification of the remediation: 30/30 external tests pass with both DSNs set
exactly as CI invokes them; `ruff check` clean; guard suite 7 passed and proven
to fail on injected drift.

## Repeating this audit

This audit is reproducible. It was produced by the `/deep-audit` skill
(`~/.claude/skills/deep-audit/`), which is read-only by construction —
`Edit`, `Write`, and `NotebookEdit` are removed for the duration — and fans out
parallel lanes across architecture, correctness, persistence, security,
tests/CI, and doc drift, then independently re-verifies every candidate finding
before reporting.

To repeat: run `/deep-audit` from the repo root, then file the result here as
`docs/audits/<YYYY-MM-DD>-full-repo-audit.md` and add a row to
[`INDEX.md`](INDEX.md).

Comparing runs is the point. The finding table above is designed to diff: keep
the `#`, `Finding`, `Sev`, and `Status` columns stable across audits so an item
that reappears, or one that silently drops off, is visible.
