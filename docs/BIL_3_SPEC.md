# BIL-3: Signed Reproducibility Bundle (B1 specification)

**Status:** specification only. Not implemented, not a supported level, and no
bundle may carry a `BIL-3` label until B2 implements and verifies it.
**Chronology:** HISTORY#649. **Stream:** B1 of [Memory formation](roadmap/MEMORY_FORMATION.md).
**Evidence base:** [reconciliation audit](audits/2026-09-18-roadmap-fork-reconciliation.md) Finding 5.
**Consumer:** [E1 evaluation contract](E1_EVALUATION_CONTRACT.md); M2 consumes §8.

Current supported levels on the audited base are BIL-0, BIL-1 and BIL-2,
implemented in `seam_runtime/benchmark_integrity.py`. Verification of existing
bundles must keep working exactly as documented; BIL-3 is additive.

## 1. Why a new level is required

BIL-2 is a useful internal integrity check. It cannot support the claim its
successor name implies. Five defects, each verified against
`seam_runtime/benchmark_integrity.py` at `66fd3f9`:

**D1 — keyless verification can return `PASS` on altered content.** When a
bundle carries a `signature` block and the verifier holds no key, the check
emits `WARN` (line 265) and the status loop treats `WARN` as tolerable, so
overall `status` is `PASS`. An actor without the key can rewrite `result`,
recompute `bil.result_hash` and `input_manifest_hash`, and the bundle verifies
`PASS` to any keyless reader. `status == "PASS"` today does not mean the
signature was checked.

**D2 — the seal is symmetric.** `SIGNATURE_ALGO = "HMAC-SHA256"` (line 12)
keyed from `SEAM_BENCHMARK_SIGNING_KEY`. Every party able to verify is able to
forge. A shared secret cannot attest anything to a third party.

**D3 — timing evidence is outside the seal.** `result_hash` strips
`VOLATILE_RESULT_HASH_KEYS` (line 16) recursively by key name at any depth via
`stable_result_hash_input` (line 53). `answer_latency_ms`,
`retrieval_latency_ms` and `elapsed_seconds` are excluded wherever they
appear, so every latency and efficiency number in a bundle is unsigned and
freely mutable.

**D4 — publication identity is not bound.**
`validate_publication_readiness` (line 301) receives `git_sha`,
`fixture_hash` and `dataset_name` as caller arguments and checks only that
they are non-empty. They are never written into the signed BIL block, so the
commit a published claim names is not cryptographically tied to the result.

**D5 — no field-status taxonomy.** `build_input_manifest` (line 65) emits
whatever the result happens to carry. A field that was never collected is
indistinguishable from one collected and found empty.

## 2. What a signature does and does not prove

A BIL-3 signature proves that a specific artifact, produced by a specific
identified environment, has not changed since sealing. It proves **nothing**
about whether the measurement was well designed, whether the comparison was
fair, or whether the claim drawn from it is true. Signing a bad experiment
produces a securely sealed bad experiment.

## 3. Field-status taxonomy

Every manifest field carries an explicit status. This resolves D5 and makes a
missing field an auditable statement rather than an absence.

| Status | Meaning | Effect on verification |
| --- | --- | --- |
| `present` | Collected, with a value | Covered by the signature |
| `unavailable` | Applicable, collection attempted and failed; reason required | Sealed as `unavailable` + reason; **not** a pass |
| `unsupported` | Not applicable to this platform/backend; reason required | Sealed as `unsupported` + reason |
| `omitted` | Deliberately excluded by policy (e.g. redaction); reason required | Sealed as `omitted` + reason |

A field that is simply absent from the manifest makes the bundle **invalid**.
There is no fourth state of "not mentioned". Per the roadmap: a missing field
is not a successful attestation.

Every `unavailable`, `unsupported` and `omitted` entry carries a machine
-readable `reason` from a controlled vocabulary, so a verifier can distinguish
"this runner has no GPU" from "the collector crashed".

## 4. Manifest sections

All sections are required; individual fields within them use §3 statuses.

**`environment`** — OS, kernel, architecture, CPU model and count, RAM, GPU
model and count, container/runner identity.

**`code`** — exact git SHA, dirty-state flag, branch, and the contract
versions in force (retrieval policy, formation, ingestion, entity-resolution).
A dirty tree is recorded as such and disqualifies the bundle from publication.

**`dependencies`** — Python version, resolved dependency set and lockfile
hash (`uv.lock`), plus the hash of any declared extra in use.

**`data`** — dataset name, source URL, file SHA-256, case count, fixture hash,
split manifest path, split manifest SHA-256, salt, ratio, and the split
actually exercised.

**`models`** — answerer and judge identity, **requested** model id and
**served** model id recorded separately, transport name and version, seeds
where the provider supports them, and any cross-judge. Judging mode
(`synchronous` or `batch`) is recorded explicitly: `_build_report` in
`benchmarks/external/common/runner.py` accepts `judge_batch` but emits no
corresponding field, so a batched and a synchronous run currently produce
indistinguishable artifacts. E1 §3 requires each run to record judge identity;
mode is part of that identity, because a batch judge is a different call path
with different failure modes. B2 adds the field.

**`retrieval`** — policy identity, leg weights, top-k, context budget in both
characters and tokens, embedding model identity plus version and hash.

**`formation`** — the §8 contract.

**`results`** — per-case outcomes, aggregate scores, per-category breakdown,
and the §5 timing block.

