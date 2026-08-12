# SEAM Native Model End-State Roadmap

**Status:** Active long-horizon architecture target
**Added:** 2026-08-10
**Scope:** Native model, provenance, affective semantics, dream consolidation, embodied/spatial memory

## End Goal

SEAM's end goal is not only to be a memory backend for third-party LLMs. The long-term target is a language model built from the ground up to use SEAM as a native memory substrate as efficiently and routinely as current models use RAG/tool-retrieval systems, while preserving 100% provenance for any memory-derived claim.

The target model should treat SEAM memory as a first-class computational resource rather than as prompt text bolted onto inference.

```text
USER / WORLD
    |
    v
PERCEPTION + EVENTS
    |
    v
SEAM MEMORY SUBSTRATE
    |-- episodic
    |-- semantic
    |-- temporal
    |-- spatial
    |-- relational
    |-- affective
    |-- provenance graph
    |
    v
SEAM-NATIVE LLM
    |-- retrieval policy
    |-- graph activation
    |-- source selection
    |-- uncertainty
    |-- planning
    |-- reasoning
    |
    v
ANSWER / ACTION
    |
    v
TRACEABLE DERIVATION
```

## Non-Negotiable Provenance Invariant

Every memory-derived answer, belief update, spatial conclusion, dream-derived hypothesis, affective update, or action recommendation must be traceable back to its evidence.

SEAM should be able to reconstruct:

```text
raw observation
    -> append-only RAW record + provenance anchor
       |-> SEAM-RC/1 exact-source representation
       `-> canonical MIRL / IR record
    -> graph nodes + edges
    -> retrieval / activation path
    -> transformations
    -> model reasoning context
    -> output claim
```

SEAM-RC/1 certifies the exact source text on the RAW side of the boundary; it
must never certify reconstructed canonical text. Canonical MIRL/IR is a sibling
derivation from the same anchored observation, not an input to RC/1. The system
may summarize, consolidate, compress, infer, and dream, but RAW remains
append-only and every derived product must retain lineage back to that immutable
evidence.

### Derived-state classes

SEAM must distinguish at minimum:

- `observed_fact`
- `reported_fact`
- `inferred_state`
- `semantic_consolidation`
- `dream_hypothesis`
- `counterfactual`
- `prediction`
- `affective_state`
- `agent_action`

Derived records must retain parent record IDs, derivation method, model/runtime version, timestamp, confidence, and verification status.

## Native Memory Interface

The eventual model should not require SEAM to serialize its entire memory into natural-language prompt context. The model should learn to call or directly consume compact SEAM-native memory operations.

Every primitive executes under an authenticated principal/capability context.
For hosted use, the runtime derives namespace and scope from that binding;
caller-selected namespace text is never an identity boundary. Reads, writes,
traces, and actions are attributed to the same context. Track S6 decides
whether the binding terminates at a trusted proxy or inside the runtime, but no
native-model surface may claim multi-tenant safety before that boundary exists.

Target primitives:

```text
recall(context, query)
activate(context, node, depth, budget)
world_state(context, entity)
timeline(context, entity | interval)
spatial_query(context, region | entity)
relationship_state(context, entity_a, entity_b)
trace(context, memory_id | claim_id)
verify(context, claim_id)
store(context, observation)
consolidate(context, derived_scope)
```

Long-term research should compare three integration levels:

1. **Tool-level SEAM** — existing LLM calls SEAM like a RAG/tool backend.
2. **Adapter-level SEAM** — model-specific memory adapters expose compact structured SEAM state during inference.
3. **Native SEAM model** — model is trained from the beginning to retrieve, interpret, weight, and cite SEAM graph memory as part of its normal reasoning process.

The end state is level 3.

## Semantic / Affective Engine (EPOC Track)

SEAM should support a dynamic semantic-affective control system provisionally referred to as **EPOC**. EPOC is not a cosmetic emotion-label layer. It is a persistent state system driven by context, memory activation, graph relationships, prediction error, goals, uncertainty, and embodied/system observations.

Until the EPOC acronym/schema is formally defined, treat this as an architectural track rather than a frozen protocol.

### Affective state

Represent state as a bounded multidimensional vector rather than a single emotion label. Candidate dimensions include:

- valence
- arousal
- control / agency
- uncertainty
- novelty
- threat
- curiosity
- frustration
- confidence
- attachment / social relevance
- fatigue / resource pressure

Named emotions, if exposed, should be interpretations of regions in this state space rather than primary stored truth.

### Cognitive modulation

EPOC may modulate:

- graph activation thresholds
- retrieval weighting
- novelty weighting
- exploration budget
- verification budget
- planning depth
- retry / strategy-switch thresholds
- consolidation priority
- dream replay priority
- memory salience

EPOC must never override provenance, factual truth, safety policy, or immutable operator constraints.

### Homeostasis

Affective state must include:

- bounded values
- inertia
- accumulation
- decay
- saturation
- regulation
- baseline recovery
- anti-runaway feedback

Negative or positive memories must not create uncontrolled self-reinforcing retrieval loops.

## Dream Mode

Dream Mode is an offline consolidation and simulation process, not a narrative-generation feature.

```text
idle / low external demand
        |
        v
