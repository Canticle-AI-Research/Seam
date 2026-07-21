# SOP - Track M P1 Real Benchmark Runs

Issued: 2026-05-20
Owner pattern: the implementation agent runs real datasets and real judges on a
fresh branch; Codex reviews artifacts, hashes, gates, and merge readiness.

Scope: after Track M P0 lands, run the standard external memory benchmarks with
operator-provided datasets and real judges. This SOP is for evidence production,
not new benchmark plumbing.

## Goal

Produce auditable real-run evidence for:

1. LoCoMo full dataset with SEAM adapter and a real judge.
2. LongMemEval full dataset validation, then execution through the pinned
   upstream benchmark-specific answer/judge contract.
3. BEAM-1M validation, then execution through the pinned upstream nugget-rubric
   contract.
4. Optional mem0 and Zep comparator runs when local credentials and dependencies
   are present.
5. BIL-2 sealed bundles and verification reports for any real result.

Stub judge results remain smoke-only and must not be used as competitive
claims.

## Branch

Create:

```bash
git switch main
git pull --ff-only origin main
git switch -c deepseek/track-m-p1-real-benchmark-runs
```

## Required First Reads

Read in order:

1. `PROJECT_STATUS.md`
2. `REPO_LEDGER.md`
3. `HISTORY_INDEX.md`
4. `docs/CODE_LAYOUT.md`
5. `docs/DATA_ROUTING.md`
6. `docs/SOP_TRACK_M_P1_REAL_BENCHMARK_RUNS.md`
7. `docs/SOP_BENCHMARKABLE_STATE_ROADMAP.md`
8. `docs/SOP_CRITICAL_BENCHMARKABILITY_FIX.md`
9. `benchmarks/external/README.md`
10. `docs/ledgers/agents/deepseek.md`

Do not read all of `HISTORY.md`. Use bounded context packs only.

## Inputs Required From Operator

The agent must not download datasets into the repo. The operator provides local
paths outside git:

- `LOCOMO_DATASET_PATH`: full LoCoMo JSON.
- `LONGMEMEVAL_DATASET_PATH`: full LongMemEval JSON.
- `BEAM_1M_DATASET_PATH`: exported Hugging Face rows JSON for local validation,
  or `BEAM_DATASET_CACHE_DIR` for upstream execution.
- `MEMORY_BENCHMARKS_ROOT`: checkout of `mem0ai/memory-benchmarks` at the
  revision pinned by `benchmarks/external/mem0_harness/upstream_runner.py`.
- `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`: real judge credential.
- Optional comparator credentials: `MEM0_API_KEY`, `ZEP_API_KEY`, or local
  service endpoints, depending on the comparator adapter.

If an input is missing, run the relevant dry-run or smoke validator and report
the missing variable/path. Do not fake a score.

## Hard Rules

1. Do not commit downloaded datasets, result bundles, API responses, local
   `.env` values, SQLite test artifacts, provider session URLs, or private
   conversation links.
2. Store real result bundles outside the repo, then record only command, path
   placeholder, result hash, fixture hash, BIL level, and verification status in
   the handback.
3. Use `--judge claude` or `--judge openai` for competitive evidence. `--judge
   stub` is smoke-only.
4. Every real result must be sealed with `seam bench seal --level BIL-2` and
   verified with `seam bench verify`.
5. A result is not publication-ready unless
   `validate_publication_readiness(...)` receives a passing BIL-2 verification
   report and returns `ready: true`.
6. The in-repo LongMemEval and BEAM parsers are validators only. Never use the
   generic external-memory scorer for a competitive result; use the pinned
   upstream harness through SEAM's loopback facade.

## Pre-flight

```bash
git status --short --branch
python3 -m tools.history.verify_integrity
python3 -m tools.history.verify_routing
python3 -m tools.history.verify_continuity
python3 -m tools.streams.verify_streams
.venv/bin/python -m pytest test_seam_all/ tools/history/test_history_tools.py tools/streams/ tests/ -q
.venv/bin/python -m seam bench external --plan --format json
.venv/bin/python -m seam bench external --quickstart locomo --adapter seam --judge stub --format json
```

Acceptance for quickstart smoke: `context_recall_mean` must be greater than
`0.5`. If it is `0.0`, stop and report P0 regression.

## Runbook

### LoCoMo

Dry-run:

```bash
.venv/bin/python -m seam bench external locomo \
  --dataset-path "$LOCOMO_DATASET_PATH" \
  --dry-run --format json
```

Real run:

```bash
.venv/bin/python -m seam bench external locomo \
  --dataset-path "$LOCOMO_DATASET_PATH" \
  --adapter seam \
  --judge claude \
  --output /tmp/seam-track-m/locomo-seam-claude.json \
  --format json
```

Use `--judge openai` only if that is the available real judge credential.

Seal and verify:

```bash
.venv/bin/python -m seam bench seal /tmp/seam-track-m/locomo-seam-claude.json \
  --level BIL-2 \
  --output /tmp/seam-track-m/locomo-seam-claude.bil2.json \
  --format json
.venv/bin/python -m seam bench verify /tmp/seam-track-m/locomo-seam-claude.bil2.json \
  --format json
```

### LongMemEval

Dry-run:

```bash
.venv/bin/python -m seam bench external longmemeval \
  --dataset-path "$LONGMEMEVAL_DATASET_PATH" \
  --dry-run --format json
```

Start the SEAM facade in a persistent shell, then run the free upstream
predict-only path first:

