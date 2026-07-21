# SEAM Framework Adapters — Path Exploration

**Date:** 2026-07-18
**Status:** Roadmap analysis — no code changes

## Summary

All three adapters can be built as thin wrappers over the existing `SeamRuntime`
API. No SEAM core changes are required. Each adapter is a single Python file
under 300 lines, a `pyproject.toml` optional extra, and hermetic tests.

The core mapping is the same in every case: the framework's "store conversation
turn" maps to `runtime.ingest_text()`, and the framework's "retrieve relevant
memory" maps to `runtime.search_ir()`. Namespace/scope isolation already exists
on both methods.

---

## What SEAM Already Has (No Changes Needed)

### Constructor — zero-config default

```python
from seam_runtime.runtime import SeamRuntime
runtime = SeamRuntime()  # SQLite at seam.db, local embedding model, all defaults
```

One import. No API keys. No Docker. No remote services. This is the "change one
line of code" foundation.

### Recall — `search_ir()`

```python
def search_ir(self, query: str, lens: str = "general",
              scope: str | None = None,
              budget: int = 5, include_raw: bool = False,
              temporal_window=None, temporal_reference=None,
              ns: str | None = None, flags=None) -> SearchResult:
```

- `ns` = namespace (maps to LangGraph thread_id, CrewAI crew_id, AutoGen agent_id)
- `scope` = sub-scope within a namespace (maps to LangGraph checkpoint namespace)
- Returns `SearchResult` with ranked `.candidates` (each has record ID, score, kind, text excerpt)
- Supports 20+ tool-exposed retrieval surfaces (MCP `seam_memory_search`, `seam_retrieve`, REST `/search`, etc.)

### Ingest — `ingest_text()`

```python
def ingest_text(self, text: str, source_ref: str = "local://input",
                ns: str = "local.default", scope: str = "thread",
                persist: bool = True, agent_id: str | None = None) -> IngestReport:
```

- Compiles NL text → MIRL records → persists to storage in one call
- `ns` + `scope` isolate data per framework entity
- Returns `IngestReport` with record count, compile time, persist stats

### Compile-then-persist (for batch/conversation use)

```python
batch = runtime.compile_nl(turn_text, source_ref=source_ref, ns=ns, scope=scope)
runtime.persist_ir(batch)
```

Two-step variant when you want to inspect MIRL records before persisting (useful
for AutoGen's compression use case — compile first, inspect what was extracted,
then decide what to persist vs what to summarize).

### Env-based retrieval tuning (no code changes for adopters)

All retrieval behavior is configurable via env vars — adopters don't touch
RetrievalFlags in code:

```bash
export SEAM_RETRIEVAL_PROFILE=broad           # top_k=300, budget=60000
export SEAM_CONVERSATION_ADAPTER=conversation/2  # cross-turn set completion
export SEAM_TEMPORAL_POLICY=temporal/1        # resolve relative dates
export SEAM_INFERENCE_POLICY=inference/high-confidence/2
```

---

## Adapter 1: LangGraph (`seam-langgraph`)

### Framework interface to implement

LangGraph's `BaseCheckpointSaver` (from `langgraph.checkpoint.base`):

```python
class BaseCheckpointSaver:
    def put(self, config: dict, checkpoint: dict, metadata: dict) -> dict:
        """Store a checkpoint. config contains thread_id, checkpoint_ns, etc."""
    async def aget_tuple(self, config: dict) -> CheckpointTuple | None:
        """Retrieve latest checkpoint for a config."""
    def get_tuple(self, config: dict) -> CheckpointTuple | None:
        """Sync version of aget_tuple."""
    def list(self, config: dict, *, limit: int = 10, before: dict = None) -> Iterator[CheckpointTuple]:
        """List checkpoints for a config, paginated."""
```

### SEAM mapping (zero core changes)

| LangGraph concept | SEAM mapping |
|---|---|
| `config["configurable"]["thread_id"]` | `ns=f"langgraph:{thread_id}"` |
| `config["configurable"]["checkpoint_ns"]` | `scope=checkpoint_ns or "default"` |
| `put(checkpoint)` | `runtime.ingest_text(serialize(checkpoint), ns=ns, scope=scope)` |
| `get_tuple(config)` | `runtime.search_ir(query="*", ns=ns, scope=scope, budget=1)` → reconstruct checkpoint |
| `list(config)` | `runtime.search_ir(query="*", ns=ns, scope=scope, budget=limit)` → iterate |

### Adapter shape (pseudocode)

