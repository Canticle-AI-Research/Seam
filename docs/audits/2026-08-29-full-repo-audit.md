# SEAM Full-Repository Audit — 2026-08-29

**Scope:** whole-repository health audit. **Repository:** `Canticle-AI-Research/Seam`.
**Audited tree:** working tree at `ad302ec` (branch `feat/tui-canticle-rework`, dirty)
for the sweep; the tree moved to `859863c` (branch
`preserve/rejected-terminal-graph-tui-20260829`, clean) mid-audit when a concurrent
agent committed the in-flight TUI work. Every citation was re-validated against
`859863c` after the move. **Observed `origin/main`:** `6608f7d`.
**Method:** four read-only lanes (orchestrator-run architecture/tests/drift;
plus correctness, persistence, and security sub-agents), 344 `path:line`
citations validated against EOF, one full test-suite run with the live pgvector
lane, one confirming re-run isolating an environment cause, 20 empirical
persistence probes including two live two-process lock tests and read-only
`EXPLAIN` against the 152,152-row pgvector store, one independently reproduced
authentication-limiter bypass, and all seven repository gates.
**Governing history entry:** `HISTORY#613`.

---

## 1. Verdict

SEAM's engineering substrate is stronger than this audit expected, and its
exposure is almost entirely in three places the substrate does not cover:
**derived state that does not follow canonical state through deletion**, **an
operator surface that reports things it did not do**, and **a self-hosted CI
runner that executes untrusted code.** The migration spine, the connection pool,
the vector outbox, rank fusion, the cross-process persistence lock, corrupt-database
refusal, and every one of the six continuity gates do exactly what the repository
documents — several verified empirically rather than by reading. There are zero
import cycles across 163k lines of tracked Python, the audit registry is complete,
and `main`'s status router is genuinely current.

The single thing most standing in the way is that **deletion is not a guarantee
the system actually keeps.** A scoped delete clears the vector and projection
indexes and correctly disappears from every retrieval path, and then `trace()`
hands the full payload of the deleted record back through an authenticated REST
route, while the G4 graph products keep the deleted text verbatim in a second
table that even a hard delete does not clean. For a memory product whose public
API ships `/v1/memories/delete`, that is the load-bearing defect.

This audit records 3 CRITICAL, 7 HIGH, 25 MEDIUM, and 10 LOW findings. It changes
no repository file other than itself.

Two things that were true when the sweep began and are no longer true are recorded
here rather than dropped, because they describe a real operating risk: the in-flight
TUI slice and three HISTORY entries existed only as uncommitted working-tree state
with tracked files importing untracked modules — resolved at `859863c`, now pushed;
and the full suite was red at 44 failed / 6 errors from an environment cause the
operator was already servicing. Neither is a live defect. The repository-side
residue of the second is F-30.

## 2. System map (as found)

```
   CLI (57 verbs)   TUI      webui/dashboard.html      REST /v1  /persist /chat   MCP    SDK
        │            │        [!F-7][!F-8]                │  [!F-16][!F-15]        │      │
        │         [!F-17]     served unauthenticated ─────┘  [!F-18][!F-9]      [!L-4]    │
        └────────────┴──────────────┬───────────────────────┴────────────────────┴────────┘
                                    │  SeamRuntime      [!F-28] flags cached for process life
                                    │                   [!F-5]  ingest_text = 3 commits
                            RetrievalOrchestrator
                                    │
      ┌─────────────────────────────┼──────────────────────────────┐
      │ SQL leg                     │ planner / fusion             │ graph leg
      │ [!F-12] scans ALL           │ [!F-21] gate drops boundary  │ [!F-26] dangling edges
      │   namespaces per query      │ [!F-22] two RRF rank bases   │ [!F-19] ISO compared as text
      │ [!F-21]                     │ [!F-20][!F-23] flag contract │ [!F-27] loads whole ns
      └─────────────────────────────┼──────────────────────────────┘
                                    │  storage.py (1 class, 145 methods, 5,467 lines)
        ┌───────────────────────────┼────────────────────────────────┐
        │ migrations.py             │ lifecycle.py scoped delete     │ vector / pgvector
        │  spine: SOUND             │  [!F-2] trace() leaks payload  │ [!F-13] HNSW unusable
        │  [!F-1] restore w/ live   │  [!F-3] graph products retain  │ [!F-29] no tie-break
        │  [!F-4] restore crash win │  [!F-11] 9 tables retain bytes │
        └───────────────────────────┴────────────────────────────────┘
                                    │
                          read_snapshot  [!F-14] a failed write silently ends it

  CI: .github/workflows/ci.yml — all 5 jobs on [self-hosted, seam-box]  [!F-6] PR-triggered
```

## 3. Findings

Ordered by the sequence in which they should be resolved. Items at the same
indent level with no dependency between them are parallel-safe.

| # | Finding | Area | Sev | Conf | Evidence | Blocks |
|---|---|---|---|---|---|---|
| F-1 | Restore with a live runtime silently discards committed rows | persistence | CRITICAL | CONFIRMED | `seam_runtime/migrations.py:2213` | F-4 |
| F-2 | `trace()` returns soft-deleted payloads through authenticated REST | persistence | CRITICAL | CONFIRMED | `seam_runtime/storage.py:5420` | F-3, F-11 |
| F-3 | Graph products retain deleted text forever; hard delete misses them | persistence | CRITICAL | CONFIRMED | `seam_runtime/lifecycle.py:320` | F-11 |
| F-4 | Restore crash-window replays the pre-restore WAL over the recovery | persistence | HIGH | CONFIRMED | `seam_runtime/migrations.py:2238` | — |
| F-5 | `ingest_text` is three commits; failing the third splits the ledger | persistence | HIGH | CONFIRMED | `seam_runtime/runtime.py:337` | — |
| F-6 | Self-hosted CI runner executes untrusted pull-request code | ci/security | HIGH | CONFIRMED | `ci.yml:5` | — |
| F-7 | WebUI persists every provider API key to browser `localStorage` | security | HIGH | CONFIRMED | `seam_runtime/webui/dashboard.html:806` | F-8 |
| F-8 | WebUI fabricates credential, persistence, and benchmark results | surfaces | HIGH | CONFIRMED | `seam_runtime/webui/dashboard.html:904` | — |
| F-9 | Rotating the auth header defeats the rate limiter entirely | security | HIGH | CONFIRMED | `seam_runtime/server.py:293` | — |
| F-10 | The working branch is 13 behind `main` and carries fixed defects | workspace | HIGH | CONFIRMED | `seam_runtime/reasoning_graph.py:1186` | F-19..F-27 |
| F-11 | Scoped delete leaves content at rest in nine tables | persistence | MEDIUM | CONFIRMED | `seam_runtime/storage.py:2264` | — |
| F-12 | Every structured retrieval scans `vector_index` across all namespaces | retrieval | MEDIUM | CONFIRMED | `seam_runtime/retrieval_orchestrator/adapters.py:1448` | — |
| F-13 | pgvector HNSW indexes cannot serve the adapter's own query | persistence | MEDIUM | CONFIRMED | `seam_runtime/vector_adapters.py:481` | F-29 |
| F-14 | A failed write silently terminates a bound read snapshot | persistence | MEDIUM | CONFIRMED | `seam_runtime/pool.py:201` | — |
| F-15 | `/chat` allowlist is bypassed by any host resolving to loopback | security | MEDIUM | CONFIRMED | `seam_runtime/server.py:511` | — |
| F-16 | The dashboard static mount is unauthenticated and unmetered | security | MEDIUM | CONFIRMED | `seam_runtime/server.py:412` | — |
| F-17 | TUI chat client has no host allowlist and no response cap | security | MEDIUM | CONFIRMED | `seam_runtime/dashboard.py:304` | — |
| F-18 | `/v1` tenancy is caller-asserted whenever principal mode is off | security | MEDIUM | CONFIRMED | `seam_runtime/server.py:936` | — |
| F-19 | Temporal comparison is done three different wrong ways | correctness | MEDIUM | CONFIRMED | `seam_runtime/reconcile.py:176` | — |
| F-20 | `search_top_k` and `context_budget` are silently unsettable | retrieval | MEDIUM | CONFIRMED | `seam_runtime/retrieval.py:509` | — |
| F-21 | Structured-score gate contradicts its comment, drops boundary records | retrieval | MEDIUM | CONFIRMED | `seam_runtime/retrieval_orchestrator/adapters.py:1429` | — |
| F-22 | Two RRF engines disagree on rank base | retrieval | MEDIUM | CONFIRMED | `seam_runtime/retrieval.py:616` | — |
| F-23 | One approved retrieval flag still resolves three different ways | retrieval | MEDIUM | CONFIRMED | `seam_runtime/mcp.py:416` | — |
| F-24 | Unevidenced dispute edges demote verified claims | trust | MEDIUM | CONFIRMED | `seam_runtime/knowledge_graph.py:3082` | — |
| F-25 | Reasoning-pattern result disagreement is silently, permanently dropped | reasoning | MEDIUM | CONFIRMED | `seam_runtime/reasoning_patterns.py:627` | — |
| F-26 | `query_graph` returns edges whose endpoints it already filtered out | graph | MEDIUM | CONFIRMED | `seam_runtime/knowledge_graph.py:1711` | — |
| F-27 | Compat and temporal retrieval load the entire namespace into memory | retrieval | MEDIUM | CONFIRMED | `seam_runtime/storage.py:951` | — |
| F-28 | Retrieval flags are cached for the whole process lifetime | retrieval | MEDIUM | CONFIRMED | `seam_runtime/runtime.py:1066` | — |
| F-29 | pgvector's `limit` cut has no tie-break; SQLite's does | persistence | MEDIUM | PLAUSIBLE | `seam_runtime/vector.py:418` | — |
| F-30 | The KB forbids setting `HF_HUB_CACHE`; the environment sets it anyway | drift | MEDIUM | CONFIRMED | `docs/kb/eval-methodology/locomo-mem0-harness.md:21` | — |
| F-31 | The no-deletion invariant is violated by the repo's own closeout tooling | protocol | MEDIUM | CONFIRMED | `tools/streams/rebuild_cross_index.py:127` | — |
| F-32 | Untracked, non-ignored tool artifacts sit in the tree | hygiene | MEDIUM | CONFIRMED | `.gitignore:57` | — |
| F-33 | Worktree, branch, and PR hygiene has drifted from AGENTS.md's own rules | hygiene | MEDIUM | CONFIRMED | `AGENTS.md:48` | — |
| F-34 | Secret scanners never rescan existing history | security | MEDIUM | CONFIRMED | `tools/security/secret_scan.py:188` | — |
| F-35 | Four declared dependency upper bounds are violated by the installed venv | supply-chain | MEDIUM | CONFIRMED | `pyproject.toml:40` | — |

