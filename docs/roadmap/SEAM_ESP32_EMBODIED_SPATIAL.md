# SEAM ESP32-S3 Embodied / Spatial Edge Architecture

**Status:** Active research roadmap; implementation and measurements must be qualified separately
**Added:** 2026-08-12
**Scope:** ESP32-S3 edge sensing, Wi-Fi CSI, spatial memory, sensor fusion, SEAM-native world modeling, Dream Mode, EPOC, and embodied-agent dogfooding

## Purpose

The ESP32-S3 work is a SEAM architecture track, not a standalone hardware experiment. The goal is to give a persistent SEAM-backed agent a low-power physical-world observation layer while the core SEAM runtime continues its memory, retrieval, provenance, and benchmark work.

The end state is a local-first embodied system in which distributed ESP32-S3 nodes collect attributable observations, SEAM turns those observations into persistent temporal/spatial memory, and an agent can query and reason over that world model without losing the evidence chain that produced it.

This track must remain measurement-first. Presence, motion, zone state, trajectories, identity, affective interpretation, and dream-derived hypotheses are different claim classes and must not be collapsed into one another.

## Fixed Initial System Contract

The first embodied agent is one persistent agent with four observation devices:

```text
Galaxy Tab A7 camera (the agent's eyes)
Galaxy Tab A7 mic/speaker (the agent's voice)
                 \
ESP32-S3 node A ---\
ESP32-S3 node B ----> Linux edge host -> SEAM -> one executive agent
ESP32-S3 node C ---/
```

- The **Galaxy Tab A7** is the primary visual-observation producer and mobile
  voice/interaction surface. It is not a second agent and is not durable truth.
- The deployed sensing array is **exactly three ESP32-S3 nodes**, identified as
  A, B, and C. Individual bring-up may use one board at a time, but an expanded
  deployed array is not part of this contract.
- The Linux host owns normalization, durable persistence, model execution that
  does not fit the edge, and SEAM provenance.
- Every fused claim must retain separate A7 and node-level evidence. Agreement
  may raise confidence; disagreement must remain visible.

The A7 transport is deliberately not selected here. ADB capture, a local app,
RTSP, or WebRTC remain implementation candidates until a short transport spike
measures latency, frame attribution, reconnect behavior, privacy controls, and
offline operation.

The initial voice path uses the A7 microphone and speaker. ASR, TTS, wake-word
or push-to-talk behavior, and transport remain replaceable components selected
by measurement rather than treated as agent identity.

```text
PHYSICAL WORLD
    |
    v
ESP32-S3 SENSOR / CSI NODES
    |
    +-- Wi-Fi CSI / RSSI / timing
    +-- optional cheap sensors
    +-- local filtering / feature extraction
    +-- node clock + device identity
    |
    v
EDGE INGEST (Linux / SEAM host)
    |
    +-- receive raw observations
    +-- normalize timestamps
    +-- preserve device/source IDs
    +-- attach calibration state
    +-- retain raw evidence where required
    |
    v
SEAM MEMORY + PROVENANCE
    |
    +-- temporal events
    +-- spatial observations
    +-- derived features
    +-- confidence / uncertainty
    +-- source lineage
    |
    v
SPATIAL WORLD MODEL
    |
    +-- occupancy
    +-- zones
    +-- motion
    +-- transitions
    +-- trajectories
    +-- fused identity/state
    |
    v
AGENT / SEAM-NATIVE MODEL
```

## Hardware Direction

The current development pool is based on ESP32-S3 boards, including R8/R16-class variants already acquired for experimentation. Exact flash/PSRAM capabilities must be probed from each board rather than inferred from seller naming.

Initial bring-up requires only the boards, data-capable USB cables, and the Linux host. Sensors, SD cards, external power, and permanent enclosures are later-stage additions rather than prerequisites for first communication and CSI experiments.

### Node-count strategy

Bring up each board independently before qualifying the fixed three-node array:

```text
node A      -> firmware + transport + provenance bring-up
nodes A/B/C -> spatial / CSI geometry, redundancy, and fusion experiments
```

The three-node qualification must include node-loss, placement-change,
interference, and recalibration tests. Spare boards may be used only as
replacements or isolated A/B firmware controls; they do not silently expand the
deployed topology.

## Architectural Roles

### ESP32-S3 nodes

Nodes are low-power perception endpoints. Their initial responsibilities are intentionally narrow:

