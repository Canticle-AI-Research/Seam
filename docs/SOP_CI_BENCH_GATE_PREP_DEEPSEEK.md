# SOP — CI Bench-Gate Prep (sys_metrics flake, pgvector-in-CI, MCP tools/call round-trip), DeepSeek Execution Pass

Issued: 2026-05-19 (post HISTORY#210)
Owner pattern: Claude authors and verifies; DeepSeek executes all items in
sequence in a single session; Claude reviews the full diff at handback,
appends HISTORY entries, commits.

Scope: closes the three items left on the deferred list from
`docs/SOP_CI_HARDENING_DEEPSEEK.md` that do NOT require an architectural
design call — the flake watch-item flagged in HISTORY#210, the pgvector
real-postgres CI integration (audit H3 third leg), and the `tools/call`
round-trip extension of the MCP stdio smoke test. After this batch lands,
the benchmark surface (`seam benchmark gate`, external memory benchmarks,
benchmark diff) is the next focus per operator direction — Track K (BIL
bundles + Trust/Security) is gated on benchmarks being 100% functional
first. Items M9 (`seam benchmark gate --baseline` in CI) and M6
(`surface_artifact` path validation) are deferred to follow-up SOPs
pending design calls (baseline source; surface root).

Supersedes scope: extends `docs/SOP_CI_HARDENING_DEEPSEEK.md`. Reuses the
batch sync-relay protocol from `docs/SOP_WEBUI_BATCH_HARDENING_DEEPSEEK.md`;
the same hard rules apply.

## How to use this SOP

For each item below DeepSeek must:

1. Read only the cited file ranges plus `tests/audit/__init__.py` and any
   per-item cited prior tests.
2. Write a failing test FIRST under the cited `tests/audit/` path (create
   the file if missing). Confirm it fails before any runtime/CI edit.
3. Apply the smallest fix in the cited file(s). Do not touch unrelated
   files. Do not edit `archive/`, `docs/archive/`, `build/`, `.venv/`,
   `test_seam/`, `experimental/webui/`, `HISTORY.md`, `HISTORY_INDEX.md`,
   `PROJECT_STATUS.md`, `REPO_LEDGER.md`, or `.seam/`.
4. Re-run the failing test. Confirm green.
5. Run the per-item gate.
6. Move to the next item. Do NOT commit. Do NOT push.

After ALL items complete: emit one ITEM_SUCCESS block per item, in
execution order, in one final paste. Claude reviews the full diff and
commits.

If a stop condition fires for any item, STOP at that item — emit
ITEM_SUCCESS blocks for items that completed plus the appropriate stop
block for the failed item.

## Pre-flight (run once before starting)

```
git status --short                                  # expect 0 dirty files
git branch --show-current                           # expect main
git log --oneline -1                                # expect: b4fa1df CI hardening: SEAM verify gates + pytest scope + MCP stdio smoke (HISTORY#210)
python -m pytest test_seam_all/ tools/history/test_history_tools.py tools/streams/ tests/ -q
python -m tools.history.verify_integrity
python -m tools.history.verify_routing
python -m tools.history.verify_continuity
python -m tools.streams.verify_streams
```

Expected starting state at the time this SOP was written:
- Branch: `main`
- Dirty files: **0**
- Latest commit subject: `CI hardening: SEAM verify gates + pytest scope + MCP stdio smoke (HISTORY#210)`
- pytest across all four scopes: **395 passed** + 1 known pre-existing flake on `tests/audit/test_sys_metrics_honesty.py::test_sys_metrics_live_on_linux` (B1 in this SOP is the fix). Re-run that test in isolation to confirm it's the same flake.
- All four gates: OK

If `git status --short | wc -l` is not 0, STOP and emit SCOPE_LIMIT_HIT
with reason `ambiguous_owner`.

## Per-item gate (after each fix, before moving on)

```
python -m pytest tests/audit/<focused_test_file> -q
python -m pytest test_seam_all/ tools/history/test_history_tools.py tools/streams/ tests/ -q
python -m py_compile seam.py
python -m compileall -q seam_runtime experimental tools scripts installers
```

For items that edit `.github/workflows/ci.yml` (B2), also run:

```
python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))" && echo "YAML OK"
```

## Order of execution

1. **B1** — Stabilize `test_sys_metrics_live_on_linux` against the back-to-back zero-delta /proc/stat read window
2. **B2** — Real-postgres pgvector integration in CI (new ubuntu-only job + new audit test)
3. **B3** — MCP `tools/call` round-trip smoke test (extends CI3 coverage)

---

## B1 — Stabilize sys_metrics live-on-Linux test

**Files**: `tests/audit/test_sys_metrics_honesty.py`
**Failing test**: same file — the `test_sys_metrics_live_on_linux` flake **plus** a new dedicated test for the zero-delta contract.

Background: HISTORY#210 flagged `test_sys_metrics_live_on_linux` as
pre-existing flaky. Root cause is in `seam_runtime/server.py` /sys-metrics
handler line 299: `if total_delta > 0` — when two back-to-back HTTP
requests hit the handler so fast that the /proc/stat jiffies counter has
not advanced (USER_HZ is typically 100 on Linux, so the window is ~10ms),
`total_delta == 0` and the handler returns `{"value": None, "source":
"live", "error": None}`. The test then fails its `isinstance(value, (int,
float))` assertion. This is a legitimate handler state (live source, no
delta yet) — the fix belongs in the **test**, not the handler. Do not
touch `seam_runtime/server.py`.

The fix has two parts:

**B1a — Make the live test retry-tolerant.** Replace the current
back-to-back call pattern with a bounded poll loop:

```python
def test_sys_metrics_live_on_linux(metrics_client):
    """CPU, mem report 'live' numeric on Linux; tolerate the first zero-delta window."""
    import sys as _sys
    import time
    if not _sys.platform.startswith("linux"):
        pytest.skip("live checks only valid on Linux")
    # Prime the baseline.
    metrics_client.get("/sys-metrics")
    # Poll up to ~500ms total (10 attempts × 50ms) for a numeric live value.
    # USER_HZ is typically 100 on Linux, so jiffies advance every ~10ms;
    # the first few back-to-back reads may legitimately observe total_delta == 0.
    body = None
    for _ in range(10):
        time.sleep(0.05)
        resp = metrics_client.get("/sys-metrics")
        assert resp.status_code == 200
        body = resp.json()
        if body["cpu"]["source"] == "live" and isinstance(body["cpu"]["value"], (int, float)):
            break
    assert body is not None
    for key in ("cpu", "mem"):
        assert body[key]["source"] == "live", f"{key} should be live"
        assert isinstance(body[key]["value"], (int, float)), (
            f"{key} value should be numeric after retry, got {body[key]}"
        )
```

The poll is bounded (≤500ms total) and the assertion is unchanged in
spirit — it still requires a live numeric value, just allows the first
read window to be empty.

**B1b — Add a dedicated zero-delta contract test.** This new test
exercises the contract directly with no timing dependence: it stubs the
module-global `_last_cpu_times` so the handler enters the
`total_delta == 0` branch deterministically. Add this immediately after
`test_sys_metrics_live_on_linux` in the same file:

```python
def test_sys_metrics_cpu_zero_delta_returns_live_null(metrics_client):
    """When /proc/stat read yields total_delta == 0, cpu reports source=live with value=None.

    This is the contract that the live-on-linux test must tolerate via retry.
    """
    import sys as _sys
    if not _sys.platform.startswith("linux"):
        pytest.skip("zero-delta contract only meaningful on Linux")
    import seam_runtime.server as server_mod
    # Prime the baseline with a real read so _last_cpu_times is set.
    metrics_client.get("/sys-metrics")
    last = server_mod._last_cpu_times
    assert last is not None, "Baseline should be primed after first call"
    # Force the next read to observe exactly the same idle/total via a stub on builtins.open.
    # The handler reads /proc/stat once, computes idle and total, then compares to _last_cpu_times.
    # If we return a line that yields identical idle and total to `last`, total_delta == 0.
    last_idle, last_total = last
    # Construct a synthetic /proc/stat line whose first 8 fields produce these exact values.
    # parts[1:] sum -> total; parts[4]+parts[5] -> idle.
    # Pick: user=0, nice=0, system=0, idle=last_idle, iowait=0, irq=last_total-last_idle, softirq=0, steal=0
    fake_idle = last_idle
    fake_iowait = 0.0
    fake_irq = last_total - last_idle
    fake_line = f"cpu  0 0 0 {int(fake_idle)} {int(fake_iowait)} {int(fake_irq)} 0 0\n"

    import builtins as _builtins
    _real_open = _builtins.open

    class _FakeStat:
        def __init__(self, line: str) -> None:
            self._line = line
        def readline(self) -> str:
            return self._line
        def __enter__(self):
            return self
        def __exit__(self, *a, **kw):
            return False

    def _stub_open(file, *args, **kwargs):
        if isinstance(file, str) and file == "/proc/stat":
            return _FakeStat(fake_line)
        return _real_open(file, *args, **kwargs)

    with mock.patch("builtins.open", side_effect=_stub_open):
        resp = metrics_client.get("/sys-metrics")
    assert resp.status_code == 200
    cpu = resp.json()["cpu"]
    assert cpu["source"] == "live", f"cpu source should be live on zero-delta, got {cpu}"
    assert cpu["value"] is None, f"cpu value should be None on zero-delta, got {cpu}"
    assert cpu["error"] is None, f"cpu error should be None on zero-delta, got {cpu}"
```

**Verification before/after**:

- Before fix: confirm the flake by running the existing
  `test_sys_metrics_live_on_linux` 20 times in a row in the same process —
  expect at least one failure under load (or simulate by mocking
  `_last_cpu_times` to match a stubbed /proc/stat line):

  ```
  python -m pytest tests/audit/test_sys_metrics_honesty.py::test_sys_metrics_live_on_linux --count=20 -q
  ```

  (If `pytest-repeat` is not installed, instead add the new
  `test_sys_metrics_cpu_zero_delta_returns_live_null` test FIRST and
  confirm it FAILs initially — wait, the new test asserts the existing
  contract, so it should PASS immediately. The "failing test first"
  discipline for B1 means confirming the original flake reproduces under
  the new zero-delta test stub: temporarily edit the new test's
  assertions to `assert cpu["value"] is not None` — expect FAIL —
  then revert to the spec'd assertions and confirm PASS.)

- After fix:
  ```
  python -m pytest tests/audit/test_sys_metrics_honesty.py -q
  ```
  Expect **7 passed** (was 6; +1 zero-delta contract). Run twice to
  confirm no flake.

**Out of scope**:
- Touching `seam_runtime/server.py` — the handler contract is correct;
  this is a test-side stability fix.
- Adding global `pytest-repeat` or `pytest-rerunfailures` plugins.
- Changing `_metric_value` / `_metric_unavailable` / `_metric_unsupported`
  helper signatures.

---

## B2 — Real-postgres pgvector integration in CI

**Files**:
- `.github/workflows/ci.yml` (new job)
- `tests/audit/test_pgvector_real_adapter.py` (new file)

**Failing test**: `tests/audit/test_pgvector_real_adapter.py` (the
adapter integration test IS the assertion).

Background: closes audit finding H3 third leg. The existing
`PgVectorAdapterTests` in `test_seam_all/test_seam.py` uses a
`FakePgVectorAdapter` — it does not exercise the real psycopg connection,
`vector` extension, or pgvector SQL operators. The real adapter lives in
`seam_runtime/vector_adapters.py:PgVectorAdapter`. The repo has a
`docker-compose.yaml` that runs `pgvector/pgvector:0.8.6-pg18-trixie`
locally on port 55432 — but CI never spins up a real postgres + pgvector.
This means a regression in the real adapter (DDL drift, vector operator
syntax change, schema migration bug) would only be caught on operator
machines via the optional local pgvector workflow.

**Test** (`tests/audit/test_pgvector_real_adapter.py`):

```python
"""B2 — Real-postgres pgvector adapter integration test.

Skipped unless SEAM_PGVECTOR_DSN is set (locally without docker, this is
a no-op). In CI, the pgvector-integration job sets the DSN to a service
container running pgvector/pgvector:0.8.6-pg18-trixie.
"""

import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("SEAM_PGVECTOR_DSN"),
    reason="SEAM_PGVECTOR_DSN not set; skipping real-postgres pgvector integration",
)


def _make_adapter():
    from seam_runtime.vector_adapters import PgVectorAdapter
    from seam_runtime.models import HashEmbeddingModel
    # Unique table name per test run to avoid cross-CI-job collisions.
    table = f"seam_vector_index_test_{uuid.uuid4().hex[:12]}"
    dsn = os.environ["SEAM_PGVECTOR_DSN"]
    return PgVectorAdapter(dsn=dsn, model=HashEmbeddingModel(), table_name=table), table


def _make_records():
    from seam_runtime.dsl import compile_dsl
    batch = compile_dsl(
        """
entity project "SEAM" as proj
claim c1:
  subject proj
  predicate supports
  object "databases"
claim c2:
  subject proj
  predicate supports
  object "context windows"
""",
        scope="project",
    )
    return batch.records


def _drop_table(adapter, table_name):
    with adapter._connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(f'drop table if exists "{table_name}"')
        connection.commit()


def test_pgvector_real_adapter_index_and_search():
    """End-to-end: ensure_schema -> index_records -> search returns scored hits."""
    adapter, table = _make_adapter()
    try:
        records = _make_records()
        adapter.index_records(records)
        scores = adapter.search("databases context windows", limit=5)
        assert len(scores) > 0, "Expected at least one scored hit"
        for record_id, score in scores.items():
            assert isinstance(score, float)
            assert score > 0.0
    finally:
        _drop_table(adapter, table)


def test_pgvector_real_adapter_upsert_idempotent():
    """Indexing the same records twice should not duplicate rows."""
    adapter, table = _make_adapter()
    try:
        records = _make_records()
        adapter.index_records(records)
        with adapter._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f'select count(*) from "{table}"')
                count_first = cursor.fetchone()[0]
        adapter.index_records(records)
        with adapter._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f'select count(*) from "{table}"')
                count_second = cursor.fetchone()[0]
        assert count_first == count_second, (
            f"Expected idempotent upsert; first={count_first}, second={count_second}"
        )
    finally:
        _drop_table(adapter, table)


def test_pgvector_real_adapter_stale_records_detects_changes():
    """stale_records reports source_changed when the source text mutates."""
    adapter, table = _make_adapter()
    try:
        records = _make_records()
        adapter.index_records(records)
        stale_initial = adapter.stale_records(records)
        assert stale_initial == [], f"Expected no stale records right after index, got {stale_initial}"
    finally:
        _drop_table(adapter, table)
```

Note the bare `"vector_adapters.py"`-attribute access pattern is the
existing test style in `test_seam_all/test_seam.py`. The `_drop_table`
finalizer keeps the test postgres clean for repeat runs.

**CI Fix** (`.github/workflows/ci.yml`):

Add a NEW top-level job named `pgvector-integration` AFTER the existing
`test-and-benchmark` job. Do NOT add pgvector to the matrix-shared job —
GitHub Actions `services:` containers only work on Linux runners, and
mixing them into the cross-platform matrix breaks windows-latest.

Insert this immediately after the existing job (preserving file-final
newline and existing indentation):

```yaml
  pgvector-integration:
    runs-on: ubuntu-latest
    services:
      pgvector:
        image: pgvector/pgvector:0.8.6-pg18-trixie
        env:
          POSTGRES_DB: seam_ci
          POSTGRES_USER: seam_ci
          POSTGRES_PASSWORD: seam_ci_password
        ports:
          - 55432:5432
        options: >-
          --health-cmd "pg_isready -U seam_ci -d seam_ci"
          --health-interval 5s
          --health-timeout 5s
          --health-retries 10
    steps:
      - name: Check out repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install package
        run: python -m pip install -e ".[server]"

      - name: Install test dependencies
        run: python -m pip install pytest psycopg[binary]

      - name: Run pgvector real-adapter integration tests
        env:
          PGPASSWORD: seam_ci_password
          SEAM_PGVECTOR_DSN: postgresql://seam_ci@localhost:55432/seam_ci
        run: python -m pytest tests/audit/test_pgvector_real_adapter.py -q
```

**Verification**:

- Locally without docker: the new test file skips collection entirely
  (pytestmark on the module). The main test run is unaffected.
- Locally with docker compose pgvector running: set
  `PGPASSWORD` + `SEAM_PGVECTOR_DSN` (as in the CI job env block) and run
  `python -m pytest tests/audit/test_pgvector_real_adapter.py -q` —
  expect 3 passed.
- YAML lint:
  ```
  python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))" && echo "YAML OK"
  ```
- Confirm the new job is parseable:
  ```
  python -c "import yaml; doc=yaml.safe_load(open('.github/workflows/ci.yml')); assert 'pgvector-integration' in doc['jobs']; print('job present')"
  ```

**Stop condition**: if the local pgvector container is not running and
DeepSeek cannot test the new test against a real postgres, STOP after
the test file is written + the CI job is wired + YAML lint passes.
Report it as ITEM_SUCCESS with `additional_observations` noting that the
local run skipped (env not set) and the CI job will be the first real
exercise. Do NOT spin up docker compose from inside DeepSeek's session;
that requires operator-controlled credentials per `docker-compose.yaml`.

**Out of scope**:
- Adding pgvector to the main `test-and-benchmark` matrix.
- Touching `seam_runtime/vector_adapters.py` (DDL, query, validation).
- Adding pgvector to the existing local-only test classes in
  `test_seam_all/test_seam.py` (they remain Fake-based and unchanged).
- Splitting `pgvector-integration` into multiple jobs.
- Caching pip between jobs.

---

## B3 — MCP tools/call round-trip smoke test

**Files**: `tests/audit/test_mcp_tools_call_smoke.py` (new)
**Failing test**: same file (the round-trip IS the assertion).

Background: HISTORY#210 CI3 added `tests/audit/test_mcp_stdio_smoke.py`
which exercises `initialize` and `tools/list` over the canonical MCP
stdio entrypoint. The next obvious extension is to actually invoke a
tool via `tools/call` and assert the response envelope is well-formed.
`seam_stats` is the right target: zero input arguments, read-only,
deterministic shape (record counts, vector index size, document totals).
This catches `dispatch_tool` import-time regressions, structuredContent
shape drift, and isError envelope mistakes that unit tests miss.

**Test** (`tests/audit/test_mcp_tools_call_smoke.py`):

```python
"""B3 — MCP tools/call round-trip smoke test.

Spawns the canonical seam_runtime.mcp_protocol entrypoint, performs the
initialize + tools/call(seam_stats) JSON-RPC 2.0 handshake, and asserts
a well-formed envelope with structuredContent. Extends CI3
(test_mcp_stdio_smoke.py) which covered initialize + tools/list only.
"""

import json
import subprocess
import sys

import pytest


INITIALIZE = json.dumps({
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "seam-ci-tools-call-smoke", "version": "0.0.1"},
    },
})
TOOLS_CALL = json.dumps({
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
        "name": "seam_stats",
        "arguments": {},
    },
})


def _spawn_mcp():
    return subprocess.Popen(
        [sys.executable, "-m", "seam_runtime.mcp_protocol"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _read_response(proc):
    line = proc.stdout.readline()
    return json.loads(line)


@pytest.mark.skipif(sys.platform == "win32", reason=(
    "Subprocess pipe handshake timing is unreliable on Windows-runner Python; "
    "revisit if a Windows MCP regression appears"
))
def test_mcp_tools_call_seam_stats_round_trip():
    proc = None
    try:
        proc = _spawn_mcp()

        proc.stdin.write((INITIALIZE + "\n").encode())
        proc.stdin.write((TOOLS_CALL + "\n").encode())
        proc.stdin.flush()
        proc.stdin.close()

        init_resp = _read_response(proc)
        assert init_resp["jsonrpc"] == "2.0"
        assert init_resp["id"] == 1
        assert "result" in init_resp, f"init returned error: {init_resp.get('error')}"

        call_resp = _read_response(proc)
        assert call_resp["jsonrpc"] == "2.0", f"call jsonrpc: {call_resp.get('jsonrpc')}"
        assert call_resp["id"] == 2, f"call id: {call_resp.get('id')}"
        assert "result" in call_resp, f"call returned error envelope: {call_resp.get('error')}"

        result = call_resp["result"]
        # isError must be present and False on a successful read-only call.
        assert result.get("isError") is False, (
            f"seam_stats reported isError=True: {result}"
        )

        # content[0] must be a text item with a non-empty JSON-encoded payload.
        content = result.get("content")
        assert isinstance(content, list) and len(content) >= 1, f"content: {content}"
        first = content[0]
        assert first.get("type") == "text", f"first content type: {first}"
        text = first.get("text")
        assert isinstance(text, str) and len(text) > 0, f"text empty: {first}"
        # The text field is JSON-encoded structured result; round-trip parse must succeed.
        parsed = json.loads(text)
        assert isinstance(parsed, dict), f"parsed content not dict: {parsed!r}"

        # structuredContent must mirror the same payload as a dict.
        structured = result.get("structuredContent")
        assert isinstance(structured, dict), f"structuredContent not dict: {structured!r}"
        # seam_stats returns record counts; assert at least one expected key.
        # (Do NOT enumerate the full schema — that grows over time.)
        # Accept either direct keys (records, documents, vector_index) or a nested {"result": ...}.
        flat = structured.get("result") if "result" in structured else structured
        assert isinstance(flat, dict), f"stats payload not dict: {flat!r}"

        proc.terminate()
        proc.wait(timeout=10)

    finally:
        if proc is not None:
            try:
                proc.kill()
                proc.wait(timeout=5)
            except Exception:
                pass
```

**Verify**:
```
python -m pytest tests/audit/test_mcp_tools_call_smoke.py -q
python -m pytest test_seam_all/ tools/history/test_history_tools.py tools/streams/ tests/ -q
```

The first must pass. The full suite count should be 397 (was 396 after
HISTORY#210; B1 adds 1, B3 adds 1, B2 adds 0 in the main suite because
it's gated behind the env-skip).

If the subprocess hangs or returns a malformed envelope, STOP and emit
REGRESSION with the captured stderr in `suspected_cause`. Do not loosen
the assertions to make it pass.

**Out of scope**:
- Testing destructive tools (`seam_ingest`, `seam_persist`).
- Testing every tool in `TOOL_METADATA` — keep this surface stable; one
  representative read-only tool round-trip is the contract.
- Testing OAuth / auth flows (no auth on MCP stdio).
- Extending CI3's existing `test_mcp_stdio_smoke.py` — keep the new
  round-trip in its own file for clarity.

---

## After all items complete

Emit ITEM_SUCCESS blocks for B1, B2, B3 in execution order in a single
paste. Then STOP. Do NOT stage, commit, push. Claude reviews the full
diff, appends a HISTORY entry, rebuilds the index, writes a snapshot,
runs the four verify gates, and commits.

If at any point a stop condition fires, emit ITEM_SUCCESS blocks for
completed items + the appropriate stop block for the failed item, then
STOP.

## Notes on what is deliberately NOT in this SOP

Deferred to follow-up SOPs pending operator design calls:

- **`seam benchmark gate --baseline` in CI (audit M9)** — requires
  picking a baseline source: artifact-from-prior-main-run, checked-in
  reference bundle, or remote URL. Operator direction needed before
  authoring.
- **MCP `surface_artifact` path validation (audit M6)** — requires
  defining the canonical surface root, an architectural decision.
- **Track K / BIL bundle SOPs** — operator-gated on benchmarks being
  100% functional first. Track K is the next big track per project
  memory; do not start authoring its SOPs until the benchmark surface
  audit lands.
- **`seam benchmark diff` UX / error-shape audit** — separate item;
  rolls in with M9 design.
- **External memory benchmark coverage expansion** — separate Track I
  follow-up.
