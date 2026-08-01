"""Verify LoCoMo fails fast on embedding-model integrity drift."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from benchmarks.external.common.types import BenchmarkCase, ConversationTurn


def _contract() -> dict[str, object]:
    from seam_runtime.derived_fact_context import DERIVED_FACTS_EMBEDDING_CONFIG

    return dict(DERIVED_FACTS_EMBEDDING_CONFIG)


class _ExactFakeModel:
    def __init__(
        self,
        *,
        vector: list[float] | None = None,
        error: Exception | None = None,
    ) -> None:
        contract = _contract()
        self.model_name = contract["model"]
        self.revision = contract["revision"]
        self.name = contract["name"]
        self.dimension = contract["dimension"]
        self.local_files_only = True
        self.vector = (
            vector
            if vector is not None
            else [1.0] + [0.0] * (int(contract["dimension"]) - 1)
        )
        self.error = error
        self.embed_calls = 0

    def embed(self, _text: str) -> list[float]:
        self.embed_calls += 1
        if self.error is not None:
            raise self.error
        return list(self.vector)


def _install_exact_fake(monkeypatch, model: _ExactFakeModel | None = None):
    from benchmarks.external.locomo.adapters import seam as seam_adapter

    resolved = model or _ExactFakeModel()
    monkeypatch.setattr(
        seam_adapter, "_DEFAULT_SENTENCE_TRANSFORMER_MODEL", resolved
    )
    return resolved


def test_open_runtime_constructs_exact_pinned_local_model(monkeypatch, tmp_path):
    from benchmarks.external.locomo.adapters import seam as seam_adapter

    created: list[dict[str, object]] = []

    class FakeSentenceTransformer(_ExactFakeModel):
        def __init__(self, **kwargs) -> None:
            created.append(kwargs)
            super().__init__()

    monkeypatch.setattr(seam_adapter, "_DEFAULT_SENTENCE_TRANSFORMER_MODEL", None)
    monkeypatch.setattr(
        "seam_runtime.models.SentenceTransformerModel", FakeSentenceTransformer
    )

    runtime = seam_adapter._open_runtime(tmp_path / "test_real_embed.db")
    contract = _contract()

    assert created == [
        {
            "model_name": contract["model"],
            "revision": contract["revision"],
            "local_files_only": True,
        }
    ]
    assert runtime.embedding_model.name == contract["name"]
    runtime.close()


def test_embedding_preflight_forces_real_embed_and_returns_receipt(monkeypatch):
    from benchmarks.external.locomo.adapters.seam import (
        embedding_model_preflight,
        embedding_preflight_receipt_sha256,
    )

    model = _install_exact_fake(monkeypatch)
    receipt = embedding_model_preflight()

    assert model.embed_calls == 1
    assert receipt["schema"] == "seam-locomo-embedding-preflight/1"
    assert len(receipt["contract_sha256"]) == 64
    assert receipt["name"] == _contract()["name"]
    assert receipt["revision"] == _contract()["revision"]
    assert receipt["dimension"] == 384
    assert receipt["local_files_only"] is True
    assert receipt["probe"] == {
        "performed": True,
        "dimension": 384,
        "finite": True,
        "nonzero": True,
    }
    receipt_sha256 = embedding_preflight_receipt_sha256(receipt)
    assert len(receipt_sha256) == 64
    changed_receipt = {**receipt, "dimension": 768}
    assert embedding_preflight_receipt_sha256(changed_receipt) != receipt_sha256


def test_embedding_preflight_surfaces_lazy_model_load_failure(monkeypatch):
    from benchmarks.external.locomo.adapters.seam import embedding_model_preflight

    _install_exact_fake(
        monkeypatch,
        _ExactFakeModel(error=RuntimeError("local snapshot unavailable")),
    )

    with pytest.raises(RuntimeError, match="No benchmark cases were scored"):
        embedding_model_preflight()


@pytest.mark.parametrize(
    ("attribute", "value"),
    [
        ("model_name", "different/model"),
        ("revision", "different-revision"),
        ("name", "st:different/model@different-revision"),
        ("local_files_only", False),
    ],
)
def test_embedding_preflight_rejects_identity_drift(
    monkeypatch, attribute: str, value: object
):
    from benchmarks.external.locomo.adapters.seam import embedding_model_preflight

    model = _ExactFakeModel()
    setattr(model, attribute, value)
    _install_exact_fake(monkeypatch, model)

    with pytest.raises(RuntimeError, match=attribute):
        embedding_model_preflight()
    assert model.embed_calls == 0


def test_embedding_preflight_rejects_non_boolean_local_only_claim(monkeypatch):
    from benchmarks.external.locomo.adapters.seam import embedding_model_preflight

    model = _ExactFakeModel()
    model.local_files_only = 1
    _install_exact_fake(monkeypatch, model)

    with pytest.raises(RuntimeError, match="local_files_only expected True"):
        embedding_model_preflight()
    assert model.embed_calls == 0


def test_embedding_preflight_rejects_nonlocal_contract_without_false_receipt(
    monkeypatch,
):
    from benchmarks.external.locomo.adapters import seam as seam_adapter

    contract = _contract()
    contract["local_files_only"] = False
    model = _ExactFakeModel()
    model.local_files_only = False
    _install_exact_fake(monkeypatch, model)
    monkeypatch.setattr(seam_adapter, "_embedding_contract", lambda: contract)

    with pytest.raises(
        RuntimeError,
        match="contract: local_files_only must be True, got False",
    ):
        seam_adapter.embedding_model_preflight()
    assert model.embed_calls == 0


def test_embedding_preflight_rejects_declared_dimension_drift(monkeypatch):
    from benchmarks.external.locomo.adapters.seam import embedding_model_preflight

    model = _install_exact_fake(monkeypatch)
    model.dimension = 768

    with pytest.raises(RuntimeError, match="model dimension"):
        embedding_model_preflight()


def test_embedding_preflight_rejects_vector_length_drift(monkeypatch):
    from benchmarks.external.locomo.adapters.seam import embedding_model_preflight

    _install_exact_fake(monkeypatch, _ExactFakeModel(vector=[1.0] * 383))

    with pytest.raises(RuntimeError, match="vector length"):
        embedding_model_preflight()


def test_embedding_preflight_rejects_nonfinite_vector(monkeypatch):
    from benchmarks.external.locomo.adapters.seam import embedding_model_preflight

    vector = [1.0] + [0.0] * 383
    vector[17] = float("nan")
    _install_exact_fake(monkeypatch, _ExactFakeModel(vector=vector))

    with pytest.raises(RuntimeError, match="non-finite"):
        embedding_model_preflight()


def test_open_runtime_surfaces_constructor_failure(monkeypatch, tmp_path):
    from benchmarks.external.locomo.adapters import seam as seam_adapter

    monkeypatch.setattr(seam_adapter, "_DEFAULT_SENTENCE_TRANSFORMER_MODEL", None)

    def _raise(*_args, **_kwargs):
        raise ImportError("no sentence_transformers")

    monkeypatch.setattr(
        "seam_runtime.models.SentenceTransformerModel.__init__",
        _raise,
    )
    with pytest.raises(RuntimeError, match="sentence-transformers"):
        seam_adapter._open_runtime(tmp_path / "test_missing_sbert.db")


@pytest.mark.parametrize(
    ("attribute", "value"),
    [
        ("model_name", "different/model"),
        ("revision", "different-revision"),
    ],
)
def test_open_runtime_rejects_model_identity_or_revision_drift(
    monkeypatch, tmp_path, attribute: str, value: str
):
    from benchmarks.external.locomo.adapters import seam as seam_adapter

    model = _ExactFakeModel()
    setattr(model, attribute, value)
    _install_exact_fake(monkeypatch, model)

    with pytest.raises(RuntimeError, match="embedding contract"):
        seam_adapter._open_runtime(tmp_path / "runtime-contract.db")


def _seed_scope(monkeypatch, tmp_path, scope_id: str = "warm-scope"):
    from benchmarks.external.locomo.adapters.seam import SeamLocomoAdapter

    monkeypatch.setenv("SEAM_DERIVED_FACTS_POLICY", "off")
    monkeypatch.delenv("SEAM_PGVECTOR_DSN", raising=False)
    model = _install_exact_fake(monkeypatch)
    adapter = SeamLocomoAdapter(db_path=str(tmp_path))
    try:
        adapter.reset(scope_id)
        adapter.ingest_turn(
            scope_id,
            ConversationTurn(
                speaker="Ada",
                text="The benchmark uses a pinned local embedding model.",
                timestamp="2026-07-31T00:00:00Z",
            ),
        )
    finally:
        adapter.close()
    return model, tmp_path / f"{scope_id}.db"


def test_keep_db_preflight_accepts_complete_exact_model_coverage(
    monkeypatch, tmp_path
):
    from benchmarks.external.locomo.adapters.seam import SeamLocomoAdapter

    _model, _db_path = _seed_scope(monkeypatch, tmp_path)
    adapter = SeamLocomoAdapter(db_path=str(tmp_path), keep_db=True)
    try:
        receipt = adapter.preflight(["warm-scope"])
    finally:
        adapter.close()

    keep_db = receipt["keep_db"]
    assert keep_db["reused_scopes_checked"] == 1
    assert keep_db["indexable_records_checked"] > 0
    assert keep_db["stale_records"] == 0
    assert keep_db["orphan_records"] == 0


@pytest.mark.parametrize(
    "mutation",
    [
        "update vector_index set model_name = 'st:wrong/model@wrong-revision'",
        (
            "delete from vector_index where record_id = "
            "(select record_id from vector_index limit 1)"
        ),
    ],
    ids=["wrong-model", "missing-vector"],
)
def test_keep_db_preflight_rejects_inexact_or_incomplete_vectors(
    monkeypatch, tmp_path, mutation: str
):
    from benchmarks.external.locomo.adapters.seam import SeamLocomoAdapter

    _model, db_path = _seed_scope(monkeypatch, tmp_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(mutation)
        connection.commit()

    adapter = SeamLocomoAdapter(db_path=str(tmp_path), keep_db=True)
    try:
        with pytest.raises(RuntimeError, match="exact current-model vector coverage"):
            adapter.preflight(["warm-scope"])
    finally:
        adapter.close()


def test_keep_db_preflight_rejects_current_model_orphan_vector(
    monkeypatch, tmp_path
):
    from benchmarks.external.locomo.adapters.seam import SeamLocomoAdapter

    _model, db_path = _seed_scope(monkeypatch, tmp_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            insert into vector_index (
                record_id, model_name, dimension, source_text, source_hash,
                render_version, namespace, scope, vector_json, updated_at
            )
            select
                'raw:orphan', model_name, dimension, source_text, source_hash,
                render_version, namespace, scope, vector_json, updated_at
            from vector_index
            limit 1
            """
        )
        connection.commit()

    adapter = SeamLocomoAdapter(db_path=str(tmp_path), keep_db=True)
    try:
        with pytest.raises(RuntimeError, match="no indexable canonical record"):
            adapter.preflight(["warm-scope"])
    finally:
        adapter.close()