- acquire CSI/RSSI/timing/sensor observations
- attach node identity and local timestamp
- perform lightweight filtering or aggregation when measured useful
- transmit observations to the SEAM host
- expose health / calibration metadata
- optionally run tiny specialist models later

They are not the source of durable semantic truth. The node observes; SEAM records, derives, qualifies, and links.

### SEAM edge host

The Linux edge host is the first authoritative aggregation point:

- serial / USB / Wi-Fi ingest
- clock normalization and ordering
- raw evidence retention policy
- calibration registry
- feature extraction
- provenance creation
- temporal and spatial persistence
- world-model updates
- agent query surface

The host should continue operating locally even if an external model provider is unavailable.

### Galaxy Tab A7 visual head

The Tab A7 is the agent's eyes. Each admitted visual observation must include:

- stable device and camera identifiers
- capture and host-receive timestamps
- frame or clip content hash and sequence/span identifiers
- camera configuration, orientation, and calibration version
- transport and transform versions
- permission state and a visible capture indicator
- retention class and links to every derived observation

Camera bytes are evidence, not conclusions. Object, person, activity, and
spatial labels remain typed observations or inferences with confidence and
lineage. Capture must default off when permission, visibility, or retention
policy cannot be proved.

### Galaxy Tab A7 voice head

The A7 supplies the initial microphone and speaker path. The voice loop is:

```text
visible push-to-talk or qualified wake trigger
    -> bounded audio segment
    -> ASR with timestamps/confidence
    -> agent turn + SEAM context/tools
    -> response text
    -> TTS + interrupt/cancel control
```

Each admitted voice turn records device ID, segment/span ID, capture and
receive timestamps, ASR/TTS engine and revision, language, confidence, consent
mode, and links among audio, transcript, agent action, and response. Raw audio
defaults to short retention or no retention; a transcript never silently
becomes ground truth when ASR confidence or speaker attribution is uncertain.
Always-on recording is not the starting mode. The first qualification uses a
visible push-to-talk path, with wake-word operation considered only after
false-trigger, privacy, offline, and resource tests.

### Executive agent

The executive agent sits above the world model. A DeepAgents-style executive remains a useful candidate for tool orchestration, but the architecture must not bind SEAM to one agent framework.

The agent should be able to ask questions such as:

```text
spatial_query(room)
world_state(person_or_object)
timeline(zone)
trace(spatial_claim_id)
verify(spatial_claim_id)
```

Voice, the A7 display/microphone/camera, and future movement/actuation are
consumers or producers of the same memory/provenance substrate, not separate
memory systems.

## Observation Pipeline

The first useful implementation should prove the boring pipeline before attempting rich inference.

```text
ESP32-S3
   |
   v
USB / serial / Wi-Fi transport
   |
   v
host receive timestamp
   |
   +-- node ID
   +-- firmware version
   +-- local timestamp / sequence
   +-- observation type
   +-- calibration ID
   |
   v
raw observation store
   |
   v
normalized observation
   |
   v
feature extraction
   |
   v
derived spatial state
   |
   v
SEAM provenance graph
```

Every stage should be inspectable. A spatial conclusion must be traceable backward to the contributing node observations and the exact derivation/calibration version.

## Wi-Fi CSI Spatial Track

Wi-Fi CSI is the primary non-camera spatial sensing experiment. The initial goal is not "see through walls" or photorealistic RF reconstruction. The goal is to determine which repeatable spatial signals can be extracted from the actual ESP32-S3 array in the actual environment.

### CSI processing ladder

```text
CSI acquisition
    -> packet validation
    -> timestamp alignment
    -> per-node calibration
    -> normalization
    -> baseline / environmental reference
    -> denoising
    -> feature extraction
    -> temporal windows
    -> classification / regression
    -> multi-node fusion
    -> SEAM spatial state
```

Candidate features can include amplitude/phase-derived statistics, variance, motion-sensitive deltas, temporal frequency components, cross-node agreement, and learned embeddings. Feature choice must be benchmarked rather than frozen in advance.

### Calibration

Calibration is first-class state, not a setup note.

SEAM should retain:

- node placement / orientation
- firmware version
- radio configuration
- channel / bandwidth
- reference environment state
- calibration start/end time
- calibration dataset IDs
- calibration algorithm/version
- invalidation reason when the environment changes

A model result produced under calibration `C1` must not silently be compared with a result under `C2` as if the sensing geometry were unchanged.

