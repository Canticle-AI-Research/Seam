# SOP: Mem0 LoCoMo Comparator Adapter

Handoff target: DeepSeek (or any contributor)
Track: I — External Memory Benchmarks
Canonical spec: `docs/roadmap/MEMORY_BENCHMARKS.md`
Sequence: **SOP 3 of 5.** Prereqs: SOP 0 (registry/runner), SOP 1 (SEAM LoCoMo adapter). Recommended companion: SOP 2 (LLM-judge). Follow-up: SOP 4 (Zep comparator).

## 1. Goal

Add Mem0 as a comparator memory system for the LoCoMo benchmark so a user can run:

```bash
seam bench external --quickstart locomo --adapter mem0
```

and get an apples-to-apples comparison against SEAM on the same quickstart fixture and the same scoring functions.

The first real scoreboard becomes possible after this PR lands: `seam bench external --quickstart locomo --adapter seam` and `... --adapter mem0` produce JSON reports that can be diffed.

## 2. Scope

In:
- `benchmarks/external/locomo/adapters/mem0.py` — Mem0 adapter implementing `MemorySystemAdapter`
- `benchmarks/external/locomo/run.py` — `--adapter mem0` choice; adapter factory
- `pyproject.toml` — `bench-mem0` optional extra
- Tests with a stub Mem0 client (no live API calls in CI)
- `benchmarks/external/README.md` — Mem0 setup section
- `benchmarks/external/locomo/README.md` (new) — comparator setup matrix
- HISTORY entry

Out:
- Zep comparator (SOP 4)
- A SEAM-vs-Mem0 publishable scoreboard (informal local comparison only — publish requires SOP 2 + Track K wrapping)
- Mem0's own scoring system (we use SEAM's `scoring.py`, not Mem0's)
- Cost tracking

## 3. Prerequisites

- SOP 0 and SOP 1 merged on `main`
- A working `seam bench external --quickstart locomo --adapter seam` baseline run on the dev machine
- Read Mem0's quickstart: https://docs.mem0.ai/quickstart
- Mem0 v1.0+ Python SDK (`pip install mem0ai`)
- An LLM provider API key for Mem0 to use as its backing model (Mem0 calls an LLM during `add` and `search` for extraction and ranking — typically OpenAI). Document this requirement; do not assume the user already has one.

## 4. Files to create or modify

### 4.1 `benchmarks/external/locomo/adapters/mem0.py` (new)