@pytest.mark.parametrize("workers", [1, 2])
def test_cli_preflights_in_parent_before_runner_and_records_receipt(
    monkeypatch, tmp_path, workers: int
):
    from benchmarks.external.locomo import run as locomo_run

    events: list[str] = []
    receipt = {"schema": "test-preflight/1"}

    class FakeAdapter:
        name = "seam"

        def preflight(self, scope_ids):
            events.append("preflight")
            assert list(scope_ids)
            return receipt

        def close(self):
            events.append("close")

    def fake_build_adapter(_name: str, **_kwargs):
        events.append("build")
        return FakeAdapter()

    def fake_serial(**_kwargs):
        events.append("runner")
        _kwargs["checkpoint"]([{"case_id": "scope-1::q0"}], 1, 1)
        return {"status": "ok", "integrity_hash": "existing-report-integrity"}

    def fake_parallel(**kwargs):
        events.append("runner")
        kwargs["adapter_factory"]()
        kwargs["checkpoint"]([{"case_id": "scope-1::q0"}], 1, 1)
        return {"status": "ok", "integrity_hash": "existing-report-integrity"}

    output_path = tmp_path / f"result-{workers}.json"
    partial_payloads: list[dict] = []
    real_atomic_write = locomo_run._atomic_write

    def capture_atomic_write(path, text):
        if str(path).endswith(".partial.json"):
            partial_payloads.append(json.loads(text))
        real_atomic_write(path, text)

    monkeypatch.setattr(locomo_run, "build_adapter", fake_build_adapter)
    monkeypatch.setattr(locomo_run, "run_benchmark_grouped", fake_serial)
    monkeypatch.setattr(locomo_run, "run_benchmark_grouped_parallel", fake_parallel)
    monkeypatch.setattr(locomo_run, "_atomic_write", capture_atomic_write)
    monkeypatch.setenv(
        "SEAM_BENCH_RESULTS_DIR", str(tmp_path / "durable-results")
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "locomo-run",
            "--quickstart",
            "--limit",
            "1",
            "--adapter",
            "seam",
            "--judge",
            "stub",
            "--workers",
            str(workers),
            "--output",
            str(output_path),
        ],
    )

    locomo_run.main()

    assert events.index("preflight") < events.index("runner")
    result = json.loads(output_path.read_text(encoding="utf-8"))
    from benchmarks.external.locomo.adapters.seam import (
        canonical_json_sha256,
        embedding_preflight_receipt_sha256,
    )

    receipt_sha256 = embedding_preflight_receipt_sha256(receipt)
    assert partial_payloads == [
        {
            "status": "PARTIAL",
            "completed": 1,
            "total": 1,
            "case_results": [{"case_id": "scope-1::q0"}],
            "embedding_preflight": receipt,
            "embedding_preflight_sha256": receipt_sha256,
        }
    ]
    assert result["embedding_preflight"] == receipt
    assert result["embedding_preflight_sha256"] == receipt_sha256
    assert result["integrity_hash"] == "existing-report-integrity"
    binding = {
        "schema": "seam-locomo-run-contract/1",
        "report_integrity_hash": "existing-report-integrity",
        "embedding_preflight": receipt,
        "embedding_preflight_sha256": receipt_sha256,
    }
    assert result["run_contract"] == {
        "schema": "seam-locomo-run-contract/1",
        "report_integrity_hash": "existing-report-integrity",
        "embedding_preflight_sha256": receipt_sha256,
        "integrity_sha256": canonical_json_sha256(binding),
    }


