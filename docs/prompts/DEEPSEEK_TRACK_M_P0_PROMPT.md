# DeepSeek Batch Prompt - Track M P0 Standard Benchmarks

Paste this prompt verbatim into the DeepSeek session. The canonical SOP is
`docs/SOP_TRACK_M_P0_DEEPSEEK.md`.

---

You are DeepSeek working in the SEAM repo at:

`/home/terrabyte/Documents/Projects/Seam`

Execute `docs/SOP_TRACK_M_P0_DEEPSEEK.md` exactly. This is the Track M P0
standard-benchmark completion pass for PR #31.

Your branch:

`deepseek/track-m-p0-standard-benchmarks`

Your mission:

1. Start from current `main`, not PR #31's stale/conflicting branch.
2. Calibrate PR #31's P0 claims against current code.
3. Complete the missing P0 engineering for standard benchmark readiness:
   - pgvector composite-PK upgrade migration
   - SEAM adapter contract for `mem0ai/memory-benchmarks`
   - full LoCoMo local-dataset/dry-run path
   - LongMemEval local-dataset/dry-run path
   - BEAM-1M local-dataset/dry-run path
   - publication gate that refuses stub-judge competitive claims
4. Use your own parallel workers with disjoint file ownership.
5. Do not edit forbidden continuity/status paths; Codex will do final history
   closeout after review.

Required first reads:

1. `PROJECT_STATUS.md`
2. `REPO_LEDGER.md`
3. `HISTORY_INDEX.md`
4. `docs/CODE_LAYOUT.md`
5. `docs/DATA_ROUTING.md`
6. `docs/SOP_TRACK_M_P0_DEEPSEEK.md`
7. `docs/SOP_BENCHMARKABLE_STATE_ROADMAP.md`
8. `docs/SOP_CRITICAL_BENCHMARKABILITY_FIX.md`
9. `docs/ledgers/agents/deepseek.md`

Do not read all of `HISTORY.md`. Use bounded context packs only.

Hard rules:

1. Do not stage, commit, or push secrets, API keys, local `.env` values,
   provider session URLs, or private conversation links.
2. Do not commit generated benchmark result bundles, downloaded datasets,
   `node_modules/`, `dist/`, SQLite test artifacts, or files under `test_seam/`.
3. Do not edit `HISTORY.md`, `HISTORY_INDEX.md`, `.seam/`,
   `PROJECT_STATUS.md`, `REPO_LEDGER.md`, `ROADMAP.md`, `archive/`,
   `docs/archive/`, `build/`, `.venv/`, `test_seam/`, or
   `experimental/webui/`.
4. Stub judge results are smoke-only. They are not publishable scores.
5. If a full benchmark requires a local dataset or API key that is not present,
   run the dry-run validator and report the exact missing dataset/env.
6. Every code change needs a focused test.
7. Every benchmark claim needs command, git SHA, dataset, fixture hash, adapter,
   judge, BIL level, and skipped reason when skipped.

Pre-flight:

```bash
git status --short --branch
git switch main
git pull --ff-only origin main
git switch -c deepseek/track-m-p0-standard-benchmarks
gh pr view 31 --json number,title,state,headRefName,baseRefName,mergeable,isDraft,url
python3 -m tools.history.verify_integrity
python3 -m tools.history.verify_routing
python3 -m tools.history.verify_continuity
python3 -m tools.streams.verify_streams
.venv/bin/python -m pytest test_seam_all/ tools/history/test_history_tools.py tools/streams/ tests/ -q
```

If pre-flight has unrelated dirty files or failing continuity from someone
else's local history edit, stop and return `SCOPE_LIMIT_HIT` with exact output.

Parallel worker assignment:

1. Worker A: PR #31 rebase/doc calibration. Read-only unless the SOP allows a
   current Track M docs reapply.
2. Worker B: pgvector upgrade migration.
3. Worker C: mem0 harness adapter contract.
4. Worker D: full LoCoMo local dataset and dry-run route.
5. Worker E: LongMemEval local dataset and dry-run route.
6. Worker F: BEAM-1M local dataset and dry-run route.
7. Worker G: publication/BIL gate.
8. Coordinator: integrate, run verification, produce final report.

Required verification before handback:

```bash
git diff --check
.venv/bin/python -m pytest tests/audit/test_pgvector_pk_composite.py -q
.venv/bin/python -m pytest tests/audit/test_mem0_harness_adapter_contract.py -q
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

Benchmark smoke/dry-run commands:

```bash
.venv/bin/python -m seam bench external --plan --format json
.venv/bin/python -m seam bench external --quickstart locomo --adapter seam --judge stub --format json
.venv/bin/python -m seam bench external locomo --dataset-path <local-locomo-json> --dry-run --format json
.venv/bin/python -m seam bench external longmemeval --dataset-path <local-longmemeval-json> --dry-run --format json
.venv/bin/python -m seam bench external beam --track 1m --dataset-path <local-beam-dir> --dry-run --format json
```

Return this final block:

```text
===== DEEPSEEK REPORT: TRACK_M_P0 =====
branch: deepseek/track-m-p0-standard-benchmarks
head: <sha>
base: main
pr31_state_seen: <state>

fixed:
- <item id>: <files>, <tests>, <result>

stale_or_already_done:
- <item id>: <evidence>

deferred:
- <item id>: <reason and required operator decision>

benchmark_results:
- quickstart_locomo_stub: <command>, <metrics>, <smoke-only/BIL info>
- full_locomo: <dry-run or real-run result>
- longmemeval: <dry-run or real-run result>
- beam_1m: <dry-run or real-run result>

publication_gate:
- stub_refused_for_publication: <yes/no>
- bil2_verification: <command/result>

verification:
- <command> -> <result>

changed_files:
- <path>

generated_or_local_artifacts_not_committed:
- <path or none>

open_questions:
- <question or none>

codex_review_prompt:
Codex, review DeepSeek's Track M P0 branch.
Repo: /home/terrabyte/Documents/Projects/Seam
Base: main
Branch: deepseek/track-m-p0-standard-benchmarks
HEAD: <sha>
PR #31 context: Track M P0 standard benchmark completion.
Please verify the diff, focused tests, full active pytest scope, benchmark
smoke/dry-run commands, BIL/publication gate behavior, generated artifact
exclusion, secret scan, and all SEAM gates before merging.
```
