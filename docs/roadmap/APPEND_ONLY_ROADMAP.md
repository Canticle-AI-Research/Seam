# Append-Only Roadmap Workflow

**Status:** Active operator protocol

SEAM's roadmap is never expected to become empty or permanently complete.
Direction changes by appending evidence, not by rewriting the past. Three
small streams keep different claim types from being confused:

| Stream | Meaning | Canonical path |
|---|---|---|
| `future-ideas` | Interesting possibilities with no delivery commitment | `.seam/streams/future-ideas/log.md` |
| `plans` | Intentionally scheduled or dependency-blocked work with an exit gate | `.seam/streams/plans/log.md` |
| `executed` | Observed completed, partial, failed, or abandoned outcomes | `.seam/streams/executed/log.md` |

The derived current view is `.seam/streams/roadmap_workflow_state.md`. The
global `.seam/cross_index.md` joins these events with history, the authored
roadmap, and experience.

## One stable item, many immutable events

Keep the same `item` ID across all three streams. For example:

```text
roadmap:track:T:data:generator-core-v1
```

Promotion does not move or delete an entry:

```text
future-ideas:004 --origin--> plans:012 --origin--> executed:009
```

A correction in one stream appends a new event whose `supersedes` field names
the exact previous event for that item:

```text
plans:017 supersedes plans:012
```

The old event remains byte-for-byte intact. The state renderer follows the
single unsuperseded head. Forked heads, missing targets, cross-item
supersession, and invalid promotion references fail verification.

## Event requirements

Every event has `item`, `event`, `supersedes`, `refs`, and `topics`.

- A future idea states the question or possible value without implying a
  commitment.
- A plan adds `origin`, `depends-on`, and an observable `gate`.
- An executed result adds its plan `origin`, an honest `outcome`, and exact
  `verification`. Failure and negative evidence belong here just as much as
  success.

Do not edit an old event to add `superseded_by`; the derived view computes that
reverse relationship. Do not put work in `executed` because code exists locally:
record the actual publication and verification boundary.

## Fast operator loop

Initialize or rebuild the workflow:

```bash
python -m tools.streams.roadmap_lifecycle init
python -m tools.streams.roadmap_lifecycle rebuild-state
python -m tools.streams.roadmap_lifecycle verify
```

Append one event:

```bash
python -m tools.streams.roadmap_lifecycle append \
  --stream plans \
  --item roadmap:track:T:data:generator-core-v1 \
  --event planned \
  --origin future-ideas:001 \
  --depends-on roadmap:track:T:data:contract-v1 \
  --gate "Deterministic replay emits the same manifest and zero orphan lineage" \
  --refs docs/roadmap/SEAM_NATIVE_MODEL.md \
  --topics "roadmap, streams, models, provenance" \
  --body "Build the first provenance-aware dataset generator core."
```

The append command validates before writing, rebuilds the affected index,
refreshes the state view and cross-index, and then verifies the lifecycle.

## Tonight's launch boundary

Fast work may change schemas, adapters, fixtures, deterministic validators,
small unit tests, and documentation. The following are explicitly deferred
until started as their own measured run:

- model pretraining, fine-tuning, distillation, quantization, or evaluation;
- bulk corpus conversion, deduplication, embedding, or contamination scans;
- paid/provider grading calls;
- long benchmark suites or full repository test suites;
- prolonged camera, CSI, calibration, or environmental data capture; and
- firmware flashing or destructive device/storage operations.

Track S is reconciled but parked: S0-S5 are merged; S6 is the next unstarted
stage; S7-S10 remain open behind it. This workflow records that boundary but
does not authorize starting S6.