def test_cli_preflight_failure_happens_before_runner_or_checkpoint_dir(
    monkeypatch, tmp_path
):
    from benchmarks.external.locomo import run as locomo_run

    class FailingAdapter:
        name = "seam"

        def preflight(self, _scope_ids):
            raise RuntimeError("preflight stopped the run")

        def close(self):
            raise RuntimeError("close failed")

    archive_dir = tmp_path / "must-not-exist"
    monkeypatch.setattr(
        locomo_run, "build_adapter", lambda *_args, **_kwargs: FailingAdapter()
    )
    monkeypatch.setattr(
        locomo_run,
        "run_benchmark_grouped",
        lambda **_kwargs: pytest.fail("runner must not execute"),
    )
    monkeypatch.setenv("SEAM_BENCH_RESULTS_DIR", str(archive_dir))
    monkeypatch.setattr(
        "sys.argv",
        [
            "locomo-run",
            "--quickstart",
            "--limit",
            "1",
            "--adapter",
            "seam",
            "--judge",
            "stub",
        ],
    )

    with pytest.raises(RuntimeError, match="preflight stopped"):
        locomo_run.main()

    assert not archive_dir.exists()


def test_cli_closes_serial_adapter_when_runner_fails(monkeypatch, tmp_path):
    from benchmarks.external.locomo import run as locomo_run

    closed = 0

    class FakeAdapter:
        name = "seam"

        def preflight(self, _scope_ids):
            return {"schema": "test-preflight/1"}

        def close(self):
            nonlocal closed
            closed += 1

    monkeypatch.setattr(
        locomo_run, "build_adapter", lambda *_args, **_kwargs: FakeAdapter()
    )
    monkeypatch.setattr(
        locomo_run,
        "run_benchmark_grouped",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("runner failed")),
    )
    monkeypatch.setenv(
        "SEAM_BENCH_RESULTS_DIR", str(tmp_path / "benchmark-results")
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "locomo-run",
            "--quickstart",
            "--limit",
            "1",
            "--adapter",
            "seam",
            "--judge",
            "stub",
        ],
    )

    with pytest.raises(RuntimeError, match="runner failed"):
        locomo_run.main()

    assert closed == 1


