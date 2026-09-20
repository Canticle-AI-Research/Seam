---
handoff_id: 2026-09-20-formation-m3-next
supersedes: 2026-09-19-m1-evidence-repair-next
handoff_status: current
history: HISTORY#655
---

# M1 accepted for design; bounded formation candidate implemented

## Decision and scope

Continue [memory formation](../roadmap/MEMORY_FORMATION.md) on draft PR #269.
M1's retained synthetic findings are accepted as inputs to M2. The original
helper's historical test-first evidence and cumulative mixed-PR release
qualification remain separate. M2 freezes the first `context-segments/1`
slice. M3 implements that explicit opt-in through the existing Python compiler
and ingestion interfaces; `baseline` remains the default. M4 remains open.

The implementation starts at `93eafed269f2f49252ad382a92c7b5bfbf3cbc00`.
Protected main was `66fd3f93081712871ff827e756026c3e73c71790` at reconciliation.
HISTORY#655 records completed checks and remaining limitations. A protected
merge and whole-PR acceptance are not established by local candidate checks.

## Implemented contract

- Unicode, newline and sentence boundaries, decimal/abbreviation handling,
  and whitespace-preferred hard splitting with a 1,024-character default.
- Original RAW retained verbatim; exact SPAN anchors plus original-source
  context ranges preserve conditions, reported speech and source attribution
  across a hard split. The bound applies to SPAN text, not context pointers.
- Conservative first-person attribution from validated source envelopes or
  line speakers; quoted and ambiguous subjects stay unresolved. Possessive
  subjects such as `My dog` do not become the speaker. Missing timestamps
  stay unknown; M3 does not infer event intervals.
- Versioned, content-free diagnostics in RAW and document metadata. Empty
  output reports zero admitted segments and unavailable fractions explicitly;
  the legacy document `chunk_count` floor remains unchanged.
- Stable replay, distinct source references, namespace isolation and existing
  atomic same-source supersession. Changing candidate configuration creates
  a new document generation. Correction, deletion and rebuild follow existing
  lifecycle rules. No storage schema or retrieval ranking changes.

Rich extractors, derived-fact policies and enabled environment enrichment are
incompatible with this initial candidate and reject before persistence.
Native-loader event IDs and separate captions remain a follow-up: the compiler
cannot recover metadata an intake path did not deliver.

## Research interpretation

The pre-edit M1 observation probe completed on clean `93eafed`; its external
JSON hash is `98696aa953114ccfb1cbe6608bb7c24249226dcfe08ac97f50ee1fdb71b2b5db`.
Local synthetic comparisons establish improved structural preservation for
the named Unicode, abbreviation, line-speaker and long-input cases. They do
not establish better retrieval, answers, general language understanding or
latency. Review counterexamples sharpen the hypothesis: exact fragments need
their interpretive context and attribution before downstream aggregation.

The operator's unspecified research paper has not been identified separately;
this assessment uses the retained M1 audit and formation roadmap. Do not
attribute these results to an unseen manuscript.

## Next bounded work

1. Read HISTORY#655, verify the actual pushed PR head and its required checks,
   and inspect the independently authored incremental closeout receipt.
2. Keep the candidate opt-in. Resolve cumulative E1/B1/M1 PR qualifications
   and protected review separately from M3's implementation evidence.
3. Design M4 against validated M3 output: temporal entity projections must
   retain contributing evidence, unknown times, contradictions and lifecycle
   exclusions. Do not introduce another identity registry or erase history.
4. Before M5, reconcile E1's judging contract: two independent judges distinct
   from the answerer, retained disagreements and a separate final adjudication.
   Finish B2 and grouped-runner seeding/resume/rate-limit prerequisites.
5. Notify the operator before benchmarks, then agree models, roles, selection,
   calls, spending cap and stop conditions. OpenAI, DeepSeek and possibly Grok
   are funding options, not selected models. This slice uses no paid calls.

The broad audit regression retains the previously reproduced
`tests/audit/test_history_closeout.py::test_preflight_gates_match_canonical_commit_hook`
failure: its parser misses the explicit staged agent-config check. Keep that
separate CI cleanup; do not weaken a gate. Exact commands and outcomes are in
HISTORY#655 and external logs under
`/home/terrabyte/LLM-Logs/codex/formation-m3-20260919/`.

## Preserved work and recovery

The primary `docs/deep-audit-20260829` checkout is untouched. Excluded dirty
paths include HISTORY/index/history streams/cross-index, audit/handoff indexes,
the August handoff, and untracked `.codex/`, `.disposable/`, orchestration,
cross-index archive, audit/handoff documents and `error.log`. Existing other
worktrees and stashes are preserved. The root owns status, history, handoff,
snapshot and PR records; the builder owns `formation.py`, `nl.py`, `runtime.py`
and `tests/audit/test_memory_formation_m3.py` only.

If interrupted, first collect and run the M3 module, then the affected compiler,
source-dedup and lifecycle suites. The isolated dependency environment is
`/home/terrabyte/.cache/seam-m1-review-20260919/venv`; real-model checks use the
operator's offline Hugging Face cache. Never rewrite the retained M1 artifact.
Archive ignored receipts/snapshots externally and remove this session's clean
worktree after the reviewed commit is safely pushed.
