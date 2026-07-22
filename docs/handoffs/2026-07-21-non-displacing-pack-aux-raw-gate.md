---
handoff_id: 2026-07-21-non-displacing-pack-aux-raw-gate
supersedes: 2026-07-21-multi-speaker-derived-facts-cloud-probe
handoff_status: superseded
history: HISTORY#450
---

# Handoff: non-displacing PACK passes through auxiliary RAW, not facts

**For:** the next agent continuing retrieval, graph, or derived-fact work.
**Date:** 2026-07-21
**Branch:** `agent/non-displacing-derived-fact-pack`
**Spend:** zero provider, extraction, answerer, judge, embedding, or retrieval
calls in this replay. It reuses the GPT-4o artifacts recorded by HISTORY#448.

## One-line state

The exact 130-question free gate now passes without regression at the smallest
tested source-safe cap, N=3, but both gains come from auxiliary RAW episodes.
The GPT-4o fact and its exact source produce zero miss gain by themselves. This
is evidence for a non-displacing PACK and isolated auxiliary-RAW retrieval
contract, not evidence that derived facts improve the benchmark.

## Exact result

The replay uses the frozen GPT-4o LoCoMo contract from HISTORY#448:

- conversations 3/4/5, categories 1/3;
- 130 unique questions: 34 baseline misses and 96 sentinels;
- GPT-4o answerer/judge baseline and GPT-4o/OpenAI multi-speaker extraction
  provenance (1,968 historical extraction calls, 1,046 accepted facts);
- pinned clean `mem0ai/memory-benchmarks` revision
  `4b61c5d31b9c668a12b4f5e78064248a02c82d2b`;
- replay provider calls: zero.

Every candidate keeps the complete baseline RAW sequence as the logical prefix.
The physical tail row becomes one strict direct-readable PACK ordered as:

`raw_protected -> raw_source -> raw_episode x 0..N -> grounded_fact`

The fact's exact source id and body must match the `raw_source` item. Parsing is
digest-bound and character-length-delimited; malformed, duplicate, reordered,
truncated, missing-source, over-budget, or preservation-breaking inputs fail
closed. The policy is artifact-only and intentionally absent from live
`POLICIES` because live RAW-primary retrieval is not isolated from derived
candidate ranking yet.

| novel RAW cap | miss gained/lost | sentinel gained/lost | result |
| ---: | ---: | ---: | --- |
| 0 | 0 / 0 | 0 / 0 | no lift |
| 1 | 0 / 0 | 1 / 0 | no miss lift |
| 2 | 0 / 0 | 1 / 0 | no miss lift |
| 3 | 1 / 0 | 1 / 0 | **pass; smallest tested cap** |
| 4 | 1 / 0 | 1 / 0 | pass; no added evidence |

For N=3, all 130 cases preserve physical row count, logical baseline RAW prefix,
tail score/date, source-before-fact order, upstream score-sort placement, and
chronological prompt placement. Maximum PACK size is 3,197 characters. The
largest pinned GPT-4o prompt is 15,190 `o200k_base` tokens, an 891-token maximum
increase over baseline and 108,714 tokens of headroom after reserving 4,096
output tokens.

The two changed cases are numeric-only in the external audit. Independent
recomputation found that the sentinel gain is the first `raw_episode` and the
miss gain is the third `raw_episode`. Neither gain matches the fact or its
mandatory source item. Therefore direct derived-fact lift on this gate remains
zero.

## Reproducibility artifacts

Licensed candidate artifacts remain outside git under
`/media/terrabyte/T7/Proprietary/DATA/seam-ms-gpt4o-probe.ekhTRe/`. The CLI now
rejects candidate output paths inside the repository.

- N=3 candidate:
  `candidate-ms4o0721b-nondisplacing-source-safe-n3.json`, SHA-256
  `b703fc3fa83f070c952017fb3aa1a57b1d0a4d8c493af3c056556683a682546d`;
- N=3 numeric audit:
  `non-displacing-source-safe-n3-audit.json`, SHA-256
  `05d5ec8b496b6d8eab3205ce1f323104adbe6eab19fc46499dfc4a0239c941d5`.

The N=0/1/2/4 ablation artifacts and numeric audits are beside them. Do not copy
the candidate files into the repository; they contain licensed benchmark text.

## What landed

- `seam_runtime/multi_scope_pack.py`: artifact-only source-safe composer, strict
  parser, and logical RAW expander. N=3 is the measured default; the parser
  accepts at most four novel episodes for bounded ablations.
- `benchmarks/external/mem0_harness/preflight_non_displacing_pack.py`: exact
  coverage join, GPT-4o provenance validation, candidate construction, logical
  preservation/source-order gates, pinned prompt token audit, numeric report,
  hashes, exclusive output writes, and outside-repo licensed-artifact guard.
- `tests/audit/test_multi_scope_pack.py` and
  `tests/audit/test_non_displacing_pack_preflight.py`: fail-closed composition,
  parsing, provenance, coverage, no-regression, prompt, zero-provider, and
  licensed-output contracts.

## Interpretation and promotion boundary

This resolves the immediate HISTORY#448 wall: a complete non-displacing PACK can
add evidence without evicting any baseline RAW. It also sharpens the diagnosis:
the measured win is the retrieval/serving contract, not GPT-4o fact wording.
GPT-4o still improved extraction yield over the local 7b (0.8015 versus 0.73),
but remained below the borrowed 0.90 yield gate and produced zero direct evidence
lift here.

Do not wire `non-displacing-fact-pack/1` into the live facade, promote cloud
facts, run a full cloud ingest, or request paid scoring from this result. N=3 was
selected adaptively on the same 130 questions, so this is a mechanism proof and
regression ratchet, not a held-out score claim.

## Recommended next build

Build a lane-neutral, non-displacing auxiliary-RAW path before more model work:

1. Freeze the primary lane to RAW-only retrieval whose ranking cannot be
   perturbed by CLM/REL/EVT candidates.
2. Add a separate auxiliary lane that returns source RAW ids. For graph, make it
   query-conditioned through edge `source_record_id` bridges and require
   multi-node/path agreement; for derived signals, resolve the selected claim
   back to source RAW without entering the primary ranker.
3. Pack at most three novel auxiliary RAW episodes beside the protected RAW tail
   and verify the same source/order/preservation invariants.
4. Reproduce this 130-question gate mechanically, then predeclare a fresh
   provider-free held-out graph/RAW scope before any promotion or paid judge.

The highest-value immediate ablation is a fact-free, lane-neutral auxiliary-RAW
PACK using the same three episode ids. If it retains the two gains, delete the
fact-specific overhead from the candidate design and carry the generic PACK into
the graph lane.

## CI and verification note

The HISTORY#447 ordering item is resolved intra-run: PR #154, PR #155, and the
`0e87c58` merge workflow all started advisory `test-and-benchmark` only after the
five fast jobs completed. The remaining caveat is global single-runner
contention: an advisory from an earlier run can still delay a later run's fast
jobs. PR #155 and merge advisory runs were red only on the 180-second LoCoMo
quickstart timing guard (269.57 and 285.81 seconds); the sentence-transformers
2.7 failures did not recur.

Focused PACK/replay tests, displacement and PR-gate guards, Ruff, compileall,
diff hygiene, CodeRabbit review, and an independent artifact recomputation are
green. Required GitHub checks remain the merge authority. Operator-owned
`.ua/` and five `report*.png` files remain untouched and excluded.
