# Track S S6 principal-tenancy threat-model delta

**Date:** 2026-08-19; candidate requalified and review-repaired 2026-08-22
**Scope:** optional in-process principal binding, opaque public deletion, and
the indexed public-handle projection
**Baseline:** protected `main@a177852`
**Status:** implementation candidate; not protected-main fact until its PR
merges and exact-head gates pass

## Outcome

The candidate closes the code-level S6 boundary without changing trusted local
self-host behavior. A configured principal is resolved from a bearer credential
inside the process, hashed into an internal tenant identity, and combined with
the caller's namespace/session labels. The labels can select only inside that
principal. Principal mode serves the opaque `/v1` memory routes and health
checks. A pre-router allowlist returns the same rate-limited 404 for older
private routes, wrong methods, and slash variants while retaining CORS
preflight handling.

Recall/context register every returned `mem_` handle plus its canonical
generation in a versioned indexed projection before sending the response.
Delete resolves only registered handles inside the exact derived
tenant/namespace/scope and binds the lifecycle plan to that generation before
calling the existing G6 apply engine. Canonical soft delete, immediate
retrieval exclusion, append-only audit, and recoverable derived cleanup
therefore keep one source of truth without letting a stale capability delete a
replacement incarnation.

This is implementation and conformance evidence, not hosted deployment proof.
TLS, shared limiting, service supervision, secrets delivery, backup/restore,
rollback, and disaster recovery remain S10 work.

# Threat-Model Delta — S6 principal tenancy and opaque deletion

## Changed entrypoints and boundaries

- `create_app(..., principal_resolver=..., public_id_key=...,
  process_workers=<exact-count>)` is the hosted
  authentication adapter seam. `SEAM_API_PRINCIPAL` can bind the existing
  `SEAM_API_TOKEN` to one stable subject for a single-principal deployment.
- `POST /v1/memories`, `/v1/memories/recall`, `/v1/context`, and
  `/v1/memories/delete` receive the resolved principal as a dependency.
- Principal mode disables legacy private data routes and generated API docs
  before router matching. `GET/HEAD /health` and `/v1/health` remain
  rate-limited service probes without memory access, and `OPTIONS` remains
  available only for the four public data routes so CORS middleware can answer
  valid preflights.
- Recall/context now write a disposable `public_memory_handle` projection,
  including the canonical generation, before returning opaque memory IDs. Core
  storage advances through the exact registered `core-storage/3 ->
  core-storage/4` migration.
- Delete reuses `plan_scoped_delete`/`apply_scoped_delete`; no second deletion
  state machine or authorization store was added.

## Assets newly read, written, transmitted, or exposed

- Bearer credential: read by the resolver only; never written or returned.
- Principal subject: accepted from trusted application configuration, hashed
  before it enters internal tenant/actor fields, never returned.
- Public ID key: read from injected bytes or `SEAM_API_PUBLIC_ID_KEY`; used only
  for HMAC; never stored in SQLite, logged, or returned.
- Opaque-handle projection: stores `mem_` handle, hashed tenant boundary,
  internal namespace/scope, canonical record ID, canonical generation, and
  version metadata.
- Lifecycle ledger: retains the internal operation/event chain and prior
  canonical content under the existing soft-delete audit contract.

## Attacker-controlled fields

- `Authorization`: exact `Bearer <credential>` parsing; resolver returns a
  configured `PublicPrincipal` or the request receives the same HTTP 401.
- `text`: string, nonblank, at most 100,000 characters.
- `query`: string, nonblank, at most 4,096 characters.
- `namespace`, `session_id`, `agent_id`: bounded public dimensions; none can
  provide or override the derived principal prefix.
- `scope`: closed MIRL scope vocabulary.
- `memory_ids`: 1-50 unique `mem_` handles with exactly 24 lowercase hex
  characters; every handle must resolve in the caller's exact indexed boundary.
- `idempotency_key`: nonblank, at most 128 characters, identifier characters
  only; lifecycle uniqueness remains per derived tenant.
- `limit`, `max_chars`, and the server request body retain their existing hard
  numeric/allocation bounds.

## Abuse cases

1. A caller replays another caller's namespace and session labels.
2. Two principals submit identical source text, attempting a canonical-ID
   collision or overwrite.