---

**F-1 — CRITICAL · `restore_database_backup` silently discards committed rows when a runtime is live**

- **What is wrong.** The function documents a precondition it never enforces, and it is the one destructive write path outside the cross-process lock the repository otherwise uses for every canonical write.
- **Evidence.** `seam_runtime/migrations.py:2213` — `    The caller must close every runtime using ``path`` before restore. SQLite`
- **Failure scenario.** An operator recovers a database while `seam serve` is running. Probe output: a store with 301 rows is restored from a 1-row backup without closing; the call returns normally, the live store still reports 301 rows from cached pages, then successfully commits a further row — and after the process exits a fresh reader sees 1 row. Both the 300 pre-restore rows and the acknowledged post-restore write are gone, and `PRAGMA integrity_check` reports `ok`, so no gate detects it.
- **Why here in the order.** It is the only finding that destroys already-committed data with no error and no detectable trace, and its fix is a precondition check that also closes F-4's blast radius.
- **Resolution.** Acquire the existing `.seam-runtime-<digest>.lock` for the resolved store path with `LOCK_EX | LOCK_NB` at the top of `restore_database_backup` and refuse if any runtime holds it. Every `SeamRuntime` already honours that lock.
- **How to verify the fix.** Re-run the probe shape: open a store, take a backup, insert, call restore without closing — assert it raises rather than returning.

**F-2 — CRITICAL · `store.trace()` returns the full payload of soft-deleted records**

- **What is wrong.** `_load_record_by_id` applies no status predicate, and `trace()` calls it unconditionally for the root and every neighbour. The sibling `knowledge_edges` query does filter deleted rows, but that filter is on the *edge's* status, so it never protects the payload read.
- **Evidence.** `seam_runtime/storage.py:5420` — `    row = connection.execute("select payload_json from ir_records where id = ?", (record_id,)).fetchone()`
- **Failure scenario.** A record containing an address and passport number is ingested, then removed by a G6 scoped delete that reaches `applied`; `vector_index` and `projection_index` go to zero and every retrieval path is verified clean. A token holder then calls `GET /trace` with an id kept from an earlier `/search` and receives the complete deleted record. Probe output: `trace(raw)  LEAKS CANARY  (len=531)`.
- **Why here in the order.** It is the shortest path from "the operator believes the data is deleted" to "the data is returned", and it is reachable on a shipped authenticated route.
- **Resolution.** Give `_load_record_by_id` the excluded-status tuple already defined for `assertable_record_ids`, have `trace()` refuse a deleted root and drop deleted neighbours, or add `include_deleted: bool = False` and leave it False on the REST and CLI surfaces.
- **How to verify the fix.** Ingest, scoped-delete, then assert `trace(root_id)` raises `KeyError` and that no response field contains the deleted text.

**F-3 — CRITICAL · G4 graph products retain deleted text verbatim, and hard delete does not reach them**

- **What is wrong.** `apply_scoped_delete` clears knowledge records and two index tables and never touches `graph_product`, `graph_product_sentence`, or `graph_product_build`. The deleted text has been *copied* into those tables, so even a later hard `delete_ir` — whose table list is `raw_docs`, `raw_spans`, `symbol_table`, `pack_store`, `prov_log` — does not remove it.
- **Evidence.** `seam_runtime/lifecycle.py:320` — `            remove_knowledge_records(connection, targets)`
- **Failure scenario.** After the same scoped delete as F-2, the live read API `SQLiteStore.graph_products(namespace=…, scope=…)` returns three products containing the deleted sentence verbatim, and the shipped SDK exposes that path. `read_graph_products` selects "the latest complete snapshot", which remains the pre-delete build indefinitely.
- **Why here in the order.** Same guarantee as F-2 and the same delete transaction, but strictly harder to remediate afterwards because the content is duplicated — so it should be fixed in the same change rather than after.
- **Resolution.** In the lifecycle transaction, either delete `graph_product_sentence` rows whose supporting record ids intersect the targets and mark the build incomplete, or record a staleness marker for the boundary and have `read_graph_products` refuse or rebuild. The second preserves the append-only contract.
- **How to verify the fix.** The canary probe: ingest, build products, scoped-delete, then scan every table for the canary string and assert zero hits in the graph-product tables.

**F-4 — HIGH · The restore path swaps the database file before invalidating the sidecars**

- **What is wrong.** `os.replace()` then a sidecar unlink is a non-atomic two-step. A crash between them leaves the restored file beside the *old* database's WAL, and WAL recovery has no binding to file identity, so it replays.
- **Evidence.** `seam_runtime/migrations.py:2238` — `        os.replace(temporary_path, database_path)`
- **Failure scenario.** Reproduced at byte level: a child process writes 500 rows with autocheckpoint disabled and exits via `os._exit(0)` so the sidecars survive as after a power loss; the probe performs the `os.replace()` of a 1-row backup and stops before the unlink. On reopen the 500 pre-restore rows are back, the restored row is gone, and `integrity_check` reports `ok`.
- **Why here in the order.** Same function and same review as F-1; fixing F-1 without this leaves a narrower but identical silent-revert window.
- **Resolution.** Make the swap the single commit point: verify no live runtime, rename the existing file and all three sidecars aside into quarantine, `os.replace()`, `fsync` the directory, then discard the quarantine. A cheaper partial fix is `PRAGMA wal_checkpoint(TRUNCATE)` plus `journal_mode=DELETE` on the live file before the replace.
- **How to verify the fix.** Copy the function, inject `os._exit(1)` immediately after the replace, run against a database with a populated WAL, reopen and count rows.

