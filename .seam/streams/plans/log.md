---BEGIN-PLANS-EVENT-#001---
id: plans:001
date: 2026-08-12T18:00:03Z
agent: codex
kind: roadmap-item
item: roadmap:track:T:data:contract-v1
event: planned
supersedes: none
origin: none
depends-on: none
gate: Schema round-trips deterministically, hashes reproduce, and zero admitted rows have orphan lineage.
outcome: none
verification: none
refs: docs/roadmap/SEAM_NATIVE_MODEL.md
topics: roadmap, models, provenance, json, integrity
tokens: 12
---
Define the canonical append-only example envelope and lineage closure rules.
---END-PLANS-EVENT-#001---

---BEGIN-PLANS-EVENT-#002---
id: plans:002
date: 2026-08-12T18:00:04Z
agent: codex
kind: roadmap-item
item: roadmap:track:T:data:source-registry-v1
event: planned
supersedes: none
origin: none
depends-on: roadmap:track:T:data:contract-v1
gate: Every source is explicitly admitted or rejected with a reason and immutable source hash.
outcome: none
verification: none
refs: docs/roadmap/SEAM_NATIVE_MODEL.md
topics: roadmap, models, provenance, registry, security
tokens: 19
---
Register every source with rights, license, consent, privacy, retention, and content-hash decisions.
---END-PLANS-EVENT-#002---

---BEGIN-PLANS-EVENT-#003---
id: plans:003
date: 2026-08-12T18:00:05Z
agent: codex
kind: roadmap-item
item: roadmap:track:T:eval:independent-grader-v1
event: planned
supersedes: none
origin: none
depends-on: roadmap:track:T:data:contract-v1
gate: A different model family grades blinded arms, replay is stable on a sealed set, and disagreements remain explicit.
outcome: none
verification: none
refs: docs/roadmap/SEAM_NATIVE_MODEL.md
topics: roadmap, models, judge, benchmark, quality
tokens: 19
---
Build blinded cross-model grading with deterministic checks, calibration, disagreement routing, and skeptical failure analysis.
---END-PLANS-EVENT-#003---

---BEGIN-PLANS-EVENT-#004---
id: plans:004
date: 2026-08-12T18:00:06Z
agent: codex
kind: roadmap-item
item: roadmap:track:T:data:generator-core-v1
event: planned
supersedes: none
origin: none
depends-on: roadmap:track:T:data:contract-v1,roadmap:track:T:data:source-registry-v1
gate: Repeated generation emits the same content and manifest hashes with zero silent drops.
outcome: none
verification: none
refs: docs/roadmap/SEAM_NATIVE_MODEL.md
topics: roadmap, models, provenance, scripts, integrity
tokens: 13
---
Build deterministic versioned source adapters and transformation lineage for candidate examples.
---END-PLANS-EVENT-#004---

---BEGIN-PLANS-EVENT-#005---
id: plans:005
date: 2026-08-12T18:00:07Z
agent: codex
kind: roadmap-item
item: roadmap:track:T:data:pretrain-view-v1
event: planned
supersedes: none
origin: none
depends-on: roadmap:track:T:data:generator-core-v1
gate: The view parses, tokenizes reproducibly, retains source closure, and contains zero known holdout rows.
outcome: none
verification: none
refs: docs/roadmap/SEAM_NATIVE_MODEL.md
topics: roadmap, models, provenance, tokenizer
tokens: 15
---
Emit a tokenizer-ready pretraining view from admitted sources without evaluation leakage.
---END-PLANS-EVENT-#005---

---BEGIN-PLANS-EVENT-#006---
id: plans:006
date: 2026-08-12T18:00:08Z
agent: codex
kind: roadmap-item
item: roadmap:track:T:data:training-view-v1
event: planned
supersedes: none
origin: none
depends-on: roadmap:track:T:data:generator-core-v1
gate: Every trajectory validates against its task schema and cites complete admitted evidence.
outcome: none
verification: none
refs: docs/roadmap/SEAM_NATIVE_MODEL.md
topics: roadmap, models, provenance, retrieval, agent
tokens: 22
---
Emit SFT, tool, retrieval, provenance, abstention, contradiction, and embodied training trajectories.
---END-PLANS-EVENT-#006---

---BEGIN-PLANS-EVENT-#007---
id: plans:007
date: 2026-08-12T18:00:09Z
agent: codex
kind: roadmap-item
item: roadmap:track:T:data:quality-splits-v1
event: planned
supersedes: none
origin: none
depends-on: roadmap:track:T:data:pretrain-view-v1,roadmap:track:T:data:training-view-v1,roadmap:track:T:eval:independent-grader-v1
gate: Manifest replay is exact, cross-split duplicate groups are zero, and sealed holdouts remain isolated.
outcome: none
verification: none
refs: docs/roadmap/SEAM_NATIVE_MODEL.md
topics: roadmap, models, provenance, benchmark, security, quality
tokens: 18
---
Add deduplication, immutable split assignment, contamination, privacy, and quality admission gates.
---END-PLANS-EVENT-#007---