```python
from __future__ import annotations
import os, time, tempfile
from typing import Iterable

from benchmarks.external.common.types import (
    AdapterAnswer,
    ConversationTurn,
    MemorySystemAdapter,
)

class Mem0LocomoAdapter:
    """Mem0 (mem0ai) comparator adapter for LoCoMo.

    One Mem0 user_id per scope_id. Conversation turns are added as user/assistant
    messages with metadata. `answer` runs Mem0 search and returns the joined
    retrieved memories as retrieved_context. Like the SEAM adapter, this
    adapter does NOT generate an answer; LLM-judge scoring is layered separately.
    """
    name = "mem0"

    def __init__(self, *, search_limit: int = 8, config_overrides: dict | None = None):
        try:
            from mem0 import Memory
        except ImportError as exc:
            raise RuntimeError(
                "--adapter mem0 requires the mem0ai package. "
                "Install with: pip install seam[bench-mem0]"
            ) from exc
        # Require an LLM key. Mem0 default is OpenAI; allow override via Mem0 config.
        if not os.environ.get("OPENAI_API_KEY") and not (config_overrides or {}).get("llm"):
            raise RuntimeError(
                "Mem0 requires an LLM provider. Set OPENAI_API_KEY or pass config_overrides."
            )
        self.search_limit = search_limit
        # Use a per-process Mem0 instance with a local Chroma/Qdrant store under
        # a temp dir so we never write to the operator's default Mem0 path.
        self._store_dir = tempfile.mkdtemp(prefix="seam-bench-mem0-")
        config = self._build_config(self._store_dir, config_overrides)
        self._memory = Memory.from_config(config)
        self._seen_user_ids: set[str] = set()

    @staticmethod
    def _build_config(store_dir: str, overrides: dict | None) -> dict:
        cfg = {
            "vector_store": {
                "provider": "chroma",
                "config": {"path": store_dir, "collection_name": "seam_bench_mem0"},
            },
            # Mem0 default LLM/embedder (OpenAI). Operator can override.
        }
        if overrides:
            cfg.update(overrides)
        return cfg

    def reset(self, scope_id: str) -> None:
        # Mem0 isolates by user_id. Delete all memories for this scope_id.
        try:
            self._memory.delete_all(user_id=scope_id)
        except Exception:
            # First-use case: nothing to delete.
            pass
        self._seen_user_ids.add(scope_id)

    def ingest_turn(self, scope_id: str, turn: ConversationTurn) -> None:
        role = "user" if turn.speaker.lower().startswith(("speaker_a", "alice", "user")) else "assistant"
        prefix = f"[{turn.speaker} {turn.timestamp or ''}] ".rstrip() + " "
        messages = [{"role": role, "content": prefix + turn.text}]
        self._memory.add(messages, user_id=scope_id)

    def answer(self, scope_id: str, question: str) -> AdapterAnswer:
        t0 = time.perf_counter()
        results = self._memory.search(query=question, user_id=scope_id, limit=self.search_limit)
        retrieval_ms = (time.perf_counter() - t0) * 1000.0
        # Mem0 v1.0+ returns {"results": [{"memory": "...", "score": ...}, ...]}
        items = results.get("results", results) if isinstance(results, dict) else results
        joined = "\n".join(item.get("memory", "") if isinstance(item, dict) else str(item) for item in items)
        return AdapterAnswer(
            retrieved_context=joined,
            generated_answer=None,
            retrieval_latency_ms=retrieval_ms,
            answer_latency_ms=0.0,
        )

    def close(self) -> None:
        import shutil
        shutil.rmtree(self._store_dir, ignore_errors=True)
```

Keep this file under 200 lines. If Mem0's API surface changes (it has been moving fast), pin a known-good version in the optional extra and document the pin.

### 4.2 `benchmarks/external/locomo/run.py` (modify)

Add `--adapter` flag:

```python
parser.add_argument(
    "--adapter",
    default="seam",
    choices=["seam", "mem0"],
    help="Memory system under test",
)
```

Add adapter factory:

```python
def build_adapter(name: str):
    if name == "seam":
        from benchmarks.external.locomo.adapters.seam import SeamLocomoAdapter
        return SeamLocomoAdapter()
    if name == "mem0":
        from benchmarks.external.locomo.adapters.mem0 import Mem0LocomoAdapter
        return Mem0LocomoAdapter()
    raise ValueError(f"unknown adapter {name!r}")
```

Lazy-import inside the factory so SEAM-only runs do not require Mem0 installed.

Current runner note: the live LoCoMo runner also exposes
`--mem0-search-limit` and `SEAM_BENCH_MEM0_SEARCH_LIMIT` so paid diagnostics can
raise mem0 retrieval depth above the default `8` without editing the adapter.
Keep the default at `8` for backward-compatible quickstart/comparator smoke
runs; use explicit higher values for controlled fairness probes.

### 4.3 `seam_runtime/cli.py` (modify)

Add `--adapter` to `seam bench external` parser. Default `seam`.

### 4.4 `pyproject.toml` (modify)

```toml
[project.optional-dependencies]
bench-mem0 = ["mem0ai>=0.1.0", "chromadb>=0.4.0"]
```

Pin a known-good `mem0ai` version range when possible; Mem0 has shipped breaking changes between minor versions historically.

### 4.5 `test_seam_all/test_locomo_mem0_adapter.py` (new)

Cover with a **stub Mem0**:

```python
class _StubMem0:
    def __init__(self): self.store = {}
    def add(self, messages, user_id): self.store.setdefault(user_id, []).extend(messages)
    def search(self, query, user_id, limit):
        items = [{"memory": m["content"], "score": 1.0} for m in self.store.get(user_id, [])][:limit]
        return {"results": items}
    def delete_all(self, user_id): self.store.pop(user_id, None)
```

Monkeypatch `mem0.Memory.from_config` to return the stub (or refactor the adapter to accept an injected `_memory` for testability). Then:

