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

import json
import os
import re
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


def _contiguous_source_span(value: object, source: str, *, field: str) -> GroundedSpan | None:
    """Locate ``value`` as one normalized contiguous span in ``source``.

    This deliberately does not use token-set inclusion. For example,
    ``"tool release"`` cannot ground against ``"release tool"``, and
    ``"release tool"`` cannot jump across ``"release safety tool"``.
    """

    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate:
        return None
    parts = re.split(r"\s+", candidate)
    body = r"\s+".join(re.escape(part) for part in parts)
    match = re.search(_BOUNDARY.format(body=body), source, flags=re.IGNORECASE)
    if match is None:
        return None
    return GroundedSpan(
        field=field,
        text=source[match.start():match.end()],
        start=match.start(),
        end=match.end(),
    )


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
    "normalize a word. The relation is the verb or preposition exactly as written. "
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
            "object": "an evening pottery class",
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
                "required": ["subject", "relation", "object"],
            },
        },
    },
    "required": ["entities", "claims"],
}


@dataclass
class OllamaExtractor:
    """Calls a local Ollama model for grounded (S, R, O) triples + entities.

    Network-free of any cloud: talks to a local Ollama HTTP endpoint only. Uses
    ``urllib`` (no new dependency). Any failure (model down, bad JSON, timeout)
    returns an empty ``Extraction`` so the caller falls back to the floor."""

    model: str = field(default_factory=lambda: os.environ.get("SEAM_OLLAMA_MODEL", "qwen2.5:3b"))
    host: str = field(default_factory=lambda: os.environ.get("SEAM_OLLAMA_HOST", "http://127.0.0.1:11434"))
    timeout: float = 120.0
    temperature: float = 0.0
    seed: int = 7
    num_ctx: int = 2048

    def _generate(self, text: str) -> dict:
        prompt = f"{_SYSTEM}\n\nEXAMPLE\nSentence: {_EXAMPLE_IN}\nJSON: {_EXAMPLE_OUT}\n\nNOW\nSentence: {text}\nJSON:"
        body = json.dumps(
            {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "format": _SCHEMA,
                "options": {"temperature": self.temperature, "seed": self.seed, "num_ctx": self.num_ctx},
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.host.rstrip('/')}/api/generate", data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310 (local loopback only)
            payload = json.loads(response.read())
        return json.loads(payload["response"])

    def extract(self, text: str) -> Extraction:
        try:
            raw = self._generate(text)
        except Exception:
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
        required = {
            field: _contiguous_source_span(item.get(raw_key), text, field=field)
            for field, raw_key in (
                ("subject", "subject"),
                ("relation", "relation"),
                ("object", "object"),
            )
        }
        if all(required.values()):
            subject_span = required["subject"]
            relation_span = required["relation"]
            object_span = required["object"]
            assert subject_span is not None
            assert relation_span is not None
            assert object_span is not None
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
                basis = str(item.get("epistemic_basis", "explicit")).strip().lower()
                if basis not in {"explicit", "inferred", "hypothetical"}:
                    basis = "explicit"
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
