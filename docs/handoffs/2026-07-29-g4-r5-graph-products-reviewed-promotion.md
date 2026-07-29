---
handoff_id: 2026-07-29-g4-r5-graph-products-reviewed-promotion
supersedes: 2026-07-29-g3-r4-self-improving-graphs
handoff_status: superseded
history: HISTORY#495
---

# Handoff: G4 graph products and R5 reviewed promotion complete

**Date:** 2026-07-29
**Branch:** `feat/g4-r5-graph-products-promotion`
**Base:** `origin/main` at `f1e8c11f3be800fcaf3152f5b671b56641711a04`
**Scope:** G4 derived graph products and R5 reviewed, reversible MIRL promotion

## One-line state

G4 and R5 satisfy their structural, provenance, isolation, append-only, and
explicit-governance contracts; the candidate is fully verified locally but
remains uncommitted, unpushed, and unreviewed by protected PR checks.

## G4 completion boundary

- `graph-products/1` derives versioned entity summaries, connected-community
  summaries, and multi-episode observations from the canonical knowledge-graph
  projection.
- Only current same-namespace/scope facts that pass the existing assertion gate
  may contribute text. Untrusted, contradicted, superseded, inactive, missing-
  provenance, and cross-boundary inputs fail closed.
- Every sentence stores exact supporting MIRL record IDs and active episode IDs.
- Complete builds are append-only. Identical source fingerprints reuse the
  prior build; changed or empty eligible inputs append a new snapshot, and old
  versions remain auditable.
- Store, runtime, and local SDK expose explicit rebuild, latest-read, and
  bounded history operations. This is a derived product plane, not canonical
  truth and not yet G5 context assembly.

## R5 completion boundary

- A proposal can originate only from a verified, accepted same-run outcome and
  binds the current verification IDs, knowledge references, exact MIRL evidence
  fingerprints, and one bounded CLM payload.
- Human and policy reviews are separate append-only records. Approval does not
  insert MIRL, and no path auto-applies.
- Explicit Store/SDK application rechecks approval and every provenance binding
  inside the same transaction that persists the exact reviewed CLM and its
  application fingerprint.
- Reversal is permitted only while the exact applied assertion fingerprint is
  present. It appends immutable reversal audit and a canonical MIRL
  `supersedes` relation without deleting or rewriting the assertion, reasoning
  outcome, reviews, or evidence.
- Cross-boundary, stale, changed, unverified, already-applied, and already-
  reversed proposals fail closed. Free-form maps, raw logs, provider payloads,
  commands, and hidden reasoning are not part of the proposal surface.

## Verification

- Required collection:
  `.venv/bin/python -m pytest --collect-only -q
  tests/audit/test_graph_products.py tests/audit/test_reasoning_promotion.py
  tests/audit/test_g4_r5_integration.py tests/audit/test_selfhost_wheel.py`
  collected 27/27.
- Direct G4/R5, self-host, reasoning-graph, and reasoning-pattern slices passed
  39/39. The expanded affected slice including reasoning retrieval and the
  knowledge graph passed 98/98. Neither run reported skips, xfails, failures,
  or errors.
- File-backed G4/R5 smokes passed across rebuild, stale-fact removal, exact
  sentence provenance, review-gated application, additive reversal, and
  database reopen.
- Strict full suite with live pgvector:
  `PGVECTOR_TEST_DSN="$SEAM_PGVECTOR_DSN" .venv/bin/python -m pytest tests/ -q`
  exited 0 after 270.01 seconds with 1,577 collected, 1,575 passed, two
  established `compile_nl` xfails, zero skips, and zero failures.
- All changed Python files passed Ruff and compileall. `git diff --check` and
  bounded candidate scans for provider session URLs, API keys, private keys,
  and credential-bearing DSNs passed.
- Canonical integrity, routing, handoff, continuity, and stream gates passed;
  the closeout snapshot is the latest verified snapshot covering HISTORY#495.

## Preserved boundaries

- RAW/MIRL remains canonical truth. G4 output is rebuildable derived state.
- Reasoning stays a public justification plane. Only the explicit R5 review and
  application path may add its bounded assertion to MIRL.
- The public `seam-client` and opaque `/v1` boundary remain separate from MIRL,
  graph, PACK, and proprietary internals.
- No package, provider, paid benchmark, remote branch, PR, or deployment was
  created or changed.
- Unrelated untracked `.ua/`, `dist/`, report PNGs, and `seam_runtime/.ua/`
  were not read, edited, staged, or removed.

## Next

Commit the coherent candidate, push the branch, open a draft PR, and merge only
after every required protected check and review passes. G5 context assembly,
G6 lifecycle/scale, G7 comparative qualification, and R6 qualification remain
separate future milestones.