```bash
.venv/bin/python -m seam bench external longmemeval \
  --dataset-path "$LONGMEMEVAL_DATASET_PATH" \
  --harness-root "$MEMORY_BENCHMARKS_ROOT" \
  --project-name seam-longmemeval-readiness \
  --predict-only --plan --format json

.venv/bin/python -m benchmarks.external.mem0_harness.seam_mem0_server \
  --db-path /tmp/seam-longmemeval --port 8900

.venv/bin/python -m seam bench external longmemeval \
  --dataset-path "$LONGMEMEVAL_DATASET_PATH" \
  --harness-root "$MEMORY_BENCHMARKS_ROOT" \
  --project-name seam-longmemeval-predict \
  --mem0-host http://127.0.0.1:8900 \
  --predict-only --workers 1 --format json
```

Only after the predict artifact and displacement checks pass may a separately
approved scored run omit `--predict-only`; it must name the real judge and add
`--allow-paid`.

### BEAM-1M

Dry-run:

```bash
.venv/bin/python -m seam bench external beam \
  --track 1m \
  --dataset-path "$BEAM_1M_DATASET_PATH" \
  --dry-run --format json
```

The directory dry-run is count-only. Use an exported official rows JSON to
validate chat payloads and rubric nuggets. Real BEAM-1M execution uses:

```bash
.venv/bin/python -m seam bench external beam \
  --track 1m \
  --harness-root "$MEMORY_BENCHMARKS_ROOT" \
  --project-name seam-beam-1m-readiness \
  --dataset-cache-dir "$BEAM_DATASET_CACHE_DIR" \
  --predict-only --plan --format json

.venv/bin/python -m seam bench external beam \
  --track 1m \
  --harness-root "$MEMORY_BENCHMARKS_ROOT" \
  --project-name seam-beam-1m-predict \
  --mem0-host http://127.0.0.1:8900 \
  --dataset-cache-dir "$BEAM_DATASET_CACHE_DIR" \
  --predict-only --workers 1 --format json
```

BEAM-1M is 35 conversations / 700 questions; 100 / 2,000 describes the whole
four-scale release. BEAM-10M remains deferred unless an operator explicitly
approves a separate infrastructure plan and passes `--allow-10m`.
If the selected BEAM cache is missing, the upstream runner's automatic large
download is separately refused until the operator passes `--allow-download`.

### Comparator Runs

Only run comparators when the local dependency and credentials are present.
Report missing extras or env vars exactly.

The retired in-process `mem0_harness.adapter` must not be used. The supported
comparator surface is the loopback `seam_mem0_server` HTTP contract plus the
pinned upstream harness.

Do not commit upstream harness clones or comparator-generated stores.

## Publication Gate

For any real result and BIL-2 verification report, run a local Python check:

```bash
.venv/bin/python - <<'PY'
import json
from seam_runtime.benchmark_integrity import (
    load_json_payload,
    validate_publication_readiness,
    verify_benchmark_bundle,
)

result_path = "/tmp/seam-track-m/locomo-seam-claude.json"
bundle_path = "/tmp/seam-track-m/locomo-seam-claude.bil2.json"
result = load_json_payload(result_path)
bundle = load_json_payload(bundle_path)
verification = verify_benchmark_bundle(bundle)
report = validate_publication_readiness(
    result,
    git_sha="<HEAD_SHA>",
    fixture_hash="<DRY_RUN_FIXTURE_HASH>",
    dataset_name="locomo-full",
    bil_verification=verification,
)
print(json.dumps(report, indent=2, sort_keys=True))
raise SystemExit(0 if report["ready"] else 1)
PY
```

Replace placeholders before running. Do not put secrets in the snippet.

## Required Verification Before Handback

```bash
git diff --check
.venv/bin/python -m pytest tests/audit/test_locomo_adapter_evidence_text.py -q
.venv/bin/python -m pytest tests/audit/test_locomo_full_dataset_routing.py -q
.venv/bin/python -m pytest tests/audit/test_longmemeval_routing.py -q
.venv/bin/python -m pytest tests/audit/test_beam_routing.py -q
.venv/bin/python -m pytest tests/audit/test_track_m_publication_gate.py -q
.venv/bin/python -m pytest test_seam_all/ tools/history/test_history_tools.py tools/streams/ tests/ -q
.venv/bin/python -m py_compile seam.py
.venv/bin/python -m compileall -q seam_runtime benchmarks tools scripts installers
python3 -m tools.history.verify_integrity
python3 -m tools.history.verify_routing
python3 -m tools.history.verify_continuity
python3 -m tools.streams.verify_streams
```

## Final Report Format

```text
===== DEEPSEEK REPORT: TRACK_M_P1_REAL_RUNS =====
branch: deepseek/track-m-p1-real-benchmark-runs
head: <sha>
base: main

inputs_seen:
- locomo_dataset: <present/missing, path placeholder only>
- longmemeval_dataset: <present/missing, path placeholder only>
- beam_1m_dataset: <present/missing, path placeholder only>
- real_judge_env: <ANTHROPIC_API_KEY/OPENAI_API_KEY/missing>

benchmark_results:
- quickstart_locomo_stub: <command, context_recall_mean, smoke-only>
- locomo_full: <command, scores, fixture_hash, result_hash, BIL-2 verify>
- longmemeval: <dry-run/real-run status>
- beam_1m: <dry-run/real-run status>
- comparators: <mem0/zep run or missing prerequisites>

publication_gate:
- <result>: <ready true/false, blocked_by>

verification:
- <command> -> <result>

changed_files:
- <path or none>

artifacts_not_committed:
- <path placeholder, hash, reason>

deferred:
- <item, reason, required operator decision>

open_questions:
- <question or none>
```
