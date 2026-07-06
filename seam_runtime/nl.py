from __future__ import annotations

import hashlib
import os
import re
from collections import Counter

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
_SENTENCE_PUNCT = frozenset(".!?")
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


def compile_nl(raw_text: str, source_ref: str = "local://input", ns: str = "local.default", scope: str = "thread", extractor=None) -> IRBatch:
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
    if extractor is None and os.environ.get("SEAM_NL_EXTRACTOR"):
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

    def entity_id(label: str, entity_type: str = "entity") -> str:
        """Resolve (and lazily create) an ENT for ``label``, deduped by its
        lowercased form. The first call's ``entity_type`` wins (so a speaker
        resolved as ``person`` is not downgraded by a later generic mention)."""
        key = label.lower()
        existing = entity_ids.get(key)
        if existing is not None:
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

    # High-confidence proper-noun entities anywhere in the text.
    for run in _proper_noun_runs(raw_text):
        entity_id(run, "entity")

    span_index = 1
    claim_index = 1

    def add_claim(predicate: str, obj: object, subject: str, span_id: str, confidence: float = 0.9) -> None:
        nonlocal claim_index
        records.append(
            MIRLRecord(id=f"clm:{source_hash}:{claim_index}", kind=RecordKind.CLM, ns=ns, scope=scope,
                       conf=confidence, prov=[prov_id], evidence=[span_id],
                       attrs={"subject": subject, "predicate": predicate, "object": obj})
        )
        claim_index += 1

    for proposition, start, end in _segment_propositions(raw_text):
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
        extraction = extractor.extract(proposition) if extractor is not None else None
        if extraction is not None and extraction.claims:
            for entity in extraction.entities:
                entity_id(entity.name, entity.entity_type)
            for claim in extraction.claims:
                claim_subject = entity_id(claim.subject, "entity")
                entity_id(claim.obj, "entity")  # the object phrase is a grounded entity too
                add_claim(claim.relation, claim.obj, claim_subject, span_id, 0.85)
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


def _segment_propositions(text: str) -> list[tuple[str, int, int]]:
    """Split ``text`` into propositions (sentences) with REAL character offsets.

    A run of ``.!?`` is a boundary only when followed by whitespace or end of
    string (so 4.2 / 9:30 / B12 don't split). Each result is
    ``(proposition_text, start, end)`` with ``text[start:end] == proposition_text``
    (surrounding whitespace trimmed); only propositions with at least one word are
    kept. The scan is O(n) and backtracking-free, so it is safe on uncontrolled
    input."""
    result: list[tuple[str, int, int]] = []

    def emit(start: int, end: int) -> None:
        segment = text[start:end]
        lead = len(segment) - len(segment.lstrip())
        trimmed = segment.strip()
        if trimmed and _WORD.search(trimmed):
            real_start = start + lead
            result.append((text[real_start:real_start + len(trimmed)], real_start, real_start + len(trimmed)))

    length = len(text)
    cursor = 0
    index = 0
    while index < length:
        if text[index] in _SENTENCE_PUNCT:
            run_end = index
            while run_end < length and text[run_end] in _SENTENCE_PUNCT:
                run_end += 1
            if run_end >= length or text[run_end].isspace():
                emit(cursor, run_end)
                cursor = run_end
            index = run_end
        else:
            index += 1
    if cursor < length:
        emit(cursor, length)
    if not result:
        emit(0, length)
    return result


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