**F-5 — HIGH · `ingest_text` commits three times; failing the third leaves content live with no document row**

- **What is wrong.** Persist, supersede, and document-status are three independent commits with no enclosing transaction and no lock spanning them — `persist_ir` takes and releases the projection lock internally before the other two run.
- **Evidence.** `seam_runtime/runtime.py:337` — `        if persist:`
- **Failure scenario.** Reproduced by raising `OSError` in the third step: v2's records are persisted, `asserted`, and vector-indexed; `retrieve("Oslo")` returns v2's full text as a live candidate; the only `document_status` row is v1, already tombstoned with `deleted_at` by step 2 — so the ledger reports no live document for the source at all; and the caller received an exception and reasonably believes nothing was stored. A batch retry never repairs it, because ledger-driven reconciliation cannot see the record.
- **Why here in the order.** It is the remaining canonical-state integrity defect after the delete cluster, and it is independent of F-1..F-4 — parallel-safe with them.
- **Resolution.** Run all three steps on one connection inside one `BEGIN IMMEDIATE`, or add a locked store method performing persist, supersession, and document status in a single transaction. Reordering steps 2 and 3 only relocates the inconsistency.
- **How to verify the fix.** Re-run the injected-failure probe and assert the source has either both the records and a live document row, or neither.

**F-6 — HIGH · Every CI job runs untrusted pull-request code on the operator's workstation**

- **What is wrong.** The `pull_request` trigger has no `types` filter, no author guard, and no environment approval, and all five jobs target the self-hosted runner. A PR author controls `pyproject.toml` (executed by `pip install -e .`), the installer script (executed by `sh`), and the whole test tree.
- **Evidence.** `ci.yml:5` — `  pull_request:`
- **Failure scenario.** Anyone who can open a pull request obtains code execution as the runner user on the physical box — reaching SSH keys, the operator settings file, and the private checkout. `permissions: read-all` constrains only the token. The workflow additionally documents that pip and HF caches persist between runs, so a malicious PR can poison a cache that later trusted runs consume.
- **Why here in the order.** It is the only finding whose trust boundary is "any GitHub user" rather than "a token holder on loopback", and it is a configuration change independent of every code fix — start it in parallel with the persistence cluster.
- **Resolution.** Gate PR-triggered jobs on `github.event.pull_request.head.repo.full_name == github.repository` or a manual environment approval, or move the `pull_request` legs to hosted ephemeral runners and keep only `push` on the self-hosted box.
- **How to verify the fix.** Open a PR from a fork and confirm the jobs do not start without approval.

**F-7 — HIGH · The WebUI writes every provider API key to browser `localStorage`**

- **What is wrong.** The API-keys hub stores its entire key array — including the values the operator types — through a helper that persists to `localStorage`, directly against the repository's own written policy.
- **Evidence.** `seam_runtime/webui/dashboard.html:806` — `  const [keys, setKeys] = usePersisted('seam-dash-api-keys', PRESETS);` and `seam_runtime/webui/dashboard.html:765` — `      localStorage.setItem(storageKey, JSON.stringify(value));`
- **Failure scenario.** An operator enters an OpenAI or Anthropic key in Settings. It is written in plaintext to origin-scoped `localStorage`, where it survives restarts and is readable by any script that ever executes on that origin — and this file is served at `/` and packaged into the wheel. The repository already recognised this class and fixed it for the SEAM token only: `seam_runtime/webui/seam-api.js:25` — `      localStorage.removeItem(TOKEN_KEY);` — migrating that one credential to `sessionStorage`.
- **Why here in the order.** It is a credential-at-rest defect in shipped, packaged code, and it is the reason to open this file at all — F-8 is found in the same pass.
- **Resolution.** Move provider key values to `sessionStorage` as `seam-api.js` already does, or stop persisting values client-side and resolve them server-side through the existing one-to-one host/env binding.
- **How to verify the fix.** Enter a key, reload, and confirm `localStorage` contains no value field.

**F-8 — HIGH · The WebUI reports credential tests, persistence, and benchmark results that never happened**

- **What is wrong.** Four distinct fabrications are presented as real runtime outcomes, against a ledger rule that forbids exactly this.
- **Evidence.** `seam_runtime/webui/dashboard.html:904` — `        setTestResults((r) => ({ ...r, [key.key]: { ok, t: Date.now(), latency: Math.round(80 + Math.random() * 280), status: ok ? '200 OK' : !key.value ? 'empty key' : 'bad url' } }));`
- **Failure scenario.** The credential test returns `200 OK` with an invented latency after a timer, making no network call, so an operator concludes a key works when it was never exercised. `seam_runtime/webui/dashboard.html:5387` mints `id: \`clm:${Math.floor(Math.random() * 900 + 100)}\`` and marks it `[persisted]` and `indexed` — a persistence confirmation for a record never written, which in a memory system is the worst available lie. `seam_runtime/webui/dashboard.html:3284` fabricates a benchmark `hash` and a `PASS`, in a repository whose publication policy makes hashes the evidence. `seam_runtime/webui/dashboard.html:774` ships a masked placeholder value and a `rotatedAt` date, and `seam_runtime/webui/dashboard.html:916` counts those placeholders as configured keys.
- **Why here in the order.** Same file and same review as F-7, and it is the finding most likely to cause a wrong operator decision.
- **Resolution.** Delete the simulated branches, or render them behind an explicit, visually distinct "demo data" state that no success affordance can be mistaken for. Where a real check exists, call it.
- **How to verify the fix.** Grep the file for `Math.random` and confirm no remaining call feeds a status, hash, id, or latency the UI presents as a runtime result.

**F-9 — HIGH · Rotating the `Authorization` header defeats the rate limiter, permitting unlimited bearer brute force**

- **What is wrong.** For an unauthenticated request the limiter key is the SHA-256 of the caller's own header, so every distinct guess lands in a fresh bucket.
- **Evidence.** `seam_runtime/server.py:293` — `        return hashlib.sha256(authorization.encode()).hexdigest()`
- **Failure scenario.** Independently reproduced by the orchestrator with the limit set to 3/min: eight requests with a fixed wrong bearer returned `[401, 401, 401, 429, 429, 429, 429, 429]`; eight with a rotating wrong bearer returned `[401, 401, 401, 401, 401, 401, 401, 401]`. Tokens can be guessed at line rate against the constant-time comparison, with no throttle and no lockout.
- **Why here in the order.** It is a one-line keying change with no design decision attached, and it is the security finding with the largest gap between effort and effect.
- **Resolution.** Key the pre-authentication bucket on the client address only, exactly as principal mode already does via its auth-failure key, and reserve the header-derived key for successful authentications.
- **How to verify the fix.** Re-run the rotating-header probe and assert 429 appears.

**F-10 — HIGH · The working branch is 13 commits behind `main` and carries defects `main` has already fixed**