### Capability ladder

Advance only when the previous level has measurable evidence:

1. **Presence / occupancy** — distinguish empty versus occupied regions.
2. **Coarse zones** — classify which predefined region is occupied.
3. **Motion state** — static / moving / transition-like behavior.
4. **Zone transitions** — detect movement between grounded zones.
5. **Rough trajectories** — reconstruct coarse ordered movement paths.
6. **Multi-node sensor fusion** — quantify improvement over a single node.
7. **Grounded identity** — associate observations with a known person/object only when explicit ground truth supports it.
8. **Persistent object/location state** — keep state across time with decay and re-observation.
9. **Richer spatial inference / 3D world model** — only after the simpler tasks justify the added complexity.

## Candidate Architectural References

Two open-source Wi-Fi spatial-sensing projects have been identified as candidate architectural references:

- **RuView**
- **WiFi-3D-Fusion**

The exact starred repository/source should be verified before copying any implementation assumption. These are blueprints to study for architecture, CSI acquisition, calibration, spatial inference, visualization, and sensor fusion—not dependencies that define SEAM's design.

The intended approach is to extract useful patterns and then build a SEAM-native implementation around provenance, durable state, temporal continuity, and agent queryability.

## Sensor Fusion

CSI should not become a single-sensor monoculture. The long-term embodied layer can fuse:

- Wi-Fi CSI
- RSSI / radio metadata
- timing
- inexpensive motion/environment sensors
- camera-derived observations when explicitly enabled
- agent/tool observations
- user-confirmed ground truth

Fusion must retain per-source lineage. A fused state is a derived record whose parent observations remain queryable.

```text
CSI -----------\
RSSI -----------\
sensors ----------> fusion -> spatial state -> SEAM world graph
camera ----------/
user truth ------/
```

When sources disagree, SEAM should represent disagreement and confidence rather than force a single unsupported answer.

## Spatial World Model

The world model should be incremental and temporal rather than rebuilt as a decorative 3D scene.

```text
occupancy
   -> zones
   -> motion
   -> transitions
   -> trajectories
   -> grounded entities
   -> persistent state
   -> confidence decay
   -> re-observation / correction
```

Candidate node/entity classes include:

- `sensor_node`
- `physical_zone`
- `spatial_observation`
- `motion_event`
- `trajectory_segment`
- `grounded_entity`
- `location_state`
- `calibration_state`
- `sensor_fusion_result`

Useful relation examples:

- `observed_by`
- `located_in`
- `transitioned_to`
- `derived_from`
- `calibrated_under`
- `corroborated_by`
- `contradicted_by`
- `supersedes`

Screen position, visualization proximity, or inferred graph layout must never be mistaken for recorded spatial truth.

## Provenance Contract

A derived spatial claim should retain at minimum:

```text
claim_id
claim_class
value / state
confidence
created_at
valid_from / valid_to
source_node_ids
raw_observation_ids
calibration_id
feature_pipeline_version
model / classifier version
derivation parameters
parent claim IDs
verification status
```

Derived-state classes should continue to distinguish `observed_fact`, `inferred_state`, `prediction`, `dream_hypothesis`, and `agent_action`.

The provenance goal is that an operator can ask "why does SEAM think someone moved from zone A to zone B?" and inspect the exact contributing evidence.

## SEAM-µ / Tiny Edge Models

A small SEAM specialist model track can eventually move simple decisions toward the edge.

The initial concept is **SEAM-µ**, beginning around the experimental ~250K-parameter scale and growing only when measurements justify it. Candidate tasks include:

- salience / novelty
- event deduplication
- observation routing
- anomaly detection
- coarse presence / zone classification
- confidence estimation
- deciding what raw data deserves transmission or retention

The broader model ladder discussed for the research program is approximately:

```text
SEAM-µ ~250K
    -> 1B
    -> 4B
```

This is a gated research ladder, not a release commitment. The ~250K rung is a
bounded specialist/proof model, 1B is the first SEAM-aware language rung, and
4B is the scaled native rung. No rung advances merely because a parameter-count
target is reachable. MCU deployment depends on actual memory, quantization,
operator needs, and latency/energy measurements.

## Hierarchical Compute / Memory

The embodied system should treat compute and memory as tiers:

```text
ESP32 SRAM
   -> ESP32 PSRAM
   -> ESP32 flash / optional local storage
   -> edge Linux RAM
   -> edge SSD/NVMe
   -> workstation GPU/RAM
   -> durable SEAM store
```

SEAM should learn or encode policies for:

- raw retention versus feature-only retention
- local versus host-side feature extraction
- novelty-triggered upload
- state-transition-triggered persistence
- migration between hot and cold memory
- reprocessing when classifiers improve

A raw observation can be deleted only under an explicit retention policy; lineage should record when a derived record outlives its raw payload.

## Dream Mode Integration

Dream Mode can use embodied memory for offline consolidation, but it must never rewrite hypotheses into facts.

Potential spatial Dream Mode jobs:

- replay unusual trajectories
- cluster recurring occupancy patterns
- discover repeated zone transitions
- identify calibration drift candidates
- search for cross-sensor contradictions
- propose better spatial features
- generate hypotheses about routines or object state
- compress repetitive episodes into semantic patterns

```text
recorded spatial episodes
      |
      v
Dream replay / activation
      |
      +-- pattern discovery
      +-- contradiction search
      +-- counterfactual simulation
      +-- hypothesis generation
      |
      v
dream_hypothesis records
      |
      v
future observation / verification
```

Dream outputs require their own cycle IDs, parent memories, activation paths, confidence, and promotion history if later confirmed.

## EPOC Integration

Embodied context may feed the EPOC affective-semantic state, but sensor interpretation cannot override factual/provenance boundaries.

Possible embodied inputs include:

- novelty
- uncertainty
- environmental change
- repeated failed predictions
- proximity / social relevance when grounded
- resource pressure / device health

EPOC can then modulate retrieval, exploration, verification budget, dream replay priority, or salience. It must remain bounded, decay toward baseline, and avoid self-reinforcing loops.

Affective state is derived agent state, not a claim that the hardware "feels" an emotion.

## Continuous Agent / Dogfooding Target

The embodied system is intended to become a real dogfooding environment for persistent agents.

Long-term target:

```text
Galaxy Tab A7 vision / voice / display
          |
          v
executive agent
          |
   +------+------+
   |             |
SEAM memory   live tools
   |             |
   +------v------+
      world model
          |
     ESP32 array
```

The agent should persist for long periods, observe through explicit tools/sensors, answer questions about its recent environment, remember changes, and continue consolidating memory between conversations.

"Thinking between conversations" should be implemented as explicit scheduled/idle processes such as consolidation, replay, evaluation, and hypothesis generation—not as an unverifiable claim of continuous hidden cognition.

## Planned Extensions Not Yet Demonstrated

The following ideas remain roadmap items until implemented and measured:

- fixed three-node array failure, placement, and recalibration qualification
- Galaxy Tab A7 primary visual-agent surface
- Galaxy Tab A7 microphone/speaker voice loop
- A7 camera + three-node CSI + cheap-sensor fusion
- persistent self-state connected to EPOC
- stochastic cognition / exploration experiments
- synthetic spatial training-data generation
- SEAM-µ edge inference
- persistent 3D/world reconstruction
- autonomous Dream Mode spatial consolidation
- long-duration dogfooding runs measured over weeks/months
- wiki/database surfaces exposing embodied experiments and provenance

These should be documented as planned or experimental rather than shipped capability.

## Experiment Sequence

### E0 — Board inventory and bring-up

- enumerate every ESP32-S3
- record chip revision, flash, PSRAM, MAC/device ID, firmware build
- verify data-capable USB communication
- assign stable SEAM node IDs

**Gate:** all intended nodes can report identity and heartbeat reproducibly.

### E1 — Transport and raw ingest

- stream structured events by USB/serial first
- add Wi-Fi transport only after the schema is stable
- timestamp on node and host
- persist raw observations into SEAM with provenance

**Gate:** events survive restart and remain attributable to the correct node/firmware.

### E2 — Time / calibration discipline

- measure clock drift
- normalize ordering
- create calibration records
- detect stale calibration

**Gate:** repeated static tests produce bounded variance under a declared calibration.

### E3 — Single-node CSI characterization

- capture empty-room and occupied-room baselines
- quantify packet loss/noise
- compare feature candidates

**Gate:** reproducible separation above a predeclared baseline, not a visual anecdote.

### E4 — Three-node occupancy and zones

- establish fixed geometry
- collect grounded labels
- test occupancy and zone classification