3. A caller submits another principal's valid opaque handle for deletion.
4. A caller probes forged and foreign handles to distinguish membership.
5. A principal attempts to use `/persist`, `/search`, `/stats`, `/chat`, or
   another legacy route to regain a shared-token data path.
6. A caller reuses one idempotency key for a different deletion.
7. A caller submits many handles to force a namespace-wide record scan.
8. A deployment starts principal mode without a stable opaque-ID key.
9. A stale resolved handle races a delete/re-add and attempts to delete the
   replacement generation.
10. A stale recall snapshot races replacement and attempts to publish an old
    capability after the replacement commits.
11. A caller re-adds a record while an older delete is `cleanup_pending`, so
    resumed external cleanup could otherwise erase the replacement vector.
12. A deployment under-declares its process worker count so the process-local
    limiter is mistaken for shared enforcement.
13. A caller with one valid credential exhausts its subject budget but keeps
    invoking an expensive injected resolver.
14. A mounted/reverse-proxied app supplies a nonempty ASGI `root_path` that
    could make the pre-router allowlist reject legitimate public routes.
15. A failed writer restores its pre-write snapshot after another process has
    completed deletion, resurrecting canonical content and handles.
16. Rotating credential fingerprints fill the bounded key map and evict an
    active valid-credential resolver budget.
17. Malformed public POST bodies consume parser/allocation work before an
    endpoint dependency can reserve a rate-limit slot.

## Partial-failure cases

1. Handle registration fails after retrieval but before the HTTP response: no
   opaque handle is returned; canonical memory remains and recall can retry.
2. Derived-index cleanup fails after canonical soft delete: the response is an
   opaque `pending` receipt, retrieval already excludes the record, and the
   existing `cleanup_pending` operation can resume with the same receipt.
3. Migration fails after creating the handle table: the table and projection
   marker roll back together; reopen resumes the registered step.
4. HMAC key is missing/short: app creation fails before serving principal mode.
5. Public-ID key changes: newly rendered handles change, while previously
   registered handles remain boundary-scoped and usable. The deletion receipt
   is derived from the tenant-bound lifecycle identity rather than that key, so
   an idempotent replay retains the same `del_` ID. Key custody and rotation are
   still deployment procedures to prove in S10.
6. A stale recall registers after canonical replacement: registration verifies
   the generation in the same write transaction and fails closed; the request
   returns a content-free conflict instead of exposing the stale handle.
7. Vector publication fails after canonical/handle mutation: runtime
   compensation restores the exact prior canonical, vector-outbox, and handle
   rows before surfacing the failure.
8. A caller retries an old deletion key after re-ingesting the same canonical
   record: the old operation can be replayed only while its original generation
   remains absent/deleted; the replacement receives the same content-free 404
   as an unknown handle.
9. Another process registers a handle after a failed writer's snapshot but
   before compensation: rollback preserves the row only if it still matches
   the restored active canonical boundary and generation.
10. Another process deletes a record while a writer is blocked in external
    projection: store-local interprocess serialization orders compensation
    before the delete can complete, so rollback cannot resurrect the response-
    acknowledged deletion.

## Controls

