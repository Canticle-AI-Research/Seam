---
handoff_id: 2026-09-18-roadmap-fork-reconciliation-next
supersedes: 2026-09-14-claude-code-benchmark-next
handoff_status: superseded
history: HISTORY#647
---

# Roadmap fork reconciliation and the formation ready set

## Start here

The [detailed formation roadmap](../roadmap/MEMORY_FORMATION.md) remains the
execution authority, including all fourteen original requirements, Sleep and
Daydream, and the graph/reporting direction. Nothing in this handoff changes
that priority, starts a research lane, or advances a formation stream.

This handoff exists because the registered chain had fallen behind the live
repository. The predecessor
[`2026-09-14-claude-code-benchmark-next`](2026-09-14-claude-code-benchmark-next.md)
recorded dispositions for `#264` and the merged provider branch, which remain
accurate. Three pull requests opened after it were unregistered, and two of
them add overlapping research tracks that cannot both merge as authored. The
[reconciliation audit](../audits/2026-09-18-roadmap-fork-reconciliation.md)
carries the evidence for every claim below.

## What this delivery covers

Documentation and continuity only: one dated audit, this handoff, the registry
and status updates, the HISTORY entry and the derived-stream rebuild. No
runtime code, roadmap registration, benchmark, provider configuration,
website or deployment changed. No open pull request was modified, rebased or
pushed to, and no research lane was accepted.

## Live branch state

Observed against protected main `66fd3f93081712871ff827e756026c3e73c71790`.
All open pull requests are drafts.

| PR | head | disposition |
| --- | --- | --- |
| #268 | `ab1bcd348d1a07e3546b77dfe67a5c923253cce7` | `roadmap:track:PCS`; overlaps #267; unregistered |
| #267 | `24e1725134d476798992cc7ecaef7de299d27cc6` | `roadmap:track:LatentCacheBridge`; overlaps #268; unregistered |
| #266 | `9f0bfae2609d7ec587bb8375274ab7e4e63495ea` | packaging/release/MCP repair; unregistered, unexamined |
| #264 | `18abe44236021ba0bfddb78f55d067754c0d42ef` | unchanged head; still `NOT_QUALIFIED`, `TDD_UNPROVEN` for its M1 helper |
| #249 | `8d77775fe6e029717115758b917c94c757ed0d4a` | mem0 2.0.0b2; must not silently move the benchmark baseline |
| #230 | `6313f851c2cf68ef06350c910f6c9bbf3be13762` | batched embedding; unregistered, unexamined |
| #213 | `4d2609e59ffca85eb2c4c6c4e995e62f545744ec` | vector cache; unregistered, unexamined |

## The fork, and what to do about it

`#267` and `#268` are independently authored lanes over the same prior art.
They are not duplicates: `#268`'s PCS0-PCS10 ladder is the broader frame and
already stages the bridge as PCS7, while `#267`'s LC0-LC8 document is the
deeper mechanism specification and uniquely holds the induction-aware PACK
experiment, the security campaign, the package layout and the extraction
criteria. Discarding either whole loses specification work.

Both patches insert a new track section into the identical gap at
`ROADMAP.md:44-50`, with the same hunk header and leading context. Whichever
merges first, the second conflicts. `#268` also adds a backlog line at
`@@ -2050,6 +2081,7 @@` that `#267` has no counterpart for, so a careless
conflict resolution can register one track in the header and the other in the
backlog.

The recommendation is to reconcile them into **one** registered track before
either merges: retain the PCS frame, fold the branch-only
LATENT\_CACHEBRIDGE.md document in as the referenced PCS7 mechanism
specification, and drop the second `seam:item` marker. One priority and phase value must be chosen; the branches declare
3/0 and 4/2. This is a recommendation, not an executed decision — the operator
owns which lane carries the registration.

Neither lane may displace the formation ready set. Request R14 keeps the
opening formation priorities dominant, and both documents accept a parallel,
non-displacing role. Registering a planned lane is cheap. Beginning PCS0 or
LC0 before M1 acceptance, the B1 metadata contract and the E1 evaluation
design would invert the dependency order the formation roadmap sets.

## Roadmap stream drift is unenforced

`ROADMAP.md` carries 66 `seam:item` markers and `.seam/streams/roadmap/state.md`
lists 66 items, so they agree at this commit. Nothing enforces that:
`tools/streams/verify_streams.py` contains zero roadmap references. The
Session End instruction to rerun `tools.streams.roadmap_parser` is enforced by
no local gate and no required CI check.

Either research PR can therefore merge a new marker and leave `state.md` one
track short. Because `AGENTS.md` directs agents to read `state.md` **instead
of** `ROADMAP.md`, the drift would be invisible exactly where the next agent
chooses work. Adding marker-to-stream drift checking to `verify_streams` is
proposed as a separate change and is not performed here.

## The formation ready set is unchanged

