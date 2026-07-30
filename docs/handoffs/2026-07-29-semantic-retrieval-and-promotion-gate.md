---
handoff_id: 2026-07-29-semantic-retrieval-and-promotion-gate
supersedes: 2026-07-29-wandr-provider-free-replay-next
handoff_status: current
history: HISTORY#498
---

# Handoff: semantic retrieval gain implemented locally; promotion-content gain remains unproven

**Date:** 2026-07-29
**Branch:** `agent/wandr-replay-handoff`
**Base:** `origin/main` at `6d2c15bb16a00667c69862c4ab18ecd879924743`
**Scope:** free local retrieval qualification, SDK/facade bug fixes, and an
honest longitudinal promotion-content gate

## One-line state

The BGE-backed `graph_node` retrieval leg has a reproducible positive free
qualification and is now enabled whenever an explicit default-off Mem0 facade
graph policy invokes graph search; the reasoning-promotion mechanism applies
cleanly, but neither verbatim nor cross-turn concatenated promotion content has
demonstrated retrieval improvement.

## Local fixes ready for review

- `benchmarks/external/mem0_harness/seam_mem0_server.py` now passes
  `semantic_graph_seeding=True` to its explicit graph search. The surrounding
  facade policies remain default-off; this does not silently enable graph
  composition on the primary retrieval path.
- `SeamSDK.start_reasoning()` now defaults to `local.default`, matching
  `SeamSDK.ingest()`. The old `local.reasoning` default silently filtered the
  obvious ingest-then-retrieve flow to an empty namespace.
- Direct regression tests pin both behaviors.

## Positive free retrieval gate

The local provenance-matched LoCoMo/BGE qualification used all ten
conversations, 5,882 turns, and 1,977 scored questions with provider keys
blanked and Hugging Face offline:

| configuration | r@1 | r@5 | r@10 | r@20 |
| --- | ---: | ---: | ---: | ---: |
| graph, semantic leg off | 0.196 | 0.349 | 0.427 | 0.509 |
| graph, semantic leg on | 0.301 | 0.490 | 0.568 | 0.656 |
| delta | +0.105 | +0.141 | +0.141 | +0.146 |
| mix, semantic leg off | 0.317 | 0.499 | 0.572 | 0.682 |
| mix, semantic leg on | 0.338 | 0.576 | 0.667 | 0.748 |
| delta | +0.021 | +0.076 | +0.095 | +0.065 |

Every category moved positively at full scale. A `hybrid` negative control,
which has no graph leg, moved by at most one hit out of 1,977. This is a free
retrieval-quality qualification, not a judged answer-score or competitive
benchmark claim.

## Honest promotion-content gate

A one-conversation longitudinal probe ingested a fixed 419-turn corpus, split
196 scored questions into deterministic 98-question TRAIN and HELD cohorts,
then drove observe, verify, propose, review, and apply through the SDK. All
99/99 cross-turn bridge promotions applied. Strict and provenance-closure
recall deltas were only zero to three questions at every K:

| cohort and scorer | r@1 | r@5 | r@10 | r@20 |
| --- | ---: | ---: | ---: | ---: |
| TRAIN strict | -0.0306 | -0.0102 | -0.0204 | +0.0102 |
| TRAIN closure | +0.0102 | -0.0102 | -0.0102 | +0.0102 |
| HELD strict | -0.0204 | +0.0102 | -0.0102 | +0.0000 |
| HELD closure | +0.0000 | +0.0102 | -0.0102 | +0.0000 |

The bridge records reached rank one and retained correct source provenance, so
the observe-to-apply-to-retrieval plumbing works. The content was only a
deterministic concatenation of two retrieved claim objects, not a new
inference. It substituted for source evidence without adding reach. Do not
combine this null result with the positive semantic-leg result or claim that
the promotion loop has demonstrated self-improving retrieval quality.

## Verification

- The two directly affected audit files collected and passed 70/70.
- The strict full `tests/` suite with live pgvector collected 1,628 tests:
  1,626 passed, the two established `compile_nl` cases xfailed, and zero
  skipped or failed.
- Changed-file Ruff, `py_compile`, `git diff --check`, snapshot loading, and
  the canonical history closeout gates passed.
- No provider call, paid benchmark, install, download, package publication,
  deployment, or DigitalOcean mutation occurred.

## Remaining product boundary

- Public `/v1` still uses legacy `search_ir`; this change does not route the
  opaque public product through the retrieval orchestrator.
- SDK reasoning retrieval remains the only surface that records the full
  reasoning-retrieval evidence needed to drive proposals. CLI, MCP, REST, and
  `/v1` observation/apply productization remains a separate design decision.
- The current promotion probe is not a reusable checked-in benchmark and its
  concatenated bridge is not a genuine inference.

## Next

Land this bounded branch through a protected PR before further graph work. Then
build a checked-in, zero-provider longitudinal qualification that derives a
genuinely new assertion from retrieved evidence, includes a leak-free
provenance closure scorer, and scales beyond one conversation. Keep the
zero-network WANDR replay as the next independent breadth qualification; do not
confuse it with proof that the learning loop improves retrieval.