memory replay
        |
        v
spreading activation
        |
        v
association discovery
        |
        v
counterfactual simulation
        |
        v
schema / semantic consolidation
        |
        v
hypothesis creation
        |
        v
provenance-preserving graph updates
```

Dream-derived outputs must be stored separately from observations and verified facts.

Required metadata for dream-derived records:

- dream cycle ID
- source memories
- activation path
- derivation method
- confidence
- MIRL `status=hypothetical`
- verification verdict and evidence in controlled attributes or a linked PROV record
- promotion history if later confirmed

`verified` and `unverified` are not MIRL statuses. Verification appends a
verdict with its evaluator, evidence, and timestamp. Confirmation appends new
`observed` or `asserted` canonical evidence linked by `derived_from` and/or
`supersedes`; it never rewrites the dream record into fact. A new status value
would require a versioned MIRL migration and is not authorized by this roadmap.

Dream Mode should eventually support:

- episodic replay
- unresolved-goal replay
- anomaly clustering
- cross-domain association
- counterfactual planning
- semantic schema extraction
- graph pruning / consolidation
- contradiction discovery
- hypothesis generation

## Embodied / Spatial Memory Track

The ESP32-S3 edge work is part of the model end-state, not a separate hardware curiosity.

SEAM should be able to maintain a provenance-backed world model from distributed observations.

Initial hardware target:

```text
ESP32-S3 A ----\
ESP32-S3 B -----+--> SEAM Spatial --> world graph --> agent
ESP32-S3 C ----/
       |
       +--> Wi-Fi CSI
       +--> cheap sensors
       +--> local filtering
       +--> SEAM-micro models
```

The initial spatial system should focus on measurable capabilities before richer claims:

1. occupancy
2. coarse zones
3. motion state
4. zone transitions
5. rough trajectories
6. sensor fusion
7. object identity with explicit ground truth
8. persistent object/location state
9. confidence decay and re-observation

All spatial conclusions should carry evidence provenance and confidence.

## Hierarchical Compute and Memory

SEAM should learn to distribute work across heterogeneous memory/compute tiers.

```text
MCU SRAM
   -> PSRAM
   -> MCU flash / FRAM
   -> SD / local block storage
   -> edge Linux RAM / NVMe
   -> workstation RAM / GPU
   -> long-term SEAM store
```

Research questions:

- What should be processed locally versus centrally?
- What observations deserve durable memory?
- What representation belongs at each tier?
- Which tier retains or migrates immutable RAW evidence, and when may its bytes
  move to a verified external anchor while remaining exactly reconstructible?
- Which additive state transitions may be derived from RAW without replacing it?
- How should memories migrate between tiers?
- Can SEAM-micro models perform novelty, salience, deduplication, routing, and spatial classification before expensive inference?

## Provenance-Aware Dataset Generator

The dataset generator is the first model-program dependency. Pretraining,
supervised training, preference data, tool trajectories, and evaluation records
must not be assembled by unrelated scripts with incompatible lineage.

### Canonical example envelope

Every candidate example receives a stable example ID and an append-only
revision chain. At minimum the envelope records:

```text
example_id / revision / supersedes
source_id / source_content_hash / source_span
rights, license, consent, privacy, and retention decision
generator model + revision (when synthetic)
prompt/template hash + sampling parameters + seed
ordered transformation DAG + code revisions
deduplication group / contamination findings
split assignment and split-lock version
tokenizer + token count
task family / mixture / weight
quality grades + grader identities + disagreements
training_eligible + exclusion reasons
output content hash + dataset-manifest hash
```

An output without source closure is rejected, not patched with an inferred
source later. Corrections append a new revision with `supersedes`; old rows
remain auditable and are excluded by the derived current-state view.

### Admission pipeline

```text
source registry
    -> rights / consent / retention decision
    -> canonical extraction with hashes and spans
    -> deterministic versioned transforms
    -> exact and near deduplication
    -> secret / PII / safety screening
    -> benchmark-contamination screening
    -> immutable split assignment by dedup group
    -> deterministic checks + independent grading
    -> admitted pretraining or training view
    -> signed/hash-addressed dataset manifest
