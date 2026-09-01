---
handoff_id: 2026-09-01-track-s-d4-locally-qualified-t1-next
supersedes: 2026-09-01-track-s-d3-locally-qualified-d4-next
handoff_status: superseded
history: HISTORY#625
---

# Track S D4 locally qualified; T1 next after protected merge

## Exact state

Protected `main@253037a` contains complete D1 Recovery, D2 Atomic Ingest, and
D3 Lifecycle Exclusion through merged PR #241. The isolated branch
`codex/d4-snapshot-integrity`, based exactly on that commit, closes the local D4
Snapshot Integrity implementation and evidence gap.

A rejected write through the normal store path no longer rolls back the bound
read transaction. Nested readers receive a guarded connection and guarded
cursor while the raw pooled connection remains private to the snapshot owner.
Transaction/savepoint SQL, commit, rollback, close, authorizer replacement,
context-manager exit, cursor-to-connection close, writable BLOB access,
deserialize, mutating PRAGMAs, ATTACH/DETACH, temp/vtable mutation, and the
remaining SQLite mutation action family are rejected. Owner-managed
`query_only` mode is restored with the prior isolation state when the snapshot
ends. Concurrent commits become visible only after owner release.

## Qualification

- Full non-external selection: 3,238 cases; exit 0 with 3,236 passes and the two
  established xfails.
- Live pgvector external lane: all 23 tests passed against the configured local
  service.
- Focused snapshot, pool, retrieval-fingerprint, and lifecycle matrix: 51
  passed.
- Changed-file Ruff and `git diff --check`: green.
- Four root-witnessed red-green cycles record the rejected-store rollback,
  owner-control facade, BLOB/deserialize boundary, and PRAGMA/ATTACH hardening.
- Independent standards and spec assurance rejected three partial iterations;
  the final pass found no issue and independently exercised VACUUM,
  `executescript`, exceptional exit, alternate PRAGMA syntax, and connection
  state restoration.

## Claim boundary and resume order

D4 is locally qualified, not protected-main complete. Finish this branch
through explicit staging, signed commit, push, exact-head hosted checks, a
root-stored `QUALIFIED` receipt, protected merge, and exact-main resume. Do not
count D3's hosted checks for this successor tree.

After that merge, start T1 Temporal Semantics from fresh protected main with a
new isolated worktree, root session state, bounded context packet, public-seam
red test, delivery wave, and independent assurance. Then continue G1, R1, and
R2 before freezing S8. Do not start S9 measurement until all S8 streams and the
boundary-only SQL decision are frozen. No S8, S9, S10, release, deployment, or
hosted-production claim is established here.