M2 still requires all three of M1 findings, the B1 metadata contract and the
E1 evaluation design. Of those:

- **M1** is blocked on `#264`'s independent acceptance condition. The audit
  recommends splitting that PR: its 38 files bundle the M1 audit and evidence
  with a Pages report site, a deployment workflow, three test modules and two
  tool packages, while the `TDD_UNPROVEN` condition attaches to
  its branch-only helper tools/memory\_formation\_m1.py alone. Separating the
  audit and evidence from the helper and the site resolves M1 without waiving
  the condition. Passing new tests still cannot invent the missing historical
  red phase.
- **B1** is unblocked and now has recorded specification input: five BIL-2
  integrity gaps are documented in the audit's Finding 5, including a keyless
  verification path that can return `PASS` on forged content and a symmetric
  signature that cannot support third-party attestation. The operator directed
  that these be **recorded in B1 and repaired under B2**; no runtime change was
  made.
- **E1** is unblocked. The transport merged through `#265`. The mechanical
  pieces already exist — `--split dev/holdout` backed by
  `tools/h2/holdout_split.py`, and `_fixture_hash` in the LoCoMo runner. What
  is missing is the frozen written contract: dataset version and hash, the
  development/holdout partition, baseline SHA, answerer/judge protocol,
  retrieval configuration, character and token budgets, metrics, the
  uncertainty and no-change controls, and campaign cost ceilings.
- **P0** overlaps `#264`'s report-site work and should not be started
  independently until that PR's disposition is settled.

A paid development baseline with unchanged formation must still be retained
before the first candidate. The successful provider smoke is connectivity
evidence and does not substitute for it.

## Spend and billing boundary

Unchanged from the predecessor handoff, and no calls were made here. The
roughly $50 on Claude.ai is not an instruction to consume it. Use the explicit
`claude-code` transport; the `claude` choice is the separately billed API
route and the two must never be silently mixed within a baseline/candidate
comparison. CLI-reported usage is not verified account debit. A full campaign
needs its own documented bounded selection and allowance under E1.

## Verification performed

The canonical preflight is **eight** gates, not the six named in the
`AGENTS.md` Session End list: `tools/git-hooks/pre-commit` and
`tools.history.closeout` both also run `verify_agent_config` first and
`verify_audit_claims --changed-since HEAD` last. All eight pass on this
delivery.

Two environment notes, neither a defect in main. `verify_continuity` reports
no snapshot for the latest entry on a fresh clone because
`.seam/snapshots/*.json` is gitignored (`.gitignore:70`) with only `.gitkeep`
tracked; the snapshot is written locally at session close. `verify_wiki`
requires the declared `lint` extra `markdown-it-py`, absent from a bare
container; with it installed the gate reports 276 active pages reachable.

`verify_audit_claims` initially rejected four citations in the new audit to
files that exist only on `#264` and `#267` heads. That is the gate working as
intended: those paths are branch-only and are now written as branch-qualified
plain text rather than repository citations.

Targeted test slice: `tests/audit/` modules covering handoffs, wiki
navigation, closeout, local-gates-match-CI, status streams, stream content
hashing, substream isolation and PR gates. One **pre-existing** failure,
`tests/audit/test_history_closeout.py::test_preflight_gates_match_canonical_commit_hook`,
reproduces identically on a clean `origin/main` worktree and is not caused by
this change; it is unfixed and out of this delivery's scope. The remainder of
`tests/audit/` could not be collected in this container because the runtime
extras (`fastapi` and related) are not installed — 15 modules error at import.
That collection gap is an environment limitation, not an observed pass.

`ROADMAP.md` was deliberately not modified, so the roadmap parser needs no
rerun for this delivery and this branch does not conflict with `#267` or
`#268`. Candidate files were scanned for secret-shaped values and provider
session URLs; none present.

## Open items and cautions

- The three arXiv identifiers cited by `#268` were not independently verified
  against upstream listings. They are internally consistent with the
  repository's date and both documents treat the work as prior art, but the
  citations should be checked before either document is published outside the
  repository.
- `#266`, `#230` and `#213` are recorded above only so the chain stops
  under-reporting live state. Their technical dispositions are unexamined.
- `HISTORY#646` carries `commits: pending`; its merge SHA was never backfilled.
  `HISTORY.md` is append-only, so this is noted rather than edited.
- The reports branch handoff for `feat/seam-reports-pages-20260912` remains
  branch-local with its own HISTORY numbering. Its chronology and registry
  still require reconciliation against main before it can merge; never replace
  main's HISTORY with its branch copy.
- Preserve the operator's unrelated dirty checkouts and worktrees named by the
  predecessor handoff. No stash and no worktree were created by this task.

## Next unresolved step

Decide which lane carries the research registration and whether `#264` is
split. Then take B1 or E1 — both are unblocked, both feed M2, and neither
collides with an open pull request.
