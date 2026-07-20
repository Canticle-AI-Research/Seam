from __future__ import annotations

import hashlib
import os
import re
from collections import Counter

from .derived_fact_context import (
    canonical_turn_prefix_end,
    is_singular_first_person,
    segment_propositions,
)
from .mirl import IRBatch, MIRLRecord, RecordKind, Status

STOPWORDS = {"a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "into", "is", "it", "of", "on", "or", "that", "the", "this", "to", "we", "with", "without"}

# --- Unified deterministic compiler (SEAM spec §3.2 + §8) ---------------------
#
# ONE compilation path for every input — plain memories AND conversation turns.
# It replaces both the former overfit stub (which fabricated a project:SEAM/goal
# skeleton) and the separate `compile_conversation_turn`. The base is the honest
# floor: the input is preserved verbatim in one RAW, split into propositions with
# REAL character offsets, and every proposition gets a SPAN + a GROUNDED content
# claim (subject drawn from that proposition's own text, object = the verbatim
# proposition, so meaning is recoverable). On top of that, high-confidence
# conversational rules (speaker, dates, locations, named entities, action verbs)
# add grounded, span-localized enrichment claims when they fire. Every claim's
# subject is grounded in the text — never a synthetic turn entity — so the output
# satisfies the fidelity contract. Rich S-P-O triples (real predicates/objects)
# remain the job of the opt-in extractor (local Ollama), added behind the same
# contract in a later slice.

# Determiners/possessives stripped from the front of a leading subject phrase.
_LEADING_DETERMINERS = {"the", "a", "an", "my", "our", "your", "his", "her", "its", "their", "this", "that", "these", "those"}
# Capitalized words that are NOT proper nouns even when capitalized (usually
# sentence-initial); excluded from the proper-noun entity pass.
_NON_ENTITY_CAPS = {"The", "A", "An", "My", "Our", "Your", "His", "Her", "Its", "Their", "This", "That", "These", "Those", "I", "It", "We", "They", "He", "She", "You", "If", "And", "But", "Or", "So", "Then"}

# Sentence-ending punctuation. A run of these is a boundary only when followed by
# whitespace or end-of-string (so 4.2 / 9:30 / B12 don't split). Detected by a
# linear scan, NOT a regex (`[.!?]+(?=\s|$)` is polynomial on uncontrolled input).
_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'-]*")
_PROPER_NOUN_RUN = re.compile(r"[A-Z][A-Za-z0-9]*(?:\s+[A-Z][A-Za-z0-9]*)*")

# High-confidence conversational extractors (folded in from the former
# compile_conversation_turn so there is exactly one compilation path).
_SPEAKER_RE = re.compile(r"^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s*:")
_DATE_PATTERNS = [
    re.compile(r"\d{1,2}\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{4}"),
    re.compile(r"\d{1,2}/\d{1,2}/\d{4}"),
    re.compile(r"\d{4}-\d{2}-\d{2}"),
]
_LOCATION_PATTERN = re.compile(
    r"(?:in|at|to)\s+(?:the\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*"
    r"(?:\s+(?:support group|center|office|building|room|hall|park|city|town|street|avenue|lane|road))?)",
    re.IGNORECASE,
)
_CAPITALIZED_ENTITY = re.compile(r"(?:^|[.!?]\s+|\b(?:in|at|to|with|from|by|for|on)\s+)([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)")
_ACTION_PATTERNS = [
    (re.compile(r"(?:I\s+)?(?:went|go|travell?ed)\s+to\s+(.+?)(?:[,.!]|$)", re.IGNORECASE), "went_to"),
    (re.compile(r"(?:I\s+)?(?:saw|visited|attended)\s+(.+?)(?:[,.!]|$)", re.IGNORECASE), "attended"),
    (re.compile(r"(?:I\s+)?(?:met|spoke to|talked to|chatted with)\s+(.+?)(?:[,.!]|$)", re.IGNORECASE), "met"),
    (re.compile(r"(?:I\s+)?(?:learned|discovered|found out)\s+(?:that\s+)?(.+?)(?:[,.!]|$)", re.IGNORECASE), "learned"),
    (re.compile(r"(?:I\s+)?(?:feel|felt|am|was)\s+(.+?)(?:[,.!]|$)", re.IGNORECASE), "felt"),
]
_LOCATION_REJECT = {"the", "a", "an", "i", "me", "my"}
_ENTITY_REJECT = {"the", "a", "an", "i", "me", "my", "this", "that"}


def compile_nl(
    raw_text: str,
    source_ref: str = "local://input",
    ns: str = "local.default",
    scope: str = "thread",
    extractor=None,
    *,
    speaker: str | None = None,
    source_timestamp: str | None = None,
    derived_fact_policy: str | None = None,
    allow_env_extractor: bool = True,
) -> IRBatch:
    """Compile arbitrary natural language (memory or conversation turn) into
    faithful MIRL.

    Guarantees, measured by ``benchmarks/fidelity`` against the spec contract:
    one verbatim RAW; each proposition gets a SPAN with real offsets and a CLAIM
    grounded in a subject taken from the text (NEVER a fabricated project:SEAM or
    synthetic turn entity); high-confidence entities (leading subject phrases +
    capitalized proper nouns) become ENT records. When the text carries
    conversational signal (a ``Name:`` speaker, dates, locations, named entities,
    action verbs), grounded enrichment claims are added, localized to the
    proposition that produced them.

    ``extractor`` (opt-in; ``nl_extract.Extractor``, default the deterministic
    floor) adds REAL (subject, relation, object) triples + entities from a local
    model behind a grounding gate, replacing the regex enrichment when it returns
    grounded claims. The floor's verbatim content claim is always kept, so
    coverage/temporal retention are preserved; the LLM path is best-effort
    deterministic only (the floor is the determinism guarantee). Resolved from
    ``SEAM_NL_EXTRACTOR`` when not passed; CI never sets it, so the floor stays
    the default + only CI-measured behavior."""
    if (
        extractor is None
        and allow_env_extractor
        and os.environ.get("SEAM_NL_EXTRACTOR")
    ):
        from .nl_extract import extractor_from_env

        extractor = extractor_from_env()
    # Legacy regex enrichment is OFF by default (SEAM_NL_REGEX_ENRICH to re-enable):
    # the hand-rolled location/action regexes mislabel ~25% of real prose
    # (location=<allergen>, felt=<shipped>) for ZERO measured LoCoMo recall benefit
    # (the content claim already carries every token), so they are pure liability and
    # superseded by the grounded opt-in extractor. See HISTORY#317.
    regex_enrich = bool(os.environ.get("SEAM_NL_REGEX_ENRICH"))
    source_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()[:12]
    raw_id = f"raw:{source_hash}"
    prov_id = f"prov:compile:{source_hash}"

    records: list[MIRLRecord] = [
        MIRLRecord(id=raw_id, kind=RecordKind.RAW, ns=ns, scope=scope, status=Status.OBSERVED,
                   attrs={"source_ref": source_ref, "content": raw_text, "media_type": "text/plain"}),
        MIRLRecord(id=prov_id, kind=RecordKind.PROV, ns=ns, scope=scope, status=Status.OBSERVED,
                   attrs={"entity": raw_id, "activity": "compile_nl", "agent": "system.nl"}),
    ]

    entity_ids: dict[str, str] = {}

    def entity_id(
        label: str,
        entity_type: str = "entity",
        *,
        promote_type: bool = False,
    ) -> str:
        """Resolve (and lazily create) an ENT for ``label``, deduped by its
        lowercased form. The first call's ``entity_type`` wins (so a speaker
        resolved as ``person`` is not downgraded by a later generic mention)."""
        key = label.lower()
        existing = entity_ids.get(key)
        if existing is not None:
            if promote_type:
                for record in records:
                    if record.id == existing and record.kind == RecordKind.ENT:
                        record.attrs["entity_type"] = entity_type
                        break
            return existing
        slug = re.sub(r"[^a-z0-9]+", "_", key).strip("_") or "entity"
        base = f"ent:{slug}:{source_hash}"
        ent_id = base
        suffix = 2
        used = {record.id for record in records}
        while ent_id in used:
            ent_id = f"{base}:{suffix}"
            suffix += 1
        entity_ids[key] = ent_id
        records.append(
            MIRLRecord(id=ent_id, kind=RecordKind.ENT, ns=ns, scope=scope,
                       attrs={"entity_type": entity_type, "label": label})
        )
        return ent_id

    # Turn-level speaker ("Name:") grounds the conversational claims' subject.
    speaker_subject: str | None = None
    speaker_match = _SPEAKER_RE.match(raw_text)
    if speaker_match:
        speaker_subject = entity_id(speaker_match.group(1), "person")
    turn_metadata = (
        _validated_turn_metadata(
            raw_text,
            speaker=speaker,
            source_timestamp=source_timestamp,
        )
        if extractor is not None and derived_fact_policy
        else None
    )
    explicit_speaker = turn_metadata[0] if turn_metadata is not None else None
    source_prefix_end = turn_metadata[1] if turn_metadata is not None else None
    rich_extractor = extractor
    if derived_fact_policy and turn_metadata is None:
        # A candidate-policy CLM without a canonical speaker envelope cannot
        # be safely attributed or served. Do not even index it: rich CLMs
        # participate in retrieval before the presentation gate.
        rich_extractor = None
    if turn_metadata is not None:
        records[0].ext["source_metadata"] = {
            "format": "locomo-turn/1",
            "speaker": explicit_speaker,
            "timestamp": source_timestamp or "",
            "prefix_end": source_prefix_end,
        }

    # High-confidence proper-noun entities anywhere in the text.
    for run in _proper_noun_runs(raw_text):
        entity_id(run, "entity")

    span_index = 1
    claim_index = 1
    rel_index = 1

    def add_claim(
        predicate: str,
        obj: object,
        subject: str,
        span_id: str,
        confidence: float = 0.9,
        *,
        facets: dict[str, str] | None = None,
        epistemic_basis: str | None = None,
        extraction_method: str | None = None,
        subject_label: str | None = None,
        record_id: str | None = None,
        ext_fields: dict[str, object] | None = None,
    ) -> None:
        nonlocal claim_index
        attrs = {"subject": subject, "predicate": predicate, "object": obj}
        if subject_label:
            attrs["subject_label"] = subject_label
        if facets:
            attrs["facets"] = dict(facets)
        ext = dict(ext_fields or {})
        if epistemic_basis:
            ext["epistemic_basis"] = epistemic_basis
        if extraction_method:
            ext["extraction_method"] = extraction_method
        resolved_id = record_id or f"clm:{source_hash}:{claim_index}"
        records.append(
            MIRLRecord(id=resolved_id, kind=RecordKind.CLM, ns=ns, scope=scope,
                       conf=confidence, prov=[prov_id], evidence=[span_id],
                       ext=ext, attrs=attrs)
        )
        if record_id is None:
            claim_index += 1

    def add_relation(src: str, predicate: str, dst: str, span_id: str, confidence: float = 0.85) -> None:
        nonlocal rel_index
        records.append(
            MIRLRecord(id=f"rel:{source_hash}:{rel_index}", kind=RecordKind.REL, ns=ns, scope=scope,
                       conf=confidence, prov=[prov_id], evidence=[span_id],
                       attrs={"src": src, "predicate": predicate, "dst": dst})
        )
        rel_index += 1

    for proposition, start, end in segment_propositions(raw_text):
        subject_label = _leading_subject(proposition)
        if not subject_label:
            continue
        span_id = f"span:{source_hash}:{span_index}"
        span_index += 1
        records.append(
            MIRLRecord(id=span_id, kind=RecordKind.SPAN, ns=ns, scope=scope, status=Status.OBSERVED,
                       attrs={"raw_id": raw_id, "start": start, "end": end})
        )
        # Grounded subject: the turn speaker if present, else the proposition's
        # leading noun phrase (both are drawn from the input text).
        subject = speaker_subject or entity_id(subject_label, "entity")
        # Floor: the verbatim content claim carries the full proposition (this is
        # what satisfies the contract's coverage check + temporal retention).
        add_claim("content", proposition, subject, span_id)
        # Opt-in rich extractor: REAL (subject, relation, object) triples + entities
        # (already grounded against this proposition), replacing the regex
        # enrichment. Falls back to the regex enrichment when it returns nothing.
        extraction_text = proposition
        extraction_offset = 0
        if (
            source_prefix_end is not None
            and start <= source_prefix_end <= end
        ):
            extraction_offset = source_prefix_end - start
            extraction_text = proposition[extraction_offset:]
        extraction = (
            rich_extractor.extract(extraction_text)
            if rich_extractor is not None
            else None
        )
        if extraction is not None and extraction.claims:
            rebased_claim_ids = {
                id(claim)
                for claim in extraction.claims
                if explicit_speaker
                and is_singular_first_person(claim.subject)
                and _candidate_claim_is_lossless(
                    extraction_text,
                    claim,
                )
            }
            rebased_subjects = {
                _normalized_label(claim.subject)
                for claim in extraction.claims
                if id(claim) in rebased_claim_ids
            }
            if not derived_fact_policy:
                for entity in extraction.entities:
                    if (
                        _normalized_label(entity.name) in rebased_subjects
                    ):
                        continue
                    entity_id(entity.name, entity.entity_type)
            # Extractor-identified entity names gate REL emission below: a
            # claim's object is only a real entity-entity edge when the
            # extractor itself flagged that phrase (or its head words) as an
            # entity, not merely a descriptive object ("an evening pottery
            # class" is a valid claim object but not an entity to link).
            # Token-subset match (not exact string equality) so an object
            # phrase carrying a determiner ("the billing service") still
            # matches the bare entity name ("billing service").
            extracted_entity_word_sets = [_content_words(e.name) for e in extraction.entities]
            for claim in extraction.claims:
                rebased = id(claim) in rebased_claim_ids
                if derived_fact_policy and not rebased:
                    continue
                resolved_subject_label = (
                    explicit_speaker if rebased else claim.subject
                )
                assert resolved_subject_label is not None
                claim_subject = entity_id(
                    resolved_subject_label,
                    "person" if rebased else "entity",
                    promote_type=rebased,
                )
                object_ent_id = (
                    entity_id(claim.obj, "entity")
                    if not derived_fact_policy
                    else None
                )
                facets = claim.facets()
                resolution: dict[str, object] | None = None
                if rebased:
                    facets["who"] = resolved_subject_label
                    resolution = {
                        "method": "first_person_to_turn_speaker",
                        "surface": claim.subject,
                        "speaker": resolved_subject_label,
                    }
                grounded_spans = _grounded_spans_payload(
                    claim,
                    proposition_start=start + extraction_offset,
                )
                ext_fields: dict[str, object] = {
                    "grounded_spans": grounded_spans,
                }
                if derived_fact_policy:
                    ext_fields["derived_fact_policy"] = derived_fact_policy
                extractor_metadata = getattr(
                    rich_extractor,
                    "config_metadata",
                    None,
                )
                if callable(extractor_metadata):
                    config = extractor_metadata()
                    if isinstance(config, dict):
                        ext_fields["extractor"] = config
                config_fingerprint = getattr(
                    rich_extractor,
                    "config_fingerprint",
                    None,
                )
                if isinstance(config_fingerprint, str) and config_fingerprint:
                    ext_fields["derived_fact_config_fingerprint"] = (
                        config_fingerprint
                    )
                if resolution is not None:
                    ext_fields["subject_resolution"] = resolution
                add_claim(
                    claim.relation,
                    claim.obj,
                    claim_subject,
                    span_id,
                    0.85,
                    facets=facets,
                    epistemic_basis=claim.epistemic_basis,
                    extraction_method="grounded_local_model",
                    subject_label=resolved_subject_label,
                    record_id=_derived_claim_record_id(
                        source_hash,
                        span_id,
                        claim,
                        resolved_subject_label,
                    ),
                    ext_fields=ext_fields,
                )
                # Cross-turn entity coreference (storage.persist_ir) only has
                # teeth for retrieval if a real entity-to-entity edge exists;
                # the verbatim CLM above never qualifies (object is text, not
                # an id). Emit one only when both ends are genuine entities.
                object_words = _content_words(claim.obj)
                if (
                    object_ent_id is not None
                    and any(
                        words and words <= object_words
                        for words in extracted_entity_word_sets
                    )
                ):
                    add_relation(claim_subject, claim.relation, object_ent_id, span_id)
        elif regex_enrich:
            # Legacy regex enrichment (default OFF; see SEAM_NL_REGEX_ENRICH above).
            _extract_conversational(proposition, subject, span_id, add_claim, speaker_match)

    return IRBatch(records)


def _extract_conversational(text: str, subject: str, span_id: str, add_claim, speaker_match) -> None:
    """Add grounded, span-localized enrichment claims (dates/locations/named
    entities/action verbs) for one proposition. The speaker ``person`` claim is
    emitted once, on the proposition that carries the ``Name:`` prefix."""
    if speaker_match is not None and text.startswith(speaker_match.group(0)):
        add_claim("person", speaker_match.group(1), subject, span_id, 0.92)

    seen_dates: set[str] = set()
    for pattern in _DATE_PATTERNS:
        for match in pattern.finditer(text):
            value = match.group(0)
            if value not in seen_dates:
                seen_dates.add(value)
                add_claim("date", value, subject, span_id, 0.9)

    seen_locations: set[str] = set()
    for match in _LOCATION_PATTERN.finditer(text):
        loc = match.group(1).strip()
        if len(loc) > 2 and loc.lower() not in _LOCATION_REJECT and loc not in seen_locations:
            seen_locations.add(loc)
            add_claim("location", loc, subject, span_id, 0.85)

    speaker_name = speaker_match.group(1) if speaker_match is not None else None
    seen_entities: set[str] = set()
    for match in _CAPITALIZED_ENTITY.finditer(text):
        entity = match.group(1).strip()
        if entity.lower() in STOPWORDS or entity.lower() in _ENTITY_REJECT:
            continue
        if entity in seen_entities or entity == speaker_name:
            continue
        seen_entities.add(entity)
        add_claim("mentioned", entity, subject, span_id, 0.82)

    for pattern, predicate in _ACTION_PATTERNS:
        match = pattern.search(text)
        if match:
            obj = match.group(1).strip().rstrip(".").rstrip(",")
            if obj:
                add_claim(predicate, obj, subject, span_id, 0.85)


def _content_words(text: str) -> frozenset[str]:
    """Lowercased word tokens of ``text``, for token-subset entity matching."""
    return frozenset(match.group(0).lower() for match in _WORD.finditer(text))


def _normalized_label(text: str) -> str:
    return " ".join(match.group(0).lower() for match in _WORD.finditer(text))


def _validated_turn_metadata(
    raw_text: str,
    *,
    speaker: str | None,
    source_timestamp: str | None,
) -> tuple[str, int] | None:
    """Validate the adapter's exact bracketed speaker/timestamp envelope."""

    prefix_end = canonical_turn_prefix_end(
        raw_text,
        speaker=speaker,
        timestamp=source_timestamp,
    )
    if prefix_end is None or not isinstance(speaker, str):
        return None
    candidate = speaker.strip()
    return candidate, prefix_end


def _candidate_claim_is_lossless(
    proposition: str,
    claim,
) -> bool:
    """Revalidate injected extractor output before candidate indexing."""

    from .nl_extract import grounded_sro_is_coherent

    if str(getattr(claim, "epistemic_basis", "")).strip().lower() != "explicit":
        return False
    source_spans = getattr(claim, "source_spans", ())
    required = {
        field: [
            span
            for span in source_spans
            if getattr(span, "field", None) == field
        ]
        for field in ("subject", "relation", "object")
    }
    if any(len(spans) != 1 for spans in required.values()):
        return False
    spans = {field: values[0] for field, values in required.items()}
    for span in spans.values():
        if (
            not isinstance(span.start, int)
            or not isinstance(span.end, int)
            or span.start < 0
            or span.end <= span.start
            or span.end > len(proposition)
            or proposition[span.start:span.end] != span.text
        ):
            return False

    def normalized(value: object) -> str:
        return " ".join(str(value or "").casefold().split())

    if (
        normalized(spans["subject"].text) != normalized(claim.subject)
        or normalized(spans["relation"].text) != normalized(claim.relation)
        or normalized(spans["object"].text) != normalized(claim.obj)
    ):
        return False
    return grounded_sro_is_coherent(
        proposition,
        spans["subject"],
        spans["relation"],
        spans["object"],
        evidence_start=0,
        evidence_end=len(proposition),
        require_complete_clause=True,
    )


def _grounded_spans_payload(
    claim,
    *,
    proposition_start: int,
) -> list[dict[str, object]]:
    return [
        {
            "field": span.field,
            "text": span.text,
            "start": proposition_start + span.start,
            "end": proposition_start + span.end,
        }
        for span in getattr(claim, "source_spans", ())
    ]


def _derived_claim_record_id(
    source_hash: str,
    span_id: str,
    claim,
    subject_label: str,
) -> str:
    seed = "\0".join(
        (
            span_id,
            subject_label,
            str(claim.relation),
            str(claim.obj),
            str(claim.epistemic_basis),
        )
    )
    digest = hashlib.sha256(seed.encode()).hexdigest()[:12]
    return f"clm:{source_hash}:derived:{digest}"


def _leading_subject(proposition: str) -> str:
    """The proposition's leading noun phrase, used as a GROUNDED claim subject.

    Strip one leading determiner/possessive, take the next word, and extend it
    with any immediately-following capitalized words (a proper-noun tail like
    ``sister Maria``). The result's tokens are always a subset of the input, so a
    claim built on it can never be 'about' an entity absent from the text."""
    words = [match.group(0) for match in _WORD.finditer(proposition)]
    if not words:
        return ""
    index = 1 if (words[0].lower() in _LEADING_DETERMINERS and len(words) > 1) else 0
    parts = [words[index]]
    follow = index + 1
    while follow < len(words) and words[follow][:1].isupper():
        parts.append(words[follow])
        follow += 1
    return " ".join(parts)


def _proper_noun_runs(text: str) -> list[str]:
    """High-confidence proper-noun entities: capitalized word runs, with leading
    capitalized function words (``The``, ``My``, ``I`` ...) stripped. Deduped,
    order-preserving. Conservative — lowercase common-noun phrases are left to the
    opt-in extractor."""
    runs: list[str] = []
    seen: set[str] = set()
    for match in _PROPER_NOUN_RUN.finditer(text):
        kept = [word for word in match.group(0).split() if word not in _NON_ENTITY_CAPS]
        if not kept:
            continue
        run = " ".join(kept)
        key = run.lower()
        if key not in seen:
            seen.add(key)
            runs.append(run)
    return runs


def suggest_symbols(batch: IRBatch, min_frequency: int = 2) -> list[MIRLRecord]:
    counter: Counter[str] = Counter()
    for record in batch.records:
        for key in ("predicate", "entity_type"):
            value = record.attrs.get(key)
            if isinstance(value, str) and len(value) > 8:
                counter[value] += 1
    symbols: list[MIRLRecord] = []
    for index, (value, frequency) in enumerate(counter.items(), start=1):
        if frequency < min_frequency:
            continue
        short = "".join(part[0] for part in value.split("_"))[:6] or f"sym{index}"
        symbols.append(MIRLRecord(id=f"sym:auto:{index}", kind=RecordKind.SYM, status=Status.INFERRED, conf=0.7, attrs={"symbol": short, "expansion": value, "frequency": frequency}))
    return symbols