```python
class SeamCheckpointSaver(BaseCheckpointSaver):
    def __init__(self, runtime: SeamRuntime = None):
        self._runtime = runtime or SeamRuntime(store_path="seam-langgraph.db")

    def put(self, config, checkpoint, metadata):
        ns = f"langgraph:{config['configurable']['thread_id']}"
        scope = config['configurable'].get('checkpoint_ns', 'default')
        text = json.dumps({"checkpoint": checkpoint, "metadata": metadata})
        self._runtime.ingest_text(text, ns=ns, scope=scope,
                                 source_ref=f"checkpoint:{checkpoint['id']}")
        return {"configurable": config["configurable"]}

    def get_tuple(self, config):
        ns = f"langgraph:{config['configurable']['thread_id']}"
        scope = config['configurable'].get('checkpoint_ns', 'default')
        result = self._runtime.search_ir(query="*", ns=ns, scope=scope, budget=1)
        if not result.candidates:
            return None
        # Reconstruct checkpoint from stored record
        ...
```

### One-line change for LangGraph users

```python
# Before:
from langgraph.checkpoint.sqlite import SqliteSaver
checkpointer = SqliteSaver.from_conn_string("checkpoints.db")

# After:
from seam_langgraph import SeamCheckpointSaver
checkpointer = SeamCheckpointSaver()
```

### What already exists for this

- `SeamRuntime(store_path)` — zero-config constructor ✓
- `search_ir(ns=..., scope=...)` — per-thread isolation ✓
- `ingest_text(ns=..., scope=...)` — per-thread ingest ✓
- `RetrievalFlags` env-var tuning — no code changes for adopters ✓
- `pyproject.toml` optional extras pattern — `bench-mem0` is the template ✓
- `test_locomo_mem0_adapter.py` — stub/monkeypatch test pattern ✓

### Gap: none. Everything needed already exists in `SeamRuntime`.

---

## Adapter 2: CrewAI (`seam-crewai`)

### Framework interface to implement

CrewAI's memory system (from `crewai.memory`):

CrewAI uses a modular memory architecture with separate storage backends:
- `ShortTermMemory` — recent context within a task
- `LongTermMemory` — persistent across tasks/crews
- `EntityMemory` — facts about entities encountered

Each is a class implementing `save()` and `search()`:

```python
class Memory(ABC):
    @abstractmethod
    def save(self, value: str, metadata: dict = None) -> None: ...
    @abstractmethod
    def search(self, query: str, limit: int = 5) -> list[str]: ...
```

### SEAM mapping (zero core changes)

| CrewAI concept | SEAM mapping |
|---|---|
| `crew.id` or `task.id` | `ns=f"crewai:{crew_id}"` |
| Memory type (short/long/entity) | `scope` parameter (e.g., `"short_term"`, `"long_term"`, `"entity"`) |
| `save(value, metadata)` | `runtime.ingest_text(value, ns=ns, scope=scope)` |
| `search(query, limit)` | `runtime.search_ir(query=query, ns=ns, scope=scope, budget=limit)` → extract text |

### Adapter shape (pseudocode)

```python
class SeamMemoryProvider:
    def __init__(self, crew_id: str, runtime: SeamRuntime = None):
        self._crew_id = crew_id
        self._runtime = runtime or SeamRuntime(store_path="seam-crewai.db")

    def save(self, value: str, memory_type: str = "long_term", metadata: dict = None):
        ns = f"crewai:{self._crew_id}"
        self._runtime.ingest_text(
            value, ns=ns, scope=memory_type,
            source_ref=metadata.get("source", "crewai://memory") if metadata else "crewai://memory"
        )

    def search(self, query: str, memory_type: str = "long_term", limit: int = 5) -> list[str]:
        ns = f"crewai:{self._crew_id}"
        result = self._runtime.search_ir(query=query, ns=ns, scope=memory_type, budget=limit)
        return [c.text for c in result.candidates if c.text]
```

### One-line change for CrewAI users

```python
# Before:
crew = Crew(agents=[...], tasks=[...], memory=True)  # default in-process memory

# After:
from seam_crewai import SeamMemoryProvider
crew = Crew(agents=[...], tasks=[...],
            memory=True,
            memory_provider=SeamMemoryProvider(crew_id="my-crew"))
```

### What already exists for this

- `search_ir(ns=..., scope=..., budget=limit)` — per-crew, per-type isolation ✓
- `ingest_text(ns=..., scope=...)` — per-crew, per-type ingest ✓
- `SeamRuntime(store_path)` — zero-config ✓
- Stub test + optional extra pattern ✓

### Gap: none. Everything needed already exists.

---

## Adapter 3: AutoGen (`seam-autogen`)

### Framework interface to implement

AutoGen 0.7+ manages conversation history through a `ConversableAgent` with a
`ChatHistory` object. The compression point is a context manager or middleware
that intercepts the message list before it's sent to the LLM:

```python
class ChatHistory:
    messages: list[dict]  # [{"role": ..., "content": ...}, ...]

class ConversableAgent:
    async def a_generate_reply(self, messages: list[dict]) -> str: ...
```

