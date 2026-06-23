# SEAM Prompt Codec Optimization Roadmap

**Status:** Planned roadmap track. Concept harvested from `bench/add-memory-benchmark-registry`.
**Track:** J — Prompt Codec Optimization.

## Purpose

SEAM's canonical storage is MIRL, JSON, and SQLite. Those formats are not always the most token-efficient transport for sending structured data into a model prompt. This track evaluates alternative *derived* prompt serialization codecs (TOON, compact JSON, SEAM-RC/1, SEAM-LX/1, markdown tables) and lets SEAM auto-select the cheapest reversible codec for each payload class under the active tokenizer.

Canonical record formats do not change. Audit, surface, and benchmark bundles keep byte-stable canonical JSON. Codec selection is restricted to derived prompt-bound payloads.

## Candidate codecs

- **Compact JSON** — baseline. Already supported. Lossless. Verbose under most tokenizers.
- **TOON** (Token-Oriented Object Notation) — column/array oriented. Often cheaper than JSON for repeated-shape arrays.
- **SEAM-RC/1** — Record-Compact. SEAM-specific record codec tuned for MIRL record arrays.
- **SEAM-LX/1** — Long-Context. SEAM-specific codec for retrieval result lists and context packs.
- **Markdown tables** — sometimes cheapest for small comparator scorecards.

## Proposed experiment: protected-prefix lexical symbols

**Status:** Operator-originated concept; not implemented and not yet a
compression-performance claim. This is a derived `PACK`/prompt-codec experiment
only. It must never rewrite `RAW`, exact quotes, canonical MIRL/JSON, or
`SEAM-RC/1` readable-lossless records.

### Operator wording retained

> theres got to be a symbiosys of dropping vowels when x else y , what would
> tat be if its tit for tat?
>
> alot of these short forms can be altered and made specific, by adding the
> last letter of the word to the abbreviation if its a constanant
>
> okay could we take collisions, and either add a number or set a limit on
> size, if a word is x characters only X characters have to be abbreviated ex;
> foundational -> 5 character limit = foundtnl

### Working interpretation

For eligible repeated controlled terms, retain a recognizable prefix and only
compact the remaining suffix. The proposed default is:

```txt
word length <= 7: retain the original term
word length >= 8: preserve clamp(round(length * 0.4), 4, 6) leading characters
                  and drop vowels from the remaining suffix
```

For example, `foundational` preserves `found` and compacts `ational` to
`tnl`, producing `foundtnl`. Because the suffix keeps consonants, a terminal
consonant is retained; if a future variant shortens the suffix further, it must
append a missing terminal consonant before considering a collision tag.

Collision repair is ordered and reversible:

```txt
protected-prefix candidate
  -> restore the smallest distinguishing suffix vowel(s)
  -> append an immutable, scope-local numeric tag (for example, ~2)
```

The numeric tag is a last resort. Its assignment must remain recorded in the
symbol dictionary and must never be renumbered, so existing packs continue to
decode correctly.

### Promotion gates

- Apply only to structured, repeatedly occurring terms with an explicit
  symbol-to-expansion mapping; do not abbreviate arbitrary prose.
- Measure *net* token savings with the active target tokenizer, including the
  dictionary's definition cost. Character savings alone are insufficient.
- Require deterministic reverse expansion, no unresolved scoped collisions,
  and no regression in direct packed-context retrieval or answer quality.
- Compare this candidate against the existing symbol abbreviator and compact
  JSON; promote only the measured winner for the payload/model pair.

## Initial payload targets

- PACK payloads
- retrieval result lists
- benchmark case matrices
- benchmark reports
- memory search index outputs
- citation / evidence tables
- tool-result arrays
- comparator scorecards

## Gates

- Codec roundtrip exactness is 100% when the payload requires lossless transport.
- Canonical JSON/MIRL hashes remain unchanged on disk.
- An alternate codec must beat compact JSON on measured token count under the active tokenizer before auto-selection promotes it.
- Signed, tamper-evident, or canonical benchmark bundles keep byte-stable canonical JSON unless a formally specified canonical TOON profile (or equivalent) is added, versioned, and tested.

## Proposed commands

```bash
seam codec benchmark payload.json
seam codec encode payload.json --format toon
seam codec encode payload.json --format auto
seam codec decode payload.toon --format toon
```

## Relationship to other tracks

- Track I (external memory benchmarks) Phase 6 adds a prompt-codec benchmark layer that compares codecs under the active tokenizer for the same payload class.
- Track K (trust/security) keeps canonical bundle hashing untouched; codec selection lives strictly on the derived-prompt side.
- The protected-prefix lexical-symbol experiment is a Track J candidate codec
  policy. It depends on Track I's tokenizer-aware benchmark evidence before any
  automatic promotion.

## Definition of done

Track J is complete when SEAM can encode any of the listed payload classes under any of the candidate codecs, measure tokens under the active tokenizer, auto-select the cheapest reversible codec, and round-trip the result with proof of exactness — all without altering canonical storage hashes.
