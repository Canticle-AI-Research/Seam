"""Immutable portable records for SEAM's Skill Knowledge Base.

This module deliberately depends only on the Python standard library.  The
records are the authority; search indexes and graph payloads are projections.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Mapping

RELATION_KINDS = frozenset(
    {"requires", "runs_before", "runs_after", "conflicts_with", "related", "composes"}
)


@dataclass(frozen=True)
class SkillRelation:
    kind: str
    target: str

    def __post_init__(self) -> None:
        if self.kind not in RELATION_KINDS:
            raise ValueError(f"unsupported skill relation kind: {self.kind!r}")
        if not self.target.strip():
            raise ValueError("skill relation target must be non-empty")

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "target": self.target}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SkillRelation":
        return cls(kind=str(value["kind"]), target=str(value["target"]))


@dataclass(frozen=True)
class DeclaredSkillMetadata:
    title: str
    description: str
    summary: str
    category: str = ""
    contexts: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    relations: tuple[SkillRelation, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "description": self.description,
            "summary": self.summary,
            "category": self.category,
            "contexts": list(self.contexts),
            "tags": list(self.tags),
            "capabilities": list(self.capabilities),
            "tools": list(self.tools),
            "permissions": list(self.permissions),
            "relations": [relation.to_dict() for relation in self.relations],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DeclaredSkillMetadata":
        return cls(
            title=str(value["title"]),
            description=str(value["description"]),
            summary=str(value["summary"]),
            category=str(value.get("category", "")),
            contexts=tuple(str(item) for item in value.get("contexts", ())),
            tags=tuple(str(item) for item in value.get("tags", ())),
            capabilities=tuple(str(item) for item in value.get("capabilities", ())),
            tools=tuple(str(item) for item in value.get("tools", ())),
            permissions=tuple(str(item) for item in value.get("permissions", ())),
            relations=tuple(SkillRelation.from_dict(item) for item in value.get("relations", ())),
        )


@dataclass(frozen=True)
class DerivedSkillMetadata:
    source_label: str
    source_path: str
    source_kind: str
    parser_policy: str = "unknown"
    parser_version: str = "0"
    inferred_title: str = ""
    inferred_description: str = ""
    inferred_summary: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "source_label": self.source_label,
            "source_path": self.source_path,
            "source_kind": self.source_kind,
            "parser_policy": self.parser_policy,
            "parser_version": self.parser_version,
            "inferred_title": self.inferred_title,
            "inferred_description": self.inferred_description,
            "inferred_summary": self.inferred_summary,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DerivedSkillMetadata":
        return cls(
            source_label=str(value["source_label"]),
            source_path=str(value["source_path"]),
            source_kind=str(value["source_kind"]),
            parser_policy=str(value.get("parser_policy", "unknown")),
            parser_version=str(value.get("parser_version", "0")),
            inferred_title=str(value.get("inferred_title", "")),
            inferred_description=str(value.get("inferred_description", "")),
            inferred_summary=str(value.get("inferred_summary", "")),
        )


@dataclass(frozen=True)
class SkillPackage:
    namespace: str
    name: str
    revision: str
    source_sha256: str
    instructions: str
    declared: DeclaredSkillMetadata
    derived: DerivedSkillMetadata

    def __post_init__(self) -> None:
        instruction_digest = hashlib.sha256(self.instructions.encode("utf-8")).hexdigest()
        if self.source_sha256 != instruction_digest:
            raise ValueError(
                f"instruction digest mismatch for {self.namespace}:{self.name}"
            )
        if self.revision != self.source_sha256:
            raise ValueError(
                f"revision and source SHA-256 must match for {self.namespace}:{self.name}"
            )

    @property
    def skill_id(self) -> str:
        return f"{self.namespace}:{self.name}"

    @property
    def package_id(self) -> str:
        return f"{self.skill_id}@{self.revision}"

    @property
    def title(self) -> str:
        return self.declared.title or self.derived.inferred_title or self.name

    @property
    def description(self) -> str:
        return self.declared.description or self.derived.inferred_description or self.title

    @property
    def summary(self) -> str:
        return self.declared.summary or self.derived.inferred_summary or self.description

    def to_dict(self) -> dict[str, Any]:
        return {
            "namespace": self.namespace,
            "name": self.name,
            "revision": self.revision,
            "source_sha256": self.source_sha256,
            "instructions": self.instructions,
            "declared": self.declared.to_dict(),
            "derived": self.derived.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SkillPackage":
        return cls(
            namespace=str(value["namespace"]),
            name=str(value["name"]),
            revision=str(value["revision"]),
            source_sha256=str(value["source_sha256"]),
            instructions=str(value["instructions"]),
            declared=DeclaredSkillMetadata.from_dict(value["declared"]),
            derived=DerivedSkillMetadata.from_dict(value["derived"]),
        )


@dataclass(frozen=True)
class SkillSearchResult:
    skill_id: str
    revision: str
    score: int
    matched_terms: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "revision": self.revision,
            "score": self.score,
            "matched_terms": list(self.matched_terms),
        }
