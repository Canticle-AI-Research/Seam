"""Public mode selection and truthful retrieval-plan/trace reporting."""

from contextlib import contextmanager

import pytest

from seam_runtime.config import SETTINGS_BY_NAME, validate
from seam_runtime.models import HashEmbeddingModel
from seam_runtime.retrieval_orchestrator.adapters import SeamVectorSearchAdapter
from seam_runtime.retrieval_orchestrator.orchestrator import RetrievalOrchestrator
from seam_runtime.runtime import SeamRuntime
from seam_runtime.vector_adapters import MemoryVectorAdapter


@pytest.fixture
def runtime_factory(tmp_path, monkeypatch):
    monkeypatch.delenv("SEAM_VECTOR_SEARCH_MODE", raising=False)
    runtimes = []

    def create(**kwargs):
        runtime = SeamRuntime(
            tmp_path / f"mode-{len(runtimes)}.db",
            embedding_model=HashEmbeddingModel(),
            allow_pgvector_env=False,
            **kwargs,
        )
        runtimes.append(runtime)
        return runtime

    yield create
    for runtime in runtimes:
        runtime.close()


def test_default_exact_and_optional_mode_are_process_stable(runtime_factory, monkeypatch):
    default = runtime_factory()
    assert default.vector_search_mode == "exact"
    monkeypatch.setenv("SEAM_VECTOR_SEARCH_MODE", "approximate")
    opted_in = runtime_factory()
    explicit = runtime_factory(vector_search_mode="exact")
    assert opted_in.vector_search_mode == "approximate"
    assert explicit.vector_search_mode == "exact"
    monkeypatch.setenv("SEAM_VECTOR_SEARCH_MODE", "exact")
    assert opted_in.vector_search_mode == "approximate"
    assert default.vector_search_mode == "exact"


@pytest.mark.parametrize("invalid", ["ann", "auto", "", "EXACT"])
def test_invalid_explicit_mode_fails_before_creating_storage(tmp_path, invalid):
    path = tmp_path / "invalid.db"
    with pytest.raises(ValueError, match="vector_search_mode"):
        SeamRuntime(path, vector_search_mode=invalid, allow_pgvector_env=False)
    assert not path.exists()


def test_invalid_environment_mode_is_rejected(runtime_factory, monkeypatch):
    monkeypatch.setenv("SEAM_VECTOR_SEARCH_MODE", "automatic")
    with pytest.raises(ValueError, match="vector_search_mode"):
        runtime_factory()


def test_sqlite_trace_reports_actual_exact_even_when_ann_requested(runtime_factory):
    runtime = runtime_factory(vector_search_mode="approximate")
    result = runtime.retrieve("a query", mode="vector", include_trace=True)
    plan = RetrievalOrchestrator(runtime).plan("a query", mode="vector")
    assert plan.vector_search_mode == "exact"
    assert plan.to_dict()["vector_search_mode"] == "exact"
    assert result.trace["plan"]["vector_search_mode"] == "exact"
    compatibility = runtime.retrieve(
        "a query", mode="mix", include_trace=True, ranking_policy="legacy-weighted/1"
    )
    assert compatibility.trace["plan"]["ranking_policy"] == "legacy-weighted/1"
    assert compatibility.trace["plan"]["vector_search_mode"] == "exact"


def test_injected_adapter_mode_is_not_overridden(runtime_factory):
    class ApproximateMemory(MemoryVectorAdapter):
        search_mode = "approximate"

    adapter = ApproximateMemory(HashEmbeddingModel())
    # Set on the instance too: supported adapters may expose a dataclass field.
    adapter.search_mode = "approximate"
    runtime = runtime_factory(vector_adapter=adapter, vector_search_mode="exact")
    result = runtime.retrieve("query", mode="vector", include_trace=True)
    assert runtime.vector_adapter is adapter
    assert adapter.search_mode == "approximate"
    assert result.trace["plan"]["vector_search_mode"] == "approximate"