**Gate:** holdout metrics exceed the declared baseline and survive repeated sessions.

### E5 — Motion and transitions

- collect static/moving/transition sequences
- model temporal windows
- store transition evidence and confidence

**Gate:** transition detection is temporally stable and traceable.

### E6 — Rough trajectory reconstruction

- infer ordered zone/position paths
- measure path/trajectory error
- compare single-node versus fused performance

**Gate:** fusion provides a measurable gain or is rejected as unnecessary complexity.

### E7 — Three-node resilience and recalibration

- keep the deployed topology fixed at nodes A/B/C
- test one-node loss, placement changes, interference, and recalibration
- benchmark bandwidth / CPU / storage

**Gate:** the three-node array preserves attributable degraded operation and
returns to its declared baseline after replacement or recalibration.

### E8 — Multimodal sensor fusion

- add Tab A7 camera observations under explicit visible configuration
- add cheap sensors only when they answer a declared measurement question
- compare CSI-only versus fused state

**Gate:** quantify fusion gain and disagreement handling while preserving
complete per-source lineage and a privacy-safe camera-off mode.

### E9 — SEAM-µ

- distill one bounded classifier/routing task
- compare MCU/host latency, energy, accuracy, and bandwidth

**Gate:** edge inference wins on an explicit resource or quality metric.

### E10 — Dream Mode + EPOC experiments

- replay embodied episodes offline
- generate strictly typed hypotheses
- measure contamination and verification rates
- test bounded affective modulation

**Gate:** no dream-to-fact leakage and no factual corruption from EPOC modulation.

### E11 — Continuous agent dogfooding

- Tab A7 visual, microphone/speaker voice, and display access
- interruption, cancel, reconnect, and uncertain-transcript behavior
- persistent world-state questions
- long-duration operation
- recovery from node/network/provider failures

**Gate:** the system can explain what it knows, what it inferred, what it does not know, and why.

## Metrics

Track at minimum:

### Sensing
- packet/event loss
- calibration drift
- occupancy precision/recall
- zone accuracy
- transition F1
- trajectory error
- false identity rate

### Fusion
- single-node versus multi-node gain
- CSI-only versus multimodal gain
- disagreement rate
- confidence calibration

### Persistence / provenance
- source attribution accuracy
- lineage completeness
- replay reproducibility
- temporal ordering errors
- stale-state rate

### Efficiency
- bytes per observation
- useful-memory / raw-observation ratio
- edge CPU / RAM / PSRAM
- host CPU / storage
- bandwidth per node
- energy per event / inference where measurable
- retrieval latency for world-state queries

### Dream / EPOC
- hypothesis verification rate
- dream-to-fact contamination rate
- contradiction discovery rate
- state boundedness / baseline recovery
- retrieval/planning changes without factual accuracy loss

## Security / Privacy Boundary

The intended spatial research is local-first and observation-oriented.

- keep network credentials out of committed artifacts
- assign non-secret stable node IDs separately from secrets
- authenticate mutating/control channels as the system matures
- retain raw radio/camera data only under an explicit policy
- make camera use visible and configurable
- separate sensing from active radio interference
- log firmware/calibration changes
- treat physical sensor data as sensitive provenance-bearing records

The architecture should not require cloud upload to maintain spatial memory.

## Relationship to Core SEAM

The embodied branch must not derail core memory-runtime validation. Core SEAM continues benchmarking, retrieval/provenance hardening, and production work while this track develops behind explicit interfaces.

```text
                 CORE SEAM
        memory / graph / provenance
                 /      \
                /        \
      benchmarks          embodied track
   Mem0/Zep/Hindsight      ESP32 / CSI
                \        /
                 \      /
              shared runtime
```

When embodied components produce generally useful primitives—provenance schemas, temporal state, confidence decay, world-state queries, tiny routing models—they should graduate into core only after tests and review.

## Definition of Success

The first meaningful success is not a 3D demo. It is a provenance-backed local system that can reliably answer grounded questions such as:

- Is the observed zone occupied?
- Which zone changed?
- Was there a transition?
- What evidence caused that state update?
- How confident is the system?
- Which nodes agreed or disagreed?
- When was the last direct observation?
- Is this a recorded fact, an inference, or a Dream Mode hypothesis?

From there, SEAM can climb toward persistent trajectories, multimodal world models, embodied agent memory, and eventually a SEAM-native model that treats physical-world memory as a first-class computational substrate.