The compression hook replaces the full message history with a compact memory
summary before the LLM call. This is typically done via:
- A `ContextManager` that wraps the agent's `generate_reply`
- Or a custom `ModelClient` that intercepts the message list

### SEAM mapping (zero core changes)

| AutoGen concept | SEAM mapping |
|---|---|
| Agent conversation session | `ns=f"autogen:{session_id}"` |
| Individual message turn | `scope="turns"` |
| Full transcript → compressed memory | `compile_nl(turn) → persist_ir()` per turn, then `search_ir()` for summary |
| Pre-LLM compression hook | Return compact SEAM results instead of full transcript |

### Adapter shape (pseudocode)

```python
class SeamAutoGenContext:
    def __init__(self, session_id: str, runtime: SeamRuntime = None):
        self._session_id = session_id
        self._runtime = runtime or SeamRuntime(store_path="seam-autogen.db")
        self._ns = f"autogen:{session_id}"

    def ingest_turn(self, role: str, content: str):
        """Call after each agent message to build the memory graph."""
        text = f"[{role}] {content}"
        self._runtime.ingest_text(text, ns=self._ns, scope="turns",
                                  source_ref=f"autogen://{self._session_id}")

    def compress_history(self, query: str, budget: int = 10) -> str:
        """Call before LLM call to get compact memory instead of full transcript."""
        result = self._runtime.search_ir(query=query, ns=self._ns, budget=budget)
        if not result.candidates:
            return ""  # No relevant memory yet — let the LLM handle it
        return "\n".join(c.text for c in result.candidates if c.text)
```

### One-line change for AutoGen users

```python
# Before: full chat history grows unbounded into the LLM prompt
agent = ConversableAgent("assistant", llm_config=llm_config)

# After: SEAM compresses history before the LLM sees it
from seam_autogen import SeamAutoGenContext
ctx = SeamAutoGenContext(session_id="session-1")
# After each turn: ctx.ingest_turn(role, content)
# Before LLM call: compact = ctx.compress_history(query)
```

### What already exists for this

- `compile_nl()` — MIRL compilation (extraction, provenance, structuring) ✓
- `persist_ir()` — separate compile from persist for inspection ✓
- `search_ir(ns=..., budget=...)` — scoped retrieval ✓
- `ingest_text(ns=..., scope=...)` — turn-by-turn ingest ✓

### Gap: none. The compile-then-inspect pattern already exists for the
compression use case. `search_ir()` returns compact results that replace
the full transcript in the LLM prompt.

---

## What SEAM Core Does NOT Need to Change

| Capability | Status | Where it lives |
|---|---|---|
| Zero-config constructor | Exists | `SeamRuntime()` defaults to `seam.db` |
| Namespace isolation | Exists | `ns` param on `search_ir`, `ingest_text`, `compile_nl` |
| Scope sub-isolation | Exists | `scope` param on same methods |
| Per-framework DB | Exists | Pass `store_path="seam-langgraph.db"` |
| Env-based retrieval tuning | Exists | 12+ `SEAM_*` env vars, no code changes |
| Optional extras pattern | Exists | `bench-mem0`, `bench-zep` templates in pyproject.toml |
| Stub test pattern | Exists | `test_locomo_mem0_adapter.py` |
| MIRL compile pipeline | Exists | `compile_nl()` + `persist_ir()` |
| Provenance tracing | Exists | Every record carries `source_ref`, agent, timestamp |
| MCP/CLI/REST surfaces | Exists | Adapters can wrap any surface |

## Adapter File Layout (Proposed)

```
seam_runtime/
├── framework_adapters/          # NEW directory
│   ├── __init__.py              # Re-exports all three
│   ├── langgraph_checkpoint.py  # SeamCheckpointSaver (~150 lines)
│   ├── crewai_memory.py         # SeamMemoryProvider (~120 lines)
│   └── autogen_context.py       # SeamAutoGenContext (~130 lines)
│
test_seam_all/
├── test_langgraph_adapter.py    # Stub LangGraph, hermetic tests
├── test_crewai_adapter.py       # Stub CrewAI memory, hermetic tests
└── test_autogen_adapter.py      # Stub AutoGen agent, hermetic tests

pyproject.toml                   # New extras: langgraph, crewai, autogen
```

## Build Order

1. **LangGraph first** — highest volume of potential users, smallest interface (3 methods: `put`, `get_tuple`, `list`), cleanest one-line-change pitch
2. **CrewAI second** — second-largest adoption, equally simple interface (`save`/`search`), but CrewAI's memory API is less stable than LangGraph's checkpoint API
3. **AutoGen third** — smallest interface (just `ingest_turn` + `compress_history`) but the context-manager pattern needs careful hook placement in AutoGen's generate pipeline

Each adapter is independent — none depends on another. They can be built in parallel if multiple contributors are available.
