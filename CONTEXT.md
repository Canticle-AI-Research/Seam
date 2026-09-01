# SEAM Product Core

SEAM is a provenance-preserving memory system whose canonical evidence and
memory remain durable while retrieval, graph, and context products stay
rebuildable and evidence-bound.

## Language

**Canonical Evidence**:
Immutable source material and exact anchors from which durable memory can be
reconstructed.
_Avoid_: source blob, original data

**Canonical Memory**:
The durable MIRL interpretation of accepted evidence, including lifecycle,
identity, temporal, and provenance state.
_Avoid_: database row, memory object

**Derived Projection**:
A rebuildable view of Canonical Evidence or Canonical Memory used for search,
graph traversal, ranking, compilation, or presentation.
_Avoid_: secondary truth, cache of record

**Product Core**:
The evidence, compilation, persistence, lifecycle, retrieval, graph, PACK, and
qualification behavior that defines SEAM independently of any human-facing
control surface.
_Avoid_: backend, engine internals

**Operator Surface**:
A human-facing control, inspection, benchmark, or visualization experience
that operates the Product Core without defining its truth.
_Avoid_: product core, canonical API

**Lifecycle Exclusion**:
The immediate guarantee that a soft-deleted memory is absent from ordinary
retrieval, trace, graph, PACK, and projection reads while retained evidence may
remain for recovery and audit.
_Avoid_: hard delete, erasure

**Physical Erasure**:
An explicitly destructive operation that removes retained content according to
a separately authorized retention contract.
_Avoid_: soft delete, lifecycle exclusion

**Recovery Boundary**:
The fail-closed transition that replaces, migrates, or rebuilds durable state
without allowing live users of the old state to survive across the transition.
_Avoid_: file copy, restore script

**Qualification**:
Reproducible evidence that a frozen implementation satisfies a named contract
on a named corpus and environment.
_Avoid_: benchmark success, seems production-ready

**Promotion**:
The evidence-gated decision to make a qualified policy or mechanism the
default.
_Avoid_: implementation, experiment

**Production-Core Qualified**:
The state in which Product Core invariants, recovery, deterministic rebuilds,
and frozen release artifacts have current evidence.
_Avoid_: hosted production, generally available

**Hosted-Production Qualified**:
The additional state in which a concrete service topology has current TLS,
shared-limit, supervision, secret-injection, backup, restore, upgrade,
rollback, and disaster-recovery proof.
_Avoid_: production-core qualified, local beta
