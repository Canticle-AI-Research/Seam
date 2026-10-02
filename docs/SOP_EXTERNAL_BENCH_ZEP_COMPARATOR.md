# SOP: Zep / Graphiti LoCoMo Comparator Adapter

Handoff target: DeepSeek (or any contributor)
Track: I — External Memory Benchmarks
Canonical spec: `docs/roadmap/MEMORY_BENCHMARKS.md`
Sequence: **SOP 4 of 5.** Prereqs: SOP 0 (registry/runner), SOP 1 (SEAM LoCoMo adapter), SOP 3 (Mem0 comparator — same factory/CLI pattern). Recommended companion: SOP 2 (LLM-judge).

## 1. Goal

Add Zep (specifically Zep Cloud / Zep Community Edition v2 via the `zep-cloud` or `zep-python` SDK) as a comparator memory system for the LoCoMo benchmark:

```bash
seam bench external --quickstart locomo --adapter zep
```

After this PR the first three-way scoreboard becomes possible: SEAM, Mem0, Zep on the same fixture and the same scoring functions. That is the minimum required comparator set per `MEMORY_BENCHMARKS.md` (Mem0, Zep, Letta/MemGPT) before public scoreboard claims can stand on their own.

## 2. Scope

In:
- `benchmarks/external/locomo/adapters/zep.py` — Zep adapter implementing `MemorySystemAdapter`
- `benchmarks/external/locomo/run.py` — extend `--adapter` choices with `zep`; extend factory
- `pyproject.toml` — `bench-zep` optional extra
- Tests with a stub Zep client (no live API calls in CI)
- `benchmarks/external/locomo/README.md` — Zep row in comparator matrix
- HISTORY entry

Out:
- Letta / MemGPT comparator (future SOP — not yet drafted)
- A managed Zep Cloud deployment (we assume the operator supplies credentials or a self-hosted endpoint)
- Zep's own graph-export visualization

## 3. Prerequisites

- SOP 0, SOP 1, and SOP 3 (Mem0) merged on `main`
- A working `seam bench external --quickstart locomo --adapter mem0` baseline run (the factory pattern is identical)
- A Zep deployment to point at — either:
  - Zep Cloud account + API key (set `ZEP_API_KEY`), or
  - Self-hosted Zep CE running locally with `ZEP_API_URL=http://localhost:8000` and no key
- Zep Python SDK: `pip install zep-cloud` (Zep Cloud) — confirm SDK name at install time; SDK package names have moved.

## 4. Files to create or modify

### 4.1 `benchmarks/external/locomo/adapters/zep.py` (new)

