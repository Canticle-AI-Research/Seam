# Append-Only Roadmap State (derived)

Source: `.seam/streams/{future-ideas,plans,executed}/log.md`.
Regenerate: `python -m tools.streams.roadmap_lifecycle rebuild-state`.
Do not hand-edit this file.

## Future Ideas (3)

- `roadmap:track:U:agent:actuation-v1` — **proposed** via `future-ideas:002` — Explore physical actuation as a later capability with an explicit safety and authorization boundary.
- `roadmap:track:U:dream:embodied-consolidation-v1` — **proposed** via `future-ideas:003` — Explore offline embodied Dream Mode consolidation without allowing hypothesis-to-fact promotion.
- `roadmap:track:U:world:3d-reconstruction-v1` — **proposed** via `future-ideas:001` — Explore persistent 3D world reconstruction only after the fixed A7 plus three-node fusion baseline is measured.

## Plans (19)

- `roadmap:track:T:data:contract-v1` — **planned** via `plans:001` — Schema round-trips deterministically, hashes reproduce, and zero admitted rows have orphan lineage.
- `roadmap:track:T:data:source-registry-v1` — **planned** via `plans:002` — Every source is explicitly admitted or rejected with a reason and immutable source hash.
- `roadmap:track:T:eval:independent-grader-v1` — **planned** via `plans:003` — A different model family grades blinded arms, replay is stable on a sealed set, and disagreements remain explicit.
- `roadmap:track:U:sensing:esp32s3-3node-v1` — **planned** via `plans:012` — All three nodes produce restart-safe attributable observations and recover from loss or recalibration.
- `roadmap:track:U:vision:tab-a7-v1` — **planned** via `plans:011` — Frames reconnect and remain attributable with visible permission, calibration, privacy, and camera-off behavior.
- `roadmap:track:U:voice:tab-a7-v1` — **planned** via `plans:020` — Push-to-talk voice turns remain attributable, interruptible, privacy-bounded, and usable across reconnect with measured ASR/TTS latency and uncertainty.
- `roadmap:track:T:data:generator-core-v1` — **planned** via `plans:004` — Repeated generation emits the same content and manifest hashes with zero silent drops.
- `roadmap:track:T:data:pretrain-view-v1` — **planned** via `plans:005` — The view parses, tokenizes reproducibly, retains source closure, and contains zero known holdout rows.
- `roadmap:track:T:data:training-view-v1` — **planned** via `plans:006` — Every trajectory validates against its task schema and cites complete admitted evidence.
- `roadmap:track:T:data:quality-splits-v1` — **planned** via `plans:007` — Manifest replay is exact, cross-split duplicate groups are zero, and sealed holdouts remain isolated.
- `roadmap:track:T:model:250k` — **planned** via `plans:008` — The approximately 250K model beats a declared heuristic and resource baseline under independent grading.
- `roadmap:track:S:S6` — **blocked** via `plans:019` — Principal propagation, principal-derived namespaces, opaque deletion, and two-principal denial/privacy/idempotence all pass.
- `roadmap:track:S:S7` — **blocked** via `plans:015` — All S7 exit evidence in the campaign contract passes on an exact head.
- `roadmap:track:S:S8` — **blocked** via `plans:016` — All S8 surface-parity, replay, identity, and tenant-event gates pass.
- `roadmap:track:U:fusion:a7-3node-v1` — **blocked** via `plans:013` — Fusion yields measured gain, preserves disagreements, and retains complete per-source lineage.
- `roadmap:track:S:S9` — **blocked** via `plans:017` — The frozen candidate passes overall and every category gate with independent reproducible evidence.
- `roadmap:track:S:S10` — **blocked** via `plans:018` — The frozen candidate passes every release, artifact, privacy, continuity, review, and required-CI gate.
- `roadmap:track:T:model:1b` — **blocked** via `plans:009` — The 1B model passes provenance, abstention, category non-regression, efficiency, and contamination gates.
- `roadmap:track:T:model:4b` — **blocked** via `plans:010` — The 4B model improves declared capabilities without provenance, contamination, or category regressions.

## Executed / Finished (6)

- `roadmap:track:S:S0` — **completed** via `executed:001` — Merged/shipped at 778de2c.
- `roadmap:track:S:S1` — **completed** via `executed:002` — Merged/shipped at ebbf2f3.
- `roadmap:track:S:S2` — **completed** via `executed:003` — Merged/shipped at 6b7c22d.
- `roadmap:track:S:S3` — **completed** via `executed:004` — Merged/shipped at 9bd40cb.
- `roadmap:track:S:S4` — **completed** via `executed:005` — Merged/shipped at ea4e46e.
- `roadmap:track:S:S5` — **completed** via `executed:006` — Merged/shipped at 19b3a76.