def test_cli_preserves_completed_report_when_preflight_binding_fails(
    monkeypatch, tmp_path
):
    from benchmarks.external.locomo import run as locomo_run

    receipt = {"schema": "test-preflight/1"}

    class FakeAdapter:
        name = "seam"

        def preflight(self, _scope_ids):
            return receipt

        def close(self):
            return None

    output_path = tmp_path / "completed-with-binding-error.json"
    archive_dir = tmp_path / "durable-results"
    monkeypatch.setattr(
        locomo_run, "build_adapter", lambda *_args, **_kwargs: FakeAdapter()
    )
    monkeypatch.setattr(
        locomo_run,
        "run_benchmark_grouped",
        lambda **_kwargs: {"status": "ok"},
    )
    monkeypatch.setenv("SEAM_BENCH_RESULTS_DIR", str(archive_dir))
    monkeypatch.setattr(
        "sys.argv",
        [
            "locomo-run",
            "--quickstart",
            "--limit",
            "1",
            "--adapter",
            "seam",
            "--judge",
            "stub",
            "--output",
            str(output_path),
        ],
    )

    with pytest.raises(SystemExit, match="integrity binding failed"):
        locomo_run.main()

    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["embedding_preflight"] == receipt
    assert report["embedding_preflight_binding_error"].startswith(
        "RuntimeError: LoCoMo result is missing"
    )
    archived = list(archive_dir.glob("*.json"))
    assert len(archived) == 1
    assert json.loads(archived[0].read_text(encoding="utf-8")) == report


