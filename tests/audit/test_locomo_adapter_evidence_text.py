"""Regression tests for SEAM LoCoMo adapter retrieved evidence text."""

from benchmarks.external.common.types import ConversationTurn
from benchmarks.external.locomo.adapters.seam import SeamLocomoAdapter


def test_locomo_adapter_returns_plain_evidence_text(tmp_path):
    adapter = SeamLocomoAdapter(db_path=str(tmp_path), budget=2000)
    scope_id = "evidence-text"

    adapter.reset(scope_id)
    adapter.ingest_turn(
        scope_id,
        ConversationTurn(
            speaker="user",
            text="I moved to Tokyo in April and my cat is named Pixel.",
            timestamp="2026-01-01T00:00:00Z",
        ),
    )

    answer = adapter.answer(scope_id, "Where did I move in April?")

    assert "Tokyo" in answer.retrieved_context
    assert "moved to Tokyo" in answer.retrieved_context
    assert answer.generated_answer is None
    assert answer.retrieval_latency_ms >= 0.0


def test_locomo_adapter_respects_context_budget(tmp_path):
    adapter = SeamLocomoAdapter(db_path=str(tmp_path), budget=120)
    scope_id = "budget"

    adapter.reset(scope_id)
    adapter.ingest_turn(
        scope_id,
        ConversationTurn(
            speaker="user",
            text="Tokyo " * 200,
            timestamp="2026-01-01T00:00:00Z",
        ),
    )

    answer = adapter.answer(scope_id, "Tokyo?")

    assert len(answer.retrieved_context) <= 120


def test_locomo_adapter_uses_separate_search_top_k(monkeypatch, tmp_path):
    """Context budget must not fan out into thousands of retrieval candidates."""
    observed = {}

    class FakeRuntime:
        def search_ir(self, query, **kwargs):
            observed["budget"] = kwargs["budget"]

            class Result:
                candidates = []

            return Result()

    monkeypatch.setattr(
        "benchmarks.external.locomo.adapters.seam._open_runtime",
        lambda _db_path, **_kwargs: FakeRuntime(),
    )
    adapter = SeamLocomoAdapter(db_path=str(tmp_path), budget=2000, search_top_k=20)

    adapter.answer("scope", "What happened?")

    assert observed["budget"] == 20


def test_locomo_adapter_reports_retrieval_policy_diagnostics(monkeypatch, tmp_path):
    class FakeRuntime:
        def search_ir(self, query, **kwargs):
            class Result:
                candidates = []

            return Result()

    monkeypatch.setattr(
        "benchmarks.external.locomo.adapters.seam._open_runtime",
        lambda _db_path, **_kwargs: FakeRuntime(),
    )
    adapter = SeamLocomoAdapter(
        db_path=str(tmp_path),
        budget=8000,
        search_top_k=100,
        rerank_top_k=40,
        semantic_recovery_mode="pack-budget-deep",
    )

    answer = adapter.answer("scope", "What happened?")

    assert answer.answerer_diagnostics == {
        "retrieval_policy": {
            "mode": "pack-budget-deep",
            "context_char_budget": 8000,
            "search_top_k": 100,
            "rerank_top_k": 40,
            "retrieval_mode": "legacy-weighted",
        },
        "retrieval": {
            "candidate_count": 0,
            "closure_id_count": 0,
            "sub_question_count": 0,
        },
    }


def test_locomo_adapter_reuses_runtime_per_scope(monkeypatch, tmp_path):
    """Repeated turns/questions in a scope should not reload the runtime."""
    opens = []

    class FakeRuntime:
        def ingest_conversation_turn(self, **kwargs):
            return None

        def search_ir(self, query, **kwargs):
            class Result:
                candidates = []

            return Result()

    def fake_open_runtime(db_path, **_kwargs):
        opens.append(db_path)
        return FakeRuntime()

    monkeypatch.setattr(
        "benchmarks.external.locomo.adapters.seam._open_runtime",
        fake_open_runtime,
    )
    adapter = SeamLocomoAdapter(db_path=str(tmp_path), budget=2000)

    adapter.ingest_turn(scope_id="scope", turn=ConversationTurn(speaker="A", text="one"))
    adapter.ingest_turn(scope_id="scope", turn=ConversationTurn(speaker="A", text="two"))
    adapter.answer("scope", "What happened?")

    assert len(opens) == 1


def test_open_runtime_reuses_default_embedding_model(monkeypatch, tmp_path):
    """Different scope runtimes should share one loaded sentence-transformer."""
    from benchmarks.external.locomo.adapters import seam as seam_adapter

    created = []

    class FakeModel:
        def __init__(self, model_name, revision=None, local_files_only=False):
            created.append(model_name)
            self.model_name = model_name
            self.revision = revision
            self.local_files_only = local_files_only
            self.name = f"st:{model_name}@{revision}"
            self.dimension = 384

        def embed(self, text):
            return [1.0] + [0.0] * 383

    class FakeRuntime:
        def __init__(
            self,
            store_path,
            embedding_model=None,
            allow_pgvector_env=True,
        ):
            self.store_path = store_path
            self.embedding_model = embedding_model
            self.allow_pgvector_env = allow_pgvector_env

    monkeypatch.setattr(seam_adapter, "_DEFAULT_SENTENCE_TRANSFORMER_MODEL", None, raising=False)
    monkeypatch.setattr("seam_runtime.models.SentenceTransformerModel", FakeModel)
    monkeypatch.setattr("seam_runtime.runtime.SeamRuntime", FakeRuntime)

    first = seam_adapter._open_runtime(tmp_path / "one.db")
    second = seam_adapter._open_runtime(tmp_path / "two.db")

    assert len(created) == 1
    assert first.embedding_model is second.embedding_model