---BEGIN-PLANS-EVENT-#008---
id: plans:008
date: 2026-08-12T18:00:10Z
agent: codex
kind: roadmap-item
item: roadmap:track:T:model:250k
event: planned
supersedes: none
origin: none
depends-on: roadmap:track:T:data:quality-splits-v1
gate: The approximately 250K model beats a declared heuristic and resource baseline under independent grading.
outcome: none
verification: none
refs: docs/roadmap/SEAM_NATIVE_MODEL.md
topics: roadmap, models, benchmark, agent
tokens: 16
---
Train one bounded SEAM-micro specialist only after its admitted dataset slice exists.
---END-PLANS-EVENT-#008---

---BEGIN-PLANS-EVENT-#009---
id: plans:009
date: 2026-08-12T18:00:11Z
agent: codex
kind: roadmap-item
item: roadmap:track:T:model:1b
event: blocked
supersedes: none
origin: none
depends-on: roadmap:track:T:model:250k,roadmap:track:T:eval:independent-grader-v1
gate: The 1B model passes provenance, abstention, category non-regression, efficiency, and contamination gates.
outcome: none
verification: none
refs: docs/roadmap/SEAM_NATIVE_MODEL.md
topics: roadmap, models, benchmark, agent, provenance
tokens: 20
---
Build the first SEAM-aware language rung after the 250K evidence and curriculum gates pass.
---END-PLANS-EVENT-#009---

---BEGIN-PLANS-EVENT-#010---
id: plans:010
date: 2026-08-12T18:00:12Z
agent: codex
kind: roadmap-item
item: roadmap:track:T:model:4b
event: blocked
supersedes: none
origin: none
depends-on: roadmap:track:T:model:1b
gate: The 4B model improves declared capabilities without provenance, contamination, or category regressions.
outcome: none
verification: none
refs: docs/roadmap/SEAM_NATIVE_MODEL.md
topics: roadmap, models, benchmark, agent, provenance
tokens: 24
---
Scale to the native 4B rung only when the 1B results prove a measured capability or efficiency need.
---END-PLANS-EVENT-#010---

---BEGIN-PLANS-EVENT-#011---
id: plans:011
date: 2026-08-12T18:00:13Z
agent: codex
kind: roadmap-item
item: roadmap:track:U:vision:tab-a7-v1
event: planned
supersedes: none
origin: none
depends-on: roadmap:track:T:data:contract-v1
gate: Frames reconnect and remain attributable with visible permission, calibration, privacy, and camera-off behavior.
outcome: none
verification: none
refs: docs/roadmap/SEAM_ESP32_EMBODIED_SPATIAL.md
topics: roadmap, agent, provenance, surface, models
tokens: 21
---
Qualify the Galaxy Tab A7 as the agent's attributable visual head and choose its transport by measurement.
---END-PLANS-EVENT-#011---

---BEGIN-PLANS-EVENT-#012---
id: plans:012
date: 2026-08-12T18:00:14Z
agent: codex
kind: roadmap-item
item: roadmap:track:U:sensing:esp32s3-3node-v1
event: planned
supersedes: none
origin: none
depends-on: roadmap:track:T:data:contract-v1
gate: All three nodes produce restart-safe attributable observations and recover from loss or recalibration.
outcome: none
verification: none
refs: docs/roadmap/SEAM_ESP32_EMBODIED_SPATIAL.md
topics: roadmap, agent, provenance, models, test
tokens: 26
---
Inventory, identify, ingest, calibrate, and qualify exactly three ESP32-S3 sensing nodes A, B, and C.
---END-PLANS-EVENT-#012---

---BEGIN-PLANS-EVENT-#013---
id: plans:013
date: 2026-08-12T18:00:15Z
agent: codex
kind: roadmap-item
item: roadmap:track:U:fusion:a7-3node-v1
event: blocked
supersedes: none
origin: none
depends-on: roadmap:track:U:vision:tab-a7-v1,roadmap:track:U:sensing:esp32s3-3node-v1
gate: Fusion yields measured gain, preserves disagreements, and retains complete per-source lineage.
outcome: none
verification: none
refs: docs/roadmap/SEAM_ESP32_EMBODIED_SPATIAL.md
topics: roadmap, agent, provenance, graph, models, benchmark
tokens: 19
---
Fuse Tab A7 vision with the fixed three-node sensing array only after both sources qualify separately.
---END-PLANS-EVENT-#013---