- `Mem0LocomoAdapter` constructs against the stub without raising
- `ingest_turn` stores turn into the stub
- `answer` returns joined retrieved_context with the ingested text
- `reset` clears scope state
- Without `OPENAI_API_KEY` and without `config_overrides`, constructor raises `RuntimeError` with a clear message
- Without `mem0ai` installed, constructor raises `RuntimeError` pointing at the `seam[bench-mem0]` install command (simulate via `sys.modules` monkeypatch)

Do **not** call the real Mem0 SDK in any test.

### 4.6 `benchmarks/external/locomo/README.md` (new)

Comparator matrix table:

| Adapter | Install | Required env | Local data path |
|---|---|---|---|
| `seam` | base install | none | per-scope SQLite under `test_seam/locomo/` |
| `mem0` | `pip install seam[bench-mem0]` | `OPENAI_API_KEY` (or Mem0 config override) | temp Chroma store |
| `zep` | (SOP 4) | (SOP 4) | (SOP 4) |

Include a "Reproducing a comparison" section:
```bash
seam bench external --quickstart locomo --adapter seam --output /tmp/seam.json
seam bench external --quickstart locomo --adapter mem0 --output /tmp/mem0.json
python -m benchmarks.external.locomo.compare /tmp/seam.json /tmp/mem0.json
```

If `compare` does not exist yet, plant a TODO and reference SOP 5 (future) for the comparison rendering.

### 4.7 `benchmarks/external/README.md` (modify)

Add a "Comparators" section pointing at `locomo/README.md`. Reaffirm the publish rule: no public "SEAM beats X" claims without SOP 2 (judge) + Track K BIL wrapping.

## 5. DeepSeek implementation checklist

- [ ] SOPs 0 and 1 merged on `main`
- [ ] `pip install mem0ai chromadb` on dev machine; baseline `from mem0 import Memory` works
- [ ] Created `benchmarks/external/locomo/adapters/mem0.py` per section 4.1, under 200 lines
- [ ] Lazy import of `mem0` inside `__init__`
- [ ] Clear error message when `OPENAI_API_KEY` missing
- [ ] Per-scope `user_id` isolation; `delete_all` on reset
- [ ] Mem0 store written under `tempfile.mkdtemp(...)`, not the user's home dir
- [ ] `close()` cleans the temp dir
- [ ] Added `--adapter` flag and factory to `benchmarks/external/locomo/run.py`
- [ ] Added `--adapter` to `seam bench external` in `seam_runtime/cli.py`
- [ ] Added `bench-mem0` optional extra in `pyproject.toml` with pinned version
- [ ] Wrote `test_seam_all/test_locomo_mem0_adapter.py` with stub Mem0, all cases in section 4.5
- [ ] No live Mem0 / OpenAI / Anthropic calls in tests
- [ ] All tests pass (`pytest test_seam_all/test_locomo_mem0_adapter.py -v`)
- [ ] Full suite still passes (`pytest test_seam_all -x`)
- [ ] Created `benchmarks/external/locomo/README.md` with the comparator matrix
- [ ] Updated `benchmarks/external/README.md` with the Comparators section
- [ ] Ran a real comparison on dev machine: `--adapter seam` and `--adapter mem0` against the quickstart fixture; recorded both JSON reports (do not commit them)
- [ ] Appended HISTORY entry per template in section 8
- [ ] `python -m tools.history.verify_continuity` passes
- [ ] Pushed branch and opened **draft** PR titled `Phase 4: Mem0 LoCoMo comparator adapter`

## 6. Reviewer verification checklist