def test_locomo_context_preserves_ranked_raw_order():
    """Ranked retrieval order should survive context construction."""
    from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind

    class FakeStore:
        def load_ir(self, ids):
            records_by_id = {
                "raw:z": MIRLRecord(
                    id="raw:z",
                    kind=RecordKind.RAW,
                    attrs={"content": "first ranked answer evidence"},
                ),
                "raw:a": MIRLRecord(
                    id="raw:a",
                    kind=RecordKind.RAW,
                    attrs={"content": "second ranked distractor"},
                ),
            }
            return IRBatch([records_by_id[record_id] for record_id in ids])

    class FakeRuntime:
        store = FakeStore()

    adapter = SeamLocomoAdapter(budget=2000)

    context = adapter._build_evidence_context_from_ids(FakeRuntime(), ["raw:z", "raw:a"])

    assert context.index("first ranked") < context.index("second ranked")


def test_locomo_adapter_empty_scope_returns_empty_context(tmp_path):
    adapter = SeamLocomoAdapter(db_path=str(tmp_path), budget=2000)

    answer = adapter.answer("empty", "What do you remember?")

    assert answer.retrieved_context == ""
    assert answer.generated_answer is None


def test_locomo_adapter_keep_db_skips_reingest_on_second_reset(tmp_path):
    """With keep_db, a second reset() of an already-ingested scope must keep
    the DB and stop subsequent ingest_turn() from re-writing the same RAWs."""
    adapter = SeamLocomoAdapter(db_path=str(tmp_path), budget=2000, keep_db=True)
    scope_id = "keep-db-scope"

    adapter.reset(scope_id)
    adapter.ingest_turn(
        scope_id,
        ConversationTurn(
            speaker="user",
            text="The cat is named Pixel.",
            timestamp="2026-01-01T00:00:00Z",
        ),
    )
    rt = adapter._runtime(scope_id)
    first_count = len(rt.store.load_ir(ns=f"locomo:{scope_id}").records)
    assert first_count > 0

    db_path = adapter._db_path(scope_id)
    assert db_path.exists()
    first_mtime = db_path.stat().st_mtime_ns

    # Second reset must NOT delete (keep_db) and ingest_turn must NOT re-persist.
    adapter.reset(scope_id)
    assert scope_id in adapter._cached_scopes
    assert db_path.exists()

    adapter.ingest_turn(
        scope_id,
        ConversationTurn(
            speaker="user",
            text="The cat is named Pixel.",  # identical text
            timestamp="2026-01-01T00:00:00Z",
        ),
    )
    rt2 = adapter._runtime(scope_id)
    second_count = len(rt2.store.load_ir(ns=f"locomo:{scope_id}").records)
    assert second_count == first_count, (
        f"keep_db should skip re-ingest; got {second_count} records vs {first_count}"
    )
    second_mtime = db_path.stat().st_mtime_ns
    assert second_mtime == first_mtime, "keep_db should skip re-ingest; DB file was rewritten"

    # Retrieval must still work against the cached DB.
    answer = adapter.answer(scope_id, "What is the cat named?")
    assert "Pixel" in answer.retrieved_context


def test_locomo_adapter_keep_db_updates_anchor_on_cached_scope(tmp_path):
    """Even when ingest is skipped, the temporal anchor must update from the
    incoming turn timestamps so relative-date questions still work."""
    adapter = SeamLocomoAdapter(db_path=str(tmp_path), budget=2000, keep_db=True)
    scope_id = "anchor-scope"

    adapter.reset(scope_id)
    adapter.ingest_turn(
        scope_id,
        ConversationTurn(speaker="u", text="hi", timestamp="2026-03-15"),
    )
    assert scope_id in adapter._scope_anchor_by_id
    earlier = adapter._scope_anchor_by_id[scope_id]

    adapter.reset(scope_id)
    assert scope_id not in adapter._scope_anchor_by_id  # cleared on cached reset

    # Send an earlier timestamp; anchor should still pick it up despite skip.
    adapter.ingest_turn(
        scope_id,
        ConversationTurn(speaker="u", text="hi", timestamp="2026-01-01"),
    )
    assert scope_id in adapter._scope_anchor_by_id
    assert adapter._scope_anchor_by_id[scope_id] < earlier


def test_locomo_adapter_keep_db_default_off_still_deletes(tmp_path):
    """Default keep_db=False must preserve the original delete-on-reset behavior."""
    adapter = SeamLocomoAdapter(db_path=str(tmp_path), budget=2000)
    scope_id = "delete-scope"

    adapter.reset(scope_id)
    adapter.ingest_turn(
        scope_id,
        ConversationTurn(
            speaker="user",
            text="Hello world",
            timestamp="2026-01-01T00:00:00Z",
        ),
    )
    db_path = adapter._db_path(scope_id)
    assert db_path.exists()

    adapter.reset(scope_id)
    assert not db_path.exists()
    assert scope_id not in adapter._cached_scopes


def test_locomo_answerer_prompt_prefers_supported_answer_over_abstention(monkeypatch):
    captured = {}

    def fake_short_answer(model, prompt):
        captured["model"] = model
        captured["prompt"] = prompt
        return "July 2023"

    monkeypatch.setattr(
        "benchmarks.external.locomo.adapters.seam._openai_short_answer",
        fake_short_answer,
    )
    adapter = SeamLocomoAdapter(answerer="openai", answerer_model="gpt-5-mini")

    answer = adapter._generate_answer(
        "When did Caroline move?",
        "[Caroline 2023-07-01] I moved in July 2023.",
    )

    assert answer == "July 2023"
    assert captured["model"] == "gpt-5-mini"
    assert "Return the best supported answer found in the context" in captured["prompt"]
    assert "Say 'unknown' only when the context contains no answer candidate" in captured["prompt"]
