---
handoff_id: 2026-09-12-memory-formation-roadmap
supersedes: 2026-09-08-package-names-testpypi-candidate
handoff_status: current
history: HISTORY#645
---

# Recovered direction, detailed roadmap and continuation handoff

## Read this first

The operator's **Chunking Strategy Proposal** conversation was recovered on
September 12 from regular ChatGPT. The opening request and all 81 rendered
message blocks were read, including the typed opening and later voice
conversation. This handoff preserves derived project requirements without a
private conversation URL, transcript identifier, raw transcript or credentials.
The operator confirmed that this direction is the new roadmap and asked for a
very detailed repo handoff, pushed and merged, so the work can resume on the G7.

The [detailed roadmap](../roadmap/MEMORY_FORMATION.md) is the execution
specification. It contains the complete R01-R14 request register, M0-Q1 stream
specifications, acceptance gates, temporal dependency diagram and parallel
ownership rules. Root `ROADMAP.md` registers and routes the track; it does not
compete with this detailed specification. When asked **“what's next?”**, consult
the specification's current ready set and this handoff, verify current main
and actual completion evidence, then choose the earliest unblocked work.

**First runtime-relevant work is M1's current-code/history audit.** B1 BIL-3
design, E1 Anthropic/evaluation setup and P0 report-home discovery can proceed
alongside it in independent scopes. M2 chooses implementation only after the
audit. This is a setup/design handoff, not a report that chunking is repaired.

## Operator intent that must survive compaction

1. Return to chunking and memory formation first. The operator wants entity
   observations consolidated through a temporal chain, using the context and
   metadata that memory/graph structures can express. This is a new hypothesis
   to audit, not a root cause already demonstrated on current main.
2. Inspect current repository behavior and Git history/results before deciding
   what is broken or declaring an old experiment equivalent to the new idea.
3. Formulate a feasible plan, then implement, test, benchmark and qualify
   deployment. The operator explicitly said this is not a race; setup and
   detailed dependency-aware specifications matter.
4. Develop BIL-3 in parallel. The correction was that BIL is not broken;
   BIL-2 does not cover all desired modern system/reproducibility details.
5. Set up direct Anthropic API use for the benchmark campaign. The operator
   reported $72 credit and said the key needed configuration. The balance and
   a working authenticated call have not been verified by this planning work.
6. Keep Canticle's website updated with benchmark and test reports.
7. Find the existing consolidated report/data folder in or near SEAM, organize
   benchmarks/tests/metadata there, and retain prior evidence with supersession.
8. Produce two Canticle-styled formats: full research/study papers and separate
   benchmark/test reports covering predictions, changes, measured outcomes,
   failures and predicted-versus-observed differences.
9. Keep all requests together in a repo handoff usable on the G7. A promise in
   chat is not proof that a file was saved, committed, pushed or merged.
10. Treat SEAM as a foundational dependency for AI memory and reasoning. This
    is product direction, not proof of adoption or a measured capability.
11. Include **Sleep** for offline/deep consolidation and **Daydream** for
    lightweight online consolidation in available moments, improving formation.
    The existing Codex session-learning `/sleep` tooling is a separate effort.
12. Make ordinary installation/use plug-and-play and mostly automatic, with
    manual commands such as remembering a particular item and clear operator
    control over automation.
13. Preserve the knowledge/reasoning graphs and their visual experience as
    central product value. Better formation should feed useful inspectable
    evidence into those products; graph visual appeal alone is not a benchmark.
14. Keep the opening chunking priorities dominant. Later consolidation and UI
    ideas must not take over the first work stream.

The conversation's beyond-80% aspiration is not a verified outcome or an
agreed metric. The older 90% launch aspiration cannot be substituted for it.
E1 must specify the benchmark/metric, split, models/judge, comparator, context
budget and spending protocol. Never equate recall with answer accuracy or
promise the result in advance.

The operator also explicitly asked for honest action reporting: distinguish
completed work, an attempted action, a blocker, a proposal and an unverified
claim. Disclose access/tool failures when they happen. Do not say a handoff is
pushed or merged until GitHub evidence establishes it.

## Current implementation evidence and its limits

This documentation work started from fetched `origin/main`
`b62303209e7d8e4d33b11c2c33b44c8310a8468c` in an isolated clean worktree.
PR #256 package naming and PR #258 Claude memory pin were already merged.
After qualifying and merging #257, this documentation branch advanced to
`736eb91cdb6ce3267d74dec4400b663e9dbfadf3` before its own closeout.
Current source supports BIL-0/1/2 in
`seam_runtime/benchmark_integrity.py`; BIL-3 is not implemented here.
No runtime source, compiler contract, database, retrieval weight or default
has been changed by the roadmap/handoff slice. No paid model call, benchmark
campaign, package upload, website update or deployment was performed.

