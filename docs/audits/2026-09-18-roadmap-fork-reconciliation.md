# Roadmap fork reconciliation and open-PR disposition

[Reports](INDEX.md) · [Formation roadmap](../roadmap/MEMORY_FORMATION.md) ·
[Handoff registry](../handoffs/INDEX.md)

Chronology: HISTORY#647. Scope: repository continuity state observed on
protected main `66fd3f93081712871ff827e756026c3e73c71790`. This is a
documentation and continuity reconciliation. No runtime code, roadmap
registration, benchmark, provider configuration or deployment changed. No
research lane is started, accepted or funded by this report.

## Question and method

The handoff head registered at the time of this audit,
[`2026-09-14-claude-code-benchmark-next`](../handoffs/2026-09-14-claude-code-benchmark-next.md)
(HISTORY#646), records PR dispositions for `#264` and the merged provider
branch. Three pull requests were opened after that handoff was authored. This
audit asks whether the recorded state still matches the live repository, and
whether the two research-lane pull requests opened on 2026-09-17 and
2026-09-18 can both merge as authored.

Method: read the registered handoff chain, then enumerate open pull requests
and their changed files through the GitHub API, then compare the observed
patches against the current contents of `ROADMAP.md`,
`.seam/streams/roadmap/state.md` and `tools/streams/verify_streams.py` in the
local checkout at the same base commit. Every claim below is stated against a
pinned head SHA or a repository path and line.

## Observed open pull requests

All seven open pull requests are drafts. Heads observed during this audit:

| PR | head | base | opened / updated | registered in handoff chain |
| --- | --- | --- | --- | --- |
| #268 | `ab1bcd348d1a07e3546b77dfe67a5c923253cce7` | `66fd3f9` | 2026-09-18 | no |
| #267 | `24e1725134d476798992cc7ecaef7de299d27cc6` | `66fd3f9` | 2026-09-17 | no |
| #266 | `9f0bfae2609d7ec587bb8375274ab7e4e63495ea` | `66fd3f9` | 2026-09-17 | no |
| #264 | `18abe44236021ba0bfddb78f55d067754c0d42ef` | `614141c` | 2026-09-13 | yes, `NOT_QUALIFIED` |
| #249 | `8d77775fe6e029717115758b917c94c757ed0d4a` | `7bd47d2` | dependabot | yes, named in E1 |
| #230 | `6313f851c2cf68ef06350c910f6c9bbf3be13762` | `bc6b927` | — | no |
| #213 | `4d2609e59ffca85eb2c4c6c4e995e62f545744ec` | `f0bc4b0` | — | no |

`#264`'s head is unchanged from the value recorded in the 2026-09-14 handoff,
so its `TDD_UNPROVEN` disposition for its branch-only helper
tools/memory\_formation\_m1.py still describes the current head. `#249`'s mem0 2.0.0b2 bump remains the baseline
hazard named in the formation roadmap's E1 stream.

## Finding 1 — two research lanes claim the same roadmap slot

`#267` and `#268` are overlapping, independently authored research lanes over
the same prior art. They are not duplicates, and neither is a superset of the
other in full.

| | #267 | #268 |
| --- | --- | --- |
| track id | `roadmap:track:LatentCacheBridge` | `roadmap:track:PCS` |
| detail document (branch-only) | docs/roadmap/LATENT\_CACHEBRIDGE.md (551 lines) | docs/roadmap/PERSISTENT\_CONCEPT\_STATE.md (297 lines) |
| stages | LC0–LC8 | PCS0–PCS10 |
| `ROADMAP.md` delta | +34 | +33 / −1 |
| other files | `docs/roadmap/README.md` (+7) | none |
| declared priority / phase | 3 / 0 | 4 / 2 |
| status | `planned`, since 2026-09-17 | `planned`, since 2026-09-18 |

Shared prior art: both cite Cache-to-Cache (Fu et al., arXiv:2510.03215).
`#268` adds Latent Cache Flow (arXiv:2605.22863) and Dynamic Large Concept
Models (arXiv:2512.24617). Both adopt an explicit baseline-first rule and
both hold MIRL/SQLite canonical with latent artifacts derived and disposable,
so their architectural boundaries agree.

The overlap is structural, not incidental. `#268`'s stage **PCS7** is titled
"Latent reactivation / SEAM CacheBridge" and proposes projected KV state, a
learned prefix and cross-attention memory — the same mechanism `#267` develops
across LC2–LC8. Registering both means one research area carries two
`seam:item` markers, two stage numbering schemes and two priority values.

Each document also holds material the other lacks. `#267` alone specifies the
induction-aware PACK ordering experiment (LC1), the security and failure
campaign (LC7), the `seam_runtime/latent/` package layout, the branch-per-stage
delivery strategy and the `seam-cachebridge` extraction criteria. `#268` alone
frames persistent cross-turn state, the provenance-gated semantic delta
(PCS6), concept compression against DLCM (PCS4) and the long-horizon scaling
experiment. Discarding either whole loses specification work.

## Finding 2 — the two patches cannot both apply

This is mechanical, not a matter of judgement. On main, `ROADMAP.md:44-48`
ends the memory-formation priority paragraph and line 50 begins
`## 2026-05-01 Functional Visual Memory Target`. Both patches carry the hunk
header `@@ -47,6 @@` with identical leading context and insert their new track
section into the same gap before line 50.

Whichever merges first, the second produces a textual conflict at that
position. Neither branch has been rebased onto the other. `#268` carries a
second hunk at `@@ -2050,6 +2081,7 @@` adding a PCS line to the phased
backlog; `#267` has no corresponding entry there, so a naive conflict
resolution can silently register one track in the header and the other in the
backlog list.

## Finding 3 — neither lane carries its continuity artifacts

`AGENTS.md` Session End requires an appended `HISTORY.md` entry, a rebuilt
`HISTORY_INDEX.md`, a snapshot, the verify chain, and — when `ROADMAP.md`
changes — a rerun of `tools.streams.roadmap_parser`.

Observed in the two patches: `#267` changes `ROADMAP.md`,
the branch-only docs/roadmap/LATENT\_CACHEBRIDGE.md, and
`docs/roadmap/README.md` only.
`#268` changes `ROADMAP.md` and the branch-only
docs/roadmap/PERSISTENT\_CONCEPT\_STATE.md only. Neither adds a HISTORY entry, a handoff registration, or a regenerated
roadmap stream. `#266`'s packaging repair is likewise unregistered in the
handoff chain.

This is a gap in the pull requests as authored, not a defect in main.

## Finding 4 — roadmap stream drift is unenforced

`ROADMAP.md` currently carries 66 `seam:item` markers and
`.seam/streams/roadmap/state.md` lists 66 items, so the stream and the authored
prose are in sync at this base commit.

Nothing enforces that. `tools/streams/verify_streams.py` contains zero
references to the roadmap stream (whole-file `grep -c roadmap` returns `0`).
The gate checks parseability, history-mirror byte-equivalence, per-stream index
consistency and cross-index presence; it does not compare `ROADMAP.md`'s
markers against the derived roadmap stream. The Session End instruction to
rerun the parser is therefore protocol-only, enforced by no local gate and no
required CI check.

Consequence: either research-lane PR can merge with a new `seam:item` marker
and leave `state.md` silently one track short. Because `state.md` is the
agent-facing status view that `AGENTS.md` Context Loop directs agents to read
**instead of** `ROADMAP.md`, the drift is invisible at exactly the point where
the next agent decides what to work on. Remediation is proposed, not performed,
in this audit.

## Finding 5 — BIL-2 integrity gaps recorded as B1 input

Recorded here as specification input for the formation roadmap's B1 stream
(BIL-3 schema design). Remediation belongs to B2; no runtime change is made by
this audit. Evidence is `seam_runtime/benchmark_integrity.py` at this base
commit.

1. **Keyless verification of a signed bundle can return `PASS` on forged
   content.** When a bundle carries a `signature` block and the verifier has no
   key, the signature check emits `WARN` (line 265). The status loop treats
   `WARN` as tolerable, so overall `status` stays `PASS`. An actor without the
   key can rewrite `result`, recompute `bil.result_hash` and
   `input_manifest_hash`, and the bundle verifies `PASS` to any keyless reader.
   `status == "PASS"` therefore does not mean the signature was verified.
2. **The signature is symmetric.** `SIGNATURE_ALGO = "HMAC-SHA256"` (line 12)
   keyed from `SEAM_BENCHMARK_SIGNING_KEY`. Anyone able to verify is able to
   forge, so the
   current seal cannot support third-party reproducibility attestation. A
   "Signed Reproducibility Bundle" requires asymmetric signing.
3. **Timing evidence is outside the seal.** `result_hash` strips
   `VOLATILE_RESULT_HASH_KEYS` (line 16) recursively by key name at any depth
   via `stable_result_hash_input` (line 53), so
   `answer_latency_ms`, `retrieval_latency_ms` and `elapsed_seconds` are
   excluded from the hash wherever they appear. Every latency and efficiency
   number in a bundle is unsigned and freely mutable.
4. **Publication identity is not bound into the bundle.**
   `validate_publication_readiness` (line 301) receives `git_sha`, `fixture_hash` and
   `dataset_name` as caller arguments and only checks that they are non-empty.
   They are never written into the signed BIL block, so the commit a published
   claim names is not cryptographically tied to the result it names.
5. **No field-status taxonomy.** `build_input_manifest` (line 65) emits whatever the
   result happens to carry. There is no distinction between required, optional,
   unavailable and unsupported, so a missing field is indistinguishable from a
   field that was collected and found empty. B1 must define that taxonomy
   explicitly; the roadmap already states that a missing field is not a
   successful attestation.

Items 1 and 3 mean the existing BIL-2 seal is weaker than its consumers are
likely to assume. This is recorded, not repaired, per the operator's decision
to schedule remediation under B2.

## Recommended disposition

These are recommendations. None is executed by this audit, and none of the
three pull requests was modified.

1. **Reconcile `#267` and `#268` into one registered track before either
   merges.** Retain a single `seam:item` marker for the research area. The
   broader frame belongs to `#268`, whose ladder already stages the bridge as
   PCS7; `#267`'s document is the deeper mechanism specification for that
   stage. Folding LATENT\_CACHEBRIDGE.md in as the referenced PCS7 mechanism
   spec, and dropping the second track marker, keeps both bodies of work and
   removes the duplicate registration. One priority and phase value must be
   chosen; the branches currently declare 3/0 and 4/2.
2. **Rebase the retained branch onto current main and rerun
   `tools.streams.roadmap_parser`** so `state.md` gains the new track in the
   same change that adds the marker, until Finding 4 is gated.
3. **Add roadmap-marker-to-stream drift checking to `verify_streams`** as a
   separate change, so the parser rerun stops depending on protocol memory.
4. **Split `#264`.** Its 38 files bundle the M1 audit and evidence with a
   GitHub Pages report site, a deployment workflow, three test modules and two
   new tool packages. The `TDD_UNPROVEN` condition attaches to
   its branch-only helper tools/memory\_formation\_m1.py alone. M1 acceptance
   and P0/P2 report routing are held behind a 195-line helper that the audit's
   findings do not depend on. Separating the audit and evidence from the helper and the site is the
   shortest path to resolving M1 without waiving the release condition.
5. **Neither research lane displaces the formation ready set.** Request R14
   keeps the opening formation priorities dominant, and both documents accept a
   parallel, non-displacing role. Registering a planned lane is cheap;
   beginning PCS0 or LC0 before M1 acceptance, the B1 metadata contract and the
   E1 evaluation design are resolved would invert the dependency order the
   formation roadmap sets.

## Open items not resolved here

- The three arXiv identifiers cited by `#268` were **not** independently
  verified against the upstream listings during this audit. They are
  internally consistent with the repository's date, and both documents treat
  the cited work as prior art rather than as a SEAM result, but the citations
  should be checked before either document is published outside the repository.
- The disposition of `#266` (packaging/release/MCP repair), `#230` and `#213`
  is unchanged and unexamined by this audit; they are recorded above only so
  the handoff chain stops under-reporting live branch state.
- `HISTORY#646` carries `commits: pending`; its merge SHA was never backfilled.
  `HISTORY.md` is append-only, so this is noted rather than edited.

## Pinned identities

Content-addressed pull-request heads and repository locations observed for this
audit.

| Subject | Identity |
| --- | --- |
| Base commit for every claim | `66fd3f93081712871ff827e756026c3e73c71790` |
| PR #268 head (research/pcs-c2c-dlcm-roadmap) | `ab1bcd348d1a07e3546b77dfe67a5c923253cce7` |
| PR #267 head (feat/latent-cachebridge-roadmap-20260917) | `24e1725134d476798992cc7ecaef7de299d27cc6` |
| PR #266 head (fix/pypi-release-flow-20260917) | `9f0bfae2609d7ec587bb8375274ab7e4e63495ea` |
| PR #264 head (feat/seam-reports-pages-20260912) | `18abe44236021ba0bfddb78f55d067754c0d42ef` |
| Shared insertion point | ROADMAP.md lines 44-50 |
| Marker and stream counts | ROADMAP.md 66 markers; roadmap state view 66 items |
| Unenforced drift | tools/streams/verify_streams.py, 0 roadmap references |
| BIL findings | seam_runtime/benchmark_integrity.py lines 12, 16, 53, 127, 265, 301 |

## Evidence manifest

Raw artifacts: none

This audit read live pull-request state and repository files at the pinned base
commit. It produced no raw result bundles, logs or generated artifacts; every
claim is reproducible from the identities above and the repository at that
commit.
