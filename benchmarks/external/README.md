# External benchmarks

## What this directory is for

Each subdirectory under `benchmarks/external/<benchmark>/` holds an adapter that
wires an external benchmark into the SEAM evaluation harness. Adapters are
registered through `benchmarks/registry/memory_benchmarks.json`. Each adapter
declares its own `command_env` so the harness knows which environment variable
to set before invocation.

## How to wire a benchmark

1. Set the environment variable the adapter expects.
2. Run `seam bench external --plan` to confirm the harness detects the
   benchmark and can produce an execution plan.
3. Run `seam bench external --scope <id>` to execute the benchmark.

The `--plan` step is always safe (no side effects) and lets you validate wiring
before any work runs.

## LoCoMo

### Quickstart

```bash
seam bench external --quickstart locomo --adapter seam --judge stub
```

Runs a bundled 10-case synthetic fixture against the SEAM adapter using
string-match scoring (EM, token F1, context recall). Completes in under
60 seconds with no network access and no dataset download required.

### Full dataset dry-run

```bash
seam bench external locomo \
    --dataset-path /path/to/locomo.json --dry-run --format json
```

Validates dataset shape, prints case/category counts and fixture hash
without executing the adapter or judge.

### Full run

```bash
seam bench external locomo \
    --dataset-path /path/to/locomo.json --adapter seam --judge claude --output run.json
```

The full LoCoMo dataset (`snap-research/locomo` on HuggingFace) is required.
Stub judge results are smoke-only; publication requires a real judge.

## LongMemEval

```bash
seam bench external longmemeval \
    --dataset-path /path/to/longmemeval.json --dry-run --format json
```

500 questions across five abilities represented by six official
`question_type` values. Dry-run validates exact dates/session alignment,
question metadata, abstention markers, and expected totals. Real execution is
delegated to the pinned upstream harness; the generic LoCoMo scorer is refused.

## BEAM

```bash
seam bench external beam \
    --track 1m --dataset-path /path/to/beam-dataset-dir --dry-run --format json
```

BEAM as a whole has 100 conversations and 2,000 questions. The 1M track is
35 conversations / 700 questions. Official local repository layouts are fully
validated from `chats/<scale>/<conversation>/chat.json` and nested probing
questions, including nonempty chats, rubric nuggets, all ten categories, exact
track totals, and a root-independent source-file hash. Unknown legacy
directory layouts remain structural-only and invalid. Real execution uses the
pinned upstream harness and official nugget scoring. BEAM-10M is separately
deferred and gated.

## mem0 harness adapter

```bash
.venv/bin/python -m benchmarks.external.mem0_harness.seam_mem0_server --port 8900
```

SEAM's loopback HTTP facade for the `mem0ai/memory-benchmarks` harness. See
`benchmarks/external/mem0_harness/README.md` for setup instructions.

## Publication gate

Stub-judge results are refused for competitive publication. The publication
gate (`seam_runtime.benchmark_integrity.validate_publication_readiness`)
requires: non-stub judge, dataset name, fixture hash, git SHA, adapter name,
and BIL-2 verification. See `tests/audit/test_track_m_publication_gate.py`.

## Judges

- Default: string-match only (no API key or extra deps needed)
- `--judge stub`: deterministic smoke-only judge that abstains and never claims correctness
- `--judge claude`: requires `pip install seam[bench-judge]` and `ANTHROPIC_API_KEY`
- `--judge openai`: requires `pip install seam[bench-judge]` and `OPENAI_API_KEY`
- Cost: one LLM call per case. Quickstart has ~10 cases.

## Where adapters go

One subdirectory per benchmark. The LoCoMo adapter lives under
`benchmarks/external/locomo/`. Future adapters follow the same pattern
with shared infrastructure under `benchmarks/external/common/`.

## Benchmark Integrity Levels

External benchmark results can be sealed into deterministic SEAM benchmark
bundles:

```bash
seam bench external --quickstart locomo --adapter seam --judge stub --output locomo-result.json
seam bench seal locomo-result.json --level BIL-2 --allow-stub-seal --output locomo.seam-bundle.json
seam bench verify locomo.seam-bundle.json
seam bench inspect locomo.seam-bundle.json
```

Current Track K support covers BIL-0 through BIL-2 only. BIL-3 signing,
BIL-4 audit-chain linkage, BIL-5 transparency logs, and BIL-6 independent
reruns require operator policy decisions and are not implemented yet.
LLM judge scores remain informational; sealing records the evidence but
does not make probabilistic judge scores a deterministic gate.
Stub-judge results require the explicit `--allow-stub-seal` flag so test-only
judge output cannot be mistaken for independently judged evidence. BIL result
hashes exclude volatile timing fields such as run start time, elapsed seconds,
and per-case latency measurements; those fields remain present in the sealed
result payload for inspection.