- **What is wrong.** The primary checkout has been developed on a branch that never took `main`'s S8 retrieval-coherence and Ghost slices, so it reintroduces defects that are fixed upstream.
- **Evidence.** `seam_runtime/reasoning_graph.py:1186` — `            raise ValueError("retrieval candidate score does not match the pinned policy")`
- **Failure scenario.** On this branch, setting the documented, registered knob `SEAM_RETRIEVAL_LEG_WEIGHTS` makes every SDK reasoning retrieval unrecordable: the merger stores the weighted score, the recorder re-derives the unweighted sum, and the row is refused — and separately the run is labelled with a policy id the recorder rejects. Even a weight of exactly 1.0 trips it, because the branch tests for non-empty weights rather than for weights that differ. `main` fixed this, accepts both policy ids, and persists `leg_weights_json`; its in-code comment reads *"refusing it here turned a supported retrieval into an unrecordable one."* Two further findings in this audit are also `main`-only defects: the temporal leg missing from the recorder's allowlist, and the unchunked graph-episode `IN` expansion that `main` chunks at 400.
- **Why here in the order.** It is a merge, not a code change, and landing it removes three findings outright and rebases the rest onto the tree that actually ships.
- **Resolution.** Merge `origin/main` into the working branch before acting on any retrieval finding below, then re-verify F-19 through F-27 against the merged tree.
- **How to verify the fix.** `git rev-list --left-right --count origin/main...HEAD` shows zero behind, and setting a leg weight records a reasoning retrieval without raising.

**F-11 — MEDIUM · Scoped delete leaves the deleted content at rest in nine tables**

- **What is wrong.** Soft delete clears two derived index tables; the hard-delete path clears five specialised content tables and reaps orphan node vectors. Soft delete does neither.
- **Evidence.** `seam_runtime/storage.py:2264` — `                for table in (`
- **Failure scenario.** A full-table canary scan after a scoped delete found the deleted text still present in `graph_product`, `graph_product_sentence`, `ir_edge_sources`, `ir_edges`, `ir_records`, `knowledge_node_vectors`, `lifecycle_event`, `lifecycle_operation`, and `raw_docs`. The surviving node-vector rows are orphans whose node is gone; retrieval cannot reach them, so this is data-at-rest retention rather than a wrong answer. An operator who honours a deletion request reports the data gone while the file still yields it to one `SELECT`.
- **Why here in the order.** It shares the delete transaction with F-2 and F-3 and should be decided in the same change — but unlike those it may be intended behaviour, so it needs an explicit call.
- **Resolution.** Either extend the scoped-delete transaction to the hard-delete table list plus orphan-vector reaping, or state in `REPO_LEDGER.md` that scoped delete is a visibility operation and say so at every surface that offers it.
- **How to verify the fix.** The canary scan, asserting the intended table set.

**F-12 — MEDIUM · Every structured retrieval materialises `vector_index` across all namespaces**

- **What is wrong.** The outer query filters namespace and scope on `ir_records`, but the `vector_index` subquery is uncorrelated and unfiltered, so SQLite groups the whole table before joining. `vector_index` carries namespace and scope columns and has no index on them.
- **Evidence.** `seam_runtime/retrieval_orchestrator/adapters.py:1448` — `    left join (`
- **Failure scenario.** Measured with one namespace held constant at 200 records while others grew: 3.5 ms at 200 total records, 21.1 ms at 20,200, 88.4 ms at 80,200 — a 25x slowdown on an unchanged slice caused entirely by other tenants. The plan shows `MATERIALIZE v`, a full `SCAN vector_index`, and an `AUTOMATIC COVERING INDEX`, which is SQLite reporting it had to build a throwaway index per query.
- **Why here in the order.** No correctness impact, but it sets the hosted SLO by the largest neighbour, and the fix is local to one query plus one index.
- **Resolution.** Push the boundary predicate into the subquery or correlate it on the outer row, and add a `(namespace, scope)` index. `knowledge_node_vectors` already has exactly this index, so the pattern is established.
- **How to verify the fix.** Re-run the growth measurement and assert the constant slice stays flat.

**F-13 — MEDIUM · pgvector builds HNSW indexes its own query cannot use, then reports `ok`**

- **What is wrong.** The index is on the expression `(embedding)::vector(N)`; the query orders by the bare `embedding` column, so the planner never uses it. The adapter then sets its status unconditionally.
- **Evidence.** `seam_runtime/vector_adapters.py:481` — `                        order by embedding <=> %s::vector`
- **Failure scenario.** Read-only `EXPLAIN` against the live 152,152-row table shows the adapter's SQL producing a Bitmap Heap Scan plus Sort, while the same query rewritten to match the index expression produces `Index Scan using seam_vector_index_hnsw_384_idx`. Every recall pays a full boundary scan and top-k sort, ingest pays the ANN write cost on every insert, and `ann_index_status` says `"ok"` so nobody looks.
- **Why here in the order.** It must be fixed together with F-29, because the fix converts exact search into approximate search and can silently change results.
- **Resolution.** Order by the indexed expression with the dimension bound from the model, make the dimension a literal so the partial-index predicate is provable, and set the status from an `EXPLAIN` assertion rather than from `create index` returning.
- **How to verify the fix.** An `EXPLAIN` test asserting the HNSW index appears in the plan, plus the F-29 parity test.

**F-14 — MEDIUM · A failed write silently terminates a bound read snapshot**

- **What is wrong.** The pool hands the bound snapshot connection to every caller including write paths, and a write path's error handler rolls back — ending the snapshot's own transaction. The snapshot authorizer denies DML but deliberately not transaction control, unlike the migration spine's authorizer, which denies exactly that.
- **Evidence.** `seam_runtime/pool.py:201` — `        connection = active_connection(self._snapshot_key)`
- **Failure scenario.** Reproduced: inside a bound snapshot, a `persist_ir` call fails validation before any DML, its handler rolls back, and the snapshot ends — `in_transaction` goes `True` to `False` with nothing reported. Later retrieval legs then read per-statement, so a merged candidate set can span two committed states and `candidate_set_sha256` attests a set that never existed. The docstring states this is impossible.
- **Why here in the order.** It undermines the fingerprint guarantee the reasoning ledger rests on, and the fix is additive to an existing deny list.
- **Resolution.** Add the transaction and savepoint action codes to the snapshot's denied set, and have the pool refuse rather than yield the bound connection to a caller that drives the transaction.
- **How to verify the fix.** Re-run the probe and assert the snapshot survives a failed write.

**F-15 — MEDIUM · `/chat` allowlist is bypassed by any caller-supplied host that resolves to loopback**

- **What is wrong.** The loopback branch admits an arbitrary attacker-owned hostname. The docstring justifies skipping rebinding defence on the grounds that the host must be a name the attacker does not control — true for the allowlist branch, false for this one.
- **Evidence.** `seam_runtime/server.py:511` — `    if host.lower() not in allowed and not is_loopback_host:`
- **Failure scenario.** With resolution patched so an attacker-owned name returns `127.0.0.1`, validation accepted a host that is in neither the built-in set nor the operator allowlist; the control case resolving to a public address was rejected. A TTL-0 record answering loopback for validation and an internal address for the connection inside `urlopen` yields blind SSRF with a fully attacker-chosen JSON body. Read-back is correctly closed — loopback targets reduce provider errors to status only and never forward a credential — so this is probe-and-write, not exfiltration.
- **Why here in the order.** It is a narrowing of one condition with no design decision, and it is independent of the other security items.
- **Resolution.** Require the hostname itself to be `127.0.0.1`, `::1`, or `localhost` for the local-provider allowance, or pin the validated address and connect to it directly so validation and connection share one resolution.
- **How to verify the fix.** Re-run the patched-resolution probe and assert rejection.

**F-16 — MEDIUM · The dashboard static mount is served with no authentication and no rate limiting**

- **What is wrong.** The mount sits outside both the bearer guard and the limiter, and the served directory is operator-controlled with no containment check beyond the presence of a `dashboard.html`.
- **Evidence.** `seam_runtime/server.py:412` — `    app.mount("/", StaticFiles(directory=str(directory)), name="webui")`
- **Failure scenario.** With a token configured and a 3/min limit, unauthenticated `GET /`, `/dashboard.html`, and `/seam-api.js` all returned 200 while `/stats` returned 401; eight unauthenticated asset requests returned 200 each while eight `/health` requests returned 429. An operator who sets a token reasonably believes the surface is authenticated. Traversal is correctly blocked and API routes are not shadowed, so the exposure is asset disclosure and an unmetered request sink.
- **Why here in the order.** Same file and same middleware review as F-9 and F-15.
- **Resolution.** Put the mount behind the limiter and, when a token is set, behind the guard; separately resolve the directory override and log the resolved path at startup.
- **How to verify the fix.** Repeat the unauthenticated asset requests and assert 401 or 429.

