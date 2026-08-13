# SEAM Full-Repository Audit — 2026-08-12

**Scope:** whole-repository health audit. **Repository:** `BlackhatShiftey/Seam`.
**Observed main:** `f5d304c` (HISTORY#559). **Method:** six read-only audit lanes
(architecture, correctness, persistence, security, tests/CI, doc/state drift),
two respawned correctness lanes (reasoning subsystem; context/trust subsystem),
a bounded HISTORY.md timeline extraction (7 lanes), 17 adversarial verification
agents, 2 citation spot-check lanes (20 findings, all confirmed), one empirical
SQLite locking probe, and one full test-suite run. Companion document:
[complete project timeline](2026-08-12-seam-complete-timeline.md).

---

## 1. Verdict

SEAM is in its best measured state in two audits, with one honest caveat. All
four critical/high reproducers carried over from the prior audits are verified
fixed in code by three independent lanes (persist entity race, `/chat` env-var
exfiltration, `/docs` route bypass, trust-timestamp fallback), and no new
CRITICAL or HIGH runtime defect was found. The suite is green and growing
(2,382 passed / 0 skipped / 2 xfailed in 256s, live pgvector lane). But the
audit found **fifteen MEDIUM findings** — eleven in the runtime and four in the
documentation layer — plus a long LOW tail from subsystems (reasoning graph,
context assembly, trust derivation) that no prior audit ever read. The
documentation layer had materially drifted from the code: the campaign header
pointed S6 at a superseded build base, and the status router carried stale
counts, stale claims, and a continuity failure (`verify_continuity` exit 1 at
HEAD). This audit repairs the documentation drift and records the runtime
findings for the next slice; it changes no runtime code.

The strongest single cluster is **loopback trust**: `/chat` reads provider
responses unbounded, the TUI chat client skips the host allowlist the REST
server enforces, and REST `/persist` accepts caller-supplied record ids into an
`insert or replace`. The strongest single inconsistency is the **applied
retrieval policy**: one H2-approved flag resolves three different ways across
runtime, MCP, and SDK, and the resolved flags are cached for the process
lifetime. None of these is reachable without a bearer token or local access;
none is a data-loss or exfiltration primitive by itself — but together they
mean a hosted deployment of the current tree would be one misconfiguration away
from real incidents, which is exactly the gap S6 exists to close.

## 2. System map (as found)

```
                CLI ── TUI ── REST /v1 ── REST /persist,/chat ── MCP ── SDK
                 │      │ [!A]     │           │ [!B][!C]      │ [!D]  │ [!E]
                 └──────┴──────────┴─────┬─────┴───────────────┴───────┘
                                         │  SeamRuntime
                                         │  [!F] _retrieval_flags_cached (process lifetime)
                                   RetrievalOrchestrator
                                         │
              ┌──────────────────────────┼───────────────────────────┐
              │ [!G] SQL leg            │ [!H] planner/fusion        │ [!I] graph leg
              │  ORDER BY updated_at    │  legacy-weighted/1 → rrf   │  _graph_episode_rows
              │  structured gate 1.0    │  0-based vs 1-based ranks  │  ~40k bind vars
              └──────────────────────────┼───────────────────────────┘
                                         │  storage.py (god object)
                    ┌────────────────────┼───────────────────────┐
                    │ [!J] outbox replay │ [!K] trust derivation │ [!L] reasoning
                    │  re-embeds soft-   │  dispute demotes       │  silent result drop
                    │  deleted records   │  verified claims       │  (append-only, permanent)
                    └────────────────────┴───────────────────────┘

[!A] TUI chat client: no host allowlist (MED)         [!G] tie-break / gate (MED)
[!B] /persist caller ids + INSERT OR REPLACE (MED)   [!H] RRF rank-base split (MED)
[!C] /chat unbounded resp.read() (MED)               [!I] IN expansion (MED)
[!D] MCP hard-False policy surface (MED)             [!J] soft-delete replay (MED)
[!E] SDK hard-True policy surface (MED)              [!K] contested asymmetry (MED)
[!F] flags cache (MED)                               [!L] pattern stats (MED)
```

## 3. Findings (resolution order)

### 3.1 Documentation layer — fixed by this entry

**F-1 — HIGH · docs/roadmap/MEMORY_GUARANTEES_CAMPAIGN.md:5-10**
*What is wrong.* The campaign header states "Latest evidence: S4 … at
`main@ea4e46e`" and "S6 … must be built on `main@ea4e46e`", while the same
file's S5 section (`:292-294`) records S5 published at `main@19b3a76` and S6
depending on "S2 and S5". The two build-base claims contradict each other and
the wrong one is the header, which is what an operator reads first.
*Failure scenario.* The next S6 slice is started from `ea4e46e` (S4) instead of
the published S5 head, silently discarding the snapshot/pool/outbox stage.
*Why here.* Documentation that directs the next build step is the highest-value
thing to be wrong. *Resolution.* Header corrected in this entry.
*How to verify.* `rg "ea4e46e" docs/roadmap/MEMORY_GUARANTEES_CAMPAIGN.md`
returns only S4's own historical record.

**F-2 — MED · PROJECT_STATUS.md:12-18,64-65 · docs/status/operations.md:65-66,96-103**
*What is wrong.* Status router drift: headline pinned to `19b3a76`/HISTORY#533
while HEAD is `f5d304c`; suite count stale (2028 → 2382); "Audit findings 7-10
and 12 remain open" is false (7/9/10 closed, 8 partial); the S6 bullet claims
the tenancy decision "is written down nowhere" and `/v1` has "zero HTTP-level
tests" — both false since 2026-08-05.
*Failure scenario.* A resuming operator re-derives a closed decision or starts
from a stale count; per the file's own router contract it must not be an
archive. *Why here.* Cheap to fix, expensive to leave wrong.
*Resolution.* All corrected in this entry. *How to verify.* `git show` this
entry's diff; `rg "2028 passed" docs/` returns nothing.

**F-3 — MED · handoff head · docs/handoffs/INDEX.md:3,20**
*What is wrong.* Handoff head is `2026-08-05-tui-rebuild-canticle` whose
"Remaining work" begins "PR #203 … must merge first" — merged weeks ago; no
handoff exists for #538-#559.
*Failure scenario.* Handoff-following agents re-tread closed work.
*Resolution.* New handoff registered in this entry; predecessor marked
superseded. *How to verify.* `python -m tools.history.verify_handoffs`.

**F-4 — MED · protocol continuity · tools.history snapshot**
*What is wrong.* `verify_continuity` exits 1 at HEAD: latest snapshot
(2026-08-11) predates HISTORY#559 (2026-08-12) — #559 was committed without a
snapshot.
*Failure scenario.* The continuity gate that exists precisely to catch this
rot had been red at HEAD. *Resolution.* This entry's closeout snapshot
re-anchors the chain. *How to verify.* `verify_continuity` exit 0.

### 3.2 Runtime MEDIUMs — recorded for the next slice

**F-5 — MED · /chat unbounded response buffering**
`seam_runtime/server.py:518,526` (`resp.read()` with no cap, both provider
branches) → `_persist_chat_turn` `:1207-1217` compiles and persists the full
reply to SQLite. `/chat/stream` `:1409-1470` uses the same buffered read; the
SSE chunking only re-slices the already-buffered string. Loopback `base_url`
is deliberately allowed (`:367-415`) and the only size guard in the file caps
inbound *request* bodies (`:222-246`) — the wrong direction.
*Failure scenario.* A rogue service bound to 127.0.0.1 answers 200 with a
multi-gigabyte JSON body; server RAM fills, then `compile_nl` + `persist_ir`
push it into SQLite — OOM/disk exhaustion. The 60s timeout is no mitigation on
loopback.
*Resolution.* Cap provider response reads (e.g. Content-Length check + bounded
read) on both /chat paths. *How to verify.* A loopback stub returning >N bytes
must yield a 502 with status-only detail, and nothing persisted.

**F-6 — MED · REST /persist trusts caller-supplied record ids**
`server.py:1104-1109` passes body records into `IRBatch.from_json`;
`mirl.py:111-135` takes `id`, `ns`, `scope`, `created_at` verbatim from the
caller; `storage.py:1071-1076` writes via `insert or replace` keyed on that id.
The only guard blocks a `kind` change (`storage.py:1009-1020`).
*Failure scenario.* A token holder reads existing ids via `/search` or `/trace`,
then POSTs a same-kind record reusing a victim id with forged
`prov`/`evidence`/`attrs` — the genuine row is silently replaced and the forged
payload reprojects into graph/vector state with fabricated provenance.
*Resolution.* Enforce id ownership/format and refuse overwrite of existing ids
on the REST surface (upsert stays available to the internal SDK/store path).
*How to verify.* POST /persist reusing an existing id returns 409 and the
original row is byte-identical.

**F-7 — MED · applied retrieval policy resolves three ways**
Canonical source: `retrieval.py:483-513` (`retrieval_flag_state` table). Only
`Runtime.retrieve()` consults it (`runtime.py:945-955`). MCP `seam_retrieve`
(`mcp.py:403-425`) never passes the flag → orchestrator default `False`
(`orchestrator.py:387`). SDK hard-codes `True` (`sdk.py:343`; also
`seam_mem0_server.py:528`).
*Failure scenario.* The H2 loop applies `graph_semantic_seeds=N`; runtime
queries honor it, MCP queries silently run unseeded, SDK queries stay seeded
even under policy `0` — two surfaces diverge from policy in opposite
directions, and benchmark numbers stop meaning the same thing per surface.
*Resolution.* One resolution function (runtime's) consumed by all three
surfaces; MCP/SDK default to "policy" rather than a literal.
*How to verify.* Apply a flag, query all three surfaces, assert identical
resolved policy in each trace.

**F-8 — MED · process-lifetime retrieval-flags cache**
`runtime.py:905-918` memoizes flags with the literal comment "cache … for the
process lifetime"; `seam improve apply` writes `retrieval_flag_state`
(`storage.py:4668-4686`) from a separate process; no invalidation path exists.
*Failure scenario.* An operator applies an approved H2 proposal while
`seam serve`/TUI is running — every subsequent query keeps the pre-apply flags
until restart, so apply looks like a no-op and the applied state is never
exercised.
*Resolution.* Version the flag table (e.g. monotonic `applied_at`) and re-read
when the cached copy's version goes stale — cheap per-query check.
*How to verify.* Apply while serving; next query's trace shows the new flags
without restart.

**F-9 — MED · unbounded SQL IN expansion (`_graph_episode_rows`)**
`knowledge_graph.py:2613-2660` builds placeholders from unbounded
`seed_episode_ids`/`node_ids`/`edge_ids`; `query_graph` accumulates
`edge_by_id` across hops (`:1530` → `:1621`, up to `max(limit*8, 200)` per hop),
so `limit=1000, hops=5` on a hub-heavy graph yields **~40,000 bind variables**
in one statement — above even the 32,766 ceiling on SQLite ≥ 3.32; the default
`limit=300` path (~12k) is fatal on the 999-variable default (Debian 10,
RHEL/CentOS 7-8, Amazon Linux 2). The 400-chunk exists only in
`reusable_node_vectors` (`:1182-1187`); no chunk bounds the graph path.
*Resolution.* Chunk the `edge_ids` IN (and siblings) in
`_graph_episode_rows`. *How to verify.* Dense-graph query at limit=1000/hops=5
completes with no "too many SQL variables".

**F-10 — MED · vector-outbox replay re-embeds soft-deleted records**
`runtime.py:443-494` replays pending `index` intents through `load_ir`
(`storage.py:1768-1770`, no status filter) into `index_records` (`vector.py:167-168`
skips only non-indexable kinds). Scoped delete clears `vector_index`/
`projection_index` but never retires outbox intents (`lifecycle.py:258-277`).
*Failure scenario.* persist commits → external backend index fails (intent stays
pending) → scoped delete soft-deletes → crash → reopen replays and re-embeds
the deleted content locally and into external pgvector. Main retrieval filters
`deleted_soft` (`retrieval.py:519-536`), but the vector tables and other
consumers do not — a privacy/storage regression on the exact guarantee S4/S5
built. *Resolution.* Retire pending intents for delete targets, or filter
`deleted_soft` in replay. *How to verify.* Sequence above leaves zero
vector rows for the deleted record after reopen.

**F-11 — MED · SQL leg tie-break violates the rrf/2 contract**
`adapters.py:1470`: `order by sql_score desc, lexical_hits desc, updated_at
desc, id asc` — mutable `updated_at` breaks ties before `id`, while
`FUSION_POLICY_CONTRACT` (`retrieval_policy.py:12-17`) mandates
`sort(-raw-score, record-id)`. `insert or replace` overwrites `updated_at`
(`storage.py:1073-1087`), so a metadata-only rewrite reorders the leg at its
`limit ?` truncation boundary (`planner.py:101`) — flipping membership, fused
scores, budgeted output, and `candidate_set_sha256`.
*Resolution.* `order by sql_score desc, id asc` (fold `lexical_hits` into the
score if it is intended as one). *How to verify.* Re-persist an identical row;
`candidate_set_sha256` unchanged.

**F-12 — MED · structured-score gate drops boundary-only records**
`adapters.py:1411-1417` claims ns+scope filters "sufficient to retain
non-lexical tail records", but the gate at `:1418-1423` is
`lexical_hits > 0 or structured_score >= gate` with `gate = 1.0` on the default
non-RAW path (ns 0.4 + scope 0.4 = 0.8 < 1.0) — boundary-only records are
silently dropped; the 0.8 gate only engages when `include_raw=True`.
*Resolution.* Make the gate match the documented threshold (0.8) or document
the 1.0 as deliberate. *How to verify.* Boundary-only record appears in the
default-path SQL leg output.

**F-13 — MED · legacy-weighted silently converted to RRF with mismatched rank bases**
`flags.fusion="rrf"` (proposed by the loop `self_improve.py:927`, or env
`SEAM_RETRIEVAL_RRF`) routes `search_batch` through `_fuse_rrf`
(`retrieval.py:580`) while `search_ir` hardcodes `ranking_policy="legacy-weighted/1"`
(`runtime.py:1020`) and the trace reports `legacy_weighted`
(`orchestrator.py:598-620`). The legacy fusion enumerates 0-based
(`retrieval.py:615-616`, top rank 1/60) vs the canonical 1-based
(`merger.py:46`, 1/61, per `retrieval_policy.py:9,117`) — engines disagree on
rank base, and the docs still treat legacy-weighted/1 as the live ablation
control (`docs/status/retrieval.md:14-16`).
*Resolution.* Retire the legacy path (route everything through the canonical
rrf/2 ranker) or block the flag combination. *How to verify.* Same query under
both rankers yields identical ranks; plan/trace report what ran.

**F-14 — MED · unevidenced dispute demotes verified claims (asymmetry)**
`knowledge_graph.py:2987-3016`: `verified_refutations` requires independent
evidence, but `disputes` collects every `contradicts`/`refutes` edge with no
evidence gate, and the ladder tests `elif disputes: contested` *before*
`elif independent_count >= 2: verified` — one unevidenced model-produced edge
ejects a multi-episode verified claim from every asserted-context pack
(`ASSERTABLE_TRUST_STATES`, `:69`; `assertable_record_ids`, `:1856`).
The contested exclusion itself is correct fail-closed behavior pinned by test
(`tests/audit/test_deep_knowledge_graph.py:315-371`) and HISTORY#403; the
defect is that dispute edges skip the evidence rule the file's own docstring
applies to support edges.
*Resolution.* A deliberate design decision: gate disputes on edge evidence like
refutations (real disputes often lack immediate evidence, so this is not a
blind patch). *How to verify.* Unevidenced refutes edge no longer demotes a
verified claim — or the asymmetry is documented as policy.

**F-15 — MED · reasoning-pattern result disagreement silently dropped (permanent)**
`reasoning_patterns.py:624-635` returns the pre-existing row when a later call
disagrees (`succeeded`, `outcome_node_id`, `reason` ignored) — no warning, no
update; the table is append-only with `use_id` unique (`:83,114-121`), so a
reject-then-success sequence (reachable in the live SDK flow:
`reject_pattern()` → `finalize_verified()`) permanently counts an uncorrectable
failure in `trust_score` (`:373-388,442`), which gates pattern ranking.
*Resolution.* Raise on disagreement, or let `record_successful_pattern_uses`
skip rejected uses. *How to verify.* Reject a use, finalize verified, assert the
pattern's trust score reflects the success (or the conflict surfaced).

**F-16 — MED · TUI chat client lacks the host allowlist**
`dashboard.py:263-316` posts to `SEAM_CHAT_BASE_URL` verbatim with the bearer
key, no allowlist/loopback/redirect checks, and falls back to `OPENAI_API_KEY`
(`:268-271`); httpx follows redirects by default. The REST server's layered
defense for the same call (`server.py:350-489`) is entirely absent on the TUI
path, and the live TUI uses this client (`tui/app.py:676-678,982-992`).
*Failure scenario.* A typo'd or hostile `SEAM_CHAT_BASE_URL` (env or seam.env)
silently exfiltrates the API key on the first chat message — the exact class of
hole the server-side allowlist was built to close.
*Resolution.* Reuse `_validate_provider_base_url` semantics in
`SeamChatClient`; `follow_redirects=False`. *How to verify.* TUI chat to an
un-allowlisted host refuses before any network call.

**F-17 — MED · local commit gates are quieter than required CI**
`tools/git-hooks/pre-commit:69-74`, `tools/claude/preflight_protocol.sh:54-72`,
`tools/history/closeout.py:45-52` run the same 6 verifiers only, while CI
`repo-hygiene` (`ci.yml:220-261`) additionally runs `ruff check .` (233),
`verify_dependency_contract` (257-258), and `git diff --check` (220-221). The
parity test (`tests/audit/test_local_gates_match_ci.py:38-45`) pins exactly the
6 modules and structurally cannot see the gap — HISTORY#535's I001 failure mode
(passes local, rejected post-push) remains live. (HISTORY#536 closed the
fact-audit gap; this is the remainder.)
*Resolution.* Mirror the three CI-only checks into pre-commit and preflight,
then extend the parity test to the full set. *How to verify.* An I001 committed
locally fails pre-commit.

**F-18 — MED (known S6 gap, re-verified) · /v1 tenancy binding absent**
`public_api.remember/recall/context` take no caller identity; `namespace`/
`session_id` are body fields (`public_api.py:109-122,253-258`). Correct for
BUSL self-host; wrong for anything hosted. Now with the decision recorded
(in-process, optional principal; HISTORY#538, campaign S6) and 35 HTTP tests,
the gap is precisely scoped and unblocked.
*Resolution.* S6 as specified. *How to verify.* S6 exit gate.

### 3.3 Verified LOW findings (compact)

| # | Area | file:line | defect |
|---|---|---|---|
| L-1 | arch | `orchestrator.py:17,159,400,482-488`; `runtime.py:920-926` | engine↔runtime bidirectional private-member coupling (`_retrieval_flags_cached`, `_persist_projection_lock`); attribute-time break on rename; deliberate + CI-guarded → LOW (was HIGH) |
| L-2 | arch | `dashboard.py:263-326` vs `server.py:322-489` | two chat-provider clients; TUI one lacks allowlist (see F-16) |
| L-3 | arch | `dashboard.py:3072,3087` vs `cli.py:1880,2027` | duplicated `_split_ids`/`_read_text_source` with diverged contracts |
| L-4 | arch | `public_api.py:303-307` | "opaque" mem ids are unkeyed sha256 — reversible; opacity cosmetic |
| L-5 | arch | `adapters.py:55,165,309,441,490,502,588,605,665,754,987` | 11 sites reach store's private `_pool` directly |
| L-6 | correctness | `retrieval.py:211-218,504-514`; `planner.py:47-50` | negative persisted `search_top_k`/`context_budget` passes loader, then ValueError kills all retrieval — contradicts "a bad row can never take down the search path" |
| L-7 | persistence | `storage.py:1882-1899`; `read_snapshot.py:60-76,145-148,185` | rollback compensation terminates the bound read snapshot (authorizer omits `SQLITE_TRANSACTION`); rest of request reads per-statement |
| L-8 | persistence | `runtime.py:230-250` | `ingest_text` not atomic across canonical persist and `document_status` bookkeeping |
| L-9 | persistence | `lifecycle.py:724-731,269-277,757` | `apply_scoped_delete` expands up to 10,000 ids into unchunked INs |
| L-10 | security | `cli.py:1702-1709`; `mcp.py:215-228` | MCP stdio: no `SEAM_API_TOKEN` enforcement (local-spawn by design); legacy bridge `readline()` unbounded — reuse `_read_capped_lines` |
| L-11 | security | `server.py:211-215,137-139,663-675` | rate limiter keyed pre-auth on raw header hash; bucket rotation evicts legit clients; default-off |
| L-12 | security | `qualification.py:38-42,754-758` | secret regex misses dotted separators (`--api.key=sk-…`); validation only for `EXTERNAL_LANES` |
| L-13 | tests | `test_locomo_mem0_adapter.py:254-256` | `test_close_cleans_temp_dir` asserts nothing |
| L-14 | tests | `test_tui_supersedes_dashboard.py:27-33`; `conftest.py:38-45` | "textual is not installed" skip reason not allowlisted; in-test comment claims CI doesn't install textual — false |
| L-15 | tests | `test_webui_chat_memory_controls.py:6-14` | `tweaks-panel.jsx` zero test refs; `seam-api.js` substring-only assertions |
| L-16 | tests | `ci.yml:100` vs `pytest.ini:2-6` | CI test dirs hand-duplicated from testpaths; drift already visible (`tools/history` scope) |
| L-17 | tests | `test_cross_encoder_rerank.py:44-67` | cross-encoder tests assert their own mocks, never real rerank output |
| L-18 | reasoning | `workspace.py:166,241-244` | `identity_verified` const-True coercion; recorded in `redacted_fields`; nothing gates on it → LOW (was MED) |
| L-19 | reasoning | `reasoning_promotion.py:725-732` | post-apply `rejected` review accepted but inert; eligibility reads are consistent → LOW (was MED) |
| L-20 | reasoning | `knowledge_graph.py:1344-1351` | `supersede_source` splits an unvalidated suffix; both production callers pass sha256-derived ids → LOW (was MED) |
| L-21 | reasoning | `reasoning_graph.py:2104,2137` | `reasoning_graph()` returns all nodes/edges unbounded (retrievals cap at 100) |
| L-22 | reasoning | `reasoning_graph.py:1496,2034` | chroma leg latency recorded under `vector_latency_ms` |
| L-23 | reasoning | `reasoning_patterns.py:277` | distilled templates embed full runs uncapped; re-serialized per read |
| L-24 | reasoning | `workspace.py:613` | `confidence=0` treated as missing → 1.0 in graph activation spread |
| L-25 | reasoning | `improvement_experiments.py:129` | plain read path returns chain rows unverified (writer + `verify_improvement_experiment` do enforce) → LOW (was MED) |
| L-26 | context | `knowledge_graph.py:1162` | `limit=0` floors to 1 result |
| L-27 | context | `knowledge_graph.py:1537,1568-1572` | BFS edges not pruned when node re-filter drops endpoints — dangling edges in output |
| L-28 | context | `knowledge_graph.py:2537-2543,2563,2603` | ISO timestamps compared lexicographically; mixed formats misorder `at`-qualified queries |
| L-29 | context | `graph_products.py:393-443` | `_eligible_fact` trusts caller-supplied `trust_state`/`episode_ids` (documented disclaimer; downstream re-admits) |
| L-30 | context | `lifecycle.py:295-304` | `derived_cleanup_complete` always True, even when no cleanup ran |
| L-31 | context | `lifecycle.py:367-369` | batch items recordable while operation still `planned` |
| L-32 | surfaces | `server.py` (openapi generation) | duplicate FastAPI operation IDs `health_health_get` / `public_health_v1_health_get` (pytest warning, 2026-08-12 run) |
| L-33 | docs | `tools/release/public_manifest.py:78` | comment claims "seam-runtime >= 2.3.0 on PyPI"; 2.3.0/2.3.1 built, never published; live = 1.3.1 |

## 4. Health dashboard

```
Core storage (migrations, pool, outbox)   ██████████░░  good — no criticals; 1 MED (F-10), 3 LOW
Retrieval engine (orchestrator, fusion)   ███████░░░░░  needs work — 5 MED (F-7,F-9,F-11,F-12,F-13), 2 LOW
Surfaces (REST/MCP/SDK/TUI/CLI)           ██████░░░░░░  needs work — 4 MED (F-5,F-6,F-16,F-17), 4 LOW
Reasoning subsystem (R2-R5, workspace)    ████████░░░░  good — 1 MED (F-15), 7 LOW
Graph & trust (KG, products, context)     ███████░░░░░  needs decision — 1 MED (F-14), 5 LOW
Tests & CI                                ████████░░░░  good — 5 LOW; parity test gap (F-17)
Documentation & state routing             ██████░░░░░░  repaired this entry (F-1..F-4, L-33)
WebUI dashboard.html (7,479 lines)        ░░░░░░░░░░░░  not audited (three audits running)
Benchmark seal/BIL integrity, MIRL        ░░░░░░░░░░░░  not audited (three audits running)
  losslessness round-trip
```

## 5. Watch list

| signal | threshold | where it surfaces |
|---|---|---|
| `candidate_set_sha256` flips on a metadata-only rewrite | any flip without content change | F-11; retrieval fingerprint tests |
| `retrieval_flag_state` applied while a server/TUI process is up | any divergence until restart | F-8; trace `resolved_flags` vs table |
| pending `vector_outbox` intents for soft-deleted ids | > 0 after scoped delete | F-10; outbox replay logs |
| SQLite bind-variable count on graph queries | ≥ 999 (legacy floor) / 32,766 | F-9; dense-graph query at limit 1000 |
| policy resolution per surface | MCP ≠ SDK ≠ runtime | F-7; per-surface traces |
| provider reply size on /chat | > configured cap (none today) | F-5; persist size |
| trust transitions verified → contested | any unevidenced edge causing it | F-14; trust derivation logs |
| `verify_continuity` exit code | any exit 1 | closeout gate (tripped once at HEAD — F-4) |

## 6. Going unnoticed

- `storage.py` is a 140-method god object with 24 internal imports and no
  dedicated test file — three audits of increasing breadth still discover
  storage-adjacent bugs through other lanes' tests.
- Six duplicated retrieval-engine construction sites (runtime, sdk, mcp, cli,
  dashboard, benchmarks) each copy chroma defaults; the MCP surface rebuilds
  the orchestrator per call.
- Benchmark-only lever modules (`multi_scope_pack.py` 926 lines,
  `second_hop_context.py`, `temporal_instance_context.py`,
  `graph_source_selector.py`) ship inside the runtime package, imported only
  by the mem0 harness, and their env hooks are absent from `config.py`'s
  93-entry registry — set, and silently ignored.
- `webui/dashboard.html` (7,479 lines) has been read by no audit, ever.
- The old `TextualDashboardApp` remains 64% of `dashboard.py` (2,050 of 3,198
  lines) kept alive only by legacy tests.
- The drift lane found three of the four drifts it flagged on 2026-08-10 still
  unrepaired nine days later — the status router has no mechanical freshness
  check (this entry's closeout now includes the verifiers, which is the
  available backstop).

## 7. Verifications performed

**Executed this audit:**

- Full suite `pytest tests/` with live pgvector lane: **2,382 passed,
  2 xfailed, 0 skipped, 0 failed** in 256.16s (exit 0). The 2 xfails are the
  pinned `compile_nl` fidelity targets.
- `verify_integrity` OK · `verify_routing` OK · `verify_handoffs` OK ·
  `verify_streams` OK · `verify_wiki` OK (215 pages).
- `verify_continuity` **FAILED** at HEAD (snapshot predates #559) — repaired
  by this entry's closeout.
- Six read-only audit lanes + two respawned micro-lanes (reasoning; context/
  trust) over the 52k-line runtime; 7 bounded HISTORY.md timeline lanes
  (#001-#559); 17 adversarial verification agents; 2 citation spot-check lanes
  (20/20 confirmed); 1 empirical SQLite `locking_mode=EXCLUSIVE` probe.
- Lane-run focused suites: persistence 54 passed; tests/CI lane's inventory:
  2,342 test functions analyzed, exactly 2 xfails, skips all allowlisted or
  deliberately external.

**Prior-audit criticals/highs — independently re-verified fixed in code**
(three separate lanes): persist entity race (`storage.py:1006-1007` +
`test_persist_ir_concurrency.py`); `/chat` env-var exfiltration
(`server.py:418-467`); `/docs`/`/redoc`/`/openapi.json` bypass (`server.py:641-648`);
trust-timestamp fallback (`knowledge_graph.py:2821-2832`). Projection registry
now covers core-storage 1→2→3 and KG 4→5→6 in-transaction (residual: 2/13
projections registered, no static completeness gate).

**Not verified:** webui/dashboard.html contents; mem0-harness semantics;
clean-venv import smoke; GitHub ruleset config (API 404); cross-namespace test
internals; installed-stack CVE scan.

## 8. The next step

One PR, two fixes, both one-file-scale and both on the loopback-trust cluster:
cap `/chat` provider response reads (F-5) and refuse caller-supplied overwrite
on REST `/persist` (F-6). They are the two MEDIUMs a misconfigured hosted
deployment converts into incidents, and neither requires a design decision —
everything else on the list (F-7 policy unification, F-14 trust asymmetry)
wants a decision first.

---

## Corrections to prior belief

- "S6 tenancy decision written down nowhere" was **wrong** — recorded
  2026-08-05 (in-process, optional principal; HISTORY#538, campaign S6). The
  status router was the stale party.
- The WAL/"exclusive owner is false" finding is **refuted** empirically:
  `locking_mode=EXCLUSIVE` applies under WAL and holds across per-step commits
  until connection close; a competing process cannot interleave migration
  steps. (Add a cross-process test to lock it in.)
- The improvement-experiment "hash chain unenforced" finding is **refuted** at
  the writer layer: appends run a full-chain validation on cache miss and a
  tail re-hash on hit; tamper tests exist. Residual: the plain read path is
  unverified.
- IN-expansion line citations carried from the prior audit were stale; current
  sites re-derived (F-9, L-9, A4-style citations).
- Engine-runtime coupling was rated HIGH by the architecture lane; verification
  found a deliberate, commented, CI-guarded seam — downgraded to LOW.

## Evidence manifest

Raw artifacts: none

All evidence is in-repo file:line citations above. The full-suite pytest
run was performed live and is summarized in §7; its session-local log was
not preserved.
