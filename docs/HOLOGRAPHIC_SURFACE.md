# SEAM Holographic Surface

See the [SEAM terminology glossary](TERMINOLOGY.md) for the distinction among
MIRL, RC/1, LX/1, HS/1, and canonical versus derived data. The governing
behavior remains defined by the [SEAM specification](../SEAM_SPEC_V0.1.md) and
[MIRL v1 contract](MIRL_V1.md).

`SEAM-HS/1` is the first Holographic Surface format for SEAM. It stores
machine-language payload bytes inside lossless PNG pixel data so SEAM can read
and query a portable memory snapshot without OCR, natural-language recompilation,
or SQLite import.

## Theory Boundary

Holographic Surface does not create free compression. The useful compression
already happened when SEAM converted source material into MIRL, `SEAM-RC/1`, or
`SEAM-LX/1`. The surface is a dense visual container for that payload.

The information-theory boundary is:

- Shannon entropy still controls compressibility of the bytes.
- Kolmogorov complexity still bounds the shortest exact program or description.
- A raw image can have fixed container size, but filling empty pixels with real
  payload bytes increases actual information content.
- Lossy formats such as JPEG are not exact memory formats because they mutate
  pixel values.

The breakthrough is practical, not magical: SEAM can encode directly readable
machine language into a compact, immutable, visual artifact and query that
artifact directly.

## Runtime Contract

`SEAM-HS/1` surfaces contain:

- a `SEAM-HS/1` envelope
- payload format metadata: `MIRL`, `SEAM-RC/1`, `SEAM-LX/1`, or `bytes`
- payload byte length
- payload SHA-256
- payload bytes encoded into PNG pixels

Supported v1 modes:

- `bw1`: proof mode using black/white pixels as bits
- `rgb24` / `rgb`: density mode using RGB channel bytes directly
- `rgba32`: explicit high-density mode using RGBA channel bytes directly
- `rgba64`: explicit 16-bit RGBA mode using 8 exact channel bytes per pixel

Direct-read behavior:

- MIRL payloads can be parsed and searched directly from the surface.
- `SEAM-RC/1` payloads can be queried directly through the readable-compression
  query path.
- `SEAM-LX/1` payloads can be verified and decoded exactly, but they are not
  directly queryable until converted into MIRL or `SEAM-RC/1`.

SQLite remains the canonical long-term store. Holographic surfaces are portable,
immutable, directly readable snapshots and transport artifacts.

The surface library adapter stores verified surface metadata in SQLite without
copying PNG bytes into the database. By default, `surface store`, `compile
--store`, and `encode --store` also create a redundant hash-named PNG copy under
`.seam/surfaces/` or `SEAM_SURFACE_DIR`, so stored-ID query still works if the
original output path is moved. Stored entries receive stable `hs:<hash>` IDs,
keep artifact paths, source refs, payload/surface hashes, PNG mode,
verification state, queryability, and import state. Direct-read commands can use
either a file path or a stored surface ID.

## Commands

```powershell
seam surface compile input.txt --output memory.seam.png --mode rgb24
seam surface compile input.txt --output memory.seam.png --mode rgb
seam surface encode input.seamrc --output memory.seam.png --mode rgb24
seam surface encode input.seamrc --output memory.seam.png --mode rgba32
seam surface encode input.seamrc --output memory.seam.png --mode rgba64
seam surface decode memory.seam.png --output restored.seamrc
seam surface verify memory.seam.png
seam surface query memory.seam.png "behavior"
seam surface search memory.seam.png "stable compression"
seam surface context memory.seam.png --query "agent behavior" --budget 1200
seam surface import memory.seam.png --db seam.db
seam surface store memory.seam.png --db seam.db
seam surface list --db seam.db
seam surface show hs:<surface-id> --db seam.db
seam surface repair hs:<surface-id> --db seam.db
seam surface query hs:<surface-id> "behavior" --db seam.db
```

`surface query`, `surface search`, and `surface context` read the embedded
machine-language payload from the image in memory. They do not require database
import first.

`surface store` records an existing verified surface in the SQLite surface
library. `surface compile --store` and `surface encode --store` write the PNG
and store its metadata in one step. The default redundant file adapter copies
the PNG into `.seam/surfaces/<surface-sha>.seam.png`; use `--artifact-dir` to
choose a different private surface library root or `--no-copy` only when the
given path is already durable. Stored entries point to operator-controlled
artifact paths; generated `.seam.png` user artifacts are not committed to the
runtime repo unless they are deliberate fixtures or documentation assets.

`surface repair hs:<id>` audits the stored redundant copy. If that copy is
missing or has the wrong hash, SEAM restores it from the original source path
recorded during `--store` when that source is still available and hash-matches
the stored surface. Failed repairs mark the SQLite entry as `verification=FAIL`
and `query=unavailable` instead of pretending the surface remains queryable.

`surface compile` is the automatic source-to-surface path: source text is
compiled into MIRL, then the MIRL bytes are encoded into `SEAM-HS/1`. `rgb24`
is the default because it survives ordinary PNG tooling more predictably.
`rgba32` stores 4 bytes per pixel instead of 3, increasing raw channel density
by about 33%, but it must stay explicit because alpha channels are more likely
to be rewritten or stripped by image editors and optimization tools. `rgba64`
stores 8 bytes per pixel as a 16-bit-per-channel RGBA PNG and should be used
only when that density is worth the higher tooling-compatibility risk.

## Benchmark Gate

The `surface` benchmark family requires:

- `surface_exact_rate == 1.0`
- `payload_hash_match_rate == 1.0`
- `direct_query_exactness_rate == 1.0`
- `stored_lookup_rate == 1.0`
- `stored_query_exactness_rate == 1.0`
- `repair_success_rate == 1.0`
- `repair_query_exactness_rate == 1.0`

Any pixel-packing, envelope, stored-library lookup, redundant-copy repair, or
query-dispatch change that drops exactness below 100% is release-blocking.

Fixture policy:

- Public `benchmarks/fixtures/surface_cases.json` cases are part of the
  release-blocking `surface` family and must pass at 100%.
- Richer document-structure cases for headings, table cells, references, and
  citations can be promoted into the public `surface` fixture only when the
  implementation is expected to satisfy them.
- Intentionally failing research cases must use a separate exploratory suite or
  local-only fixture. Do not loosen the release gate to carry partial passes.