**F-17 — MEDIUM · The TUI chat client sends the provider key to an unvalidated base URL with no response cap**

- **What is wrong.** A configured base URL reaches the HTTP post verbatim with a bearer credential attached, bypassing all four protections the REST path applies.
- **Evidence.** `seam_runtime/dashboard.py:304` — `            response = httpx.post(`
- **Failure scenario.** A mistyped, suggested, or settings-file-injected chat base URL sends the operator's provider key to that host on the first message. None of the host allowlist, the resolved-address check, the redirect refusal, or the response cap applies here. One correction to the prior audit's version of this finding: the client library does not follow redirects by default, so that half does not apply — the allowlist gap and the missing cap do.
- **Why here in the order.** Its root cause is the duplicated provider client, so it is cheapest to fix while F-15 is open in the REST one.
- **Resolution.** Call the REST path's validator from the TUI client and apply the same response-size contract; better, extract one shared provider client.
- **How to verify the fix.** Set a non-allowlisted base URL and assert the client refuses before sending.

**F-18 — MEDIUM · `/v1` tenancy is caller-asserted whenever principal mode is off**

- **What is wrong.** With no token and no principal resolver the guard authorises the request and returns nothing, leaving namespace and scope as body fields with no caller binding. The mechanism for the safe mode exists and is correct; the safe mode is opt-in.
- **Evidence.** `seam_runtime/server.py:936` — `        enforce_rate_limit(request, _client_key(request, authorization))`
- **Failure scenario.** In the default configuration, unauthenticated reads returned 200 across the private surface and public routes accept caller-chosen tenancy labels. `main` widens this: it registers four new agent-turn routes unconditionally rather than inside the principal-mode block, and one of them persists memory — so the blast radius grows from reads to writes keyed on a caller-asserted handle. Documented as correct for single-user self-host; wrong for anything hosted.
- **Why here in the order.** This is the declared S6/S8 track, not a repair — it is listed so the audit's picture of the boundary is complete.
- **Resolution.** Make principal mode the default whenever the bind is non-loopback; the safety validator already knows the bind.
- **How to verify the fix.** Start with a non-loopback host and no principal configuration and assert startup refuses.

**F-19 — MEDIUM · Temporal comparison is done three different wrong ways**

- **What is wrong.** Three separate defects share one root: there is no canonical timestamp parser. The graph compares ISO strings as text with no validation of the requested horizon; the shared parser cannot read the repository's own canonical timestamp format, silently zeroing the temporal channel; and naive/aware mixing classifies future validity intervals as stale.
- **Evidence.** `seam_runtime/reconcile.py:176` — `def _event_time(record: MIRLRecord) -> datetime | None:` — this is the one timestamp reader in the repository that is fully correct, and the template the other three should adopt.
- **Failure scenario.** Mixed timestamp formats misorder time-qualified graph queries; a record whose `t0` came from the canonical generator contributes nothing to temporal retrieval while appearing to work; and an interval that begins in the future is reported stale today.
- **Why here in the order.** One shared resolution retires three findings, and it is cheap.
- **Resolution.** Extract `_event_time`'s logic into a single module-level parser and route the graph, the retrieval flag loader, and the interval classifier through it. Validate the requested horizon on entry.
- **How to verify the fix.** Round-trip every writer's `t0` literal through the shared parser and assert none returns `None`.

**F-20 — MEDIUM · `search_top_k` and `context_budget` cannot be set through the flag contract**

- **What is wrong.** The coercion helper returns nothing for these keys, so the loader drops them — including valid values.
- **Evidence.** `seam_runtime/retrieval.py:509` — `            if coerced is None:` — the loader's drop, reached whenever `coerce_flag_value` returns nothing for these two keys.
- **Failure scenario.** A persisted flag row setting `search_top_k` to 100 is silently discarded, so a tuned retrieval profile has no effect and nothing reports it. This also removed a prior finding's symptom — a negative value used to kill all retrieval — but by a mechanism that is itself the defect.
- **Why here in the order.** It sits with F-23 and F-28 in the flag-contract cluster; fix them together.
- **Resolution.** Give both keys explicit coercion with range validation, and make an out-of-range persisted value a logged rejection rather than a silent drop.
- **How to verify the fix.** Persist a valid value, reload, and assert the resolved flags contain it.

**F-21 — MEDIUM · The structured-score gate contradicts its own comment and drops boundary records**

- **What is wrong.** The gate excludes records whose score equals the boundary value, while the adjacent comment describes inclusive behaviour.
- **Evidence.** `seam_runtime/retrieval_orchestrator/adapters.py:1429` — `            f"and (lexical_hits > 0 or structured_score >= {structured_gate})"` — with the gate resolving to 1.0 whenever graph kinds are included (`:1425-1427`), against the comment at `:1418` claiming the boundary filters alone retain the non-lexical tail.
- **Failure scenario.** A record scoring exactly at the gate is silently absent from the candidate set; empirically reproduced, and byte-identical on `main`.
- **Why here in the order.** Independent one-line fix in the same file as F-12 and F-22.
- **Resolution.** Make the comparison inclusive to match the documented contract, or correct the comment and the contract to match the code — the two must agree.
- **How to verify the fix.** A boundary-valued record appears in the candidate set.

**F-22 — MEDIUM · Two RRF engines disagree on rank base**

- **What is wrong.** One path treats ranks as 0-based and the other as 1-based, so the same candidate set fuses to different scores depending on which engine ran.
- **Evidence.** `seam_runtime/retrieval.py:616` — `            rrf[record.id] += 1.0 / (k + rank)` — 0-based, against `seam_runtime/retrieval_orchestrator/merger.py:46` — `        for rank, hit in enumerate(ranked_leg, start=1):` — 1-based.
- **Failure scenario.** A legacy-weighted policy is converted to RRF with a mismatched base, so scores are not comparable across the two engines and a recorded fingerprint may not reproduce.
- **Why here in the order.** Same fusion review as F-21; both are in the ranking contract.
- **Resolution.** Pick one base, assert it in the fusion contract, and add a test that the two engines agree on a shared fixture.
- **How to verify the fix.** Fuse one fixture through both paths and assert identical scores.

**F-23 — MEDIUM · One approved retrieval flag resolves three different ways**

- **What is wrong.** Runtime, MCP, and SDK each resolve the same approved flag differently, so the applied policy depends on which surface the caller used.
- **Evidence.** `seam_runtime/mcp.py:416` — `        orchestrator = RetrievalOrchestrator(runtime)`
- **Failure scenario.** A flag approved through the improvement loop takes effect on one surface and not another, so a validated lever silently does not ship — the exact failure the "productize to core" rule exists to prevent. Unchanged on `main`.
- **Why here in the order.** Flag-contract cluster with F-20 and F-28; one resolution site fixes all three surfaces.
- **Resolution.** Resolve flags in exactly one place and have every surface call it.
- **How to verify the fix.** Assert the three surfaces produce identical resolved flags for one configuration.

**F-24 — MEDIUM · Unevidenced dispute edges demote verified claims**

- **What is wrong.** A dispute demotes a claim without requiring evidence, while promotion requires it — an asymmetry that lets an unevidenced assertion outrank a verified one.
- **Evidence.** `seam_runtime/knowledge_graph.py:3082` — `            trust_state = "contested"` — reached from `elif disputes:` at `:3081`, where `disputes` (`:3061`) is every `contradicts`/`refutes` edge, evidenced or not, while the promotion side builds a separate `verified_refutations` list at `:3054`.
- **Failure scenario.** An agent writes a dispute with no supporting record and a previously verified claim drops below the trust gate, disappearing from context assembly.
- **Why here in the order.** It needs a design decision about the trust model, so it should not block the mechanical fixes above.
- **Resolution.** Require dispute edges to carry evidence references at the same standard as promotion, or weight unevidenced disputes below evidenced claims.
- **How to verify the fix.** An unevidenced dispute leaves the claim's trust state unchanged.