```python
from __future__ import annotations
import os, time
from typing import Iterable

from benchmarks.external.common.types import (
    AdapterAnswer,
    ConversationTurn,
    MemorySystemAdapter,
)

class ZepLocomoAdapter:
    """Zep / Graphiti comparator adapter for LoCoMo.

    One Zep `user_id` per scope_id; one Zep `session_id` per scope_id. Conversation
    turns added as messages on the session. `answer` runs Zep memory search and
    returns the joined retrieved facts as retrieved_context. Like the SEAM and
    Mem0 adapters, this adapter does NOT generate an answer.
    """
    name = "zep"

    def __init__(self, *, search_limit: int = 8):
        try:
            from zep_cloud.client import Zep
        except ImportError:
            try:
                from zep_python.client import Zep  # older SDK path
            except ImportError as exc:
                raise RuntimeError(
                    "--adapter zep requires the zep-cloud (or zep-python) package. "
                    "Install with: pip install -e .[bench-zep]"
                ) from exc
        api_key = os.environ.get("ZEP_API_KEY")
        base_url = os.environ.get("ZEP_API_URL")
        if not api_key and not base_url:
            raise RuntimeError(
                "Zep requires ZEP_API_KEY (Zep Cloud) or ZEP_API_URL "
                "(self-hosted Zep CE) in the environment."
            )
        kwargs = {}
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["base_url"] = base_url
        self._client = Zep(**kwargs)
        self.search_limit = search_limit
        self._sessions: dict[str, str] = {}

    def reset(self, scope_id: str) -> None:
        # Ensure a fresh user + session for this scope.
        user_id = f"seam-bench-{scope_id}"
        session_id = f"seam-bench-{scope_id}-session"
        try:
            self._client.user.delete(user_id=user_id)
        except Exception:
            pass
        self._client.user.add(user_id=user_id)
        self._client.memory.add_session(session_id=session_id, user_id=user_id)
        self._sessions[scope_id] = session_id

    def ingest_turn(self, scope_id: str, turn: ConversationTurn) -> None:
        session_id = self._sessions[scope_id]
        role = "user" if turn.speaker.lower().startswith(("speaker_a", "alice", "user")) else "assistant"
        prefix = f"[{turn.speaker} {turn.timestamp or ''}] ".rstrip() + " "
        self._client.memory.add(
            session_id=session_id,
            messages=[{"role": role, "role_type": role, "content": prefix + turn.text}],
        )

    def answer(self, scope_id: str, question: str) -> AdapterAnswer:
        session_id = self._sessions[scope_id]
        t0 = time.perf_counter()
        # Zep's memory.search / memory.get returns a payload that includes facts,
        # summary, and messages. Pull the most-relevant facts list when present.
        results = self._client.memory.search_sessions(
            text=question,
            session_ids=[session_id],
            limit=self.search_limit,
        )
        retrieval_ms = (time.perf_counter() - t0) * 1000.0
        facts = []
        for hit in (results.results or []):
            fact = getattr(hit, "fact", None) or getattr(hit, "content", None) or str(hit)
            facts.append(str(fact))
        return AdapterAnswer(
            retrieved_context="\n".join(facts),
            generated_answer=None,
            retrieval_latency_ms=retrieval_ms,
            answer_latency_ms=0.0,
        )

    def close(self) -> None:
        # Best-effort: drop the users we created.
        for scope_id in list(self._sessions.keys()):
            user_id = f"seam-bench-{scope_id}"
            try:
                self._client.user.delete(user_id=user_id)
            except Exception:
                pass
        self._sessions.clear()
```

Keep under 200 lines. The Zep SDK surface has changed between v1 and v2; pin the SDK and document the pin. If `memory.search_sessions` is not the canonical method at implementation time, swap to the current equivalent and update this SOP.

### 4.2 `benchmarks/external/locomo/run.py` (modify)

Extend `--adapter` choices and factory:

```python
parser.add_argument(
    "--adapter",
    default="seam",
    choices=["seam", "mem0", "zep"],
    help="Memory system under test",
)

def build_adapter(name: str):
    if name == "seam":
        from benchmarks.external.locomo.adapters.seam import SeamLocomoAdapter
        return SeamLocomoAdapter()
    if name == "mem0":
        from benchmarks.external.locomo.adapters.mem0 import Mem0LocomoAdapter
        return Mem0LocomoAdapter()
    if name == "zep":
        from benchmarks.external.locomo.adapters.zep import ZepLocomoAdapter
        return ZepLocomoAdapter()
    raise ValueError(f"unknown adapter {name!r}")
```

### 4.3 `seam_runtime/cli.py` (modify)

Add `zep` to the `--adapter` choices in `seam bench external`.

### 4.4 `pyproject.toml` (modify)

```toml
[project.optional-dependencies]
bench-zep = ["zep-cloud>=2.0.0"]
```

Pin a tested SDK version range. Document the alternative `zep-python` path in the README if Zep Cloud is unavailable for the operator.

### 4.5 `test_seam_all/test_locomo_zep_adapter.py` (new)

Use a **stub Zep client**:

```python
class _StubZepUser:
    def __init__(self, parent): self.parent = parent
    def add(self, user_id): self.parent.users.add(user_id)
    def delete(self, user_id): self.parent.users.discard(user_id); self.parent.messages.pop(user_id, None)

class _StubZepMemory:
    def __init__(self, parent): self.parent = parent
    def add_session(self, session_id, user_id):
        self.parent.sessions[session_id] = user_id
        self.parent.messages.setdefault(session_id, [])
    def add(self, session_id, messages):
        self.parent.messages.setdefault(session_id, []).extend(messages)
    def search_sessions(self, text, session_ids, limit):
        from types import SimpleNamespace
        hits = []
        for sid in session_ids:
            for m in self.parent.messages.get(sid, [])[:limit]:
                hits.append(SimpleNamespace(fact=m["content"]))
        return SimpleNamespace(results=hits)

class _StubZep:
    def __init__(self, **kw):
        self.users = set(); self.sessions = {}; self.messages = {}
        self.user = _StubZepUser(self); self.memory = _StubZepMemory(self)
```

