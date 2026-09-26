"""Public SEAM exports loaded lazily to keep portable subpackages isolated."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "ContextCandidate": (".context_assembly", "ContextCandidate"),
    "ContextPack": (".context_assembly", "ContextPack"),
    "GraphProductFact": (".graph_products", "GraphProductFact"),
    "BatchIngestItem": (".lifecycle", "BatchIngestItem"),
    "Artifact": (".mirl", "Artifact"),
    "IRBatch": (".mirl", "IRBatch"),
    "MIRLRecord": (".mirl", "MIRLRecord"),
    "Pack": (".mirl", "Pack"),
    "PersistReport": (".mirl", "PersistReport"),
    "ReconcileReport": (".mirl", "ReconcileReport"),
    "RecordKind": (".mirl", "RecordKind"),
    "SearchResult": (".mirl", "SearchResult"),
    "Status": (".mirl", "Status"),
    "TraceGraph": (".mirl", "TraceGraph"),
    "VerifyReport": (".mirl", "VerifyReport"),
    "AdapterEnvelope": (".qualification", "AdapterEnvelope"),
    "AdapterResponse": (".qualification", "AdapterResponse"),
    "QualificationBoundary": (".qualification", "QualificationBoundary"),
    "QualificationCase": (".qualification", "QualificationCase"),
    "QualificationManifest": (".qualification", "QualificationManifest"),
    "QualificationResult": (".qualification", "QualificationResult"),
    "build_frozen_manifest": (".qualification", "build_frozen_manifest"),
    "execute_provider_free": (".qualification", "execute_provider_free"),
    "qualify_results": (".qualification", "qualify_results"),
    "SeamRuntime": (".runtime", "SeamRuntime"),
    "ReasonedRetrieval": (".sdk", "ReasonedRetrieval"),
    "ReasoningSession": (".sdk", "ReasoningSession"),
    "SeamSDK": (".sdk", "SeamSDK"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute = target
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})
