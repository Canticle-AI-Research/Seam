from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol

try:
    # Optional fast path only; core deps stay lean (rich + tiktoken). numpy
    # arrives transitively with the sbert/rerank extras, where dense-vector
    # search volume makes it matter.
    import numpy as _numpy
except ImportError:  # pragma: no cover - exercised via the pure-Python branch
    _numpy = None


class EmbeddingModel(Protocol):
    name: str
    dimension: int

    def embed(self, text: str) -> list[float]:
        ...


@dataclass(frozen=True)
class EmbeddingSettings:
    provider: str = "hash"
    model: str = "text-embedding-3-small"
    base_url: str = "https://api.openai.com/v1/embeddings"
    api_key_env: str = "OPENAI_API_KEY"
    timeout_s: float = 30.0
    dimensions: int | None = None


@dataclass
class HashEmbeddingModel:
    name: str = "hash-bow-v1"
    dimension: int = 64

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for token in _tokens(text):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        return _normalize(vector)


@dataclass
class SentenceTransformerModel:
    model_name: str = "all-MiniLM-L6-v2"
    revision: str | None = None
    local_files_only: bool = False
    name: str = ""
    dimension: int = 384
    _model: Any = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.name:
            revision = f"@{self.revision}" if self.revision else ""
            self.name = f"st:{self.model_name}{revision}"

    def _load(self):
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is not None:
                return self._model
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise RuntimeError("sentence-transformers is not installed") from exc
            if self.local_files_only:
                model_source = self.model_name
                if not os.path.exists(model_source):
                    # Resolve the exact cached snapshot through huggingface_hub
                    # first. Passing the resulting local path preserves offline
                    # behavior across the supported sentence-transformers 2.x
                    # range, whose constructor lacks local_files_only.
                    from huggingface_hub import snapshot_download

                    model_source = snapshot_download(
                        repo_id=self.model_name,
                        revision=self.revision,
                        local_files_only=True,
                    )
                kwargs = {}
            else:
                model_source = self.model_name
                kwargs = {}
                if self.revision:
                    kwargs["revision"] = self.revision
            self._model = SentenceTransformer(model_source, **kwargs)
            getter = getattr(self._model, "get_embedding_dimension", None) or self._model.get_sentence_embedding_dimension
            self.dimension = getter()
        return self._model

    def embed(self, text: str) -> list[float]:
        model = self._load()
        vector = model.encode(text, convert_to_numpy=True)
        return _normalize(vector.tolist())


@dataclass
class OpenAICompatibleEmbeddingModel:
    model: str
    api_key_env: str = "OPENAI_API_KEY"
    base_url: str = "https://api.openai.com/v1/embeddings"
    timeout_s: float = 30.0
    dimensions: int | None = None
    name: str = ""
    dimension: int = 1536

    def __post_init__(self) -> None:
        if self.dimensions is not None:
            self.dimension = self.dimensions
        if not self.name:
            self.name = f"openai-compatible:{self.model}"

    def embed(self, text: str) -> list[float]:
        api_key = os.environ.get(self.api_key_env)
        if not api_key:
            raise RuntimeError(f"Missing API key in {self.api_key_env}")
        body_payload: dict[str, Any] = {"model": self.model, "input": text}
        if self.dimensions is not None:
            body_payload["dimensions"] = self.dimensions
        body = json.dumps(body_payload).encode("utf-8")
        request = urllib.request.Request(
            self.base_url,
            data=body,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        max_retries = 3
        base_delay = 1.0
        last_exc: BaseException | None = None
        for attempt in range(max_retries):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as exc:
                last_exc = exc
                if exc.code not in (429, 500, 502, 503, 504) or attempt == max_retries - 1:
                    raise
            except urllib.error.URLError as exc:
                last_exc = exc
                if attempt == max_retries - 1:
                    raise
            if attempt < max_retries - 1:
                time.sleep(base_delay * (2 ** attempt))
        else:
            if last_exc is not None:
                raise last_exc
            raise RuntimeError("Embedding request failed after retries")
        vector = [float(value) for value in payload["data"][0]["embedding"]]
        if len(vector) != self.dimension:
            raise RuntimeError(
                f"Embedding dimension drift: provider returned {len(vector)} dims, "
                f"expected {self.dimension}. Set SEAM_EMBEDDING_DIMENSIONS to match."
            )
        return _normalize(vector)


def embedding_settings_from_env() -> EmbeddingSettings:
    provider = os.environ.get("SEAM_EMBEDDING_PROVIDER", "hash").strip().lower() or "hash"
    model = os.environ.get("SEAM_EMBEDDING_MODEL", "text-embedding-3-small")
    base_url = os.environ.get("SEAM_EMBEDDING_BASE_URL", "https://api.openai.com/v1/embeddings")
    api_key_env = os.environ.get("SEAM_EMBEDDING_API_KEY_ENV", "OPENAI_API_KEY")
    timeout_s = float(os.environ.get("SEAM_EMBEDDING_TIMEOUT_S", "30"))
    dimensions = _coerce_positive_int(os.environ.get("SEAM_EMBEDDING_DIMENSIONS"))
    return EmbeddingSettings(
        provider=provider,
        model=model,
        base_url=base_url,
        api_key_env=api_key_env,
        timeout_s=timeout_s,
        dimensions=dimensions,
    )


def default_embedding_model() -> EmbeddingModel:
    settings = embedding_settings_from_env()
    if settings.provider in {"hash", "local", "deterministic"}:
        return HashEmbeddingModel()
    if settings.provider in {"sentence-transformers", "st", "sbert"}:
        return SentenceTransformerModel(model_name=settings.model)
    if settings.provider in {"openai", "openai-compatible"}:
        return OpenAICompatibleEmbeddingModel(
            model=settings.model,
            base_url=settings.base_url,
            api_key_env=settings.api_key_env,
            timeout_s=settings.timeout_s,
            dimensions=settings.dimensions,
        )
    raise ValueError(f"Unsupported embedding provider: {settings.provider}")


def cosine(left: list[float], right: list[float]) -> float:
    """Cosine similarity for dense embedding vectors stored as lists.

    Both vectors must have the same length.  Use this when working with
    dense embeddings from ``EmbeddingModel.embed()`` (hash, sentence-transformers,
    OpenAI-compatible, etc.).

    For sparse / bag-of-words vectors (``dict[str, float]``), use
    ``seam_runtime.mirl.cosine_similarity`` instead.
    """
    if not left or not right or len(left) != len(right):
        return 0.0
    if _numpy is not None:
        left_arr = _numpy.asarray(left, dtype=_numpy.float64)
        right_arr = _numpy.asarray(right, dtype=_numpy.float64)
        denominator = float(_numpy.linalg.norm(left_arr)) * float(_numpy.linalg.norm(right_arr))
        if not denominator:
            return 0.0
        return float(left_arr @ right_arr) / denominator
    numerator = sum(a * b for a, b in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if not left_norm or not right_norm:
        return 0.0
    return numerator / (left_norm * right_norm)


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if not norm:
        return [0.0] * len(vector)
    return [value / norm for value in vector]


def _tokens(text: str) -> list[str]:
    return [part for part in text.lower().replace("\n", " ").split(" ") if part]


def _coerce_positive_int(value: str | None) -> int | None:
    if value is None or not value.strip():
        return None
    parsed = int(value)
    if parsed <= 0:
        raise ValueError("Embedding dimensions must be a positive integer")
    return parsed