**`cost`** — reported usage per role, attempt counts including failed and
retried calls, and an explicit `is_lower_bound: true` flag. Benchmark trap 7:
artifacts retain only the last clean pass per case, so a reported total is
always a lower bound on real spend and must say so in the sealed data.

## 5. Timing is inside the seal

D3 is resolved by removing timing from the volatile-key exclusion and moving
it into a dedicated `results.timing` block that **is** signed.

Volatility is handled by scope, not by deletion. Two hashes are computed:

- **`content_hash`** — over the semantic result with wall-clock timestamps
  (`created_at`, `run_started_at`) excluded. This is what a re-run can
  legitimately reproduce.
- **`artifact_hash`** — over the complete bundle including timing and
  timestamps. This is what the signature covers.

Exclusion is by **explicit path**, never by key name at arbitrary depth. The
current recursive name-based strip is what silently unsealed every nested
latency field; a path list makes each exclusion a reviewable decision.

## 6. Signing

**Algorithm:** Ed25519. Asymmetric signing resolves D2: the private key seals,
a public key verifies, and verification confers no ability to forge.

**Coverage:** the signature covers the canonical serialization of the entire
bundle except the `signature` block itself — not merely a small `bil` block.
This resolves D4, because `code.git_sha`, `data.fixture_hash` and
`data.dataset_name` are inside the signed region by construction rather than
being passed alongside it.

**Canonical serialization:** UTF-8 JSON, keys sorted lexicographically by
Unicode code point, no insignificant whitespace, no non-finite floats, and
integers distinguished from floats. The canonical form is specified in full
so an independent implementation can reproduce the bytes exactly.

**Key identity:** each signature carries the public key fingerprint and a key
id. Trust is established out of band; BIL-3 does not define a PKI and must not
imply one. A bundle signed by an unknown key verifies as
`VALID_SIGNATURE_UNTRUSTED_KEY` — cryptographically intact, not endorsed.

## 7. Verification is fail-closed

D1 is resolved by removing the tolerated-`WARN` path. Verification returns
exactly one status:

| Status | Condition |
| --- | --- |
| `PASS` | Signature present, key available, signature valid, all hashes match, all required fields present or explicitly statused |
| `FAIL` | Any hash mismatch, malformed bundle, or invalid signature |
| `UNVERIFIED` | Signature present but no key available to check it |

**`UNVERIFIED` is not a pass.** A caller that cannot check the signature is
told so in a status it cannot mistake for success. `validate_publication_readiness`
accepts only `PASS`.

Required negative cases for B2: altered `result` with recomputed hashes;
altered timing; altered git SHA; signature stripped; signature from a
different key; truncated bundle; a field absent rather than statused; a
duplicated JSON key; non-finite floats. Each must produce `FAIL`, and the
keyless case must produce `UNVERIFIED`, never `PASS`.

## 8. Formation metadata contract (M2 consumes this)

M2's design freeze depends on these fields existing and being stable. They are
specified here so M3/M4 emit them and M5 can compare arms.

| Field | Meaning |
| --- | --- |
| `formation.version` | Versioned identity of the formation pipeline that produced the records |
| `formation.segmentation_policy` | Policy identity and version; `baseline` names the unchanged path |
| `formation.segment_count` | Segments emitted per source document |
| `formation.segment_size` | Distribution summary in characters and tokens |
| `formation.boundary_signals` | Which signals fired (speaker, time, event, discourse, size fallback) |
| `formation.source_anchor_coverage` | Fraction of emitted observations with an exact RAW/SPAN backreference |
| `formation.attribution_preserved` | Fraction retaining speaker attribution |
| `formation.timestamp_preserved` | Fraction retaining a source timestamp; synthesized dates are forbidden and counted separately as `formation.timestamp_synthesized` (must be 0) |
| `formation.entity_view_version` | Entity-view contract version (M4) |
| `formation.contradictions_retained` | Count of conflicting claims preserved rather than collapsed |
| `formation.reingest_required` | Whether the arm was freshly re-ingested |

`formation.reingest_required` must be `true` for any formation comparison, per
the E1 contract's prohibition on `--keep-db`. A bundle claiming a formation
delta with `reingest_required: false` is invalid.

These are **diagnostics**, not quality. A change in segment count or coverage
is not an answer-quality result and may never be reported as one.

## 9. Redaction

Never fingerprint a secret. Hashing a credential into a public manifest leaks
an oracle against it. Configuration is fingerprinted only after secret-valued
keys are removed, and the removal is recorded as `omitted` with a reason
naming the key, never the value. API keys, tokens, DSNs with credentials,
session URLs and local `.env` values never enter a bundle in any form,
including hashed. This matches the repository's existing security rules.

## 10. Compatibility

BIL-0/1/2 bundles keep their documented semantics and existing verification
behavior. BIL-3 is a new version alongside them, not a reinterpretation.

D1 and D3 are live weaknesses in BIL-2 that B2 must decide about explicitly:
changing BIL-2's keyless path from `PASS` to `UNVERIFIED` is a **behavior
change** for existing consumers and needs a recorded migration decision, not a
silent fix. This specification records the defect; it does not authorize the
change.

## 11. Out of scope

No PKI, no key distribution or rotation mechanism, no revocation, no
transparency log, no cross-organization trust model. No claim that a signature
validates an experiment's design. BIL-3 is not implemented by this document
and no artifact may carry the label until B2 delivers it with the §7 negative
cases passing.