- [ ] `pip install -e .` (without `[bench-mem0]`) succeeds; `seam bench external --quickstart locomo --adapter seam` still works
- [ ] `seam bench external --quickstart locomo --adapter mem0` (without Mem0 installed) prints a clear error mentioning `pip install seam[bench-mem0]` and exits non-zero
- [ ] `pip install -e ".[bench-mem0]"` succeeds
- [ ] `seam bench external --quickstart locomo --adapter mem0` (without `OPENAI_API_KEY`) prints a clear error mentioning the env var and exits non-zero
- [ ] With both installed and `OPENAI_API_KEY` set, `seam bench external --quickstart locomo --adapter mem0 --output /tmp/mem0.json` runs end-to-end and produces a valid `SEAM-EXTERNAL-MEMORY-BENCHMARK-RESULT/1` JSON
- [ ] `pytest test_seam_all/test_locomo_mem0_adapter.py -v` passes (6+ tests)
- [ ] `pytest test_seam_all -x` passes (full suite)
- [ ] `grep -RE "mem0|chromadb" requirements.txt` returns nothing (must stay in optional extras only)
- [ ] `grep -RE "(sk-[A-Za-z0-9]{20,})" benchmarks/ test_seam_all/test_locomo_mem0_adapter.py` returns nothing
- [ ] No test calls the real Mem0 SDK (grep `from mem0 import` in tests should show only the import inside a monkeypatch-guarded fixture)
- [ ] Temp dir cleanup: `ls /tmp | grep seam-bench-mem0-` after a run shows nothing (the adapter's `close` ran)
- [ ] `python -m tools.history.verify_continuity` passes
- [ ] PR description ticks every box in section 5

## 7. Acceptance commands

```bash
pip install -e .

# SEAM-only path unchanged
seam bench external --quickstart locomo --adapter seam --output /tmp/seam.json

# Mem0 path needs the optional extra and an API key
pip install -e ".[bench-mem0]"
OPENAI_API_KEY=<your-key> seam bench external --quickstart locomo --adapter mem0 --output /tmp/mem0.json

# Eyeball the comparison
jq '{adapter, scores}' /tmp/seam.json /tmp/mem0.json

# Tests
pytest test_seam_all/test_locomo_mem0_adapter.py -v
pytest test_seam_all -x

python -m tools.history.verify_continuity
```

## 8. HISTORY entry template

```yaml
id: NNN
date: <ISO date>
agent: deepseek
status: done
topics: [benchmark, retrieval, command, protocol]
commits: [<sha>]
refs:
  - benchmarks/external/locomo/adapters/mem0.py
  - benchmarks/external/locomo/run.py
  - benchmarks/external/locomo/README.md
  - benchmarks/external/README.md
  - seam_runtime/cli.py
  - pyproject.toml
  - test_seam_all/test_locomo_mem0_adapter.py
  - docs/SOP_EXTERNAL_BENCH_MEM0_COMPARATOR.md
supersedes: <last benchmark-topic entry id>
tokens: ~<count>
body: |
  Added Mem0 (mem0ai) comparator adapter for the LoCoMo external memory
  benchmark. Lives behind seam[bench-mem0] optional extra. Per-scope
  user_id isolation, temp Chroma store, no writes to operator's default
  Mem0 path. First apples-to-apples SEAM-vs-Mem0 run is now reproducible
  on the quickstart fixture. No publishable scoreboard claim until SOP 2
  (LLM-judge) and Track K (BIL wrapping) are in.
```

## 9. Pitfalls

- **Mem0 calls an LLM during `add`.** Even quickstart ingest costs tokens. Document this in the README so users are not surprised by a $0.50 bill on a "quickstart."
- **Mem0's API has churned.** Pin `mem0ai` and Chroma versions. When upgrading, re-run all adapter tests and the live `--adapter mem0` quickstart.
- **Do not let Mem0 write to the operator's default path** (`~/.mem0` or similar). Always pass a temp dir in the config. Confirm with `lsof` or `strace` on a test run that no writes happen outside `tempfile`.
- **Do not import `mem0` at module top level.** Lazy-import inside `__init__`.
- **Do not commit any Mem0 dataset or vector store** (`*.parquet`, `chroma.sqlite3`, `*.bin`) from a test run.
- **Do not claim "SEAM beats Mem0" in any commit message, README, HISTORY entry, or PR description from this PR.** First comparison is informal local evidence. Publish requires SOP 2 + Track K.
- **Per AGENTS.md security rules**, never log Mem0 API keys, never write `OPENAI_API_KEY` into the report JSON, never commit `.env` files.

## 10. Estimated scope

~500-800 lines net. One review cycle. Optional extra: `mem0ai`, `chromadb`. No change to SEAM core.
