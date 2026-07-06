# SEAM How-To Runbooks

Command-first runbooks for daily operator workflows. Each section gives Windows
PowerShell and bash equivalents (Linux, WSL2, and macOS), then a success checklist.

These commands assume the global `seam` shim from the installer is on `PATH`. If
you are working from a repo-local dev checkout, replace `seam` with
`.\.venv\Scripts\seam.exe` (Windows) or `./.venv/bin/seam` (macOS / Linux).

macOS install and layout: [MACOS.md](MACOS.md)

## 1) Ingest, Search, Retrieve

Windows PowerShell:

```powershell
seam ingest README.md --persist
seam memory search "durable memory"
seam memory get clm:1,clm:2 --timeline
seam retrieve "durable memory" --mode mix --budget 5 --trace
seam context "durable memory" --retrieval-mode mix --view prompt
```

Linux / WSL2:

```bash
seam ingest README.md --persist
seam memory search "durable memory"
seam memory get clm:1,clm:2 --timeline
seam retrieve "durable memory" --mode mix --budget 5 --trace
seam context "durable memory" --retrieval-mode mix --view prompt
```

Success checklist:

- `seam memory search` returns at least one record id
- `seam retrieve --mode mix` returns ranked candidates with `--trace` reasons
- `seam context --view prompt` emits a token-bounded pack ready for an agent

## 2) Compile A Document Into A Holographic Surface And Query It Directly

Windows PowerShell:

```powershell
seam surface compile README.md --output readme.seam.png --mode rgb24
seam surface verify readme.seam.png
seam surface query readme.seam.png "persistent agent memory"
seam surface context readme.seam.png --query "persistent agent memory" --budget 1200
```

Linux / WSL2:

```bash
seam surface compile README.md --output readme.seam.png --mode rgb24
seam surface verify readme.seam.png
seam surface query readme.seam.png "persistent agent memory"
seam surface context readme.seam.png --query "persistent agent memory" --budget 1200
```

Success checklist:

- `surface verify` reports `PASS` and `payload_format: MIRL`
- `surface query` returns ranked hits without OCR or SQLite import
- `surface context` emits a budgeted prompt pack from the embedded payload

## 3) Run The Visual-Memory Loop Benchmark And Track Improvement

Run before any change you want to measure, save the result, then run after the
change and diff.

Windows PowerShell:

```powershell
seam benchmark run all --persist --output baseline.json
# make a change
seam benchmark run all --persist --output after.json
seam benchmark diff baseline.json after.json
seam benchmark gate after.json
```

Linux / WSL2:

```bash
seam benchmark run all --persist --output baseline.json
# make a change
seam benchmark run all --persist --output after.json
seam benchmark diff baseline.json after.json
seam benchmark gate after.json
```

Success checklist:

- `benchmark diff` shows per-case green/red/gray deltas plus added/removed cases
- `benchmark gate` reports `PASS` with all 8 families present
- Surface family rates stay at `1.0` for `surface_exact_rate`,
  `payload_hash_match_rate`, `direct_query_exactness_rate`,
  `stored_query_exactness_rate`, `repair_success_rate`,
  `repair_query_exactness_rate`

## 4) Drive A New Structural Extractor From A Failing Fixture

The visual-memory loop is structurally measurable: adding a fixture case in
`benchmarks/fixtures/surface_cases.json` whose query references a structural
primitive that `_structural_quote_spans` does not yet emit will fail the
`direct_query_exactness_rate` gate. Closing the failure means adding the
extractor and a fixture query exercising it.

Windows PowerShell:

```powershell
# 1. add a fixture case to benchmarks/fixtures/surface_cases.json
seam benchmark run surface --output spec.json
# 2. extend _structural_quote_spans in seam_runtime/lossless.py
seam benchmark run surface --output fix.json
seam benchmark diff spec.json fix.json
python -m pytest test_seam_all/test_seam.py tools/history/test_history_tools.py -q
```

Linux / WSL2:

```bash
# 1. add a fixture case to benchmarks/fixtures/surface_cases.json
seam benchmark run surface --output spec.json
# 2. extend _structural_quote_spans in seam_runtime/lossless.py
seam benchmark run surface --output fix.json
seam benchmark diff spec.json fix.json
python -m pytest test_seam_all/test_seam.py tools/history/test_history_tools.py -q
```

Success checklist:

- `spec.json` shows the new case as `FAIL`
- `fix.json` shows it as `PASS` with no other case regressing
- the scoped pytest command above passes; do not hard-code the count in logs

## 5) Run The Interactive Memory Shell

Windows PowerShell:

```powershell
seam shell
```

Linux / WSL2:

```bash
seam shell
```

Inside the shell:

```text
/remember SEAM stores durable memory for agents.
/search durable memory
/context durable memory
/stats
/doctor
/exit
```

Success checklist:

- `/remember` persists a record and returns its id
- `/search` returns compact results
- `/context` emits a prompt-ready pack
- `/doctor` returns `PASS`

## 6) Expose SEAM To An External Agent Via The MCP Stdio Bridge

Windows PowerShell:

```powershell
seam mcp stdio
```

Linux / WSL2:

```bash
seam mcp stdio
```

The bridge speaks standard MCP JSON-RPC on stdio. Wrappers can call
`seam_memory_search`, `seam_memory_get`, `seam_ingest`, surface tools, and
benchmark summaries without embedding the Python runtime. Use
`seam-mcp --ensure-pgvector` when the agent should auto-start Docker Compose
pgvector before MCP discovery.

Success checklist:

- the process stays open, reading stdin and emitting MCP JSON-RPC responses
- `seam doctor` reports the runtime as healthy in another terminal

## 7) Run Guarded Real-Adapter Validation (Postgres + PgVector)

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_real_adapters_guarded.ps1
```

Optional smoke-only run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_real_adapters_guarded.ps1 -SkipPytest
```

Linux / WSL2 has no equivalent guarded runner yet; use the manual flow:

```bash
docker compose --env-file "$HOME/.config/seam/.env" up -d pgvector
seam doctor
docker compose --env-file "$HOME/.config/seam/.env" down
```

Success checklist:

- runner exits cleanly
- pgvector container cleanup completes
- `seam doctor` reports `PgVector: reachable` while the service is up

## 8) Archive Benchmark Bundles To Documents (Windows)

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\store_benchmark.ps1 -Suite all
```

Success checklist:

- run folder created under `%USERPROFILE%\Documents\SEAM\benchmarks`
- `publication_manifest.json` and `case_hashes.json` exist
- daily `_index.json` updated

The archive script is Windows-specific. On Linux, copy the JSON output of
`seam benchmark run all --persist --output <name>.json` into a path of your
choice; commit-grade archives live outside the runtime repo.

## 9) Recover From An Interrupted Local Run

Windows PowerShell:

```powershell
docker ps --filter "name=seam-pgvector-test"
docker rm -f seam-pgvector-test
seam doctor
python -m pytest test_seam_all/test_seam.py::SeamTests::test_dashboard_snapshot_renders_runtime_metrics -q
```

Linux / WSL2:

```bash
docker ps --filter "name=seam-pgvector-test"
docker rm -f seam-pgvector-test
seam doctor
python -m pytest test_seam_all/test_seam.py::SeamTests::test_dashboard_snapshot_renders_runtime_metrics -q
```

Success checklist:

- no stale test container remains
- `seam doctor` returns `PASS`
- the targeted dashboard smoke test passes