def test_custom_adapter_without_mode_does_not_claim_exact(runtime_factory):
    class UndeclaredAdapter:
        name = "external"

        def index_records(self, records):
            pass

        def delete_records(self, record_ids):
            pass

        def search(self, query, limit=10, namespace=None):
            return {}

    runtime = runtime_factory(vector_adapter=UndeclaredAdapter())
    result = runtime.retrieve("query", mode="vector", include_trace=True)
    assert result.trace["plan"]["vector_search_mode"] == "unknown"


def test_runtime_passes_explicit_mode_to_pg_constructor(runtime_factory, monkeypatch):
    class CapturingPg(MemoryVectorAdapter):
        def __init__(self, dsn, model, *, table_name, search_mode):
            super().__init__(model)
            self.search_mode = search_mode

    monkeypatch.setattr("seam_runtime.runtime.PgVectorAdapter", CapturingPg)
    runtime = runtime_factory(pgvector_dsn="local-test", vector_search_mode="approximate")
    assert runtime.vector_adapter.search_mode == "approximate"
    assert runtime.retrieve("query", mode="vector", include_trace=True).trace[
        "plan"
    ]["vector_search_mode"] == "approximate"


def test_chroma_receives_mode_but_compatibility_trace_uses_runtime_backend(
    runtime_factory, monkeypatch
):
    class CapturingChroma:
        def __init__(self, store, model, *, persist_directory, collection_name, search_mode):
            self.search_mode = search_mode

        def delete_records(self, record_ids):
            pass

        def search(self, plan, limit):
            return []

    monkeypatch.setattr(
        "seam_runtime.retrieval_orchestrator.orchestrator.ChromaSemanticAdapter",
        CapturingChroma,
    )
    runtime = runtime_factory(vector_search_mode="approximate")
    engine = RetrievalOrchestrator(runtime, semantic_backend="chroma")
    assert engine.search("query", mode="vector", include_trace=True).trace[
        "plan"
    ]["vector_search_mode"] == "approximate"
    assert engine.search(
        "query", mode="mix", include_trace=True, ranking_policy="legacy-weighted/1"
    ).trace[
        "plan"
    ]["vector_search_mode"] == "exact"


def test_nonvector_plan_does_not_claim_a_search_mode(runtime_factory):
    runtime = runtime_factory()
    result = runtime.retrieve("query", mode="graph", include_trace=True)
    assert result.trace["plan"]["vector_search_mode"] == "unused"


def test_operator_setting_declares_the_same_default_and_choices():
    setting = SETTINGS_BY_NAME["SEAM_VECTOR_SEARCH_MODE"]
    assert setting.default == "exact"
    assert setting.choices == ("exact", "approximate")
    assert validate(setting, "approximate")[0]
    assert not validate(setting, "auto")[0]


def test_injected_semantic_wrapper_reports_its_own_backend(runtime_factory):
    runtime = runtime_factory()
    backend = MemoryVectorAdapter(runtime.embedding_model)
    backend.search_mode = "approximate"
    engine = RetrievalOrchestrator(
        runtime, semantic_adapter=SeamVectorSearchAdapter(runtime.store, backend)
    )
    result = engine.search("query", mode="vector", include_trace=True)
    assert result.trace["plan"]["vector_search_mode"] == "approximate"


@pytest.mark.parametrize("method", ["search", "decide"])
def test_semantic_read_lock_is_entered_once_per_public_request(runtime_factory, method):
    class LockedSemantic:
        search_mode = "exact"

        def __init__(self):
            self.active = False
            self.entries = 0

        @contextmanager
        def read_lock(self):
            assert not self.active, "non-reentrant semantic lock acquired twice"
            self.active = True
            self.entries += 1
            try:
                yield
            finally:
                self.active = False

        def search(self, plan, limit):
            assert self.active
            return []

    adapter = LockedSemantic()
    engine = RetrievalOrchestrator(runtime_factory(), semantic_adapter=adapter)
    getattr(engine, method)("query", mode="vector")
    assert adapter.entries == 1
    assert not adapter.active
