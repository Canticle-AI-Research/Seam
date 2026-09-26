"""Deterministic, fail-closed activation planning and SkillFrame projection."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from dataclasses import dataclass
from typing import Any, Iterable, Protocol

from .models import SkillPackage
from .registry import RegistrySnapshot

TOKENIZER_ID = "tiktoken:cl100k_base"


class PlanningError(ValueError):
    """The requested skill chain cannot be activated safely."""


class FrameTokenizer(Protocol):
    encoding_name: str
    implementation: str
    version: str

    @property
    def fingerprint(self) -> str: ...

    def count(self, text: str) -> int: ...


class TiktokenFrameTokenizer:
    """Exact tokenizer for the complete serialized SkillFrame text."""

    implementation = "tiktoken"

    def __init__(self, encoding_name: str = "cl100k_base"):
        import tiktoken

        self.encoding_name = encoding_name
        self.version = importlib.metadata.version("tiktoken")
        self._encoding = tiktoken.get_encoding(encoding_name)

    @property
    def fingerprint(self) -> str:
        return _sha(
            _canonical_json(
                {
                    "encoding": self.encoding_name,
                    "implementation": self.implementation,
                    "version": self.version,
                }
            )
        )

    def count(self, text: str) -> int:
        return len(self._encoding.encode(text, disallowed_special=()))


@dataclass(frozen=True)
class ActivationPolicy:
    max_skills: int = 8
    token_budget: int = 16_000

    def __post_init__(self) -> None:
        if self.max_skills < 1:
            raise ValueError("max_skills must be positive")
        if self.token_budget < 1:
            raise ValueError("token_budget must be positive")

    def to_dict(self) -> dict[str, int]:
        return {"max_skills": self.max_skills, "token_budget": self.token_budget}


@dataclass(frozen=True)
class HostCapabilities:
    capabilities: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()

    def normalized(self) -> "HostCapabilities":
        return HostCapabilities(
            capabilities=tuple(sorted(set(self.capabilities))),
            tools=tuple(sorted(set(self.tools))),
            permissions=tuple(sorted(set(self.permissions))),
        )

    def to_dict(self) -> dict[str, list[str]]:
        normalized = self.normalized()
        return {
            "capabilities": list(normalized.capabilities),
            "tools": list(normalized.tools),
            "permissions": list(normalized.permissions),
        }


@dataclass(frozen=True)
class SkillReference:
    skill_id: str
    revision: str

    @property
    def package_id(self) -> str:
        return f"{self.skill_id}@{self.revision}"

    def to_dict(self) -> dict[str, str]:
        return {"skill_id": self.skill_id, "revision": self.revision}


@dataclass(frozen=True)
class PlanExclusion:
    skill_id: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {"skill_id": self.skill_id, "reason": self.reason}


@dataclass(frozen=True)
class ActivationPlan:
    skills: tuple[SkillReference, ...]
    exclusions: tuple[PlanExclusion, ...]
    requested_ids: tuple[str, ...]
    task_fingerprint: str
    policy_fingerprint: str
    capabilities_fingerprint: str
    tokenizer_fingerprint: str
    snapshot_fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "seam-activation-plan/v1",
            "skills": [skill.to_dict() for skill in self.skills],
            "exclusions": [exclusion.to_dict() for exclusion in self.exclusions],
            "requested_ids": list(self.requested_ids),
            "task_fingerprint": self.task_fingerprint,
            "policy_fingerprint": self.policy_fingerprint,
            "capabilities_fingerprint": self.capabilities_fingerprint,
            "tokenizer_fingerprint": self.tokenizer_fingerprint,
            "snapshot_fingerprint": self.snapshot_fingerprint,
        }

    def to_json(self) -> str:
        return _canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ActivationPlan":
        if value.get("schema") != "seam-activation-plan/v1":
            raise ValueError("unsupported activation plan schema")
        return cls(
            skills=tuple(
                SkillReference(str(item["skill_id"]), str(item["revision"]))
                for item in value.get("skills", ())
            ),
            exclusions=tuple(
                PlanExclusion(str(item["skill_id"]), str(item["reason"]))
                for item in value.get("exclusions", ())
            ),
            requested_ids=tuple(str(item) for item in value.get("requested_ids", ())),
            task_fingerprint=str(value["task_fingerprint"]),
            policy_fingerprint=str(value["policy_fingerprint"]),
            capabilities_fingerprint=str(value["capabilities_fingerprint"]),
            tokenizer_fingerprint=str(value["tokenizer_fingerprint"]),
            snapshot_fingerprint=str(value["snapshot_fingerprint"]),
        )

    @property
    def fingerprint(self) -> str:
        return _sha(self.to_json())


@dataclass(frozen=True)
class SkillFrameEntry:
    skill_id: str
    revision: str
    instructions: str
    token_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "revision": self.revision,
            "instructions": self.instructions,
            "token_count": self.token_count,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SkillFrameEntry":
        return cls(
            skill_id=str(value["skill_id"]),
            revision=str(value["revision"]),
            instructions=str(value["instructions"]),
            token_count=int(value["token_count"]),
        )


@dataclass(frozen=True)
class SkillFrame:
    entries: tuple[SkillFrameEntry, ...]
    token_count: int
    max_skills: int
    token_budget: int
    plan_fingerprint: str
    task_fingerprint: str
    policy_fingerprint: str
    capabilities_fingerprint: str
    tokenizer_fingerprint: str
    snapshot_fingerprint: str
    tokenizer_name: str
    tokenizer_implementation: str
    tokenizer_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "seam-skill-frame/v1",
            "entries": [entry.to_dict() for entry in self.entries],
            "token_count": self.token_count,
            "max_skills": self.max_skills,
            "token_budget": self.token_budget,
            "plan_fingerprint": self.plan_fingerprint,
            "task_fingerprint": self.task_fingerprint,
            "policy_fingerprint": self.policy_fingerprint,
            "capabilities_fingerprint": self.capabilities_fingerprint,
            "tokenizer_fingerprint": self.tokenizer_fingerprint,
            "snapshot_fingerprint": self.snapshot_fingerprint,
            "tokenizer": {
                "name": self.tokenizer_name,
                "implementation": self.tokenizer_implementation,
                "version": self.tokenizer_version,
            },
        }

    def to_json(self) -> str:
        return _canonical_json(self.to_dict())


def plan_activation(
    snapshot: RegistrySnapshot,
    requested_ids: Iterable[str],
    *,
    task: str,
    policy: ActivationPolicy | None = None,
    host: HostCapabilities | None = None,
    candidate_ids: Iterable[str] = (),
    pinned: Iterable[SkillFrameEntry] = (),
    tokenizer: FrameTokenizer | None = None,
) -> tuple[ActivationPlan, SkillFrame]:
    """Close requirements, validate policy, and emit a complete bounded frame."""

    policy = policy or ActivationPolicy()
    host = (host or HostCapabilities()).normalized()
    tokenizer = tokenizer or TiktokenFrameTokenizer()
    pinned_entries = tuple(pinned)
    packages = {package.skill_id: package for package in snapshot.packages}
    for entry in pinned_entries:
        package = packages.get(entry.skill_id)
        if package is None:
            raise PlanningError(f"pinned skill missing from snapshot: {entry.skill_id}")
        if package.revision != entry.revision:
            raise PlanningError(
                f"pinned revision mismatch for {entry.skill_id}: "
                f"window {entry.revision}, snapshot {package.revision}"
            )
    requested = tuple(
        dict.fromkeys(
            [*(entry.skill_id for entry in pinned_entries), *(str(skill_id) for skill_id in requested_ids)]
        )
    )
    if not requested:
        raise PlanningError("at least one requested skill is required")
    selected: dict[str, SkillPackage] = {}
    visiting: list[str] = []

    def visit(skill_id: str, requester: str | None = None) -> None:
        if skill_id in visiting:
            start = visiting.index(skill_id)
            cycle = " -> ".join((*visiting[start:], skill_id))
            raise PlanningError(f"dependency cycle: {cycle}")
        if skill_id in selected:
            return
        package = packages.get(skill_id)
        if package is None:
            prefix = f" required by {requester}" if requester else ""
            raise PlanningError(f"missing dependency {skill_id}{prefix}")
        if package.derived.parser_policy == "minimal-scalar-fallback":
            raise PlanningError(
                f"policy metadata is incomplete for {package.skill_id}: "
                "malformed front matter was indexed with scalar fallback"
            )
        visiting.append(skill_id)
        for relation in package.declared.relations:
            if relation.kind == "requires":
                visit(_qualified_target(package, relation.target), package.skill_id)
        visiting.pop()
        selected[skill_id] = package

    for requested_id in requested:
        visit(requested_id)

    _validate_host(selected.values(), host)
    _validate_conflicts(selected)
    ordered = _topological_order(selected)
    if len(ordered) > policy.max_skills:
        raise PlanningError(
            f"skill-count budget exceeded: selected {len(ordered)}, maximum {policy.max_skills}"
        )

    task_fp = _sha(task)
    policy_fp = _sha(_canonical_json(policy.to_dict()))
    capabilities_fp = _sha(_canonical_json(host.to_dict()))
    tokenizer_fp = tokenizer.fingerprint
    candidate_set = tuple(dict.fromkeys(str(skill_id) for skill_id in candidate_ids))
    exclusions = tuple(
        PlanExclusion(skill_id, "not selected") for skill_id in sorted(candidate_set) if skill_id not in selected
    )
    plan = ActivationPlan(
        skills=tuple(SkillReference(package.skill_id, package.revision) for package in ordered),
        exclusions=exclusions,
        requested_ids=requested,
        task_fingerprint=task_fp,
        policy_fingerprint=policy_fp,
        capabilities_fingerprint=capabilities_fp,
        tokenizer_fingerprint=tokenizer_fp,
        snapshot_fingerprint=snapshot.fingerprint,
    )
    entries = tuple(
        SkillFrameEntry(
            package.skill_id,
            package.revision,
            package.instructions,
            tokenizer.count(package.instructions),
        )
        for package in ordered
    )
    total_tokens = tokenizer.count(render_skill_frame_text(entries))
    if total_tokens > policy.token_budget:
        raise PlanningError(
            f"token budget exceeded: complete instructions require {total_tokens}, maximum {policy.token_budget}"
        )
    frame = SkillFrame(
        entries=entries,
        token_count=total_tokens,
        max_skills=policy.max_skills,
        token_budget=policy.token_budget,
        plan_fingerprint=plan.fingerprint,
        task_fingerprint=task_fp,
        policy_fingerprint=policy_fp,
        capabilities_fingerprint=capabilities_fp,
        tokenizer_fingerprint=tokenizer_fp,
        snapshot_fingerprint=snapshot.fingerprint,
        tokenizer_name=tokenizer.encoding_name,
        tokenizer_implementation=tokenizer.implementation,
        tokenizer_version=tokenizer.version,
    )
    return plan, frame


def render_skill_frame_text(entries: Iterable[SkillFrameEntry]) -> str:
    """Return the exact complete text counted against the frame budget."""

    return "\n".join(
        f'<skill id="{entry.skill_id}" revision="{entry.revision}">\n'
        f"{entry.instructions}\n</skill>"
        for entry in entries
    )


def _validate_host(packages: Iterable[SkillPackage], host: HostCapabilities) -> None:
    available = {
        "capabilities": set(host.capabilities),
        "tools": set(host.tools),
        "permissions": set(host.permissions),
    }
    for package in sorted(packages, key=lambda item: item.skill_id):
        required = {
            "capabilities": set(package.declared.capabilities),
            "tools": set(package.declared.tools),
            "permissions": set(package.declared.permissions),
        }
        for kind in ("capabilities", "tools", "permissions"):
            missing = sorted(required[kind] - available[kind])
            if missing:
                raise PlanningError(
                    f"{package.skill_id} missing {kind}: {', '.join(missing)}"
                )


def _validate_conflicts(selected: dict[str, SkillPackage]) -> None:
    for package in selected.values():
        for relation in package.declared.relations:
            target = _qualified_target(package, relation.target)
            if relation.kind == "conflicts_with" and target in selected:
                pair = sorted((package.skill_id, target))
                raise PlanningError(f"explicit conflict: {pair[0]} conflicts with {pair[1]}")


def _topological_order(selected: dict[str, SkillPackage]) -> tuple[SkillPackage, ...]:
    outgoing = {skill_id: set() for skill_id in selected}
    indegree = {skill_id: 0 for skill_id in selected}
    for package in selected.values():
        for relation in package.declared.relations:
            target = _qualified_target(package, relation.target)
            edge: tuple[str, str] | None = None
            if relation.kind in {"requires", "runs_after"} and target in selected:
                edge = (target, package.skill_id)
            elif relation.kind == "runs_before" and target in selected:
                edge = (package.skill_id, target)
            if edge and edge[1] not in outgoing[edge[0]]:
                outgoing[edge[0]].add(edge[1])
                indegree[edge[1]] += 1
    ready = sorted(skill_id for skill_id, degree in indegree.items() if degree == 0)
    ordered: list[SkillPackage] = []
    while ready:
        current = ready.pop(0)
        ordered.append(selected[current])
        for target in sorted(outgoing[current]):
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
                ready.sort()
    if len(ordered) != len(selected):
        cyclic = sorted(skill_id for skill_id, degree in indegree.items() if degree)
        raise PlanningError(f"dependency cycle in ordering relations: {', '.join(cyclic)}")
    return tuple(ordered)


def _qualified_target(package: SkillPackage, target: str) -> str:
    return target if ":" in target else f"{package.namespace}:{target}"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
