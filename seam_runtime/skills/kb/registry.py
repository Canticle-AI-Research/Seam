"""Bounded ingestion and deterministic lexical search for portable SkillDB."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping

import yaml

from .models import (
    RELATION_KINDS,
    DeclaredSkillMetadata,
    DerivedSkillMetadata,
    SkillPackage,
    SkillRelation,
    SkillSearchResult,
)

SNAPSHOT_SCHEMA = "seam-skilldb/v1"
SEARCH_PROJECTION_SCHEMA = "seam-skill-search-projection/v1"
DEFAULT_MAX_FILE_BYTES = 1_048_576
_SAFE_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_TOKEN = re.compile(r"[a-z0-9]+(?:[-_][a-z0-9]+)*")
_FRONTMATTER_SCALAR = re.compile(r"^(name|title|description|summary):[ \t]*(.*)$")


class SkillSourceError(ValueError):
    """A source cannot be safely represented in the canonical registry."""


@dataclass(frozen=True)
class SkillSourceRoot:
    """An explicitly typed source root for bounded skill discovery."""

    label: str
    path: Path
    kind: Literal["hybrid", "markdown"]

    def __post_init__(self) -> None:
        if not _SAFE_LABEL.fullmatch(self.label):
            raise SkillSourceError(f"unsafe root label: {self.label!r}")
        object.__setattr__(self, "path", Path(self.path))
        if self.kind not in {"hybrid", "markdown"}:
            raise SkillSourceError(f"unsupported skill source root kind: {self.kind!r}")


@dataclass(frozen=True)
class SkillSearchDocument:
    skill_id: str
    revision: str
    token_scores: tuple[tuple[str, int], ...]
    category: str
    contexts: tuple[str, ...]
    tags: tuple[str, ...]
    capabilities: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "revision": self.revision,
            "token_scores": [[token, score] for token, score in self.token_scores],
            "category": self.category,
            "contexts": list(self.contexts),
            "tags": list(self.tags),
            "capabilities": list(self.capabilities),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SkillSearchDocument":
        return cls(
            skill_id=str(value["skill_id"]),
            revision=str(value["revision"]),
            token_scores=tuple((str(item[0]), int(item[1])) for item in value.get("token_scores", ())),
            category=str(value.get("category", "")),
            contexts=tuple(str(item) for item in value.get("contexts", ())),
            tags=tuple(str(item) for item in value.get("tags", ())),
            capabilities=tuple(str(item) for item in value.get("capabilities", ())),
        )


@dataclass(frozen=True)
class SkillSearchIndex:
    documents: tuple[SkillSearchDocument, ...]
    schema: str = "seam-skill-index/v1"

    def __post_init__(self) -> None:
        if self.schema != "seam-skill-index/v1":
            raise SkillSourceError(f"unsupported search index schema: {self.schema}")
        ids = [document.skill_id for document in self.documents]
        if ids != sorted(ids) or len(ids) != len(set(ids)):
            raise SkillSourceError("search index documents must have unique sorted identities")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "documents": [document.to_dict() for document in self.documents],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SkillSearchIndex":
        if value.get("schema") != "seam-skill-index/v1":
            raise SkillSourceError(f"unsupported search index schema: {value.get('schema')!r}")
        return cls(
            documents=tuple(
                SkillSearchDocument.from_dict(item) for item in value.get("documents", ())
            )
        )

    @classmethod
    def build(cls, packages: tuple[SkillPackage, ...]) -> "SkillSearchIndex":
        return cls(tuple(_search_document(package) for package in packages))

    def search(
        self,
        query: str,
        *,
        limit: int,
        category: str | None,
        context: str | None,
        tag: str | None,
        capability: str | None,
    ) -> tuple[SkillSearchResult, ...]:
        terms = tuple(dict.fromkeys(_tokens(query)))
        ranked: list[SkillSearchResult] = []
        for document in self.documents:
            if category and document.category != category:
                continue
            if context and context not in document.contexts:
                continue
            if tag and tag not in document.tags:
                continue
            if capability and capability not in document.capabilities:
                continue
            scores = dict(document.token_scores)
            matched = tuple(term for term in terms if term in scores)
            score = sum(scores[term] for term in matched)
            if score or not terms:
                ranked.append(
                    SkillSearchResult(document.skill_id, document.revision, score, matched)
                )
        ranked.sort(key=lambda result: (-result.score, result.skill_id, result.revision))
        return tuple(ranked[:limit])


@dataclass(frozen=True)
class SkillSearchProjection:
    snapshot_fingerprint: str
    search_index: SkillSearchIndex
    schema: str = SEARCH_PROJECTION_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "snapshot_fingerprint": self.snapshot_fingerprint,
            "search_index": self.search_index.to_dict(),
        }

    def write(self, snapshot_path: str | Path) -> Path:
        path = search_projection_path(snapshot_path)
        path.write_bytes(
            (
                json.dumps(
                    self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
                )
                + "\n"
            ).encode("utf-8")
        )
        return path

    @classmethod
    def read(cls, snapshot_path: str | Path) -> "SkillSearchProjection":
        path = search_projection_path(snapshot_path)
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, Mapping) or value.get("schema") != SEARCH_PROJECTION_SCHEMA:
            raise SkillSourceError(f"unsupported search projection schema in {path}")
        raw_index = value.get("search_index")
        if not isinstance(raw_index, Mapping):
            raise SkillSourceError(f"missing search index in {path}")
        projection = cls(
            snapshot_fingerprint=str(value["snapshot_fingerprint"]),
            search_index=SkillSearchIndex.from_dict(raw_index),
        )
        current_fingerprint = _snapshot_file_fingerprint(snapshot_path)
        if projection.snapshot_fingerprint != current_fingerprint:
            raise SkillSourceError(
                "search projection snapshot fingerprint mismatch: "
                f"projection {projection.snapshot_fingerprint}, snapshot {current_fingerprint}"
            )
        return projection


def search_projection_path(snapshot_path: str | Path) -> Path:
    path = Path(snapshot_path)
    return path.with_name(path.name + ".index.json")


def _snapshot_file_fingerprint(snapshot_path: str | Path) -> str:
    """Hash canonical snapshot bytes without loading or parsing package bodies."""

    digest = hashlib.sha256()
    tail = b""
    with Path(snapshot_path).open("rb") as handle:
        while chunk := handle.read(64 * 1024):
            buffered = tail + chunk
            if len(buffered) > 2:
                digest.update(buffered[:-2])
            tail = buffered[-2:]
    if tail.endswith(b"\r\n"):
        tail = tail[:-2]
    elif tail.endswith(b"\n"):
        tail = tail[:-1]
    digest.update(tail)
    return digest.hexdigest()


@dataclass(frozen=True)
class RegistrySnapshot:
    packages: tuple[SkillPackage, ...]
    search_index: SkillSearchIndex | None = None
    schema: str = SNAPSHOT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != SNAPSHOT_SCHEMA:
            raise SkillSourceError(f"unsupported snapshot schema: {self.schema}")
        ids = [package.skill_id for package in self.packages]
        if ids != sorted(ids):
            raise SkillSourceError("snapshot packages must be sorted by skill_id")
        if len(ids) != len(set(ids)):
            raise SkillSourceError("snapshot contains duplicate skill identities")
        if self.search_index is None:
            object.__setattr__(self, "search_index", SkillSearchIndex.build(self.packages))
        assert self.search_index is not None
        indexed = [(document.skill_id, document.revision) for document in self.search_index.documents]
        expected = [(package.skill_id, package.revision) for package in self.packages]
        if indexed != expected:
            raise SkillSourceError("search index identities or revisions do not match packages")

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    def package(self, skill_id: str) -> SkillPackage:
        for package in self.packages:
            if package.skill_id == skill_id:
                return package
        raise KeyError(skill_id)

    def to_dict(self) -> dict[str, Any]:
        assert self.search_index is not None
        return {
            "schema": self.schema,
            "packages": [package.to_dict() for package in self.packages],
            "search_index": self.search_index.to_dict(),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def write(self, path: str | Path) -> None:
        Path(path).write_bytes((self.to_json() + "\n").encode("utf-8"))
        assert self.search_index is not None
        SkillSearchProjection(self.fingerprint, self.search_index).write(path)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RegistrySnapshot":
        if value.get("schema") != SNAPSHOT_SCHEMA:
            raise SkillSourceError(f"unsupported snapshot schema: {value.get('schema')!r}")
        raw_packages = value.get("packages")
        if not isinstance(raw_packages, list):
            raise SkillSourceError("snapshot packages must be a list")
        raw_index = value.get("search_index")
        index = SkillSearchIndex.from_dict(raw_index) if isinstance(raw_index, Mapping) else None
        return cls(
            packages=tuple(SkillPackage.from_dict(item) for item in raw_packages),
            search_index=index,
        )

    @classmethod
    def from_json(cls, payload: str) -> "RegistrySnapshot":
        value = json.loads(payload)
        if not isinstance(value, Mapping):
            raise SkillSourceError("snapshot must be a JSON object")
        return cls.from_dict(value)

    @classmethod
    def read(cls, path: str | Path) -> "RegistrySnapshot":
        return cls.from_json(Path(path).read_text(encoding="utf-8"))

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        category: str | None = None,
        context: str | None = None,
        tag: str | None = None,
        capability: str | None = None,
    ) -> tuple[SkillSearchResult, ...]:
        if limit < 1:
            raise ValueError("limit must be positive")
        assert self.search_index is not None
        return self.search_index.search(
            query,
            limit=limit,
            category=category,
            context=context,
            tag=tag,
            capability=capability,
        )


def build_registry(
    roots: Mapping[str, str | Path] | Iterable[SkillSourceRoot],
    *,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
) -> RegistrySnapshot:
    if max_file_bytes < 1:
        raise ValueError("max_file_bytes must be positive")
    packages: list[SkillPackage] = []
    identities: dict[str, Path] = {}
    source_roots = _normalize_roots(roots)
    for source_root in source_roots:
        label = source_root.label
        root = source_root.path
        if root.is_symlink() or root.absolute() != root.resolve() or not root.is_dir():
            raise SkillSourceError(f"unsafe or missing root: {root}")
        resolved_root = root.resolve()
        markdown_candidates = set(root.rglob("SKILL.md"))
        if source_root.kind == "markdown":
            candidates = sorted(markdown_candidates, key=lambda path: path.as_posix())
        else:
            candidates = sorted(
                {*root.glob("*.yaml"), *root.glob("*.yml"), *markdown_candidates},
                key=lambda path: path.as_posix(),
            )
        for path in candidates:
            package = _load_source(path, resolved_root, label, max_file_bytes)
            if package.skill_id in identities:
                raise SkillSourceError(
                    f"duplicate skill identity {package.skill_id!r}: "
                    f"{identities[package.skill_id]} and {path}"
                )
            identities[package.skill_id] = path
            packages.append(package)
    return RegistrySnapshot(packages=tuple(sorted(packages, key=lambda package: package.skill_id)))


def _normalize_roots(
    roots: Mapping[str, str | Path] | Iterable[SkillSourceRoot],
) -> tuple[SkillSourceRoot, ...]:
    if isinstance(roots, Mapping):
        normalized = tuple(
            SkillSourceRoot(label, Path(path), kind="hybrid")
            for label, path in roots.items()
        )
    else:
        normalized = tuple(roots)
        if any(not isinstance(root, SkillSourceRoot) for root in normalized):
            raise TypeError("roots must be a mapping or an iterable of SkillSourceRoot values")
    labels = [root.label for root in normalized]
    if len(labels) != len(set(labels)):
        raise SkillSourceError("skill source root labels must be unique")
    return tuple(sorted(normalized, key=lambda root: (root.label, root.path.as_posix(), root.kind)))


def _load_source(path: Path, root: Path, namespace: str, max_file_bytes: int) -> SkillPackage:
    try:
        resolved = path.resolve(strict=True)
        relative = resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise SkillSourceError(f"unsafe source path: {path}") from exc
    relative_lexical = path.absolute().relative_to(root)
    lexical_cursor = root
    has_symlink_component = False
    for component in relative_lexical.parts:
        lexical_cursor = lexical_cursor / component
        if lexical_cursor.is_symlink():
            has_symlink_component = True
            break
    if has_symlink_component or not resolved.is_file():
        raise SkillSourceError(f"unsafe source path: {path}")
    size = resolved.stat().st_size
    if size > max_file_bytes:
        raise SkillSourceError(f"source {path} exceeds {max_file_bytes} bytes")
    raw = resolved.read_bytes()
    if len(raw) > max_file_bytes:
        raise SkillSourceError(f"source {path} exceeds {max_file_bytes} bytes")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SkillSourceError(f"source is not UTF-8: {path}") from exc
    if path.name == "SKILL.md":
        data, parser_policy, parser_version = _markdown_metadata(text, path)
        source_kind = "skill-markdown"
    else:
        loaded = yaml.safe_load(text)
        if not isinstance(loaded, Mapping):
            raise SkillSourceError(f"YAML skill must be a mapping: {path}")
        data = loaded
        parser_policy, parser_version = "yaml-safe", "1"
        source_kind = "skill-yaml"
    name = _required_text(data, "name", path)
    if not _SAFE_NAME.fullmatch(name):
        raise SkillSourceError(f"unsafe skill name {name!r} in {path}")
    digest = hashlib.sha256(raw).hexdigest()
    declared = _declared_metadata(
        data,
        path,
        require_description=source_kind == "skill-yaml",
    )
    heading = next((line[2:].strip() for line in text.splitlines() if line.startswith("# ")), "")
    inferred_title = "" if declared.title else (heading or name)
    inferred_description = (
        "" if declared.description else (declared.summary or heading or name.replace("-", " "))
    )
    inferred_summary = (
        "" if declared.summary else (declared.description or inferred_description)
    )
    return SkillPackage(
        namespace=namespace,
        name=name,
        revision=digest,
        source_sha256=digest,
        instructions=text,
        declared=declared,
        derived=DerivedSkillMetadata(
            namespace,
            relative.as_posix(),
            source_kind,
            parser_policy,
            parser_version,
            inferred_title,
            inferred_description,
            inferred_summary,
        ),
    )


def _markdown_metadata(text: str, path: Path) -> tuple[Mapping[str, Any], str, str]:
    metadata_view = text.replace("\r\n", "\n").replace("\r", "\n")
    if metadata_view.startswith("---\n"):
        end = metadata_view.find("\n---", 4)
        if end < 0:
            raise SkillSourceError(f"unterminated YAML front matter: {path}")
        frontmatter = metadata_view[4:end]
        try:
            loaded = yaml.safe_load(frontmatter)
        except yaml.YAMLError:
            return _minimal_frontmatter(frontmatter, path), "minimal-scalar-fallback", "1"
        if not isinstance(loaded, Mapping):
            raise SkillSourceError(f"SKILL.md front matter must be a mapping: {path}")
        return loaded, "yaml-safe", "1"
    name = path.parent.name
    return ({"name": name}, "inferred-markdown", "1")


def _minimal_frontmatter(frontmatter: str, path: Path) -> Mapping[str, str]:
    values: dict[str, str] = {}
    for line in frontmatter.splitlines():
        match = _FRONTMATTER_SCALAR.fullmatch(line)
        if not match:
            continue
        key, raw_value = match.groups()
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if value:
            values[key] = value
    values.setdefault("name", path.parent.name)
    return values


def _declared_metadata(
    data: Mapping[str, Any], path: Path, *, require_description: bool
) -> DeclaredSkillMetadata:
    title = _optional_text(data, "title", path)
    description = (
        _required_text(data, "description", path)
        if require_description
        else _optional_text(data, "description", path)
    )
    summary = _optional_text(data, "summary", path) or _optional_text(
        data, "short_description", path
    )
    category = str(data.get("category") or "").strip()
    relations: list[SkillRelation] = []
    for kind in sorted(RELATION_KINDS):
        for target in _string_tuple(data.get(kind), kind, path):
            relations.append(SkillRelation(kind, target))
    return DeclaredSkillMetadata(
        title=title,
        description=description,
        summary=summary,
        category=category,
        contexts=_string_tuple(data.get("contexts"), "contexts", path),
        tags=_string_tuple(data.get("tags"), "tags", path),
        capabilities=_string_tuple(data.get("capabilities"), "capabilities", path),
        tools=_string_tuple(data.get("tools"), "tools", path),
        permissions=_string_tuple(data.get("permissions"), "permissions", path),
        relations=tuple(relations),
    )


def _required_text(data: Mapping[str, Any], key: str, path: Path) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SkillSourceError(f"{key} must be a non-empty string in {path}")
    return value.strip()


def _optional_text(data: Mapping[str, Any], key: str, path: Path) -> str:
    value = data.get(key)
    if value is None:
        return ""
    if not isinstance(value, str) or not value.strip():
        raise SkillSourceError(f"{key} must be a non-empty string in {path}")
    return value.strip()


def _string_tuple(value: Any, key: str, path: Path) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise SkillSourceError(f"{key} must be a string or list of non-empty strings in {path}")
    return tuple(dict.fromkeys(item.strip() for item in value))


def _tokens(value: str) -> list[str]:
    tokens: list[str] = []
    for token in _TOKEN.findall(value.lower()):
        tokens.append(token)
        if "-" in token or "_" in token:
            tokens.extend(part for part in re.split(r"[-_]", token) if part)
    return tokens


def _search_document(package: SkillPackage) -> SkillSearchDocument:
    declared = package.declared
    weighted = (
        (12, package.name),
        (10, package.title),
        (8, package.summary),
        (6, package.description),
        (5, declared.category),
        (5, " ".join(declared.contexts)),
        (4, " ".join(declared.tags)),
        (4, " ".join(declared.capabilities)),
    )
    scores: dict[str, int] = {}
    for weight, text in weighted:
        for token in set(_tokens(text)):
            scores[token] = scores.get(token, 0) + weight
    return SkillSearchDocument(
        skill_id=package.skill_id,
        revision=package.revision,
        token_scores=tuple(sorted(scores.items())),
        category=declared.category,
        contexts=declared.contexts,
        tags=declared.tags,
        capabilities=declared.capabilities,
    )