Patch the import in `adapters/zep.py` (refactor the adapter to accept an injected `_client` for testability, or monkeypatch `zep_cloud.client.Zep`). Then:

- `ZepLocomoAdapter` constructs against the stub with `ZEP_API_KEY` set
- Without `ZEP_API_KEY` and without `ZEP_API_URL`, constructor raises `RuntimeError` with a clear message
- Without `zep_cloud` and `zep_python` installed, constructor raises `RuntimeError` pointing at the `seam[bench-zep]` install
- `reset` creates a user + session
- `ingest_turn` appends to the stub
- `answer` returns joined retrieved_context
- `close` deletes all users created during the run

Do **not** call the real Zep SDK in any test.

### 4.6 `benchmarks/external/locomo/README.md` (modify)

Update the comparator matrix to include Zep:

| Adapter | Install | Required env | Local data path |
|---|---|---|---|
| `seam` | base install | none | per-scope SQLite under `test_seam/locomo/` |
| `mem0` | `pip install -e .[bench-mem0]` | `OPENAI_API_KEY` | temp Chroma store |
| `zep` | `pip install -e .[bench-zep]` | `ZEP_API_KEY` (Cloud) or `ZEP_API_URL` (CE) | remote/self-hosted Zep |

Add a note: Zep is the first comparator that requires either an external service account or a running local Zep CE container. Document the `docker run` line for Zep CE if available at implementation time. Do not bundle the Zep image.

## 5. DeepSeek implementation checklist

- [ ] SOPs 0, 1, 3 merged on `main`
- [ ] `pip install zep-cloud` (or `zep-python`) on dev machine; confirm import works
- [ ] If using self-hosted Zep CE: `docker run` it locally and confirm `ZEP_API_URL` works
- [ ] Created `benchmarks/external/locomo/adapters/zep.py` per section 4.1, under 200 lines
- [ ] Lazy import inside `__init__`; falls back from `zep_cloud` to `zep_python`
- [ ] Clear error when neither `ZEP_API_KEY` nor `ZEP_API_URL` set
- [ ] Per-scope user_id and session_id isolation
- [ ] `reset` deletes any prior user before re-adding
- [ ] `close` deletes all users created during the run
- [ ] Extended `--adapter` choices and factory in `benchmarks/external/locomo/run.py`
- [ ] Extended `--adapter` choices in `seam bench external` in `seam_runtime/cli.py`
- [ ] Added `bench-zep` optional extra in `pyproject.toml` with pinned version
- [ ] Wrote `test_seam_all/test_locomo_zep_adapter.py` with stub Zep, all cases in section 4.5
- [ ] No live Zep / OpenAI / Anthropic calls in tests
- [ ] All tests pass (`pytest test_seam_all/test_locomo_zep_adapter.py -v`)
- [ ] Full suite still passes (`pytest test_seam_all -x`)
- [ ] Updated `benchmarks/external/locomo/README.md` with the Zep row
- [ ] Ran a real three-way comparison on dev machine: `--adapter seam`, `--adapter mem0`, `--adapter zep` against the quickstart fixture; recorded all three JSON reports (do not commit them)
- [ ] Appended HISTORY entry per template in section 8
- [ ] `python -m tools.history.verify_continuity` passes
- [ ] Pushed branch and opened **draft** PR titled `Phase 4: Zep LoCoMo comparator adapter`

## 6. Reviewer verification checklist

