---
handoff_id: 2026-07-22-fact-free-auxiliary-raw-ablation
supersedes: 2026-07-21-non-displacing-pack-aux-raw-gate
handoff_status: superseded
history: HISTORY#452
---

# Handoff: the fact is dead weight — auxiliary RAW carries the gain

**For:** the next agent building the isolated RAW-primary / auxiliary-RAW lane.
**Date:** 2026-07-22
**Branch:** working tree on `main` (not yet committed at write time; see the
closeout below).
**Spend:** zero provider, extraction, answerer, judge, embedding, or retrieval
calls. This reuses the frozen GPT-4o artifacts from HISTORY#448/#450.

## One-line state

The fact-free ablation recommended by HISTORY#450 is complete and **passes the
exact 130-question gate identically to the fact-bearing PACK** (+1 miss, +1
sentinel, zero loss) while serving **zero derived facts**. The GPT-4o fact and
its mandatory source row are dead weight; the auxiliary RAW episodes alone carry
the entire measured non-displacing gain.

## Exact result

Same frozen contract as HISTORY#450: conversations 3/4/5, categories 1/3, 130
unique questions (34 baseline misses, 96 sentinels), pinned harness revision
`4b61c5d31b9c668a12b4f5e78064248a02c82d2b`, zero replay provider calls.

| metric | fact PACK (HISTORY#450) | fact-free PACK (this) |
| --- | ---: | ---: |
| miss gold gained / lost | 1 / 0 | 1 / 0 |
| sentinel gold gained / lost | 1 / 0 | 1 / 0 |
| fact items served | 130 | **0** |
| questions with pack | 130 | 130 |
| max pack chars | 3,197 | 1,868 |
| max GPT-4o prompt delta (tokens) | 891 | 466 |

The two gaining question ids are **byte-identical** between the two gates:
`conv4_q3` (the cat3 sentinel gain) and `conv4_q41` (the cat1 miss gain). 127 of
130 questions carry the full three episodes; logical RAW prefix and physical row
count are preserved on all 130.

## How the isolation is guaranteed

To hold the episode set byte-identical, the gate first re-composes the frozen
fact-bearing PACK per question, reads the `raw_episode` ids it selected, and
repacks **exactly those ids** fact-free. So the only variable removed between the
two runs is the grounded fact and its source row. This is why the reproduction
is exact rather than approximate.

## What landed

- `seam_runtime/multi_scope_pack.py`: default-off, artifact-replay-only
  `non-displacing-raw-pack/1` — `compose_non_displacing_raw_pack`,
  `parse_raw_pack_items`, `expand_logical_raw_pack_rows`, and a
  `_valid_raw_row` guard against the new pack prefix. Pack order is
  `raw_protected -> raw_episode x 0..N`, no fact, no source. Not wired into the
  live facade (`POLICIES`) — same promotion boundary as its fact-bearing sibling.
- `benchmarks/external/mem0_harness/preflight_fact_free_raw_pack.py`: the
  zero-provider replay gate. Pins episodes to the fact-version selection, runs
  the displacement audit, and gates on `no_fact_items`, `miss_gold_gain`, no
  losses, logical/physical preservation, pack-char cap, prompt headroom, and
  zero provider calls. Rejects candidate output paths inside the repo.
- Tests (green): `tests/audit/test_fact_free_raw_pack_preflight.py` (6),
  fact-free composer/parser cases added to `tests/audit/test_multi_scope_pack.py`.

## Reproducibility artifacts (outside git — licensed text)

Under `/media/terrabyte/T7/Proprietary/DATA/seam-ms-gpt4o-probe.ekhTRe/`:

- candidate `candidate-ms4o0721b-fact-free-raw-n3.json`, SHA-256
  `f5341152a2ba066d49b2b70961f47f6dd2cedf309c6911b310c7829001806086`;
- numeric report `fact-free-raw-n3-report.json`, SHA-256
  `e703c18a8d8a1d068bc5d421bf763e5ad8b5f72a5f4bd86a19ee36ea4fee609e`.

Inputs (by SHA, all reused from HISTORY#448/#450): baseline
`20260719-161639-mem0-harness-cat13-matched-final.json`; auxiliary
`candidate-ms4o0721b-cap1-post-pin.json`; source-config `stores/.seam-derived-facts.json`;
extraction-stats `probe-stats-final-original-contract.json`; dataset
`benchmarks/external/locomo/data/locomo10.json`; harness `/tmp/memory-benchmarks`.

Re-run command:

```
python -m benchmarks.external.mem0_harness.preflight_fact_free_raw_pack \
  <baseline> <auxiliary> \
  --source-config <stores/.seam-derived-facts.json> \
  --extraction-stats <probe-stats-final-original-contract.json> \
  --harness-root /tmp/memory-benchmarks \
  --candidate-output <outside-repo>.json --report-output <outside-repo>.json \
  --novel-raw-cap 3
```

## Interpretation and promotion boundary

N=3 and the episode set were selected adaptively on the same 130 questions, so
this is a **mechanism proof and regression ratchet, not a held-out score claim**.
Do not wire `non-displacing-raw-pack/1` into the live facade, promote it, run a
full cloud ingest, or request paid scoring from this result. What it licenses is
dropping the fact-specific overhead from the derived-fact experiment: carry the
**generic non-displacing auxiliary-RAW PACK** forward instead.

## Recommended next build (unchanged direction, sharper mandate)

1. Freeze the primary lane to RAW-only retrieval whose ranking cannot be
   perturbed by CLM/REL/EVT candidates.
2. Add a separate **query-conditioned** auxiliary-RAW lane that returns source
   RAW ids — for graph, bridge edge `source_record_id` values with
   multi-node/path agreement; there is no longer any reason to route it through
   a derived fact.
3. Pack at most three novel auxiliary RAW episodes beside the protected tail via
   `compose_non_displacing_raw_pack` and verify the same source/order/preservation
   invariants.
4. Predeclare a **fresh provider-free held-out** graph/RAW scope (not these 130
   questions) before any promotion or paid judge.

## Guardrails (retained)

- Free-then-paid discipline holds; any full ingest or paid answerer/judge run
  needs fresh operator approval.
- No Claude/agent attribution in commits or docs; operator-authored style.
- SEAM daylight is local-first; the cloud extractor stays a benchmark-only probe.

## Closeout verification

Affected slice collected 41 and passed all 41
(`test_multi_scope_pack.py` 16, `test_fact_free_raw_pack_preflight.py` 6,
`test_non_displacing_pack_preflight.py` 10, `test_displacement_audit.py` 9). Full
`pytest tests/` passed exit 0 with the T7 offline HF env and the local pgvector
DSN, two established xfails and zero skips. Touched-file Ruff clean. No provider
call, no paid work, no push. Operator-owned `.ua/` and `report*.png` remain
untouched and excluded.
