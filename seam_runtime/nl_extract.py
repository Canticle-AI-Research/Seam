"""Opt-in LLM rich extractor for the MIRL compiler (SEAM spec §3.2, Stage 4).

The deterministic floor in ``nl.py`` is faithful but shallow: it grounds a
subject and preserves the verbatim proposition, but assigns no structured
relation and misses lowercase common-noun entities (``billing service``). This
module adds an OPT-IN extractor that asks a LOCAL model (Ollama, free) for real
(subject, relation, object) triples and entities, then passes them through a
GROUNDING GATE so the spec's "never fabricate" guarantee (§3.2 + §8) holds even
when the model hallucinates: a triple or entity is kept only when every span it
uses is drawn verbatim from the input. Anything ungrounded is dropped, and a
proposition with no surviving grounded claim falls back to the floor.

This is opt-in by construction. CI cannot reach a local model, so the
deterministic floor stays the default and the only CI-measured behavior;
determinism (§29.1) is the floor's guarantee, not the LLM path's (an LLM is at
best best-effort deterministic at temperature 0). Enable via
``compile_nl(text, extractor=OllamaExtractor(...))`` or, in production, the
``SEAM_NL_EXTRACTOR=ollama`` environment switch (see ``extractor_from_env``).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

_BOUNDARY = r"(?<!\w){body}(?!\w)"


@dataclass(frozen=True)
class GroundedSpan:
    """One normalized-contiguous field copied from the original source.

    ``start`` is inclusive and ``end`` is exclusive, so ``source[start:end]``
    is exactly ``text``. Matching is case-insensitive and treats runs of
    whitespace as equivalent, but it never reorders tokens or skips source
    words. The stored text is always the original source slice.
    """

    field: str
    text: str
    start: int
    end: int


def _contiguous_source_spans(
    value: object,
    source: str,
    *,
    field: str,
    max_matches: int = 128,
) -> tuple[GroundedSpan, ...]:
    """Locate bounded, normalized-contiguous occurrences of ``value``."""

    if not isinstance(value, str):
        return ()
    candidate = value.strip()
    if not candidate:
        return ()
    parts = re.split(r"\s+", candidate)
    body = r"\s+".join(re.escape(part) for part in parts)
    matches: list[GroundedSpan] = []
    for match in re.finditer(
        _BOUNDARY.format(body=body),
        source,
        flags=re.IGNORECASE,
    ):
        matches.append(
            GroundedSpan(
                field=field,
                text=source[match.start():match.end()],
                start=match.start(),
                end=match.end(),
            )
        )
        if len(matches) >= max_matches:
            break
    return tuple(matches)


def _contiguous_source_span(
    value: object,
    source: str,
    *,
    field: str,
) -> GroundedSpan | None:
    """Locate ``value`` as one normalized contiguous span in ``source``.

    This deliberately does not use token-set inclusion. For example,
    ``"tool release"`` cannot ground against ``"release tool"``, and
    ``"release tool"`` cannot jump across ``"release safety tool"``.
    """

    matches = _contiguous_source_spans(value, source, field=field)
    return matches[0] if matches else None


_CLAUSE_BOUNDARY = re.compile(
    r"(?:[\r\n\]:,.!?;]+|\b(?:"
    r"and|but|or|yet|so|while|whereas|because|although|though|if|unless|"
    r"when|whenever|after|before|since|once|until|where|wherever|who|"
    r"whom|whose|which|that"
    r")\b)",
    flags=re.IGNORECASE,
)

_PAIRED_QUOTES = {
    "“": "”",
    "‘": "’",
    "«": "»",
    "‹": "›",
    "「": "」",
    "『": "』",
}
_QUOTE_CLOSERS = frozenset(_PAIRED_QUOTES.values())
_TERMINAL_PUNCTUATION = frozenset(".?!")
_UNSAFE_SUBJECT_PREFIX = re.compile(
    r"^\s*(?:hypothetical(?:ly)?|rumou?r|allegedly|reportedly|"
    r"supposedly|perhaps|maybe|according\s+to|in\s+a\s+dream)\b",
    flags=re.IGNORECASE,
)


def _word_internal_delimiter(text: str, start: int, end: int) -> bool:
    before = text[start - 1] if start > 0 else ""
    after = text[end] if end < len(text) else ""
    return before.isalnum() and after.isalnum()


def _inside_direct_speech_quotes(text: str, offset: int) -> bool:
    """Recognize common paired quotes plus standalone symmetric delimiters."""

    paired_depths = {closer: 0 for closer in _QUOTE_CLOSERS}
    symmetric_open = {'"': False, "'": False, "`": False}
    index = 0
    bound = min(max(offset, 0), len(text))
    while index < bound:
        char = text[index]
        if char in _PAIRED_QUOTES:
            paired_depths[_PAIRED_QUOTES[char]] += 1
        elif char in _QUOTE_CLOSERS:
            if (
                char != "’"
                or not _word_internal_delimiter(text, index, index + 1)
            ) and paired_depths[char] > 0:
                paired_depths[char] -= 1
        elif char == '"':
            symmetric_open[char] = not symmetric_open[char]
        elif char in {"'", "`"}:
            run_end = index + 1
            if char == "`":
                while run_end < bound and text[run_end] == "`":
                    run_end += 1
            if not _word_internal_delimiter(text, index, run_end):
                symmetric_open[char] = not symmetric_open[char]
            index = run_end - 1
        index += 1
    return any(paired_depths.values()) or any(symmetric_open.values())


def _has_quote_delimiter(text: str, start: int, end: int) -> bool:
    index = max(0, start)
    bound = min(len(text), end)
    while index < bound:
        char = text[index]
        if char == "’" and _word_internal_delimiter(
            text,
            index,
            index + 1,
        ):
            index += 1
            continue
        if char in _PAIRED_QUOTES or char in _QUOTE_CLOSERS or char == '"':
            return True
        if char in {"'", "`"}:
            run_end = index + 1
            if char == "`":
                while run_end < bound and text[run_end] == "`":
                    run_end += 1
            if not _word_internal_delimiter(text, index, run_end):
                return True
            index = run_end - 1
        index += 1
    return False


def _whitespace_only(value: str) -> bool:
    return not value or value.isspace()


def _terminal_suffix_only(value: str) -> bool:
    return all(
        char.isspace() or char in _TERMINAL_PUNCTUATION
        for char in value
    )


def _required_field_is_safe(span: GroundedSpan) -> bool:
    """Reject a required field that swallows a clause or attribution marker."""

    if (
        _CLAUSE_BOUNDARY.search(span.text)
        or _has_quote_delimiter(span.text, 0, len(span.text))
    ):
        return False
    if (
        span.field == "subject"
        and _UNSAFE_SUBJECT_PREFIX.search(span.text)
    ):
        return False
    return True


def grounded_sro_is_coherent(
    source: str,
    subject: GroundedSpan,
    relation: GroundedSpan,
    obj: GroundedSpan,
    *,
    evidence_start: int = 0,
    evidence_end: int | None = None,
    require_complete_clause: bool = False,
    allowed_prefix_end: int | None = None,
) -> bool:
    """Require ordered gap-free S-R-O, optionally covering the full clause."""

    resolved_end = len(source) if evidence_end is None else evidence_end
    if (
        evidence_start < 0
        or resolved_end > len(source)
        or evidence_start > subject.start
        or obj.end > resolved_end
    ):
        return False
    if allowed_prefix_end is not None and (
        allowed_prefix_end < evidence_start
        or allowed_prefix_end > subject.start
    ):
        return False
    if (
        "?" in source[evidence_start:resolved_end]
        or _inside_direct_speech_quotes(source, subject.start)
        or not all(
            _required_field_is_safe(span)
            for span in (subject, relation, obj)
        )
    ):
        return False
    clause_start = (
        allowed_prefix_end
        if allowed_prefix_end is not None
        else evidence_start
    )
    if not _whitespace_only(source[clause_start:subject.start]):
        return False
    if (
        require_complete_clause
        and not _terminal_suffix_only(source[obj.end:resolved_end])
    ):
        return False
    subject_relation_gap = source[subject.end:relation.start]
    relation_object_gap = source[relation.end:obj.start]
    return (
        subject.end <= relation.start
        and relation.end <= obj.start
        and _CLAUSE_BOUNDARY.search(source[subject.end:obj.start]) is None
        and _whitespace_only(subject_relation_gap)
        and _whitespace_only(relation_object_gap)
        and not _has_quote_delimiter(source, subject.end, obj.start)
    )


def clause_window(source: str, subject_start: int, obj_end: int) -> tuple[int, int]:
    """Return the [start, end) of the clause enclosing an S-R-O span.

    The window runs from the end of the clause boundary immediately before the
    subject to the start of the first clause boundary at/after the object (or the
    string ends). ``grounded-clm/2`` validates a rebased claim against this window
    instead of the whole proposition, so a clean self-claim inside a compound
    sentence ("... and I love surfing") passes the same complete-clause gate that
    ``grounded-clm/1`` only applied to single-clause propositions. Boundaries
    themselves (conjunctions/punctuation) are never included, so the strict
    verbatim/ordered/single-clause guarantees are unchanged.
    """

    start = 0
    for match in _CLAUSE_BOUNDARY.finditer(source):
        if match.end() <= subject_start:
            start = match.end()
        else:
            break
    end = len(source)
    for match in _CLAUSE_BOUNDARY.finditer(source):
        if match.start() >= obj_end:
            end = match.start()
            break
    return start, end


def _coherent_required_spans(
    item: dict,
    source: str,
) -> tuple[GroundedSpan, GroundedSpan, GroundedSpan] | None:
    """Choose one ordered S-R-O occurrence that stays inside one clause."""

    subjects = _contiguous_source_spans(
        item.get("subject"),
        source,
        field="subject",
    )
    relations = _contiguous_source_spans(
        item.get("relation"),
        source,
        field="relation",
    )
    objects = _contiguous_source_spans(
        item.get("object"),
        source,
        field="object",
    )
    if not subjects or not relations or not objects:
        return None

    best: tuple[GroundedSpan, GroundedSpan, GroundedSpan] | None = None
    best_width: int | None = None
    for subject in subjects:
        for relation in relations:
            if relation.start < subject.end:
                continue
            for obj in objects:
                if obj.start < relation.end:
                    continue
                if not grounded_sro_is_coherent(
                    source,
                    subject,
                    relation,
                    obj,
                ):
                    continue
                width = obj.end - subject.start
                if best_width is None or width < best_width:
                    best = (subject, relation, obj)
                    best_width = width
                break
    return best


@dataclass(frozen=True)
class ExtractedEntity:
    name: str
    entity_type: str = "entity"


@dataclass(frozen=True)
class ExtractedClaim:
    subject: str
    relation: str
    obj: str
    when: str | None = None
    where: str | None = None
    why: str | None = None
    how: str | None = None
    then: str | None = None
    epistemic_basis: str = "explicit"
    source_spans: tuple[GroundedSpan, ...] = ()

    def facets(self) -> dict[str, str]:
        """Return the grounded 5W1H+Then slots carried by this extraction.

        ``who``/``what`` are the triple's subject/object. Optional slots are
        included only after :func:`ground_extraction` has proved that their
        surface text occurs in the source proposition.
        """

        values = {
            "who": self.subject,
            "what": self.obj,
            "when": self.when,
            "where": self.where,
            "why": self.why,
            "how": self.how,
            "then": self.then,
        }
        return {key: value for key, value in values.items() if value}

    def span_for(self, field: str) -> GroundedSpan | None:
        """Return the source anchor for a grounded claim field, if available."""

        source_field = {"who": "subject", "what": "object"}.get(field, field)
        return next(
            (span for span in self.source_spans if span.field == source_field),
            None,
        )


@dataclass(frozen=True)
class Extraction:
    """Grounded entities + claims for one proposition."""

    entities: tuple[ExtractedEntity, ...] = ()
    claims: tuple[ExtractedClaim, ...] = ()

    def is_empty(self) -> bool:
        return not self.entities and not self.claims


@runtime_checkable
class Extractor(Protocol):
    """A per-proposition rich extractor. Returns a GROUNDED ``Extraction`` (all
    spans verbatim from ``text``); an empty result means "fall back to the floor"."""

    def extract(self, text: str) -> Extraction: ...


_SYSTEM = (
    "You extract structured facts from ONE sentence. Hard rules: every entity "
    "name, claim subject, claim relation and claim object MUST be a contiguous "
    "span of words copied VERBATIM from the sentence. Never invent, rephrase, or "
    "normalize a word. Subject, relation, and object must be ordered and gap-free: "
    "do not omit any source word between them. Put auxiliaries, negation, modality, "
    "and intervening adverbs into the relation; put determiners and modifiers into "
    "the object. The relation is the predicate phrase exactly as written. "
    "For each claim, optionally identify when, where, why, how, and then; each "
    "optional value must also be copied verbatim. Mark epistemic_basis as "
    "explicit, inferred, or hypothetical. Omit a slot when the sentence does "
    "not state it. "
    "Output JSON only."
)
_EXAMPLE_IN = "Akira teaches an evening pottery class at the community center."
_EXAMPLE_OUT = json.dumps(
    {
        "entities": [{"name": "Akira", "type": "person"}, {"name": "community center", "type": "place"}],
        "claims": [{
            "subject": "Akira",
            "relation": "teaches",
            "object": "an evening pottery class at the community center",
            "where": "community center",
            "how": "evening pottery class",
            "epistemic_basis": "explicit",
        }],
    }
)
_SCHEMA = {
    "type": "object",
    "properties": {
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "type": {"type": "string"}},
                "required": ["name", "type"],
            },
        },
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string"},
                    "relation": {"type": "string"},
                    "object": {"type": "string"},
                    "when": {"type": "string"},
                    "where": {"type": "string"},
                    "why": {"type": "string"},
                    "how": {"type": "string"},
                    "then": {"type": "string"},
                    "epistemic_basis": {
                        "type": "string",
                        "enum": ["explicit", "inferred", "hypothetical"],
                    },
                },
                "required": [
                    "subject",
                    "relation",
                    "object",
                    "epistemic_basis",
                ],
            },
        },
    },
    "required": ["entities", "claims"],
}
_PROMPT_VERSION = "grounded-sro/3"
_SCHEMA_VERSION = "grounded-sro-schema/2"
_GROUNDING_VERSION = "gap-free-coherent-sro/5"


def _prompt_fingerprint() -> str:
    payload = {
        "example_input": _EXAMPLE_IN,
        "example_output": json.loads(_EXAMPLE_OUT),
        "prompt_version": _PROMPT_VERSION,
        "schema": _SCHEMA,
        "schema_version": _SCHEMA_VERSION,
        "system": _SYSTEM,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


@dataclass
class OllamaExtractor:
    """Calls a local Ollama model for grounded (S, R, O) triples + entities.

    Network-free of any cloud: talks to a local Ollama HTTP endpoint only. Uses
    ``urllib`` (no new dependency). Compatibility mode returns an empty
    ``Extraction`` on generation failure; strict mode raises so an enabled
    derived-facts run cannot silently become a no-op."""

    model: str = field(default_factory=lambda: os.environ.get("SEAM_OLLAMA_MODEL", "qwen2.5:3b"))
    host: str = field(default_factory=lambda: os.environ.get("SEAM_OLLAMA_HOST", "http://127.0.0.1:11434"))
    timeout: float = field(
        default_factory=lambda: float(
            os.environ.get("SEAM_OLLAMA_TIMEOUT_S", "300")
        )
    )
    temperature: float = 0.0
    seed: int = 7
    num_ctx: int = 2048
    num_predict: int = field(
        default_factory=lambda: int(
            os.environ.get("SEAM_OLLAMA_NUM_PREDICT", "256")
        )
    )
    strict: bool = False
    model_digest: str | None = field(
        default_factory=lambda: os.environ.get("SEAM_OLLAMA_MODEL_DIGEST")
    )
    _resolved_model_digest: str | None = field(
        default=None,
        init=False,
        repr=False,
    )

    def config_metadata(self) -> dict[str, object]:
        """Return the immutable extraction configuration recorded on rich facts."""

        return {
            "type": "ollama",
            "model": self.model,
            "model_digest": self._resolve_model_digest(),
            "host": self._validated_host(require_loopback=self.strict),
            "timeout": self.timeout,
            "strict": self.strict,
            "temperature": self.temperature,
            "seed": self.seed,
            "num_ctx": self.num_ctx,
            "num_predict": self.num_predict,
            "prompt_version": _PROMPT_VERSION,
            "prompt_fingerprint": _prompt_fingerprint(),
            "schema_version": _SCHEMA_VERSION,
            "grounding_version": _GROUNDING_VERSION,
        }

    def validate_for_derived_facts(self) -> None:
        """Require strict, credential-free loopback extraction for v1 facts."""

        if not self.strict:
            raise ValueError(
                "grounded-clm/1 requires OllamaExtractor(strict=True)"
            )
        self._validated_host(require_loopback=True)
        self._resolve_model_digest(refresh=True)

    def _validated_host(self, *, require_loopback: bool) -> str:
        parsed = urllib.parse.urlsplit(self.host)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError(
                "Ollama host must be a credential-free HTTP(S) origin"
            )
        hostname = parsed.hostname.lower()
        if require_loopback and hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError(
                "grounded-clm/1 requires a loopback Ollama host"
            )
        display_host = f"[{hostname}]" if ":" in hostname else hostname
        port = f":{parsed.port}" if parsed.port is not None else ""
        return f"{parsed.scheme.lower()}://{display_host}{port}"

    def _installed_model_digest(self) -> str:
        """Read the currently installed content digest for ``self.model``."""

        host = self._validated_host(require_loopback=self.strict)
        request = urllib.request.Request(f"{host}/api/tags")
        try:
            with urllib.request.urlopen(
                request,
                timeout=min(max(self.timeout, 0.1), 30.0),
            ) as response:  # noqa: S310 (same configured endpoint as generation)
                payload = json.loads(response.read())
        except Exception as exc:
            raise RuntimeError(
                f"could not resolve Ollama model digest for {self.model!r}"
            ) from exc
        models = payload.get("models") if isinstance(payload, dict) else None
        if not isinstance(models, list):
            models = []
        for item in models:
            if not isinstance(item, dict):
                continue
            names = {str(item.get(key) or "") for key in ("name", "model")}
            if self.model not in names:
                continue
            digest = str(item.get("digest") or "").strip()
            if digest:
                return digest
        raise RuntimeError(
            f"Ollama model {self.model!r} is not installed or has no digest"
        )

    def _resolve_model_digest(self, *, refresh: bool = False) -> str:
        """Freeze the installed digest and reject tag drift or false attestations."""

        if self._resolved_model_digest and not refresh:
            return self._resolved_model_digest
        installed = self._installed_model_digest()
        expected = str(self.model_digest or "").strip()
        if expected and expected != installed:
            raise RuntimeError(
                f"Ollama model digest mismatch for {self.model!r}: "
                "the configured digest does not match the installed model"
            )
        if (
            self._resolved_model_digest
            and self._resolved_model_digest != installed
        ):
            raise RuntimeError(
                f"Ollama model digest changed during the run for {self.model!r}"
            )
        self._resolved_model_digest = installed
        return installed

    def _generate(self, text: str) -> dict:
        prompt = f"{_SYSTEM}\n\nEXAMPLE\nSentence: {_EXAMPLE_IN}\nJSON: {_EXAMPLE_OUT}\n\nNOW\nSentence: {text}\nJSON:"
        body = json.dumps(
            {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "format": _SCHEMA,
                "options": {
                    "temperature": self.temperature,
                    "seed": self.seed,
                    "num_ctx": self.num_ctx,
                    "num_predict": self.num_predict,
                },
            }
        ).encode("utf-8")
        host = self._validated_host(require_loopback=self.strict)
        request = urllib.request.Request(
            f"{host}/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310 (local loopback only)
            payload = json.loads(response.read())
        return json.loads(payload["response"])

    def extract(self, text: str) -> Extraction:
        try:
            if self.strict:
                # CachedExtractor calls this only on a cache miss. Re-read the
                # installed digest before every model generation so a mutable
                # tag cannot mix model bytes under one cache fingerprint.
                self._resolve_model_digest(refresh=True)
            raw = self._generate(text)
        except Exception as exc:
            if self.strict:
                raise RuntimeError(
                    f"grounded fact extraction failed for model {self.model!r}"
                ) from exc
            return Extraction()
        return ground_extraction(raw, text)


def ground_extraction(raw: dict, text: str) -> Extraction:
    """Filter a model's raw output against ``text`` — the fabrication firewall.

    Every retained entity and claim field must match one normalized-contiguous
    source span. Required claim fields (subject, relation, object) fail closed:
    if any one is reordered, scattered, or fabricated, the entire claim is
    dropped. Optional 5W1H+Then facets fail individually and are omitted. Each
    retained claim carries exact character offsets back to the source.

    Empty/malformed input yields an empty Extraction (-> floor fallback)."""
    if not isinstance(raw, dict):
        return Extraction()

    entities: list[ExtractedEntity] = []
    seen_ent: set[str] = set()
    for item in raw.get("entities", []) or []:
        if not isinstance(item, dict):
            continue
        span = _contiguous_source_span(item.get("name"), text, field="name")
        if span is not None and span.text.lower() not in seen_ent:
            name = span.text
            seen_ent.add(name.lower())
            etype = str(item.get("type", "entity")).strip() or "entity"
            entities.append(ExtractedEntity(name=name, entity_type=etype))

    claims: list[ExtractedClaim] = []
    seen_clm: set[tuple[str, str, str]] = set()
    for item in raw.get("claims", []) or []:
        if not isinstance(item, dict):
            continue
        required = _coherent_required_spans(item, text)
        if required is not None:
            subject_span, relation_span, object_span = required
            subject = subject_span.text
            relation = relation_span.text
            obj = object_span.text
            key = (subject.lower(), relation.lower(), obj.lower())
            if key not in seen_clm:
                seen_clm.add(key)
                optional: dict[str, str | None] = {}
                spans = [subject_span, relation_span, object_span]
                for facet in ("when", "where", "why", "how", "then"):
                    span = _contiguous_source_span(item.get(facet), text, field=facet)
                    optional[facet] = span.text if span is not None else None
                    if span is not None:
                        spans.append(span)
                basis = str(
                    item.get("epistemic_basis", "unknown")
                ).strip().lower()
                if basis not in {"explicit", "inferred", "hypothetical"}:
                    basis = "unknown"
                claims.append(
                    ExtractedClaim(
                        subject=subject,
                        relation=relation,
                        obj=obj,
                        epistemic_basis=basis,
                        source_spans=tuple(spans),
                        **optional,
                    )
                )

    return Extraction(entities=tuple(entities), claims=tuple(claims))


def extractor_from_env() -> Extractor | None:
    """Return an opt-in extractor if ``SEAM_NL_EXTRACTOR`` selects one, else None
    (the deterministic floor). Only ``ollama`` is wired today."""
    choice = os.environ.get("SEAM_NL_EXTRACTOR", "").strip().lower()
    if choice == "ollama":
        return OllamaExtractor()
    return None
