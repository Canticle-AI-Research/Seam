---
handoff_id: 2026-08-25-track-s-s8-retrieval-coherence-review-repaired
supersedes: 2026-08-25-track-s-s8-retrieval-coherence-in-progress
handoff_status: superseded
history: HISTORY#606
---

# Track S S8 — review repaired, four more exits closed

## Exact branch boundary

- Worktree: `/home/terrabyte/Documents/Projects/Seam-track-s-s6`.
- Branch: `track-s/s8-retrieval-coherence`, PR #228 (draft).
- Exact protected base: `440a014313870067d4c2f04a528aec9e235ba01f`.
- Branch-local S8 work. NOT S8 completion, S9 qualification, protected-main
  behavior, or any benchmark/quality claim.

## The prior red check was transient

`test-and-benchmark` failed on exact head `c6cc2eea6c`: pytest was `Killed` at
~42 percent with exit code 137 and zero assertion output. A failed-jobs-only
rerun of the same head, with no code change, passed. Kernel and systemd-oomd
journals had no entries for that window, so the kill cause is NOT asserted.

## Review findings closed

The exact-head Codex review returned three findings; all were reproduced first.

- **P1 (real defect).** `FUSION_LEG_NAMES` omitted `chroma`, which
  `ChromaSemanticAdapter` emits as its fusion source. `{"chroma": ...}` raised,
  while `{"vector": 0.0}` silently left a Chroma-backed leg at weight 1.0. The
  closed set now equals the leg names the engine emits, and
  `reasoning_graph.RETRIEVAL_SOURCES` is that same definition.
- **P2 (claim accuracy).** `_parse_leg_weights` strips names, so HISTORY#605's
  "padded names fail across the public surface" was overbroad. The split is now
  explicit and pinned: the env var owns whitespace, programmatic flags require
  exact names, and a misspelling from either surface still fails before search.
- **P3 (stale stream).** `docs/status/retrieval.md` is updated to measured state.

## Exits closed in this slice

- A legacy-policy plan executes only the legacy adapter (every leg adapter spied).
- Persisted weighted-policy replay: additive `reasoning_retrieval.leg_weights_json`
  plus migration; persistence accepts `weighted-reciprocal-rank-fusion/1`, stores
  the exact ranking weights, writes the matching fingerprint, and re-derives the
  recorded score. Absent/all-one/zero/non-unit each replay exactly; all-one is
  bitwise identical to `/2` in ids, ranks, scores, and candidate-set digest.
- Surface parity: `search_ir` no longer hardcodes its policy and returns the
  `retrieve()` ranking narrowed to compatibility kinds under both policies,
  proven through the live REST `/search` surface too.
- Surface coverage extends to MCP (`seam_retrieve`, `seam_context`) and the
  TUI's `search_ir` read path, so "every shipped surface" is proven, not asserted.
- Exactly one tenant-scoped (`ns:scope`) retrieval event per successful
  retrieval from runtime, `search_ir`, SDK, and MCP paths, default-off behind
  `SEAM_RETRIEVAL_EVENTS`, with injected telemetry failure proven answer-inert.
- Process-lifetime flag cache qualified, not removed: stability is an asserted
  contract and `SeamRuntime.refresh_retrieval_flags()` is the tested adoption path.
- SQLite 999-variable floor bounded in graph traversal. A test pinning the
  connection to the legacy limit found THREE unbounded `IN (...)` statements;
  each is chunked or clause-split with ordering reproduced exactly.

Identity merges were already reversible and audited by published S6/S7 work
(`tests/audit/test_identity_resolution.py::test_split_is_reversible_and_evidence_is_retained`);
that exit is cited, not re-implemented.

## Deliberately still open

- **`search_ir` still defaults to `legacy-weighted/1`.** It feeds the LoCoMo
  adapter and the mem0 harness, so retiring it in favour of `/2` would change
  every recorded arm. That is an S9-gated measurement decision, not an S8
  refactor, and it needs an operator-approved paid re-run to re-qualify.
- Boundary-only SQL gate decision.

## Next steps

1. Full closeout gates for HISTORY#606, then push and re-request exact-head CI
   and review on PR #228.
2. Put the legacy-versus-RRF retirement to the operator as an S9 measurement
   decision, and decide the boundary-only SQL gate. S9 remains the promotion
   gate; claim no graph/scorer lift here.

The dirty primary checkout, unrelated worktrees and branches, sibling
repositories, ignored artifacts, and operator assets remain outside this
workstream and untouched.