def test_ingest_only_preflights_before_ingest_and_records_receipt(
    monkeypatch, tmp_path, capsys
):
    from benchmarks.external.locomo import ingest_only

    events: list[str] = []
    adapter_db_paths: list[str] = []
    receipt = {"schema": "test-preflight/1"}
    case = BenchmarkCase(
        case_id="scope-1::q0",
        conversation=(ConversationTurn("Ada", "A local fact."),),
        question="What fact?",
        gold_answer="A local fact.",
    )

    class FakeAdapter:
        def preflight(self, scope_ids):
            events.append("preflight")
            assert list(scope_ids) == ["scope-1"]
            return receipt

        def reset(self, _scope):
            events.append("reset")
            resolved_root.mkdir(parents=True, exist_ok=True)
            (resolved_root / "scope-1.db").write_bytes(b"pristine corpus")

        def ingest_turn(self, _scope, _turn):
            events.append("ingest")

        def close(self):
            events.append("close")

    monkeypatch.setattr(ingest_only, "load_locomo_cases", lambda _path: [case])
    monkeypatch.chdir(tmp_path)
    requested_root = Path("relative-db-root")
    resolved_root = requested_root.resolve()

    def fake_build_adapter(*_args, **kwargs):
        adapter_db_paths.append(kwargs["db_path"])
        return FakeAdapter()

    monkeypatch.setattr(ingest_only, "build_adapter", fake_build_adapter)

    assert (
        ingest_only.main(
            [
                "--dataset-path",
                str(tmp_path / "unused.json"),
                "--db-path",
                str(requested_root),
            ]
        )
        == 0
    )

    assert events.index("preflight") < events.index("reset")
    assert adapter_db_paths == [str(resolved_root)]
    output = capsys.readouterr().out
    report = json.loads(output[output.index("{") :])
    from benchmarks.external.locomo.adapters.seam import (
        canonical_json_sha256,
        embedding_preflight_receipt_sha256,
    )

    receipt_sha256 = embedding_preflight_receipt_sha256(receipt)
    assert report["db_path"] == str(resolved_root)
    assert report["corpus_digest"] == ingest_only.corpus_digest(resolved_root)
    assert report["embedding_preflight"] == receipt
    assert report["embedding_preflight_sha256"] == receipt_sha256
    corpus_binding = {
        "schema": "seam-locomo-corpus-contract/1",
        "corpus_digest": report["corpus_digest"],
        "embedding_preflight": receipt,
        "embedding_preflight_sha256": receipt_sha256,
    }
    assert report["corpus_contract"] == {
        "schema": "seam-locomo-corpus-contract/1",
        "corpus_digest": report["corpus_digest"],
        "embedding_preflight_sha256": receipt_sha256,
        "integrity_sha256": canonical_json_sha256(corpus_binding),
    }