| Threat | Preventive | Detective | Recovery | Verification |
| --- | --- | --- | --- | --- |
| Namespace/session replay | Principal-derived internal namespace; caller labels are suffixes only | Exact stored namespace inspection | None required; request sees an empty boundary | Two-principal replay matrix |
| Identical-text overwrite | Principal namespace salts deterministic MIRL IDs | Two distinct namespaces and public IDs | Retry is safe inside each boundary | Same-content two-principal test |
| Foreign/forged delete | Keyed `mem_` handles plus exact indexed tenant/ns/scope lookup | Foreign and unknown return identical content-free 404 | Owned record remains live | Foreign-vs-unknown test |
| Legacy route bypass | Pre-router principal-mode guard compares the ASGI routed path against exact health/data method-path pairs | Route matrix, including wrong methods, slash variants, and mounted prefixes | Reconfigure only by deliberate app restart | `/stats`, `/persist`, `/chat`, schema, redirect, rate-limit, CORS, and `root_path` tests |
| Valid-credential resolver exhaustion | Credential-fingerprint budget is consumed before resolver invocation and retained after success | Resolver call count vs HTTP 429 sequence | Wait for the bounded window or rotate a deliberately provisioned credential | Repeated-valid-credential regression |
| Credential-budget eviction | Resolver budget refuses unseen fingerprints while its bounded map contains live keys | Key-map occupancy and resolver call count | Wait for expiry; do not evict active reservations | Capacity/rotation regression |
| Malformed pre-auth body work | Principal POST middleware reserves the client/auth budget before framework parsing; guard reuses or releases it | Consecutive malformed responses become 422 then 429 at a one-request budget | Wait for the bounded window | Malformed-JSON preparse regression |
| Idempotency collision | Lifecycle per-tenant uniqueness and operation fingerprint | HTTP 409 without internal IDs | Use a new caller key | Delete replay/conflict coverage |
| Cleanup failure | Canonical soft delete commits before external cleanup; durable `cleanup_pending` | Recoverable-operation query and append-only events | Repeat same opaque deletion/resume lifecycle | Injected cleanup-failure test |
| Unbounded handle resolution | Primary-key/composite-boundary handle index; max 50 IDs | No namespace `load_ir` on delete | Rebuild derived registrations through recall | Indexed-resolution regression |
| Schema drift/interruption | Registered core-storage/3-to-/4 step with required-table contract | Projection registry + integrity/foreign-key checks | Backup, rollback, reopen/resume | Migration and rollback-injection tests |
| Stale handle deletes replacement | Handle row and lifecycle precondition carry the canonical generation | In-transaction generation mismatch refuses the operation | Recall the replacement to receive its new handle | Resolve-then-replace race test |
| Stale recall publishes old capability | Registration checks an active record/generation under the runtime projection lock | Mismatch fails closed without registering a row | Retry recall against a current snapshot | Recall-registration and rollback-serialization race tests |
| Pending cleanup erases replacement | Writes overlapping `planned`, `applying`, or `cleanup_pending` scoped deletion are rejected | Content-free 409 plus durable lifecycle state | Resume the original deletion, then re-remember | Pending-cleanup/reingest test |
| Failed vector write loses handles | Runtime compensation restores prior rows and preserves only concurrent rows valid against restored active canonical state | Whole-table hash/row equality plus spawned-process registration race | Retry the original persist | Compensation and cross-process registration regressions |
| Failed writer resurrects deletion | Reentrant store-local cross-process lock spans canonical write, projection, compensation, delete planning/apply, and handle publication | Spawned writer/delete ordering and terminal canonical status | Retry failed writer only after the deletion completes | Cross-process deletion/compensation regression |

## Prompt, memory, and agent authority

- Retrieved text remains ordinary memory evidence; this change does not place
  it in a privileged instruction channel or authorize tools.
- Opaque delete is an authenticated API side effect. It requires a caller-owned
  handle plus idempotency key and performs soft deletion only; it does not hard
  erase the canonical audit record.
- No model/provider call, prompt change, autonomous promotion, or operator
  confirmation policy was added.

## Secrets and privacy

- Credential source: injected resolver or environment owned by the operator.
- Logging behavior: auth failures log client identity only; tokens, subjects,
  HMAC material, request text, handles, and canonical IDs are not logged by the
  new boundary.
- Artifact/history behavior: tests use placeholders. This report contains no
  credential, DSN, provider-session URL, or private transcript URL.
- Scope isolation: full hashed principal plus internal namespace/session and
  MIRL scope. Responses echo only caller-provided public dimensions.

## Resource bounds

- Input/body: existing 5,000,000-byte server body cap; memory text 100,000;
  query 4,096; delete IDs 50; idempotency key 128.
- Context/candidates: recall at most 50; context at most 65,536 characters.
- Authentication limiting: principal mode defaults to 60 requests/minute when
  configuration is unset or zero. Invalid/rotating credentials share a bounded
  client-address pre-parse/resolver bucket; each credential fingerprint has a
  non-released, non-evicting resolver-invocation budget; successful subjects
  use stable per-principal buckets. The limiter is process-local, so
  multi-worker launch is refused unless an upstream shared limiter is
  explicitly acknowledged.
- Memory/disk: O(number of returned/requested handles) per operation. The
  append-only derived handle projection can grow with newly rendered records;
  retention/compaction policy is residual S10 operational work.
