# Dropped PR Tracks

**Status:** durable record of long-horizon work removed from the active PR queue
**Added:** 2026-09-03
**Scope:** PR #207, PR #221 — closed without merge, branches preserved

## Why this file exists

The 2026-09-02 surface audit found five open PRs, none of which had a code
conflict with `main`. Every conflict was in append-only SEAM chain files
(`HISTORY.md`, `HISTORY_INDEX.md`, `.seam/cross_index*`,
`.seam/streams/history/*`) plus rename/rename collisions on row-count-named
archive files. That is structural: the append-only chain guarantees a conflict
for any branch not landed promptly, so a stale PR queue is self-worsening.

Two PRs carried long-horizon architecture material unrelated to the active
tracks (retrieval, graph, operator surface). They were closed to clear the
queue. Closing a PR does not delete its branch — everything below is
recoverable with the commands given.

**Nothing in this file is an implementation claim.** Both documents describe
target architecture. Neither asserts that the current SEAM implementation
already satisfies it.

## PR #207 — SEAM-native model end-state + ESP32-S3 embodied/spatial track

- **Branch:** `docs/seam-native-model-roadmap` (preserved)
- **Head commits:** `ea739d47`, `1772f2d8`, `4a4f8d86`
- **State at close:** 72 commits behind `main`

### Content

`docs/roadmap/SEAM_NATIVE_MODEL.md` (590 lines) — long-horizon target in which
SEAM is not a memory backend for third-party LLMs but the native memory
substrate of a purpose-built model: episodic, semantic, temporal, spatial,
relational, and affective memory plus a provenance graph feeding retrieval
policy, graph activation, source selection, and uncertainty. Carries a
non-negotiable provenance invariant — 100% traceable derivation for any
memory-derived claim.

`docs/roadmap/SEAM_ESP32_EMBODIED_SPATIAL.md` (734 lines) — declares the
ESP32-S3 work a SEAM architecture track rather than a standalone hardware
experiment. Fixed initial contract: one persistent agent, a Galaxy Tab A7
(camera as eyes, mic/speaker as voice, explicitly *not* a second agent and not
durable truth), exactly three ESP32-S3 nodes (A/B/C), and a Linux edge host
owning normalization, durable persistence, and SEAM provenance. Requires that
presence, motion, zone state, trajectories, identity, affective interpretation,
and dream-derived hypotheses stay separate claim classes and never collapse
into one another; every fused claim must retain separate A7 and node-level
evidence, with disagreement remaining visible. A7 transport (ADB / local app /
RTSP / WebRTC) is deliberately unselected pending a measurement spike.

`docs/roadmap/APPEND_ONLY_ROADMAP.md` (102 lines) and
`tools/streams/roadmap_lifecycle.py` — append-only roadmap lifecycle tooling.
Not referenced anywhere on `main`; standalone, safe to leave unmerged.

### Salvaged into `main` separately

`tools/git-hooks/pre-commit` was recorded in the index as mode `100644`
(non-executable). Git silently skips a non-executable hook, so any fresh clone
or CI checkout lost the pre-commit gate entirely — it only ran on boxes where
the on-disk exec bit happened to survive from an older checkout. PR #207
commits `1772f2d8` and `4a4f8d86` fixed this. The mode fix was cherry-picked
into the cleanup branch; the rest of #207 was not.

### External note

Hardware topology cross-referenced in the **Wisp** project
(`~/Documents/Projects/Wisp`), which runs the same phone-as-brain + ESP32-S3
fleet shape for RF survey work.

### Recovery

```bash
git fetch origin docs/seam-native-model-roadmap
git show origin/docs/seam-native-model-roadmap:docs/roadmap/SEAM_NATIVE_MODEL.md
git show origin/docs/seam-native-model-roadmap:docs/roadmap/SEAM_ESP32_EMBODIED_SPATIAL.md
```

## PR #221 — benchmark-proven second-brain persistence thesis

- **Branch:** `research/advanced-persistence-landscape` (preserved)
- **Head commit:** `d6999449`
- **State at close:** 68 commits behind `main`

### Content

`docs/audits/2026-08-18-seam-second-brain-persistence-dissertation.md`
(721 lines) — positions SEAM as the second brain's *persistence architecture*:
not a vector-backed memory utility, and not the agent that speaks, plans, or
uses tools. A model supplies active cognition; **Ghost** may supply the
user-facing agent experience; neither replaces SEAM as the durable cognitive
substrate. Treats Karpathy's LLM Wiki as the same persistence idea expressed as
a pattern rather than a benchmarked runtime, and proposes subsuming its
strongest idea as a derived knowledge projection while keeping stricter
canonical-truth, provenance, temporal, lifecycle, isolation, and recovery
contracts.

Its proof standard is the durable part: "most advanced" may not mean the
longest feature list or the best score on one vendor-run benchmark. "Proven"
requires a portfolio of frozen, reproducible, matched evaluations across
recall, updates, contradiction handling, temporal reasoning, million-token
scale, experience reuse, multi-session action, context efficiency, provenance,
deletion, crash recovery, and tenant isolation — measured against strong
baselines under one auditable protocol.

The document is structured as a decision instrument: numbered propositions in
§12 to be marked `ACCEPT` / `REVISE` / `REJECT`, with revisions required to
supply replacement wording and rejections required to cite contradictory
evidence or a concrete failure scenario. That review never happened.

`docs/audits/2026-08-18-advanced-agent-persistence-layers.md` (654 lines) —
companion competitive/landscape research.

### External note

Cross-referenced in the **Ghost** project, which the dissertation names as the
user-facing agent layer over SEAM.

### Recovery

```bash
git fetch origin research/advanced-persistence-landscape
git show origin/research/advanced-persistence-landscape:docs/audits/2026-08-18-seam-second-brain-persistence-dissertation.md
git show origin/research/advanced-persistence-landscape:docs/audits/2026-08-18-advanced-agent-persistence-layers.md
```

## Also closed in the same pass

- **PR #236** (`docs/seam-product-license-boundary-20260829`) — superseded;
  `docs/status/packaging-licensing.md` already carries this content on `main`.
- **PR #213** (`blackhatshiftey-performance-improvements`) — subsumed by
  PR #230, which touches the same three files and is 51 commits newer.

## Kept

- **PR #230** (`perf/batched-embedding`) — the only open PR carrying code
  absent from `main` (`tools/ingest_throughput_probe.py`,
  `tools/ranking_parity_probe.py`, `tests/audit/test_batched_embedding.py`,
  plus batching in `seam_runtime/{models,runtime,vector,vector_adapters}.py`).
  Needs a rebase; conflicts are chain-file only.
