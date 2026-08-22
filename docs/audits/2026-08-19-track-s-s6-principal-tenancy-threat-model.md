# Track S S6 principal-tenancy threat-model delta

**Date:** 2026-08-19; candidate requalified 2026-08-22
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
checks; older private data routes return 404 rather than retaining the shared-
token bypass.

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

- `create_app(..., principal_resolver=..., public_id_key=...)` is the hosted
  authentication adapter seam. `SEAM_API_PRINCIPAL` can bind the existing
  `SEAM_API_TOKEN` to one stable subject for a single-principal deployment.
- `POST /v1/memories`, `/v1/memories/recall`, `/v1/context`, and
  `/v1/memories/delete` receive the resolved principal as a dependency.
- Principal mode disables legacy private data routes and generated API docs in
  process. `GET/HEAD /health` and `/v1/health` remain rate-limited service
  probes without memory access.
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

## Controls

| Threat | Preventive | Detective | Recovery | Verification |
| --- | --- | --- | --- | --- |
| Namespace/session replay | Principal-derived internal namespace; caller labels are suffixes only | Exact stored namespace inspection | None required; request sees an empty boundary | Two-principal replay matrix |
| Identical-text overwrite | Principal namespace salts deterministic MIRL IDs | Two distinct namespaces and public IDs | Retry is safe inside each boundary | Same-content two-principal test |
| Foreign/forged delete | Keyed `mem_` handles plus exact indexed tenant/ns/scope lookup | Foreign and unknown return identical content-free 404 | Owned record remains live | Foreign-vs-unknown test |
| Legacy route bypass | Principal-mode guard returns 404 outside the four data routes | Route matrix | Reconfigure only by deliberate app restart | `/stats`, `/persist`, `/chat`, schema tests |
| Idempotency collision | Lifecycle per-tenant uniqueness and operation fingerprint | HTTP 409 without internal IDs | Use a new caller key | Delete replay/conflict coverage |
| Cleanup failure | Canonical soft delete commits before external cleanup; durable `cleanup_pending` | Recoverable-operation query and append-only events | Repeat same opaque deletion/resume lifecycle | Injected cleanup-failure test |
| Unbounded handle resolution | Primary-key/composite-boundary handle index; max 50 IDs | No namespace `load_ir` on delete | Rebuild derived registrations through recall | Indexed-resolution regression |
| Schema drift/interruption | Registered core-storage/3-to-/4 step with required-table contract | Projection registry + integrity/foreign-key checks | Backup, rollback, reopen/resume | Migration and rollback-injection tests |
| Stale handle deletes replacement | Handle row and lifecycle precondition carry the canonical generation | In-transaction generation mismatch refuses the operation | Recall the replacement to receive its new handle | Resolve-then-replace race test |
| Stale recall publishes old capability | Registration checks record/generation under the same write transaction | Mismatch fails closed without registering a row | Retry recall against a current snapshot | Recall-registration race test |
| Pending cleanup erases replacement | Writes overlapping `planned`, `applying`, or `cleanup_pending` scoped deletion are rejected | Content-free 409 plus durable lifecycle state | Resume the original deletion, then re-remember | Pending-cleanup/reingest test |
| Failed vector write loses handles | Runtime compensation snapshots and restores exact handle rows | Whole-table hash/row equality around injected failure | Retry the original persist | Compensation regression |

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
  client-address pre-resolver bucket; successful subjects use stable per-
  principal buckets. The limiter is process-local, so multi-worker launch is
  refused unless an upstream shared limiter is explicitly acknowledged.
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