**F-25 — MEDIUM · Reasoning-pattern result disagreement is silently and permanently dropped**

- **What is wrong.** When a distilled pattern's recorded outcome disagrees with the observed one, the disagreement is discarded rather than recorded.
- **Evidence.** `seam_runtime/reasoning_patterns.py:627` — `    if existing is not None:` — an existing result row short-circuits to a return of the stored `succeeded` value (`:632`), so a later disagreeing outcome is neither recorded nor surfaced.
- **Failure scenario.** A pattern that has stopped working keeps its success record, so the promotion gate continues to treat it as verified and the loop cannot learn from the failure.
- **Why here in the order.** Independent of the retrieval cluster; needed before the improvement loop is trusted to self-tune.
- **Resolution.** Record disagreements as explicit failure feedback on the pattern rather than dropping them.
- **How to verify the fix.** Force a disagreement and assert a failure record exists.

**F-26 — MEDIUM · `query_graph` returns edges whose endpoints it already filtered out**

- **What is wrong.** Node re-filtering drops endpoints without pruning the edges that referenced them.
- **Evidence.** `seam_runtime/knowledge_graph.py:1711` — `    edges = [*(_edge_payload(row) for row in edge_by_id.values()), *provenance_edges]` — every collected edge is emitted, with no membership test against the `selected` node set built at `:1638`.
- **Failure scenario.** A time- or trust-filtered graph query returns edges pointing at ids absent from the returned node set, so any consumer that resolves endpoints hits a missing key.
- **Why here in the order.** Same module and same review as F-19's graph half.
- **Resolution.** Prune edges whose endpoints did not survive the node filter, or return the filtered endpoints as explicit tombstones.
- **How to verify the fix.** Assert every returned edge's endpoints are a subset of the returned node ids.

**F-27 — MEDIUM · Compatibility and temporal retrieval load the entire namespace into memory**

- **What is wrong.** These paths read the whole boundary rather than a bounded page, and the ordering column is unindexed.
- **Evidence.** `seam_runtime/storage.py:951` — `                order by updated_at desc, id`
- **Failure scenario.** A namespace that grows past memory turns a single query into a full materialisation plus a temp b-tree sort.
- **Why here in the order.** Same scaling class as F-12 and measurable with the same harness.
- **Resolution.** Keyset-paginate both paths and add the supporting index if measurement warrants it.
- **How to verify the fix.** Measure the query against a growing namespace and assert flat cost.

**F-28 — MEDIUM · Retrieval flags are cached for the whole process lifetime**

- **What is wrong.** The cache has no invalidation path, so an approved flag change is invisible to a running process.
- **Evidence.** `seam_runtime/runtime.py:1066` — `        for the process lifetime.`
- **Failure scenario.** An out-of-process apply lands a new policy; the running server and TUI keep serving the old one until restarted, with nothing reporting the divergence. `main` adds a refresh method and documents the cache as a deliberate stability guarantee, but nothing calls it outside one test.
- **Why here in the order.** Completes the flag-contract cluster with F-20 and F-23.
- **Resolution.** Call the refresh path on an apply signal, or key the cache on the persisted flag generation so a change invalidates it.
- **How to verify the fix.** Apply a flag out of process and assert the running runtime picks it up.

**F-29 — MEDIUM · pgvector's `limit` cut has no tie-break while SQLite's does**

- **What is wrong.** SQLite's heap admission breaks ties on record id; the pgvector query has no secondary sort key, so on tied embeddings the two backends can select different sets.
- **Evidence.** `seam_runtime/vector.py:418` — `                item = (score, row["record_id"])`
- **Failure scenario.** Exact ties are real in production data — a single boundary slice in the live store holds 2,012 rows sharing one identical embedding. Three forced plans returned the same result, so today's agreement is an accident of heap order rather than a guarantee; a `VACUUM FULL` or `CLUSTER` can change it. Marked PLAUSIBLE because settling it needs writes to a scratch pgvector instance.
- **Why here in the order.** It must land with F-13, because that fix makes pgvector approximate and would otherwise mask a set divergence as a ranking change.
- **Resolution.** Append `record_id` to the pgvector ordering and add a cross-backend parity test.
- **How to verify the fix.** Index one tied corpus into both adapters and diff the returned key sets.

**F-30 — MEDIUM · The KB forbids setting `HF_HUB_CACHE`; the environment sets it, and pytest gives no diagnostic**

- **What is wrong.** The repository's own knowledge base states the rule and records that breaking it already cost a run, yet five tracked documents still teach the forbidden form, and the test path has no diagnostic for the resulting failure.
- **Evidence.** `docs/kb/eval-methodology/locomo-mem0-harness.md:21` — `- **Do NOT set `HF_HUB_CACHE`.** The default `~/.cache/huggingface` holds`
- **Failure scenario.** Measured this session: the full suite returned 3,032 passed, 44 failed, 2 xfailed, 6 errors, 0 skipped in 383.62s, exit 1 — every failure a cascade from one offline embedding load. Re-running the same 14 files against the default cache with no code change returned 157 passed, exit 0, proving the cause environmental. The LoCoMo runner prints a precise diagnostic naming this exact cause, but the pytest path does not, so the failure surfaces as an opaque hub error with no pointer to the KB. Five documents under `docs/handoffs/` still instruct the superseded external path.
- **Why here in the order.** Cheap, and it removes a recurring false signal that makes every future suite run ambiguous.
- **Resolution.** Add a session-scoped pytest check that resolves the pinned revision and fails once with the KB's explanation, and correct or mark the stale handoff exports.
- **How to verify the fix.** Point the cache at a nonexistent path and assert one clear failure rather than fifty opaque ones.

**F-31 — MEDIUM · The no-deletion invariant is violated by the repository's own closeout tooling**

- **What is wrong.** The cross-index rebuild unlinks tracked archive chunks as a routine step, in a repository whose top invariant states that nothing is ever deleted by an agent anywhere.
- **Evidence.** `tools/streams/rebuild_cross_index.py:127` — `            stale.unlink()`
- **Failure scenario.** Observed live during this audit: `git status` showed a tracked archive chunk deleted from the working tree with an untracked replacement beside it, after a routine closeout. No content was lost — the replacement was a superset — and the state has since been committed over with all three chunks tracked. But the invariant established after a real data-destruction incident has no mechanical enforcement, and the documented closeout an agent is told to run deletes tracked repository content without the agent ever knowing.
- **Why here in the order.** It is a protocol-integrity fix, independent of all code findings, and cheap.
- **Resolution.** Have the rebuild move superseded chunks aside rather than unlink them, or exempt derived stream state explicitly in the invariant so the rule matches the tooling.
- **How to verify the fix.** Run the rebuild and assert `git status` shows no deletion of a tracked file.

**F-32 — MEDIUM · Untracked, non-ignored tool artifacts sit in the working tree**

- **What is wrong.** `.gitignore` covers one agent directory and not the others, so unrelated tooling drops committable material into a private repository.
- **Evidence.** `.gitignore:57` — `.claude/`
- **Failure scenario.** At the time of the sweep, 42 untracked non-ignored paths were present, including a 30 MB plugin build directory recreated by a session-start hook and 21 unrelated skill directories. A `git add -A` — a routine agent and operator move — commits all of it into a repository whose release gate exists because a database snapshot once leaked into another repository's history.
- **Why here in the order.** One-line fix, and it protects every later commit.
- **Resolution.** Extend `.gitignore` to the sibling agent/tool directories and the plugin build output.
- **How to verify the fix.** `git status --porcelain | grep '^??'` returns only intended paths.

