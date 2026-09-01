# SEAM Standard Operating Procedures

[Back to the SEAM Wiki](README.md)

This index makes every root-level `docs/SOP_*.md` page discoverable. An indexed
SOP is not automatically current: confirm its prerequisites against active
code, the [repo ledger](../REPO_LEDGER.md), and the
[current-state streams](status/index.md) before executing it. Task-specific
DeepSeek packets record bounded procedures; they do not prove that the work ran
or remains necessary.

## Operator workflows

- [Continuing SEAM work with Codex](SOP_SEAM_CODEX_WORKFLOW.md) — ordered
  reconciliation, delivery, assurance, qualification, protected merge, and
  durable-resume workflow for continuing a SEAM initiative.
- [Model integration](SOP_MODEL_INTEGRATION.md) — configure model providers and adapters.
- [Holographic Surface workflow](SOP_HOLOGRAPHIC_SURFACE.md) — encode, verify, query, and import surface artifacts.

## Advisor, audit, and remediation workflows

- [Codex root-supplied agent orchestration](SOP_AGENT_ORCHESTRATION.md) — bounded
  context packets, four logical domain roles, JIT specialists, and SessionEnd
  closeout qualification.
- [Advisor / Executor loop](SOP_ADVISOR_EXECUTOR_LOOP.md)
- [DeepSeek parallel audit execution](SOP_DEEPSEEK_PARALLEL_AUDIT_EXECUTION.md)
- [Deep audit remediation blueprint](SOP_DEEP_AUDIT_REMEDIATION_BLUEPRINT.md)
- [Deep audit DeepSeek execution pass](SOP_DEEP_AUDIT_DEEPSEEK_EXECUTION.md)
- [DeepSeek security and benchmark remediation](SOP_DEEPSEEK_SECURITY_BENCHMARK_REMEDIATION.md)
- [Production-readiness remediation](SOP_PRODUCTION_READINESS_REMEDIATION.md)
- [WebUI batch hardening DeepSeek pass](SOP_WEBUI_BATCH_HARDENING_DEEPSEEK.md) — a bounded task packet, not current surface status.

## CI and benchmarkability workflows

- [Path to a benchmarkable state](SOP_BENCHMARKABLE_STATE_ROADMAP.md)
- [Critical benchmarkability fix](SOP_CRITICAL_BENCHMARKABILITY_FIX.md)
- [CI hardening DeepSeek pass](SOP_CI_HARDENING_DEEPSEEK.md)
- [CI benchmark-gate preparation DeepSeek pass](SOP_CI_BENCH_GATE_PREP_DEEPSEEK.md)

## External benchmark workflows

- [External benchmark registry and runner](SOP_EXTERNAL_BENCH_PHASE1_REGISTRY.md)
- [SEAM LoCoMo adapter](SOP_EXTERNAL_BENCH_LOCOMO_SEAM_ADAPTER.md)
- [LLM-as-judge scoring](SOP_EXTERNAL_BENCH_LLM_JUDGE.md)
- [Mem0 comparator](SOP_EXTERNAL_BENCH_MEM0_COMPARATOR.md)
- [Zep / Graphiti comparator](SOP_EXTERNAL_BENCH_ZEP_COMPARATOR.md)

Paid or provider-backed execution still requires the explicit approvals named
by the controlling SOP and current repository policy.

## Track K benchmark-integrity packets

- [Track K BIL Phase 1 DeepSeek pass](SOP_TRACK_K_BIL_PHASE1_DEEPSEEK.md)
- [Track K BIL Phase 1 repair handoff](SOP_TRACK_K_BIL_PHASE1_REPAIR_HANDOFF.md)

## Track M benchmark packets

- [Track M P0 standard benchmark completion](SOP_TRACK_M_P0_DEEPSEEK.md)
- [Track M P1 real benchmark runs](SOP_TRACK_M_P1_REAL_BENCHMARK_RUNS.md)
- [Track M P2 LoCoMo retrieval wiring](SOP_TRACK_M_P2_LOCOMO_RETRIEVAL_WIRING.md)
- [Track M P3 LoCoMo score improvements](SOP_TRACK_M_P3_LOCOMO_SCORE_IMPROVEMENTS.md)
- [Track M P4 score improvements and measurement](SOP_TRACK_M_P4_SCORE_IMPROVEMENTS_AND_MEASUREMENT.md)

## Historical — do not execute

- [Compiled self-host wheel SOP](SOP_SEAM_SELF_HOST_WHEEL.md) —
  **historical/non-current**. The distribution split it describes was retired,
  and the page is retained only for provenance and future design input.

Roadmap-like SOPs and phase packets describe requested work. Confirm completion
through active code, named tests, current status, and history evidence; never
infer implementation from the existence of an SOP.