---BEGIN-PLANS-EVENT-#014---
id: plans:014
date: 2026-08-12T18:00:16Z
agent: codex
kind: roadmap-item
item: roadmap:track:S:S6
event: planned
supersedes: none
origin: none
depends-on: roadmap:track:S:S5
gate: Principal propagation, principal-derived namespaces, opaque deletion, and two-principal denial/privacy/idempotence all pass.
outcome: none
verification: none
refs: docs/roadmap/MEMORY_GUARANTEES_CAMPAIGN.md,docs/audits/2026-08-10-track-s-visual-status-report.md
topics: roadmap, storage, security, provenance, test
tokens: 21
---
Reconciled and parked: resume principal tenancy and opaque deletion only when Track S work is authorized.
---END-PLANS-EVENT-#014---

---BEGIN-PLANS-EVENT-#015---
id: plans:015
date: 2026-08-12T18:00:17Z
agent: codex
kind: roadmap-item
item: roadmap:track:S:S7
event: blocked
supersedes: none
origin: none
depends-on: roadmap:track:S:S6
gate: All S7 exit evidence in the campaign contract passes on an exact head.
outcome: none
verification: none
refs: docs/roadmap/MEMORY_GUARANTEES_CAMPAIGN.md
topics: roadmap, graph, provenance, retrieval, test
tokens: 15
---
Semantic ingest, temporal reconciliation, and entity qualification remain blocked behind S6.
---END-PLANS-EVENT-#015---

---BEGIN-PLANS-EVENT-#016---
id: plans:016
date: 2026-08-12T18:00:18Z
agent: codex
kind: roadmap-item
item: roadmap:track:S:S8
event: blocked
supersedes: none
origin: none
depends-on: roadmap:track:S:S6,roadmap:track:S:S7
gate: All S8 surface-parity, replay, identity, and tenant-event gates pass.
outcome: none
verification: none
refs: docs/roadmap/MEMORY_GUARANTEES_CAMPAIGN.md
topics: roadmap, retrieval, graph, provenance, test
tokens: 16
---
One retrieval engine and coherent fusion qualification remain blocked behind S6 and S7.
---END-PLANS-EVENT-#016---

---BEGIN-PLANS-EVENT-#017---
id: plans:017
date: 2026-08-12T18:00:19Z
agent: codex
kind: roadmap-item
item: roadmap:track:S:S9
event: blocked
supersedes: none
origin: none
depends-on: roadmap:track:S:S8
gate: The frozen candidate passes overall and every category gate with independent reproducible evidence.
outcome: none
verification: none
refs: docs/roadmap/MEMORY_GUARANTEES_CAMPAIGN.md,HISTORY#509
topics: roadmap, retrieval, benchmark, judge, verify
tokens: 17
---
Provider-free retrieval and semantic qualification remains open after a measured category non-regression failure.
---END-PLANS-EVENT-#017---

---BEGIN-PLANS-EVENT-#018---
id: plans:018
date: 2026-08-12T18:00:20Z
agent: codex
kind: roadmap-item
item: roadmap:track:S:S10
event: blocked
supersedes: none
origin: none
depends-on: roadmap:track:S:S6,roadmap:track:S:S7,roadmap:track:S:S8,roadmap:track:S:S9
gate: The frozen candidate passes every release, artifact, privacy, continuity, review, and required-CI gate.
outcome: none
verification: none
refs: docs/roadmap/MEMORY_GUARANTEES_CAMPAIGN.md
topics: roadmap, ci, verify, security, integrity
tokens: 15
---
Required CI and release qualification remain blocked until S6 through S9 finish.
---END-PLANS-EVENT-#018---

---BEGIN-PLANS-EVENT-#019---
id: plans:019
date: 2026-08-12T20:30:38.294859Z
agent: codex
kind: roadmap-item
item: roadmap:track:S:S6
event: blocked
supersedes: plans:014
origin: none
depends-on: roadmap:track:S:S5
gate: Principal propagation, principal-derived namespaces, opaque deletion, and two-principal denial/privacy/idempotence all pass.
outcome: none
verification: none
refs: docs/roadmap/MEMORY_GUARANTEES_CAMPAIGN.md,docs/audits/2026-08-10-track-s-visual-status-report.md
topics: roadmap, storage, security, provenance, test
tokens: 23
---
Reconciled and dependency-ready, but explicitly parked by the operator for this session; do not start Track S.
---END-PLANS-EVENT-#019---

---BEGIN-PLANS-EVENT-#020---
id: plans:020
date: 2026-08-12T20:40:25.418152Z
agent: codex
kind: roadmap-item
item: roadmap:track:U:voice:tab-a7-v1
event: planned
supersedes: none
origin: none
depends-on: roadmap:track:T:data:contract-v1
gate: Push-to-talk voice turns remain attributable, interruptible, privacy-bounded, and usable across reconnect with measured ASR/TTS latency and uncertainty.
outcome: none
verification: none
refs: docs/roadmap/SEAM_ESP32_EMBODIED_SPATIAL.md
topics: roadmap, agent, provenance, surface, models
tokens: 30
---
Qualify the Tab A7 microphone and speaker as the initial agent voice path, with replaceable ASR/TTS and no default always-on recording.
---END-PLANS-EVENT-#020---