- Timeouts/retries: SQLite busy timeout and retry policy are unchanged;
  idempotent delete replay is explicit.
- External calls/cost: none added. Public deletion may call an already
  configured external vector adapter only through the existing recoverable
  lifecycle cleanup hook.

## Residual risk and assumptions

- Principal mode depends on the injected resolver faithfully mapping a bearer
  credential to one stable subject. The repository supplies and tests the
  boundary; a hosted identity provider adapter remains deployment-specific.
- The legacy token-only/no-token modes intentionally have no principal
  authorization and must not be marketed as shared hosted tenancy.
- Public-ID-key custody/rotation, TLS, shared rate limiting, service supervision,
  backup/restore, and disaster recovery remain S10 gates.
- The public handle registry is a derived index, not canonical truth. Its
  bounded maintenance/rebuild tooling should be included in S10 long-lived
  database operations.
- S6 does not establish semantic graph admission, retrieval-policy parity, or
  graph quality. Those remain S7-S9.

## Verification at this candidate

- Expanded HTTP/lifecycle/migration/vector/graph/server affected slice: 460
  collected and 460 passed with strict no-skip after final review repairs.
- Canonical non-external lane against a fresh isolated SQLite path with ambient
  pgvector DSNs removed: 2,926 passed, 23 deselected, 2 expected xfails, and 3
  subtests passed in 461.36 seconds.
- Live isolated pgvector external lane: 23 passed and 2,354 deselected in 3.25
  seconds; the ephemeral container was removed after the run.
- A first broad run was invalid environmental evidence: the preserved root
  `seam.db` predates the generation column and an ambient pgvector DSN selected
  a stopped service. The isolated reruns above are the qualification evidence;
  the preserved operator database was not changed or deleted.
- Review found and repaired malformed generation acceptance, a principal-mode
  zero-limit default, eager payload loading for all existing writes, successful
  principal requests retaining the shared pre-resolver reservation, non-ASCII
  static credentials raising during constant-time comparison, an optional
  rollback snapshot that could erase handles, active-delete recreation after a
  separately removed canonical row, and duplicate delete handles contradicting
  the unique-ID contract.
- A later exact-PR-head review found and repaired six additional boundary
  defects: deleted-handle registration and replay, worker-count
  under-declaration, handle rollback serialization, tenant-first active-delete
  lookup, and router-level method/redirect disclosure. The strict focused slice
  collected and passed 175 tests; the follow-up CodeRabbit working-tree review
  returned no findings. Exact-head CI on the repaired commit remains the merge
  gate.
- A second exact-head review of `921cfd0` found four more reproducible defects:
  cross-process registration loss during projection rollback, a stale applied-
  retry race, mounted `root_path` rejection, and unbounded resolver calls after
  subject limiting. The fixes preserve only concurrent handle rows still valid
  against restored canonical state, recheck replay generation inside the
  lifecycle transaction, normalize the routed ASGI path, and retain a hashed
  credential resolver budget. Four minimal regressions went red then green; the
  expanded strict focused slice collected and passed 179 tests. CodeRabbit's
  one minor spawned-process cleanup finding was repaired and reverified.
- A third exact-head review of `82849ab` found a cross-process deletion
  resurrection P1 plus three P2 gaps in concurrent first-plan replay, credential
  map eviction, and malformed-body pre-auth work. Reentrant store-local file
  serialization, universal public-apply incarnation checking, a non-evicting
  credential map, and pre-parse client reservation repair them. CodeRabbit then
  found two lock hardening gaps: the file now lives beside the resolved store
  rather than shared `/tmp`, and both POSIX/Windows acquisition paths use a
  bounded nonblocking deadline. Six minimal regressions went red then green;
  the expanded strict focused slice collected and passed 185 tests.
- The canonical working-tree secret/session scan, whole-tree Ruff, active-Python
  compilation, dependency check, diff/audit checks, and continuity closeout are
  green. Signed publication, exact-head CI, and merge remain before this is
  protected-main behavior.

## Evidence manifest

Raw artifacts: none
- Provider/model calls: none.
- External comparator calls: none.
- Code-review service: CodeRabbit, no source artifact committed.
- Operator-authored TUI source: not copied into this branch.