**F-33 — MEDIUM · Worktree, branch, and PR hygiene has drifted from AGENTS.md's own rules**

- **What is wrong.** The repository states the rules and provides the scanner; the state does not match them.
- **Evidence.** `AGENTS.md:48` — `If you created a git worktree during the session: finish it.`
- **Failure scenario.** Eight extra worktrees are live; the repository's own scanner classifies 6 branches as safe to delete and 10 as stale with unique commits and no open PR, the oldest 37 days; 5 PRs are open, two of them drafts sitting well past the point where the rules require a recorded blocker. The next agent reads stale branches as active work.
- **Why here in the order.** Independent of everything else, and the scanner already produces the worklist.
- **Resolution.** Work the scanner's output: delete the merged set, resolve or record the stale set, and move each open PR into one of the four states the rules define.
- **How to verify the fix.** The scanner reports no DELETE-class branches and no unexplained stale ones.

**F-34 — MEDIUM · Secret scanners only inspect blobs new to a push, so history is never rescanned**

- **What is wrong.** Both release gates compute the set of objects new to a push and scan only those. Nothing rescans existing history, so anything committed before a rule existed stays indefinitely and no gate will ever report it.
- **Evidence.** `tools/security/secret_scan.py:188` — `def _new_blobs(` — the enumeration both release gates scan, computed as the objects reachable from the new head and not the old.
- **Failure scenario.** The security lane found a credential-shaped DSN string in history reachable from both the private repository and the frozen public mirror. It classified the value structurally without reading it out — three dictionary words, one repeated separator — and concluded a local-development placeholder, which is why this is not rated higher. But the coverage gap is the real finding: had a live credential been committed before the deny-list existed, no mechanism would notice.
- **Why here in the order.** The scan is additive and gives a clean baseline for everything after it.
- **Resolution.** Add a full-history scan mode using a single batched object walk, run it once to establish a baseline, and widen placeholder recognition so the gate can classify rather than leaving it to a human.
- **How to verify the fix.** The full-history scan runs to completion and reports a known, reviewed set.
- **Operator action.** Confirm whether any live pgvector instance uses that password. If one does, this escalates sharply, because the blob is reachable from the public mirror.

**F-35 — MEDIUM · Four declared dependency upper bounds are violated by the installed environment**

- **What is wrong.** The contract verifier compares the manifest against the requirements file and the extras list, never against what is installed, so the venv can drift past declared majors while the gate reports success.
- **Evidence.** `pyproject.toml:40` — `sbert = ["sentence-transformers>=2.0,<3.0"]`
- **Failure scenario.** The installed environment carries `sentence-transformers` 5.5.0, `openai` 2.37.0, `mem0ai` 2.0.2, and `zep-cloud` 3.22.0 against declared ceilings of 3.0, 2.0, 1.0, and 3.0 — three of them network clients handling API credentials. The code is being exercised against majors the project never qualified, and both `pip check` and the contract verifier report clean.
- **Why here in the order.** Independent, and it makes every other measurement in this repository reproducible.
- **Resolution.** Extend the contract verifier to check installed versions against the declared specifiers for every installed extra, then either qualify and raise the bounds or pin the venv back.
- **How to verify the fix.** The verifier fails on the current venv, then passes once reconciled.

### Verified LOW findings

The ten highest-leverage are listed. A further set of verified low-severity items
from the four lane reports is not itemised here.

| id | area | evidence | claim |
|---|---|---|---|
| L-1 | persistence | `seam_runtime/storage.py:672` | no index on `ir_records(status)`, `created_at`, or `updated_at`; stats runs three unindexed full counts |
| L-2 | persistence | `seam_runtime/lifecycle.py:836` | scoped delete expands up to 10,000 ids into three unchunked `IN (...)` lists; every other bulk path chunks at 400–500 |
| L-3 | persistence | `seam_runtime/runtime.py:133` | lock exhaustion surfaces as a bare builtin `TimeoutError` out of the public API, unmappable to a retry class |
| L-4 | security | `seam_runtime/mcp.py:219` | legacy MCP stdio bridge reads unbounded lines; the modern path was fixed and this one was not. Same file prints full tracebacks to stderr |
| L-5 | security | `seam_runtime/config.py:535` | settings values are written unescaped, so a pasted newline injects arbitrary settings lines, including shell-enable and insecure-bind flags |
| L-6 | security | `seam_runtime/config.py:501` | the settings file's 0600 mode is enforced on write and never checked on read |
| L-7 | security | `seam_runtime/qualification.py:38` | the secret-option regex misses dotted separators, and the check runs only on external lanes |
| L-8 | ci | `ci.yml:38` | actions are pinned by mutable tag rather than commit SHA, on runners that are the operator's own machine |
| L-9 | security | negative check: a search for `X-Frame-Options`, `Content-Security-Policy`, `X-Content-Type-Options` and `Strict-Transport` across the server and the dashboard returns no match | no framing, CSP, or nosniff header is set on any response, including the static mount of F-16; the only headers set anywhere are the SSE headers and the 429 `Retry-After` |
| L-10 | protocol | `PROJECT_STATUS.md:117` | a status verifier exists that no gate, hook, checklist, or CI job runs; and the audit-claim gate is red at HEAD on pre-existing issues it can no longer re-flag |

## 4. Health dashboard

```
migration spine  █████████░  strong — 5/5 CODE_LAYOUT claims verified; resume, backup,
                                      integrity gating and re-entrancy all proven by probe
protocol/gates   █████████░  strong — 6/6 continuity gates exit 0; registry 28/28; 0 import cycles
concurrency      ████████░░  strong — WAL+FULL+FK+busy_timeout; pool cannot leak a transaction;
                                      cross-process lock verified with two live processes
persistence      █████░░░░░  fair   — spine sound, but delete/restore/ingest carry 3 CRITICAL + 2 HIGH
retrieval        █████░░░░░  fair   — fusion primitives and plan validation clean; 13 contract defects
security         █████░░░░░  fair   — no SQLi, no unsafe deserialization, strong outbound guard in
                                      jspace; 1 HIGH + 5 MEDIUM reachable, 1 limiter bypass reproduced
tests & CI       ██████░░░░  fair   — 3,032 passing, 0 skipped, strict-no-skip real; PR jobs run
                                      untrusted code on the operator's box
docs & drift     ████████░░  strong — main's status router current; CODE_LAYOUT paths all real;
                                      README commands all parse; 5 stale handoff exports
operator surface ██░░░░░░░░  weak   — the shipped WebUI stores provider keys in localStorage and
                                      fabricates credential, persistence and benchmark results
```

Not audited: `seam_runtime/webui/tweaks-panel.jsx`, the `main`-only agent-turn
module beyond a structural read, and the uncommitted-at-the-time TUI modules,
which carry 16 `except Exception: pass` blocks and want their own pass.

## 5. Watch list

| signal | threshold that means it has become a problem | where it surfaces first |
|---|---|---|
| `vector_index` row count across all namespaces | any single-namespace recall exceeding its own p95 while its slice is unchanged | REST `/v1/memories/recall` latency |
| pgvector duplicate-embedding group size | a tie group larger than a typical `limit` in a slice served by both backends | a backend-parity diff, not an error |
| `storage.py` method count (145 now, 140 at the prior audit) | any increase without a corresponding extraction | the next audit rediscovering storage bugs through other lanes |
| `RetrievalOrchestrator` construction sites (11 now, 6 at the prior audit) | a twelfth site copying defaults again | a flag that ships on one surface and not another |
| branch count with unique commits and no open PR (10 now) | any branch older than the prior audit's oldest | an agent resuming work that was already superseded |
| interpreter skew between the commit hook and the venv | any gate behaving differently under the two | a local gate passing where CI fails |

## 6. Going unnoticed