The governing SEAM spec and MIRL v1 contract were consulted. RAW/IR retention,
derived PACK, provenance, identity/lifecycle and supported retrieval boundaries
continue to apply. R2 completion and S8 freeze remain recorded through PR #254
at `2f9a96b9` (HISTORY#641); S9 Promotion, S10 release/deployment and operator
acceptance remain open. The new priority does not erase those completed facts
or waive their qualification requirements.

The June 15 entity-aggregation audit was read as historical evidence. It
addresses default-off retrieval-time string aggregation and documents the
risk of recall gains with diluted answer quality. Later identity/coreference
work exists. That audit alone cannot prove current compilation loses the same
information, and the earlier ChatGPT assistant's claims about graph inertness
were not independently established by recovering the conversation.

Current paths identified for M1 include `seam_runtime/nl.py::compile_nl`,
`nl_extract.py`, `runtime.py`, `identity_resolution.py`, `knowledge_graph.py`,
`graph_products.py`, `graph_source_selector.py` and the LoCoMo ingest adapter.
Relevant test families include conversation-turn compilation, entity
coreference, identity resolution, relation extraction, S7 entity evidence and
S7 temporal identity admission. Trace those paths using real fixtures before
choosing a new abstraction. The roadmap names the exact starting paths and KB.

The proposed formation design uses speaker/time/entity/event/discourse-aware
segmentation, atomic observations with original anchors, existing identity
mechanisms and rebuildable temporal entity views. Current state, transitions,
relations and contradictions must remain inspectable. This is broader than
larger chunks and different from blindly concatenating retrieval results.
The illustrative `temporal-entity/1` name remains a proposal. M2 resolves actual
schema/interface, migration and performance decisions after M1 evidence.

## BIL-3 and benchmark setup to resume

B1 must inspect existing signing and verification before finalizing the
proposed **Signed Reproducibility Bundle** tier. Desired evidence includes
hardware/OS/runtime, dependency/lock and Git identity, backend/index details,
embedding/answerer/judge versions, seeds, retrieval/context configuration,
formation/ingest/entity-resolution versions, dataset hashes, sanitized config,
per-case artifacts and signature coverage. Preserve legacy BIL-2 evidence;
unavailable metadata must be explicit. Full details and B2 test exits are in
the roadmap. Do not label a run BIL-3 before its implementation and adopted
requirements are satisfied.

Only credential **presence** was checked: `ANTHROPIC_API_KEY` was nonempty in
the current process. It was not found in the inspected primary `.env` or
`~/.config/seam/seam.env` files. No value was printed or copied. No authentication,
model access, account ownership or remaining balance was checked. Environment
presence on this host does not establish access on the G7. Use private operator
configuration and a bounded smoke after E1 defines costs and stop conditions.
Do not request secret values in chat or write them into a handoff/manifest.

The versioned KB requires matched answerer/judge conditions, variance/no-change
controls, exact runner configuration and accounting for failed/retried spend.
An Anthropic lane must be identified separately if it changes the published
Mem0 comparison protocol. Keep native strict and incumbent-relative judge
scoreboards separate. Do not merge a Mem0 beta into the baseline merely to
clear the PR list. No paid run should precede E1's bounded campaign contract.

## Reports, storage and website work

`docs/REPORTS_AND_EVIDENCE.md` was read and remains authoritative routing:
tracked dated interpretations in `docs/audits/` with index/HISTORY/Evidence
manifest, verified claims in `benchmarks/RESULTS.md`, machine bundles in
`benchmarks/runs/`, testing notes in `tests/docs/`, and rich private/raw data
in configured external storage. The storage script's default is
`Documents/SEAM/benchmarks`; this does **not** establish that the operator's
remembered consolidated folder has been found. P0 must verify the actual home.

P1 produces the two requested Canticle report forms using applicable skills;
P2 handles website publication through that repository's own policy and real
preview/deployment receipts. No cross-repo file or website has changed here.
Reports must retain negative results and supersession, distinguish hypotheses
from outcomes, and avoid large raw artifacts in the SEAM working tree.

## GitHub reconciliation at the planning checkpoint

Live triage inspected all open PRs, their exact heads/checks, the active ruleset
and the open issue list. Required checks remain `repo-hygiene`,
`chroma-real-smoke` and `locomo-quickstart-bil2`, with strict up-to-date policy
and no bypass. Issue #259 tracks execution of this roadmap, with the detailed
specification retaining dependency/acceptance authority. Advisory matrix success is distinct from required merge gates.

| Item | Observed state / next disposition |
| --- | --- |
| #257, archived WebUI Vitest/mocker manifests | Candidate `b1751676a5e48f9d21802b02e526d4e1ed3852fb`; all required checks passed. Independently qualified receipt was canonically stored; merged September 12 at `736eb91cdb6ce3267d74dec4400b663e9dbfadf3`. |
| #249, Mem0 dependency update | `8d77775fe6e029717115758b917c94c757ed0d4a`; behind main. Widens Mem0 below-1.0 to below-3.0 and locks 2.0.0b2. Existing CI does not install `bench-mem0`/`all-extras`, so dedicated comparator qualification is required. Converted to draft with that blocker; do not change E1 baseline implicitly. |
| #230, batched embeddings | `6313f851c2cf68ef06350c910f6c9bbf3be13762`; conflicting and stale. Merge-analysis evidence includes `vector_adapters.py` plus chronology files. Converted to draft with explicit rebase/mechanism-test scope; not a prerequisite to M1. |
| #213, cache no-op replay | Draft `4d2609e59ffca85eb2c4c6c4e995e62f545744ec`; conflicting. Unique named cache/idempotency cases require salvage review; it is not proven subsumed by #230. Preserve the branch and tests. |
| #212 | Its body says fixed and describes a durable TUI handoff, not an unresolved formation defect. Closed as completed September 12, retaining its historical explanation. |

`docs/roadmap/DROPPED_PR_TRACKS.md` is corrected in this slice: #213 was still
open, and shared file names or a newer branch did not prove semantic coverage.
Five named tests were found only on #213 when compared with exact main and
#230, including older-timestamp replacement and same-timestamp delete/reindex.
No unique code was deleted and no conflicting runtime PR was force-merged.

The inherited advisory failure on main and #257 is
`tests/audit/test_history_closeout.py::test_preflight_gates_match_canonical_commit_hook`:
expected gate sequence starts with `verify_agent_config`, actual sequence with
`verify_integrity`. Both GitHub job logs showed the same assertion. Issue #260 tracks the
separate CI cleanup; do not weaken canonical gates or fold an untested runtime
repair into this documentation PR. Required checks still govern this merge.

## Preserved local work and G7 recovery

The primary checkout remains on `docs/deep-audit-20260829` at `780b3772`,
with unrelated dirty work. Excluded tracked paths: `HISTORY.md`,
`HISTORY_INDEX.md`, `.seam/cross_index.md`, `.seam/streams/history/{index,log}.md`,
`docs/audits/INDEX.md`, the August 29 grounded-research handoff and handoff index.
Excluded untracked material: `.codex/`, `.disposable/`, `.seam/orchestration/`,
`.seam/cross_index_archive/0001-0477.cross.md`, the August 29 full-repo audit,
August 30 deep-audit handoff and `error.log`. No stash was present at inspection.
Do not stage these files into the new roadmap PR or erase them to clean status.

Preserved independent worktrees: `.claude/worktrees/audit-cleanup-20260903`
(locked Claude work), `.worktrees/codex-pretool-hooks`, and
`.worktrees/session-sleep-learning-20260911`. The last contains unfinished
`tools/learning` work, tests and a **local HISTORY#645** based on old main.
That local number collides with this new canonical entry and must be renumbered
and reclosed when its work resumes; do not overwrite either history or merge
the stale chain blindly. Its Codex learning workflow is not SEAM Sleep/Daydream.

Root owns temporary `memory-roadmap-handoff-20260912` and
`pr257-closeout-20260912` worktrees for this closeout and must remove them after
successful completion, retaining needed local receipts outside those trees.
This preserves other agents' checkouts. The primary dirty checkout need not be
reset or switched to prove that the new PR merged.

On the G7 or next host: fetch current main, inspect status/worktrees, read the
canonical startup route and newest handoff, verify the latest snapshot, then
use a bounded relevant context pack. Use a clean branch/worktree for new work;
verify its actual interpreter rather than assuming a sibling `.venv` exists.
Do not copy host-local credentials or infer provider access from this host.
Confirm this roadmap exists on fetched main and reconcile any later successor
before starting M1/B1/E1/P0.

## Closeout, compaction and exact next action

This slice updates the roadmap, status/ledger routing, launch priority and
canonical handoff chain; HISTORY#645 owns verification and disposition.
Documentation-only work requires continuity/stream/wiki and agent-config gates,
secret/session-link scanning, independent review and current required GitHub
checks. Runtime tests/TDD are not claimed for a docs-only change. Any failed
verification must remain recorded and resolved or explicitly handed off.

The installed desktop app supports a real `/compact` command, backed by
`thread/compact/start`. Its handler refuses compaction while a response is
in progress. The installed CLI exposes no standalone compact command;
`codex queue` queues text and is not evidence of executing a slash command.
The default shared app-server control socket was absent when checked. No
supported automatic post-response invocation was established, so no fake
`/compact` message or background control workaround was installed.

After the handoff PR is verified merged and this response ends, the operator
can type `/compact` in the current chat and select **Compact**. An earlier
automatic context compaction is not proof of executing that requested
post-merge action. Resume from this registered handoff and the roadmap ready
set, rather than attempting to reconstruct the lost conversation again.

Next work: **M1 current ingestion/identity/history audit**, with **B1, E1 and
P0** as independent parallel preparation streams. M2 design follows their
relevant evidence; runtime work and paid evaluation remain unstarted.
