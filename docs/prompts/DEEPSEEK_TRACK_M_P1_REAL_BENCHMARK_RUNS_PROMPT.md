# DeepSeek Batch Prompt - Track M P1 Real Benchmark Runs

Paste this prompt into DeepSeek after Track M P0 has landed on `main`.

---

You are DeepSeek working in the SEAM repo at:

`/home/terrabyte/Documents/Projects/Seam`

Execute:

`docs/SOP_TRACK_M_P1_REAL_BENCHMARK_RUNS.md`

Create this branch:

`deepseek/track-m-p1-real-benchmark-runs`

Mission:

1. Verify P0 is present on current `main`.
2. Run LoCoMo quickstart smoke and confirm `context_recall_mean > 0.5`.
3. Validate operator-provided full datasets with dry-run commands.
4. Run full LoCoMo with a real judge if `LOCOMO_DATASET_PATH` and either
   `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` are present.
5. Seal any real result as BIL-2, verify the bundle, and run publication
   readiness with the BIL-2 verification report.
6. Stop LongMemEval and BEAM at dry-run validation unless full real-run support
   exists on `main`.
7. Do not commit datasets, result bundles, local env files, credentials,
   provider links, or generated SQLite artifacts.

Required first reads:

1. `PROJECT_STATUS.md`
2. `REPO_LEDGER.md`
3. `HISTORY_INDEX.md`
4. `docs/CODE_LAYOUT.md`
5. `docs/DATA_ROUTING.md`
6. `docs/SOP_TRACK_M_P1_REAL_BENCHMARK_RUNS.md`
7. `benchmarks/external/README.md`
8. `docs/ledgers/agents/deepseek.md`

Pre-flight:

```bash
git status --short --branch
git switch main
git pull --ff-only origin main
git switch -c deepseek/track-m-p1-real-benchmark-runs
python3 -m tools.history.verify_integrity
python3 -m tools.history.verify_routing
python3 -m tools.history.verify_continuity
python3 -m tools.streams.verify_streams
.venv/bin/python -m pytest test_seam_all/ tools/history/test_history_tools.py tools/streams/ tests/ -q
.venv/bin/python -m seam bench external --plan --format json
.venv/bin/python -m seam bench external --quickstart locomo --adapter seam --judge stub --format json
```

Dataset dry-runs:

```bash
.venv/bin/python -m seam bench external locomo --dataset-path "$LOCOMO_DATASET_PATH" --dry-run --format json
.venv/bin/python -m seam bench external longmemeval --dataset-path "$LONGMEMEVAL_DATASET_PATH" --dry-run --format json
.venv/bin/python -m seam bench external beam --track 1m --dataset-path "$BEAM_1M_DATASET_PATH" --dry-run --format json
```

Real LoCoMo run, only when inputs are present:

```bash
mkdir -p /tmp/seam-track-m
.venv/bin/python -m seam bench external locomo \
  --dataset-path "$LOCOMO_DATASET_PATH" \
  --adapter seam \
  --judge claude \
  --output /tmp/seam-track-m/locomo-seam-claude.json \
  --format json
.venv/bin/python -m seam bench seal /tmp/seam-track-m/locomo-seam-claude.json \
  --level BIL-2 \
  --output /tmp/seam-track-m/locomo-seam-claude.bil2.json \
  --format json
.venv/bin/python -m seam bench verify /tmp/seam-track-m/locomo-seam-claude.bil2.json --format json
```

Use `--judge openai` instead when `OPENAI_API_KEY` is the available real judge.

Return the exact final report format from the SOP. Include command results,
fixture hashes, BIL-2 verification status, generated artifact paths outside the
repo, and any missing operator inputs. Do not include secrets.
