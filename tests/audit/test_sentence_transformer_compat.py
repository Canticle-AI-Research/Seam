from __future__ import annotations

import sys
from types import SimpleNamespace

from seam_runtime.models import SentenceTransformerModel


def test_local_only_resolves_cached_snapshot_for_legacy_constructor(monkeypatch) -> None:
    constructor_calls: list[tuple[str, str | None]] = []
    snapshot_calls: list[dict[str, object]] = []

    class LegacySentenceTransformer:
        def __init__(self, model_name: str, *, revision: str | None = None) -> None:
            constructor_calls.append((model_name, revision))

        def get_sentence_embedding_dimension(self) -> int:
            return 384

    def fake_snapshot_download(**kwargs: object) -> str:
        snapshot_calls.append(kwargs)
        return "/cached/bge-small-en-v1.5"

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        SimpleNamespace(SentenceTransformer=LegacySentenceTransformer),
    )
    monkeypatch.setitem(
        sys.modules,
        "huggingface_hub",
        SimpleNamespace(snapshot_download=fake_snapshot_download),
    )

    model = SentenceTransformerModel(
        model_name="BAAI/bge-small-en-v1.5",
        revision="abc123",
        local_files_only=True,
    )
    model._load()

    assert snapshot_calls == [
        {
            "repo_id": "BAAI/bge-small-en-v1.5",
            "revision": "abc123",
            "local_files_only": True,
        }
    ]
    assert constructor_calls == [("/cached/bge-small-en-v1.5", None)]


def test_local_only_existing_path_never_calls_hub(monkeypatch, tmp_path) -> None:
    constructor_calls: list[tuple[str, str | None]] = []
    local_model = tmp_path / "model"
    local_model.mkdir()

    class LegacySentenceTransformer:
        def __init__(self, model_name: str, *, revision: str | None = None) -> None:
            constructor_calls.append((model_name, revision))

        def get_sentence_embedding_dimension(self) -> int:
            return 384

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        SimpleNamespace(SentenceTransformer=LegacySentenceTransformer),
    )

    model = SentenceTransformerModel(
        model_name=str(local_model),
        revision="ignored-for-local-path",
        local_files_only=True,
    )
    model._load()

    assert constructor_calls == [(str(local_model), None)]


def test_online_load_forwards_revision(monkeypatch) -> None:
    constructor_calls: list[tuple[str, str | None]] = []

    class LegacySentenceTransformer:
        def __init__(self, model_name: str, *, revision: str | None = None) -> None:
            constructor_calls.append((model_name, revision))

        def get_sentence_embedding_dimension(self) -> int:
            return 384

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        SimpleNamespace(SentenceTransformer=LegacySentenceTransformer),
    )

    model = SentenceTransformerModel(
        model_name="BAAI/bge-small-en-v1.5",
        revision="abc123",
    )
    model._load()

    assert constructor_calls == [("BAAI/bge-small-en-v1.5", "abc123")]