@pytest.mark.parametrize("sqlite_filename", ["scope.db", "scope.db-wal", "scope.db-shm"])
def test_ingest_only_rejects_existing_sqlite_file_before_adapter_or_preflight(
    monkeypatch, tmp_path, sqlite_filename: str
):
    from benchmarks.external.locomo import ingest_only

    target_root = tmp_path / "existing-corpus"
    existing_sqlite_file = target_root / "nested" / sqlite_filename
    existing_sqlite_file.parent.mkdir(parents=True)
    existing_sqlite_file.write_bytes(b"existing corpus")
    events: list[str] = []

    def fake_load(_path):
        events.append("load")
        return []

    def fake_build(*_args, **_kwargs):
        events.append("build")
        pytest.fail("adapter must not be built for an occupied target root")

    monkeypatch.setattr(ingest_only, "load_locomo_cases", fake_load)
    monkeypatch.setattr(ingest_only, "build_adapter", fake_build)

    with pytest.raises(
        RuntimeError,
        match="already contains SQLite corpus files or sidecars",
    ) as exc_info:
        ingest_only.main(
            [
                "--dataset-path",
                str(tmp_path / "unused.json"),
                "--db-path",
                str(target_root),
            ]
        )

    assert events == []
    assert f"nested/{sqlite_filename}" in str(exc_info.value)
    assert existing_sqlite_file.read_bytes() == b"existing corpus"


def test_required_quickstart_ci_provisions_exact_revision_then_runs_offline():
    workflow = (
        Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"
    ).read_text(encoding="utf-8")
    quickstart_job = workflow.split("  locomo-quickstart-bil2:", 1)[1]
    cache_step = quickstart_job.split(
        "      - name: Cache Hugging Face models", 1
    )[1].split("      - name: Install package", 1)[0]
    provision_step = quickstart_job.split(
        "      - name: Provision exact pinned LoCoMo embedding snapshot", 1
    )[1].split("      - name: Run LoCoMo quickstart smoke", 1)[0]
    smoke_step = quickstart_job.split(
        "      - name: Run LoCoMo quickstart smoke", 1
    )[1].split("      - name: Seal LoCoMo quickstart as BIL-2", 1)[0]

    assert "DERIVED_FACTS_EMBEDDING_REVISION" in quickstart_job
    assert "snapshot_download(" in quickstart_job
    assert "steps.locomo-embedding.outputs.revision" in quickstart_job
    assert "path: ${{ runner.temp }}/seam-huggingface" in cache_step
    for step in (provision_step, smoke_step):
        assert "HF_HOME: ${{ runner.temp }}/seam-huggingface" in step
        assert "HF_HUB_CACHE: ${{ runner.temp }}/seam-huggingface/hub" in step
        assert (
            "HUGGINGFACE_HUB_CACHE: ${{ runner.temp }}/seam-huggingface/hub"
            in step
        )
        assert (
            "TRANSFORMERS_CACHE: "
            "${{ runner.temp }}/seam-huggingface/transformers"
            in step
        )
    assert 'HF_HUB_OFFLINE: "0"' in provision_step
    assert 'TRANSFORMERS_OFFLINE: "0"' in provision_step
    assert 'HF_HUB_OFFLINE: "1"' in smoke_step
    assert 'TRANSFORMERS_OFFLINE: "1"' in smoke_step