- **The verification apparatus checks its own internal consistency, not its correspondence to the tree.** Seven gates pass while `HISTORY.md` at the audited commit referenced seven files that did not exist in that tree, the handoff registry's head was twelve entries behind its own history, and three entries existed in no ref at all. No gate reads a `refs:` field and asks whether the file is there. The chain is auditable against itself and unanchored to reality.
- **Deletion is the guarantee with the least test coverage and the most surface.** Three of the four lanes independently found a path where deleted content survives, in three different subsystems. There is no single "is this record gone" assertion that every read path is tested against.
- **The webui is 7,479 lines, ships in the wheel, is served at `/`, and had never been read by an audit.** The first pass over it produced two HIGH findings. The prior audit named this blind spot explicitly and it stayed unread for another seventeen days — which is the actual finding: a named blind spot that survives being named.
- **The god object and the duplication are both getting worse between audits, despite three audits naming them.** `storage.py` went from 140 methods to 145; engine construction sites went from 6 to 11. Naming a structural problem in an audit has not, so far, been sufficient to stop it growing.
- **`main` is healthier than the tree anyone is working in.** The status router on `main` is current, the S8 slice fixes three defects this audit found, and the branch under development is 13 commits behind it. The audit's single highest-leverage action is a merge, not a patch — which suggests the branch discipline, not the code, is the constraint.
- **The competitive claim rests on evidence with no verified redundancy.** The publication policy requires bundle hashes, per-case hashes, and run records as the warrant for every benchmark statement, and the record directory is configured to a path that no longer exists. The guard built after an earlier scare correctly refuses to write there — so the failure is loud, and the existing records' redundancy is still unestablished.

## 7. Verifications performed

- [x] `PYTHONPATH=. .venv/bin/python -m pytest` with the live pgvector lane — **3,032 passed, 44 failed, 2 xfailed, 6 errors, 0 skipped** in 383.62s, exit 1
- [x] Same 14 files re-run against the default embedding cache, no code change — **157 passed** in 115.10s, exit 0, proving all 50 failures environmental
- [x] `verify_integrity` · `verify_routing` · `verify_handoffs` · `verify_continuity` · `verify_streams` — all exit 0 at both audited commits
- [x] `verify_wiki` — exit 0, 234 active pages reachable
- [x] `verify_audit_claims` over all of `docs/audits` — **exit 1, 9 pre-existing issues across 28 documents**, including a tally mismatch in the 2026-08-12 audit that the `--changed-since HEAD` scoping can no longer re-flag
- [x] Rate-limiter bypass reproduced independently by the orchestrator — fixed bearer `[401,401,401,429,429,429,429,429]`, rotating bearer `[401×8]`
- [x] Two-process cross-process lock test — B blocked 4.014s and acquired the instant A released; both processes derived the same lock path
- [x] 60-second lock bound — 75-second holder produced `TimeoutError`, exit 1
- [x] Restore with a live runtime — 300 committed rows plus one post-restore commit lost; `integrity_check: ['ok']`
- [x] Crash window between file swap and sidecar unlink — restore fully reverted; `integrity_check: ['ok']`
- [x] `ingest_text` third-commit failure — content live and retrievable with a tombstoned ledger row
- [x] Write inside a bound read snapshot — write refused, snapshot silently terminated
- [x] Corrupt-database opens (truncated, zeroed, garbage, newer schema, tampered registry) — **fail-closed on all**; empty correctly initialises
- [x] Migration re-entrancy — second and third opens applied 0 steps and took no backup
- [x] Full-table canary scan after a scoped delete — 9 tables retained the deleted content
- [x] Read-only `EXPLAIN` against the live 152,152-row pgvector table — adapter SQL produces Bitmap Heap Scan + Sort; the index-matching rewrite produces an HNSW Index Scan
- [x] Namespace-growth measurement — 3.5 → 21.1 → 88.4 ms for a constant 200-record slice
- [x] `tools.security.secret_scan --working-tree` — exit 0, 10 declared policy exclusions
- [x] `tools.release.verify_public_safe` against the public mirror head — 1,692 blocking findings, **zero** secret-shaped and zero deny-path
- [x] `tools.git.scan_stale_branches` — 6 DELETE-class, 10 stale with unique commits, 8 open-PR-backed
- [x] Import-graph analysis over `seam_runtime/` — **0 real import-time cycles**; 5 masked by lazy imports
- [x] 12 README CLI commands — all parse
- [x] Every path named in `docs/CODE_LAYOUT.md` — all exist; `experimental/`, `public_pkg/`, `selfhost/` confirmed absent as claimed
- [x] `docs/audits` registry — 28 files, 28 rows, zero unregistered
- [x] Citation spot-check — 18 orchestrator citations re-read line-by-line, 16 exact, **2 off by one and corrected**, both corrections re-verified; 13 further lane citations re-read and all exact
- [x] Citation EOF validation across all four lane reports — 344 references checked, 318 resolved in range, the remainder resolvable by basename or naming a `main`-only file that is deliberately not cited here
- [x] Secret scan of this document — no key, token, password, DSN, or session URL present; one history finding reported by location and kind only
**Phase 4 self-gate on this document:**

- [x] `verify_audit_claims --docs docs/audits/2026-08-29-full-repo-audit.md` — **exit 0**, 47 citations, 45 labelled findings, 0 issues; the labelled counts match the tally stated in the verdict
- [x] Citation self-check — 9 citations in this document named a line that did not itself demonstrate the defect (a docstring, a blank line, a parameter name, a status filter standing in for a score gate). All 9 were repointed to the true evidence line and each replacement was re-read and quoted before filing. No finding was dropped, and no line number was adjusted to make a citation fit
- [x] `tools.security.secret_scan --working-tree` — exit 0, 10 declared binary/hash-pinned exclusions
- [x] Targeted secret scan of this document for key, bearer, credential-bearing DSN, and provider session-URL shapes — no match
- [ ] Branded render — **not performed**; this repository defines no audit-profile document under docs/ and no branding step for audit documents, and no prior report in `docs/audits` carries one

- [ ] pgvector/SQLite tie-set parity — **not run**; requires writes to a scratch pgvector instance. Would settle F-29
- [ ] Principal-mode limiter behaviour under load — **not run**; requires an injected resolver, a public-ID key, and an explicit worker topology. Would settle whether the three-budget design behaves as documented
- [ ] Real power-loss crash-consistency of the migration spine — **not run**; design and injected-failure coverage verified instead
- [ ] `tweaks-panel.jsx` — **not read**; served by the same unauthenticated mount as F-16
- [ ] Whether the history credential string is live — **not determinable by an agent**; deliberately not read under the no-secrets rule

## 8. The next step

Merge `origin/main` into the working branch. It is 13 commits behind, and the
merge retires the audit's only correctness HIGH along with two MEDIUMs outright —
without a single line of new code — while rebasing every remaining retrieval
finding onto the tree that actually ships. Doing it first means the delete-cluster
work (F-2, F-3, F-11), which is the real fix this audit is asking for, lands once
on the tree that will carry it, instead of twice.

## Evidence manifest

Raw artifacts: none

Every claim in this report cites tracked repository evidence at the audited
commits, or the verbatim output of a command recorded in section 7.

- Provider/model calls: none. No paid answerer, judge, or comparator ran.
- External comparator calls: none.
- Benchmark bundles produced: none. The suite runs recorded in section 7 are
  test executions, not sealed benchmark bundles, and make no scoring claim.
- Probe artifacts: the persistence lane's scratch databases and probe scripts
  were written under a temporary directory outside the repository and are not
  durable evidence; each probe's actual output is quoted inline in section 7
  and in the finding that rests on it.
- Live services touched: the local pgvector container was read only
  (`SELECT` and `EXPLAIN`, no DDL, no DML, no `ANALYZE`); its DSN is not recorded
  here or anywhere in this document.
- Credentials: none recorded. One credential-shaped string found in git
  history is reported in F-34 by location and kind only; its value was
  deliberately not read and does not appear in this document.
- Repository writes: this document only. No source, test, doc, configuration,
  HISTORY.md, or registry file was modified while the audit ran.