- [ ] `pip install -e .` (without `[bench-zep]`) succeeds; `seam bench external --quickstart locomo --adapter seam` still works
- [ ] `seam bench external --quickstart locomo --adapter zep` (without Zep SDK installed) prints a clear error mentioning `pip install -e .[bench-zep]` and exits non-zero
- [ ] `pip install -e ".[bench-zep]"` succeeds
- [ ] `seam bench external --quickstart locomo --adapter zep` (without `ZEP_API_KEY` and `ZEP_API_URL`) prints a clear error mentioning both env vars and exits non-zero
- [ ] With Zep SDK installed and either `ZEP_API_KEY` or `ZEP_API_URL` set against a working Zep, `seam bench external --quickstart locomo --adapter zep --output /tmp/zep.json` runs end-to-end and produces a valid `SEAM-EXTERNAL-MEMORY-BENCHMARK-RESULT/1` JSON
- [ ] `pytest test_seam_all/test_locomo_zep_adapter.py -v` passes (6+ tests)
- [ ] `pytest test_seam_all -x` passes (full suite)
- [ ] `grep -RE "zep" requirements.txt` returns nothing (must stay in optional extras only)
- [ ] No test calls the real Zep SDK (grep `from zep_cloud`, `from zep_python` in tests should show only the import inside a monkeypatch-guarded fixture)
- [ ] No bundled Zep dataset, no Zep service credentials in repo (`grep -RE "(zep_api_key|ZEP_API_KEY=)" .` returns only documentation references with placeholder values)
- [ ] `python -m tools.history.verify_continuity` passes
- [ ] PR description ticks every box in section 5

## 7. Acceptance commands

```bash
pip install -e .

# SEAM-only path unchanged
seam bench external --quickstart locomo --adapter seam --output /tmp/seam.json

# Zep path needs the optional extra and either Cloud key or self-hosted URL
pip install -e ".[bench-zep]"

# Option A: Zep Cloud
ZEP_API_KEY=<your-key> seam bench external --quickstart locomo --adapter zep --output /tmp/zep.json

# Option B: self-hosted Zep CE
docker run -d -p 8000:8000 ghcr.io/getzep/zep-ce:latest  # adjust to current image
ZEP_API_URL=http://localhost:8000 seam bench external --quickstart locomo --adapter zep --output /tmp/zep.json

# Three-way comparison
jq '{adapter, scores}' /tmp/seam.json /tmp/mem0.json /tmp/zep.json

# Tests
pytest test_seam_all/test_locomo_zep_adapter.py -v
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
  - benchmarks/external/locomo/adapters/zep.py
  - benchmarks/external/locomo/run.py
  - benchmarks/external/locomo/README.md
  - seam_runtime/cli.py
  - pyproject.toml
  - test_seam_all/test_locomo_zep_adapter.py
  - docs/SOP_EXTERNAL_BENCH_ZEP_COMPARATOR.md
supersedes: <last benchmark-topic entry id>
tokens: ~<count>
body: |
  Added Zep (Cloud or self-hosted CE) comparator adapter for the LoCoMo
  external memory benchmark. Lives behind seam[bench-zep] optional extra.
  Per-scope user_id and session_id isolation; close() cleans up created
  users. Required comparator set (Mem0, Zep, Letta/MemGPT) now at two of
  three. First three-way SEAM-vs-Mem0-vs-Zep run reproducible on the
  quickstart fixture. Still no publishable scoreboard until SOP 2
  (LLM-judge) and Track K (BIL wrapping) are in.
```

## 9. Pitfalls

- **Zep SDK names have changed.** Confirm the current package (`zep-cloud` or `zep-python`) at implementation time. Pin the version in the optional extra.
- **Zep ingestion is async on the server side.** Zep extracts facts from messages in a background job. A naive `add then immediately search` can return zero hits because the background extraction has not run yet. Add a small wait or use Zep's "wait for processing" hook if available. Document the strategy chosen in the adapter docstring.
- **Self-hosted Zep CE requires Docker and a Postgres/Neo4j backend.** Do not bundle that infrastructure. Document the `docker run` line and the expected ports.
- **Do not let the adapter create users in a shared Zep tenant without cleanup.** `close()` must delete every user it created.
- **Do not import `zep_cloud` or `zep_python` at module top level.** Lazy-import inside `__init__`.
- **Do not commit any Zep dataset, session export, or service credentials.**
- **Do not claim "SEAM beats Zep" or publish a public scoreboard from this PR.** Publish requires SOP 2 + Track K + reproduction on full LoCoMo against named comparator versions.
- **Per AGENTS.md security rules**, never log `ZEP_API_KEY`, never write it into the report JSON, never commit `.env` files.

## 10. Estimated scope

~500-800 lines net. One review cycle. Optional extra: `zep-cloud`. No change to SEAM core.
