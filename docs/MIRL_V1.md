# MIRL v1 Freeze

MIRL is the canonical memory IR inside SEAM.

## Readable Lossless Compression Contract

SEAM compression is not complete when it only produces an opaque compressed
payload. The primary compressed artifact must be directly readable AI-native
machine language. A SEAM agent or query engine must be able to answer questions
from the compressed language itself without restoring the original document,
image, audio, or video.

The phrase "read just like the original" means exact details remain addressable
inside the compressed language:

- text spans, quote boundaries, headings, tables, names, numbers, and references
- image regions, OCR text, captions, object labels, and spatial relationships
- video scenes, frame or time ranges, transcript spans, audio events, and tracked objects
- provenance from each compressed record back to the source region, span, frame, or segment

SEAM-LX/1 and other byte-level codecs may exist as exact reconstruction and
integrity backing layers, but they are not the working document for AI question
answering. The working document is the readable MIRL or successor SEAM machine
language representation. If a compression path cannot be queried directly, it is
only archival compression, not finished SEAM compression.

## SEAM-RC/1 Readable Compression

`SEAM-RC/1` is the first runtime-readable lossless text compression format. It
stores exact source text as directly parseable machine-language records:

- `META` records store source identity, hash, media type, granularity, and the
  direct-read contract.
- `CHUNK` records store exact unique text chunks, chunk hashes, and terms.
- `ORDER` records store the source order and source offsets needed to rebuild
  the exact text.
- `QUOTE` records store exact quoted spans with source offsets.
- `INDEX` records store term-to-chunk postings for direct compressed-language
  queries.

Current CLI commands:

```powershell
python seam.py readable-compress input.txt --output input.seamrc
python seam.py readable-query input.seamrc '"exact quoted text"'
python seam.py readable-rebuild input.seamrc --output rebuilt.txt
python seam.py benchmark run readable
```

`readable-query` reads `SEAM-RC/1` directly. It does not rebuild the source
document before returning exact hits.

The `readable` benchmark performs the current RC/1 1:1 gate:

- read exact full text back from RC/1 `CHUNK` and `ORDER` records without using
  byte-level decompression
- rebuild the source from RC/1 records and compare text/hash exactly
- compare source quote spans against RC/1 `QUOTE` records
- compare source terms against RC/1 `INDEX` records
- run direct `readable-query` checks against the compressed language and require
  exact quoted hits or same-record term coverage for table/cell-style facts

RC/1 exactness cannot fall below 100%. A recipe document must be readable back
from the compressed language exactly, including title, yield, ingredients,
measurements, ordered steps, notes, punctuation, and quoted text.

## SEAM-HS/1 Holographic Surface

`SEAM-HS/1` is a lossless visual container for SEAM machine-language payloads.
It stores MIRL, `SEAM-RC/1`, `SEAM-LX/1`, or raw bytes inside PNG pixel data
with an envelope containing payload format, byte length, and SHA-256.

`SEAM-HS/1` does not replace the readable language contract. It carries the
payload. Direct readability still comes from MIRL or `SEAM-RC/1`; the surface
lets SEAM read those bytes from the image in memory and immediately run the
normal parser, query, search, or context path without OCR, natural-language
recompilation, or SQLite import.

Current CLI commands:

```powershell
python seam.py surface compile input.txt --output input.seam.png --mode rgb24
python seam.py surface encode input.seamrc --output input.seam.png --mode rgb24
python seam.py surface verify input.seam.png
python seam.py surface query input.seam.png "exact phrase"
python seam.py surface context input.seam.png --query "agent behavior" --budget 1200
python seam.py benchmark run surface
```

Only lossless PNG surfaces are exact memory artifacts in v1. Lossy formats such
as JPEG are rejected for exact read workflows.

`rgb24` is the default density mode, and `rgb` is accepted as an alias.
`rgba32` is supported for explicit higher-density surfaces because it stores
four channel bytes per pixel. `rgba64` is supported for explicit 16-bit RGBA
surfaces because it stores eight channel bytes per pixel. Alpha-channel modes
are easier for image tooling to alter, strip, or normalize, so verify after any
tooling touch.

## Record Kinds

- `RAW`
- `SPAN`
- `ENT`
- `CLM`
- `EVT`
- `REL`
- `STA`
- `SYM`
- `PACK`
- `FLOW`
- `PROV`
- `META`

## Shared Non-RAW Fields

- `id`
- `kind`
- `ns`
- `scope`
- `ver`
- `created_at`
- `updated_at`
- `conf`
- `status`
- `t0`
- `t1`
- `prov`
- `evidence`
- `ext`
- `attrs`

## Typed Reference Contract

Reference identity comes from the MIRL field contract and canonical record
membership, never punctuation or an ID-looking prefix. Required reference
fields (`prov`, `evidence`, `SPAN.raw_id`, `CLM.subject`, `REL.src`/`dst`,
`EVT.actor`, `STA.target`, `PACK.refs`, `FLOW.src`/`dst`, and `PROV.entity`)
remain record references so missing or wrong-kind endpoints fail integrity
checks. Optional object and facet values become references only when the exact
ID exists in the same batch or the canonical store; otherwise they remain
literal value nodes. Timestamps, URLs, and arbitrary colon-bearing prose are
therefore literals unless they exactly name an existing record.

Graph-only virtual identities must be declared explicitly by the source record
in `ext["seam.virtual_refs"]` as a list of exact IDs. Prefixes do not confer
virtual status. The SQLite edge projection persists the MIRL kind (or
`virtual`) independently for both endpoints and validates both on reopen.

## Status Enum

- `asserted`
- `observed`
- `inferred`
- `hypothetical`
- `contradicted`
- `superseded`
- `deprecated`
- `deleted_soft`

## Canonical MIRL Text Form

One line per record:

```txt
KIND|record_id|<canonical_json_payload_without_id_and_kind>
```

## PACK Contract

### Exact

- reversible to the exact MIRL subset named in `refs`
- payload contains full MIRL JSON records
- verifier checks JSON-equivalent reconstruction

### Context

- optimized for token budget
- preserves `refs`, provenance fallback, and evidence fallback
- not durable truth

### Narrative

- natural-language summary
- explicitly lossy
- never treated as durable truth