```

Rejection is a first-class outcome with a reason code. The generator never
silently drops provenance, changes a split, or promotes a failed row.

### Separate generated views

- **Pretraining view:** tokenizer-ready text/code/structured-memory records,
  source-balanced and deduplicated before splitting.
- **Training view:** SFT, tool-use, retrieval, provenance, abstention,
  contradiction, supersession, temporal, graph, and embodied trajectories.
- **Negative/adversarial view:** plausible unsupported answers, stale evidence,
  conflicting observations, missing tools, and explicit abstentions.
- **Evaluation quarantine:** benchmark prompts, gold answers, judge outputs, and
  holdout-derived rows. These default to `training_eligible=false`.

`RunRecord.write_audit_jsonl()` is an audit/candidate-row exporter, not this
generator. It machine-marks every row `training_eligible=false`; the historical
`write_training_jsonl()` name is a compatibility alias to that same quarantined
writer. Its benchmark questions and gold answers must remain quarantined unless
a benchmark is formally retired and a new sealed holdout is established.
Raw hidden reasoning or `<think>` traces also default to excluded: retain them
only under explicit rights/privacy controls, and use concise verifiable
rationales when rationale supervision is actually required.

### Generator delivery order

1. Example-envelope schema and round-trip/hash tests.
2. Source registry with admit/reject decisions.
3. Deterministic generator core and transform lineage.
4. Separate pretraining and training views.
5. Deduplication, immutable splits, contamination and privacy gates.
6. Reproducible manifests and independent quality admission.

No model rung starts until the dataset slice it consumes has a reproducible
manifest, zero orphan lineage, and zero known holdout leakage.

## Native Model Training Program

The eventual SEAM-native model should be trained to treat memory operations as normal learned behaviors.

### Stage 1 — Teacher-driven memory policy

Use frontier/large models to generate supervised traces for:

- when to retrieve
- what to retrieve
- how far to expand graph activation
- when to abstain
- how to cite provenance
- when to update/supersede memory
- when to consolidate
- when to create a hypothesis instead of a fact

### Stage 2 — Small SEAM-specialist models

Train/distill small models for:

- salience
- novelty
- deduplication
- memory routing
- graph expansion
- conflict detection
- confidence estimation
- spatial classification

Deploy selected specialists to constrained edge devices when useful.

The first explicit model rung is **SEAM-µ (~250K parameters)**. It must solve
one bounded specialist task and beat a declared heuristic/resource baseline
before it becomes a dependency for later rungs.

### Stage 3 — SEAM-aware language-model fine-tuning

Train the **1B** rung with explicit SEAM operations in its trajectories so that
retrieval and provenance become learned reasoning primitives rather than
external prompt conventions. This rung starts only after the ~250K specialist,
dataset, and independent-evaluation gates have evidence.

### Stage 4 — From-scratch SEAM-native model

Train the **4B** target model from initialization with:

- SEAM-native memory tokens / structured channels
- retrieval/action traces
- provenance-supervised outputs
- temporal reasoning
- graph reasoning
- episodic-to-semantic consolidation tasks
- abstention tasks
- contradiction and supersession tasks
- world-state tracking
- EPOC modulation experiments
- Dream Mode-derived hypothesis verification

The model ladder is exactly **~250K -> 1B -> 4B** for this program. The 4B rung
requires a measured capability or efficiency reason to scale beyond 1B; size is
not a passing result.

## Evaluation Gates

The native-model track should not advance on subjective demos alone.

### Quantitative exit contract

Every rung and dataset release requires a versioned exit manifest committed
before the evaluated run. It names the immutable dataset and split hashes,
frozen baseline, exact metric implementation, direction, numeric threshold or
budget, sample count, uncertainty method, and allowed category-level tolerance.
A metric name without that manifest is a measurement candidate, not a gate;
missing, malformed, post-hoc, or partially reported results fail closed.

The following hard gates apply to every rung:

- admitted examples and memory-derived output claims have provenance-lineage
  completeness `1.000` and deterministic source/transform hash closure;
- false-source rate, unsupported memory-derived claim rate, benchmark-holdout
  contamination, cross-split duplicate-group leakage, and dream-to-fact
  contamination are each `0` on their sealed gate sets;
- exact replay suites reproduce the declared outputs and derivation hashes
  byte-for-byte;
- every declared memory, temporal, supersession, graph, spatial, and safety
  category is non-regressing against its pinned baseline under the manifest's
  predeclared comparison rule; an omitted category is a failed report;
- promotion demonstrates a statistically justified improvement on at least one
  declared target capability or resource measure without breaching any latency,
  memory, energy, privacy, or provenance budget; parameter count is never an
  improvement metric; and
- independent-grader calibration meets its predeclared sealed-set threshold,
  while deterministic failures or provenance/safety failures remain vetoes
  regardless of grader preference.

Each model rung may set stricter absolute targets in its pre-registered
manifest. Until those rung-specific numbers exist, the benchmark families
below define required coverage, not permission to promote.

### Independent skeptical grading

The model that generates an answer, trace, synthetic example, or candidate
checkpoint may never be its sole grader. Every promotion decision requires:

1. deterministic checks wherever an exact rule is possible;
2. at least one blinded grader from a different model family/provider than the
   candidate or teacher being evaluated;
3. randomized arm labels and prompts that do not reveal the preferred system;
4. recorded grader model/revision, prompt hash, sampling settings, raw verdict,
   and rationale;
5. calibration and replay on a sealed adjudicated set before trusting the
   grader for promotion;
6. explicit disagreement rates, with material disagreements routed to a second
   independent grader or human review rather than averaged away; and
7. skeptical failure analysis that actively searches for contamination,
   unsupported claims, shortcut learning, provenance laundering, and grader
   preference bias.

Cross-model agreement is evidence, not truth. A favorable model grade cannot
override failed deterministic, provenance, privacy, contamination, or
category-level non-regression gates. Teacher, candidate, primary grader, and
adjudicator identities remain distinct in the run record.

Required benchmark families:

### Memory quality
- LoCoMo
- LongMemEval
- BEAM / long-context memory scale tests
- SEAM internal exactness suites

### Provenance
- source attribution accuracy
- lineage completeness
- derivation reproducibility
- false-source rate
- unsupported-claim rate
- dream-to-fact contamination rate

### Semantic / graph behavior
- multi-hop retrieval
- contradiction handling
- supersession
- temporal ordering
- graph expansion efficiency
- activation precision

### EPOC
- state stability
- boundedness
- reproducibility
- context sensitivity
- recovery to baseline
- effect on retrieval/planning without factual corruption

### Dream Mode
- hypothesis novelty
- hypothesis usefulness
- verification success rate
- contamination rate
- consolidation compression
- contradiction discovery

### Spatial / embodied
- presence precision/recall
- zone classification
- trajectory error
- object-state accuracy
- sensor-fusion gain
- offline recovery
- node provenance integrity

### Efficiency
- tokens avoided
- bytes stored
- retrieval latency
- energy per event
- edge inference latency
- memory-tier bandwidth
- useful-memory / raw-observation ratio

## Final Architectural Target

```text
                         SEAM-NATIVE MODEL
                               |
             +-----------------+-----------------+
             |                 |                 |
          REASONING          EPOC             PLANNING
             |                 |                 |
             +-----------------+-----------------+
                               |
                        NATIVE SEAM API
                               |
        +----------+-----------+-----------+-----------+
        |          |           |           |           |
     EPISODIC   SEMANTIC    TEMPORAL    SPATIAL    RELATIONAL
        |          |           |           |           |
        +----------+-----------+-----------+-----------+
                               |
                       PROVENANCE GRAPH
                               |
              +----------------+----------------+
              |                                 |
        DIGITAL EVENTS                      PHYSICAL WORLD
              |                                 |
       tools / files / chat                ESP / sensors / CSI
```

The defining claim to prove is:

> A language model can use SEAM as a native persistent memory substrate with RAG-like operational efficiency while preserving complete provenance for memory-derived reasoning and supporting persistent semantic, episodic, temporal, spatial, relational, and affective state.

This claim remains a research target until benchmarked. Architecture, training, and documentation must distinguish demonstrated capability from planned capability.
