# SEAM Reasoning Graph

SEAM maintains two related but deliberately different graph planes:

- the **knowledge graph** records what SEAM knows and the exact evidence behind
  it; RAW/MIRL remains its canonical source of truth;
- the **reasoning graph** records how a run used knowledge, evidence, questions,
  hypotheses, inferences, and decisions to produce an outcome.

The reasoning graph is an append-only public justification graph. It is not a
chain-of-thought store, an activation trace, or a second source of canonical
truth. It has no fields for hidden thoughts, logits, activations, or arbitrary
model payloads.

## R1 contract

Every reasoning graph is anchored to an existing `workspace_run`, inheriting
that run's namespace, scope, and agent attribution. R1 provides:

- immutable typed nodes: `objective`, `question`, `premise`, `hypothesis`,
  `inference`, `decision`, and `outcome`;
- immutable typed edges: `decomposes`, `uses`, `supports`, `opposes`,
  `derives`, `tests`, `selects`, `answers`, `supersedes`, and `produces`;
- append-only status transitions: `open`, `supported`, `challenged`,
  `accepted`, `rejected`, and `superseded`;
- exact references to knowledge-graph nodes and MIRL evidence records;
- namespace/scope isolation for every referenced artifact and a same-run rule
  for every reasoning edge;
- an acceptance guard: an inference, decision, or outcome needs a direct
  knowledge/evidence reference or an incoming supporting reasoning edge before
  it can become `accepted`;
- no automatic promotion into MIRL. Promotion remains a future explicit,
  reviewed operation.

`workspace_event` remains the bounded operational event stream used for live
UI and replay. The reasoning graph is its durable, queryable sibling: a run can
emit operational events and also accumulate a structured justification graph
without duplicating hidden model traces.

## R2 retrieval-decision contract

R2 records a retrieval as one typed, atomic decision rather than as an
arbitrary trace blob. Each record fixes the run boundary, normalized plan,
planner and fusion-policy identities, per-leg limits and latency, ordered
candidate-set fingerprint, selected prefix, and rejected alternatives. Directly
selected MIRL record IDs are copied onto the accepted decision node as exact
evidence references.

The durable candidate ledger is deliberately compact and content-free: record
ID, namespace/scope and content fingerprint, rank, fused score, per-leg
rank-normalized contributions, controlled reason codes, and disposition. Raw
leg scores stay in the live leg trace; they are not summed across incompatible
SQL, vector, and graph score domains. The fixed
`reciprocal-rank-fusion/2` policy deduplicates each record within a leg by its
best raw score, ranks that leg by raw score then record ID, assigns
`1 / (60 + rank)`, and sums contributions across legs. The policy contract and
fingerprint are stored with every new decision. The row also pins the semantic
adapter and embedding model identity/dimension. It never copies MIRL payloads,
provider responses, or hidden reasoning. The public query itself remains a
typed `question` summary and its normalized form is recorded as part of the
plan.
At most 128 candidates are recorded and at most 64 can be selected. The
run/namespace/scope boundary is enforced in Python and SQLite, rows are
append-only, and finalization fails unless the stored candidate prefix is
complete. The retrieved content fingerprint is rechecked inside the write
transaction, preventing a search-to-record race, and later record drift is
reported on detailed reads. An empty result is still a valid typed decision
with zero selected candidates; it is not represented by invented evidence.

`reasoning_graph()` returns compact retrieval summaries only. Candidate detail
is available through the bounded `retrieval(...)` and `retrievals(...)` reads,
so a long-running reasoning graph does not inline an unbounded trace history.

## Python SDK

The initial SDK is local and provider-free:

```python
from seam_runtime import SeamSDK

with SeamSDK("seam.db", allow_pgvector_env=False) as seam:
    run = seam.start_reasoning(
        "Decide which migration path is safest.",
        ns="acme",
        scope="project",
        agent_id="planner",
    )
    premise = run.add_node(
        "premise",
        "The current schema has a verified rollback path.",
        knowledge_refs=["clm:rollback-path"],
        evidence_refs=["raw:migration-plan"],
    )
    decision = run.add_node("decision", "Use the reversible migration.")
    run.link(premise["node_id"], "supports", decision["node_id"])
    run.transition(decision["node_id"], "accepted")
    retrieval = run.retrieve(
        "verified rollback evidence",
        mode="mix",
        budget=5,
        graph_hops=2,
    )
    graph = run.graph()
```

`run.retrieve(...)` is provider-free by default. It executes the live SEAM
retrieval planner, returns the selected records to the caller, and atomically
persists the bounded R2 decision. The SDK enables semantic fact seeding for its
graph leg explicitly; legacy orchestrator callers keep the prior default with
semantic graph seeding off unless they opt in.

`SeamSDK` also exposes `ingest(...)` and `knowledge(...)` so agents and
framework adapters can use one stable programmatic boundary instead of
depending on database tables, CLI output, or HTTP route details. CLI, REST, MCP,
and framework-specific packages can grow as adapters over this boundary.

## Maturity path

| Stage | Deliverable | Acceptance boundary |
| --- | --- | --- |
| R1 Durable run graph | Typed append-only nodes, edges, state history, evidence references, Python SDK | Isolation, immutability, explicit support, no hidden traces, no automatic MIRL promotion |
| R2 Retrieval decisions | First-class query plans, candidate comparisons, and selected/rejected traces | Every selection identifies candidates, policy/model identity, evidence fingerprints, and rejected alternatives |
| R3 Verification loops | Tests, tool outcomes, contradictions, retries, and supersession | Failed paths remain visible; final outcomes identify the checks that support them |
| R4 Reasoning retrieval | Search and reuse prior reasoning patterns without treating outcomes as facts | Task/run scoping, freshness, trust, and provenance gates; no conclusion laundering |
| R5 Reviewed promotion | Explicit proposal/review path from selected outcomes to new MIRL assertions | Human or policy approval, exact evidence, reversible audit, no automatic promotion |
| R6 Qualification | Cross-agent SDK adapters, concurrency/recovery, latency and usefulness evaluations | Stable versioned contract, tenant isolation, crash recovery, measured value over event-only traces |

R1 and R2 are implemented. R3-R6 remain open; an R2 retrieval decision is an
auditable record of what the current policy selected, not proof that the policy
is optimal or that the selected records are true.

Knowledge stages G1-G7 and reasoning stages R1-R6 advance in parallel. The
planes meet through stable references and reviewed promotion boundaries, not by
collapsing knowledge and reasoning into one ambiguous graph.
