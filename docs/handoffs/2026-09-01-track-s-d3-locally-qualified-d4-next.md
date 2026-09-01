---
handoff_id: 2026-09-01-track-s-d3-locally-qualified-d4-next
supersedes: 2026-09-01-track-s-d2-locally-qualified-d3-next
handoff_status: superseded
history: HISTORY#623
---

# Track S D3 locally qualified; D4 next after protected merge

## Exact state

Protected `main@a7333f0` contains complete D1 Recovery and D2 Atomic Ingest.
The isolated branch `feat/d3-lifecycle-exclusion`, based on that commit, closes
the local D3 Lifecycle Exclusion implementation and evidence gap.

Canonical records remain retained through `load_ir`. Ordinary reads recursively
exclude a non-current record and every record whose canonical support is
ineligible. That boundary now covers retrieval and trace legs, memory/decompile,
PACK, graph products and retained product rows, identity metadata, and reusable
node vectors. Explicit public history remains a retained-state surface and does
not register mutation handles.

Lifecycle apply rebuilds the current graph-product boundary from surviving
facts inside the delete transaction. Cleanup failure, reopen, repeated resume,
and repeated rebuild remain content-free and idempotent. Vector invalidation
preserves unchanged shared endpoints, removes deleted-only hashes, and
reprojects changed survivors. Hard-delete identity conflicts remain durable
audit state, while soft-deleted, superseded, deprecated, and contradicted
present endpoints remain hidden from ordinary identity list and audit reads.

## Qualification

- Focused root lifecycle/graph/vector/identity qualification: 100 passed before
  the full-suite compatibility repair.
- Full non-external collection: 3,225 tests, 3,223 passed, two established
  xfails, zero failures or errors.
- Live pgvector external lane: 23 passed against the healthy local container.
- The repaired history and identity compatibility slice: 36 passed.
- Changed-file Ruff and `git diff --check`: green.
- Independent delivery and assurance agents rejected two earlier iterations;
  the final contract closes transitive support leaks, stale PACK/history leaks,
  graph-product and identity leakage, cleanup replay, and shared-node vector
  convergence.
- Twelve root-recorded red-green cycles cover the public-seam behavior and both
  full-suite compatibility repairs.

## Claim boundary and resume order

D3 is locally qualified, not protected-main complete. Finish this branch
through explicit staging, signed commit, push, exact-head hosted checks, a
root-stored `QUALIFIED` receipt, protected merge, and exact-main resume. Do not
count D2's hosted checks for this successor tree.

After that merge, start D4 Snapshot Integrity from fresh protected main with a
new isolated worktree, root session state, bounded context packet, public-seam
red test, delivery wave, and independent assurance. Then continue T1, G1, R1,
and R2 before freezing S8. Do not start S9 measurement until all S8 streams and
the boundary-only SQL decision are frozen. No S8, S9, S10, release, deployment,
or hosted-production claim is established here.
