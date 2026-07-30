# Status Stream: Compression Visual

> MIRL/RC, SEAM-LX/1, and SEAM-HS/1 holographic surfaces

_Source of truth for current state in this area. History lives in `HISTORY.md`._

## Stable

- Lossless SEAM-LX/1 compression with integrity verification.
- SEAM-HS/1 Holographic Surface PNG snapshots: source-to-MIRL surface compile,
  direct MIRL/RC query, verify, decode, context, import.
- Surface commands: `seam surface compile|encode|decode|verify|query|search|context|import`
  with `bw1`, `rgb`/`rgb24`, explicit `rgba32` codecs.
- Surface library: `seam surface store|list|show|repair`, `compile --store`,
  `encode --store`, stable `hs:<hash>` IDs, redundant file-backed copies.

## Governing contract

`SEAM_SPEC_V0.1.md` + `docs/MIRL_V1.md` are the governing contract. Read them before
any compilation, MIRL/IR, compression, PACK, retrieval, surface, or codec work.

MIRL's objective is **queryable-after-compression and lossless**; token reduction is
a downstream concern (LX / surface / pack), not the compile layer's job. SEAM-RC/1
meets its spec contract; it is not the token-reduction layer.

## Active / open direction

- Make compression produce directly readable AI-native machine language, with opaque
  byte payloads only as optional reconstruction/integrity backing.
- Treat HS/1 as a queryable visual snapshot layer for MIRL/RC payloads — not free
  compression, not a replacement for SQLite truth.
- Ship the full visual-memory loop: documents compile to readable MIRL/RC, pack into
  HS/1 PNG surfaces, stay addressable by metadata/hash, and answer query/context
  directly from the image surface without restoring the original document, with the
  surface benchmark gating stored lookup plus repair at 100%.
- Track G5 (planned): zero-ops multi-surface `.seam.png` library index + drift verifier.
