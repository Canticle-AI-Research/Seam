---
handoff_id: 2026-09-13-m1-report-publication-benchmark-prep
supersedes: 2026-09-12-memory-formation-roadmap
handoff_status: superseded
history: HISTORY#652
---

# M1 evidence, first report and benchmark-preparation handoff

## Resume here

The operator approved the report-site design, authorized publication of new
reports, approved the exact private-URL redaction that blocked staging, and
requested a checkpoint before benchmarks. Those authorizations persist.
The site is **not yet verified live**. The source checkpoint is committed;
the M1 public edition is now admitted by a real source revision and both
content hashes. Independent assurance/release qualification is still open.

The branch and this handoff have been pushed and draft
[PR #264](https://github.com/Canticle-AI-Research/Seam/pull/264) exists. An
additional concrete release condition is now known: the closeout classifier
includes `tools/` as runtime paths, and `tools/memory_formation_m1.py` has no
recorded red-before-green cycle. Its result is `TDD_UNPROVEN`; the publisher
modules are covered. Do not fabricate a historical failing test or treat a
new green run as proof that such a cycle happened. Independent release must
resolve that condition under the governing protocol before a qualified claim.

The governing detailed roadmap remains
[`docs/roadmap/MEMORY_FORMATION.md`](../roadmap/MEMORY_FORMATION.md).
When asked "what's next?", use that document plus current completion evidence.
M1 now has a reproducible audit candidate. M1 review, B1's metadata contract and
E1's evaluation design are the inputs to M2. This session did not implement
the formation fixes or start a paid benchmark.

First, locate `feat/seam-reports-pages-20260912` and its current PR/head, then
reconcile required checks and the pending closeout request. Do not assume
this handoff's source checkpoint is the final PR head:

```bash
git status --short --branch
git log -3 --oneline
gh pr list --repo Canticle-AI-Research/Seam --head feat/seam-reports-pages-20260912 --state all
python -m tools.agents.closeout_queue pending
```

Use the project Python environment from the primary checkout if the worktree
has no interpreter. Verify current main from GitHub before integration. The
last checked protected-main SHA was
`614141c5aa96fd51d4dee2e09c186bb4035c0377` (merged roadmap PR #261).

## Publication status and persistent operator decisions

- Publish only new work beginning September 12, 2026. No historical report
  backfill. The first selected report is today's M1 investigation, not an old
  benchmark or fabricated example result.
- Publication is authorized. HISTORY#649 supersedes the hold in #648. Keep
  the reviewed Canticle design and the existing link to `https://canticle.cc`.
  Main Canticle website edits and DNS changes were not made.
- No credentials, environment references, private/local paths, provider
  session links, logs, databases or raw transcripts belong in any website
  page, metadata file, feed, asset or download. The public edition is distinct
  from the original audit source; do not switch downloads back to raw audits.
- The exact URL-only redaction in the primary `error.log` was approved and
  completed. Exactly one URL was removed, surrounding content was preserved,
  and the file's follow-up scan returned zero findings. Primary continuity
  subsequently passed. Do not ask for the same redaction approval again.
- Distinguish saved, committed, pushed, qualified, merged and deployed. A
  polished local preview, source commit or Pages setting proves none of the
  later states. Record failures and negative findings as well as wins.

The source checkpoint is signed commit
`e01284de37140b2d56a2c53e68d45f309f7e89e5`. It contains the publisher, M1
canonical audit/evidence and public edition, and HISTORY through #650.
The first catalog/handoff successor is
`0ebdde80595497a43b61754f216b919e6ee6bcc9`, verified pushed when PR #264 was
created. This handoff's later bookkeeping update creates another head;
discover the current SHA and checks with Git/GitHub. Push and draft creation
are established; qualification, merge and deployment are not.

`report-site/catalog.json` selects exactly one report:

| Field | Value |
| --- | --- |
| ID | `2026-09-13-memory-formation-m1` |
| Title / kind | Where memory loses its context / research |
| Original source | `docs/audits/2026-09-13-memory-formation-m1.md` |
| Source revision | `e01284de37140b2d56a2c53e68d45f309f7e89e5` |
| Source SHA-256 | `6622d77ac780d45a7192834ddf63e7a0b8e3d8148a36cdb67220f963e92a5a39` |
| Public edition | `report-site/editions/2026-09-13-memory-formation-m1.md` |
| Edition SHA-256 | `101aaf0e2bc00e8625ee1a3b851b2a0ee6678afc40e66a7ea756a811364b9658` |

The source revision above identifies the audit document. The audit itself
examines runtime revision `614141c5aa96fd51d4dee2e09c186bb4035c0377`.
These are intentionally different provenance boundaries.

## What M1 established

Read the [dated audit](../audits/2026-09-13-memory-formation-m1.md) and its
Evidence manifest. `tools/memory_formation_m1.py` reproduces small synthetic
compiler, native-loader, real-adapter, persistence and graph observations.
It uses the pinned cached BGE embedding model for the real adapter; a labelled
hash-embedding control tests direct storage only. It supplies no answerer.

Confirmed findings:

1. With the adapter's bracketed speaker/date header, later first-person
   sentences become generic `I` claims. Alice's painting and Bob's hiking
   merge into the same canonical `I` entity. Graph products combine them into
   a recurring observation across two episodes. Full source text and evidence
   links remain present; this is a structured attribution error.
2. The native LoCoMo loader's three-field turn type omits distinct dialogue
   IDs and a separately supplied caption. Identical formatted events collapse
   into one source reference. Specific `raw_docs.content` queries used known
   present dialogue words and absent controls. A direct runtime control with
   distinct source references preserves two identical-text events. Do not
   generalize this to captions already appended inline by the Mem0 route.
3. Unicode-only Japanese input preserves RAW/provenance but emits no SPAN/CLM,
   while ingestion reports a compiled chunk. Abbreviations split, newline
   speakers do not form separate propositions, and long unpunctuated input
   has no chunk-size bound. Every emitted span checked points to exact source
   text; an empty span set does not establish coverage.
4. Temporal wording remains verbatim, but default content claims in the
   examples have unset intervals and no typed event/state interpretation.
   Message time, event time, ingestion time and unknown time must be distinct.

Counterevidence matters: colon speaker prefixes bind correctly in a control;
canonical exact-label identity, explicit IDs, boundary separation, reversible
alias decisions, temporal/as-of reconciliation and graph products already
exist. The default sample contains graph edges despite no canonical REL rows.
Retrieval returns complete source turns in the synthetic question control.
Do not propose a new registry on the assumption there is no existing identity
or graph substrate, or claim RAW loss from a zero typed-record count.

Historical constraints remain in the audit and KB: entity aggregation,
dossiers and decomposition did not establish the desired gains; identity
folding had no alias-candidate fuel in its recorded probe. Restoring indiscriminate
regex triples or enabling a parked ranking lever is not an M1 conclusion.
No LoCoMo score, generalization result, fixed defect or independent reproduction
is established by these synthetic diagnostics.

## Benchmark readiness: what is and is not ready

| Stream | Current evidence / next exit |
| --- | --- |
| M0 | Roadmap and original request register merged in PR #261. |
| M1 | Audit and reproducible observations prepared/committed on this branch; independent review and integration remain. |
| B1 | Metadata/signature/compatibility design not produced here. Inspect current BIL-0/1/2 support before designing BIL-3. |
| E1 | Campaign contract, direct Anthropic verification, selected model roles and spending limits not completed here. No current balance or authenticated model access was verified. |
| E2 | No paid provider/harness smoke run here. It follows E1's documented limits. |
| M2 | Select the architecture after M1 evidence, B1 metadata and E1 evaluation design. Provider access and P0 discovery do not block design. |
| M3 / M4 | No segmentation or temporal-entity implementation in this slice. M3 first; M4 uses the adopted contract and validated M3 output. |
| B2 / M5 | No BIL-3 implementation or integrated baseline/candidate campaign here. Follow their roadmap dependencies. |
| P0 / P1 / P2 | Canonical report routing and a public publisher exist. The remembered external record directory and both formal reusable report templates are not fully qualified by this work. Website delivery still needs release review and live proof. |

Recommended next parallel design work, when a main session permits delegates:
B1 owns the reproducibility metadata contract; E1 owns provider/campaign
design and bounded limits; M1 review owns checking the findings against the
spec. Keep ownership disjoint. This side conversation explicitly prohibits
subagents; do not dispatch them here.

Before any paid smoke, E1 must name the dataset/hash/split, baseline/comparator,
answerer/judge and model roles, context budget, metrics and uncertainty,
retry/abort rules, per-run/campaign ceilings and spend-artifact routing.
Reported credit is not verified balance. An Anthropic lane with different
models/judges cannot be compared to a published Mem0 score as matched
conditions. PR #249's Mem0 beta remains separate from the benchmark baseline.
No secret should be requested in chat or committed to set this up.

The fourteen original requests, including Sleep/Daydream, operator control,
plug-and-play use, inspectable graphs and the two report formats, remain in
the roadmap request register and
[the predecessor handoff](2026-09-12-memory-formation-roadmap.md).
Later consolidation and UI ideas do not replace the opening chunking priority.
Existing Codex session-learning `/sleep` work is a separate workstream.

## Build, privacy and test evidence

The following command completed against the publisher slice:

`python -m pytest tests/audit/test_report_site.py tests/audit/test_report_publication_safety.py tests/audit/test_report_deployment_boundary.py tests/audit/test_secret_scan.py -q -o addopts= -p no:cacheprovider`

Observed output: `48 passed in 1.59s`, without skips. The deployment-boundary
test first failed with the absent deployment job, then passed after the guarded
workflow was added; the existing bounded session record preserves this and
earlier witnessed cycles. Scoped Ruff and actionlint 1.7.12 passed.
M1's separate focused verification commands and their results are in its audit;
no broad-suite success is claimed here.

The actual one-report catalog exported successfully and was built with the
cached official Jekyll Pages image v1.0.13. Its report route, source revision,
download digest, sole Atom entry and all local links passed verification.
The public-artifact gate scanned all 11 generated files with no exclusions.
Desktop and narrow Chrome screenshots were inspected. New report content is
readable in both; no claim about unexecuted browser interaction tests follows.

The first empty-catalog local container build failed on double-slash paths;
using `/work` fixed it. The current report build reused the stopped corrected
container. The earlier broad audit's inherited hook-test failure remains
recorded in HISTORY#646 and tracked by GitHub issue #260; it was not silently
fixed or relabelled as a green suite.

Local preview: `http://127.0.0.1:8774/Seam/`, with the M1 page under
`reports/2026-09-13-memory-formation-m1/`. It serves only a sanitized artifact
outside the repository. Screenshots and the artifact are under the operator's
preview store `seam-reports-m1-20260913`; the earlier empty preview on 8773
is a separate stale artifact. Neither URL is a public deployment.

## Release and publication closeout

1. Locate this branch's draft PR and reconcile its exact pushed head. The
   prepared source checkpoint above is not a release receipt. Required
   GitHub checks last verified from the main ruleset were `repo-hygiene`,
   `chroma-real-smoke` and `locomo-quickstart-bil2`; main requires an up-to-date
   PR. Record advisory matrix failures separately and fix any caused by this
   publisher slice.
2. In a session that permits independent agents, follow
   `docs/SOP_AGENT_ORCHESTRATION.md`: independent assurance, then release on
   the exact-state request. Its current TDD assessment is `TDD_UNPROVEN` for
   the audit helper named above, despite the existing focused tests passing.
   Resolve that concrete condition without inventing evidence. Validate and
   store the independently produced receipt. This author did
   not delegate or author an independent acceptance receipt. A queued request
   is not qualification; use the session base `614141c5...`, not clean HEAD,
   to capture the complete committed publisher delta.
3. Keep the PR draft until qualification and current required checks pass.
   Merge by the protected path with the expected head. Ensure the pinned
   source commit remains fetchable: it is an ancestor in this branch; merging
   with a merge commit preserves that lineage directly.
4. The Pages workflow publishes only a nonempty admitted catalog from main,
   after all checks and the full-artifact privacy scan. PR builds do not
   upload. Only deployment has Pages write/identity permissions; deployment
   concurrency is `pages`. No manual upload from private working directories.
5. Wait for the actual deployment result. Verify the public library, report
   route, About page, feed, manifest and downloaded edition/hash at
   `https://canticle-ai-research.github.io/Seam/`. The last pre-publication
   HTTP check returned 404 and the API listed no Pages deployments. A docs
   merge alone is not proof the website is live.
6. Record the verified deployment and update operating status. New completed
   studies/tests get their own canonical source and reviewed pinned public
   edition; corrections are successor reports, not silent historical rewrites.

## Workspace and GitHub bookkeeping

- Working branch: `feat/seam-reports-pages-20260912`, originally based on
  protected main `614141c5...`. It contains site preparation #646-648,
  publication authorization/M1 integration #649, approved redaction/source
  checkpoint #650, and this catalog/handoff #651.
- The separate `audit/memory-formation-m1-20260913` worktree contains its own
  uncommitted local #646. Its audit, observation artifact and helper have been
  carried into this publication branch, with the report registered here by
  #649. Do not merge its conflicting derived history mechanically or delete
  it without reconciling and preserving any subsequent unique work.
- Primary checkout `docs/deep-audit-20260829` remains behind main with unrelated
  dirty history/index/stream, audit/handoff and local orchestration files.
  Apart from the specifically approved URL redaction, those edits remain
  untouched and outside this PR.
- Sleep-learning, audit-cleanup and pretool-hook worktrees remain independent.
  A scoped push may use the documented one-push dirty-worktree exception to
  preserve them, with all content/signature/continuity checks still enforced.
  Do not clean them by force to satisfy a push gate.
- Two stopped task containers remain: `seam-reports-publish-check-20260913`
  and `seam-reports-publish-check-20260913-v2`. The deletion guard rejected
  their removal. They are not running services; cleanup needs its own valid
  authorization. No host configuration was changed to bypass the guard.
- GitHub issues #259 (roadmap execution) and #260 (closeout-hook test alignment)
  were still open at this checkpoint. PRs #249, #230 and #213 remain separate;
  this publication work does not close or qualify them.
- Draft PR #264 holds this publication/handoff work. Keep it draft until
  independent review, the recorded TDD condition and current required checks
  are resolved. Publication authorization is already granted.
- Keep any pending release request accessible until qualified. Finish owned
  worktree/branch cleanup after the review and merge, preserving the external
  preview and any required ignored receipt state. Never abandon an unrecorded
  dirty tree or claim that a local-only handoff is merged.

## Successor instruction

Read this indexed handoff, verify live branch/PR/check state, and finish
independent qualification plus the first report deployment. Then use the
memory-formation roadmap to review M1 and complete B1/E1 design and provider
preparation. Keep paid execution behind its explicit campaign limits. Preserve
all fourteen roadmap requests, the fresh-start publication boundary and
honest distinctions between diagnostic evidence, implementation and measured
benchmark results.
