# SEAM Skills Compiler — Phased Execution Plan

**Status:** Compiler plan plus Skill Knowledge Runtime MVP branch candidate.
**Track:** L — Skills Compiler.
**Extends:** `docs/roadmap/AGENT_COMPILER.md` Phase 4A (H1, H2, H5) and `docs/roadmap/SKILL_FACTORY.md`.

This doc is the *how* for Track L. `AGENT_COMPILER.md` defines *what* the compiler must do (H1–H5). `SKILL_FACTORY.md` defines the adaptive observation/proposal/promotion loop on top of it. This doc lands the work in reviewable phases without duplicating either spec.

## Skill Knowledge Runtime MVP

The branch-candidate `seam_runtime.skills.kb` package keeps complete skill instructions
outside ordinary model context until deterministic discovery and policy
validation select a bounded activation chain. Its portable core has no
dependency on SEAM memory, storage, server, knowledge-graph, or repository
continuity modules.

The canonical flow is:

1. `seam skills index --root LABEL=PATH --output skilldb.json` (or use
   `--markdown-root LABEL=PATH` for external `SKILL.md` catalogs whose sibling
   YAML files are configuration, not skill manifests; also available
   through the non-conflicting `seam-skills` executable) ingests bounded
   `skills/source/*.yaml` and external `SKILL.md` packages into an immutable,
   deterministic SkillDB snapshot with SHA-256 source provenance. Indexing also
   writes a compact `.index.json` metadata projection so discovery does not
   deserialize or tokenize complete instructions.
2. `seam skills find skilldb.json "query"` searches compact lexical and facet
   projections without returning full instructions.
3. `seam skills plan skilldb.json --skill LABEL:NAME --task "..."` closes
   requirements, validates ordering/conflicts and host capabilities, then emits
   a stable `ActivationPlan` plus a complete `SkillFrame` budgeted with an exact,
   fingerprinted `tiktoken` encoding.
4. `seam skills graph skilldb.json --output graph.html` writes either the JSON
   graph payload or a self-contained HTML visualization. Supplying `--plan`
   highlights the active chain.

`--window PATH --expected-revision N` lets a cooperating host atomically persist
an `ActiveSkillWindow` with pinned and rotating skills. This adapter only stores
revisioned frame state. It does **not** mutate a model's system/developer context,
and ordinary CLI or MCP output must not be described as privileged-context
injection. A host must explicitly read the frame and place it at an authorized
context boundary.

The Skill Knowledge Runtime code is a branch candidate on
`feat/skill-knowledge-runtime`; it is not shipped on `main` until its PR merges.
Older compiler-plan material harvested from
`claude/seam-trust-security-manual-8mhEL` remains historical design context.

## Hard rules

1. Read these files first, in this order, before changing any code:
   - `AGENTS.md`
   - `PROJECT_STATUS.md`
   - `REPO_LEDGER.md`
   - `HISTORY_INDEX.md`
   - `docs/CODE_LAYOUT.md`
   - `docs/DATA_ROUTING.md`
   - `docs/roadmap/AGENT_COMPILER.md`
   - `docs/roadmap/SKILL_FACTORY.md`
   - `CLAUDE.md`
   - All existing installed skill adapters under `.opencode/skills/*/SKILL.md`

2. Do not duplicate the canonical spec. `AGENT_COMPILER.md` already defines H1 (compiler), H2 (model profiles), H3 (benchmarks), H4 (optimizer), H5 (sync/audit). This doc adds the phase ledger only.

3. Do not depend on Track K commands that do not exist yet. `seam trust report`, `seam secrets scan`, `seam audit log`, `seam audit verify`, `seam redact preview` are not callable in any Phase 1–7 deliverable here.

4. Do not add cryptographic signing or Merkle proofs in v1. Provenance v1 is plain SHA-256 over a fixed field set (see Decision 3). Signing is provenance v2 and will be its own ticket with key-management policy.

5. One phase per PR. SEAM's history protocol breaks under mega-commits. Each phase = one PR + one HISTORY entry + one verify cycle.

6. `AGENTS.md` is not SkillIR input. Canonical skill source is structured YAML in `skills/source/*.yaml`. `AGENTS.md` is protocol prose.

7. Never hand-edit `HISTORY_INDEX.md`. Always rebuild via `python -m tools.history.rebuild_index`.

8. No secrets, no session URLs, no `.env` values in commits, history, snapshots, or docs. Per `CLAUDE.md`, redact or delete locally and stop if any are found in the working tree.

9. Aliases before removals. Do not rename or remove existing CLI surface. Add new commands additively.

10. Per-phase closeout discipline. Every phase ends with:
    - `HISTORY.md` append (changed files, success/failure facts, verification performed, unresolved next step)
    - `HISTORY_INDEX.md` rebuild via repo tools
    - one validated snapshot
    - `python -m tools.history.verify_continuity`
    - `python -m tools.history.verify_routing` if route classification changed
    - `python -m tools.history.verify_integrity` before closing

## Phase 0 decisions

These four decisions block every later phase.

### Decision 1 — Canonical source vs compile target

The existing files under `.opencode/skills/` are **compile targets**, not canonical source. Their intent is lifted into structured specs at `skills/source/*.yaml` as each is needed. Existing files become the audit baseline against which generated outputs are compared.

Reasoning: `AGENT_COMPILER.md` H1 SOP step 1 names `skills/source/*.yaml` as canonical. The `.opencode/skills/` files are one harness's preferred shape; treating them as canonical would couple the source format to one harness and defeat multi-target rendering.

Per-skill phase assignment:

| Existing skill | Future canonical source | Phase |
|----------------|-------------------------|-------|
| `seam-session-closeout` | `skills/source/session-end.yaml` | 1 |
| `seam-repo-navigator` | `skills/source/repo-navigator.yaml` | post-6 |
| `seam-architect` | `skills/source/architect.yaml` | post-6 |
| `seam-implementation-planner` | `skills/source/implementation-planner.yaml` | post-6 |
| `seam-implementation-executor` | `skills/source/implementation-executor.yaml` | post-6 |
| `seam-test-hardener` | `skills/source/test-hardener.yaml` | post-6 |
| `seam-roadmap-ledger-updater` | `skills/source/roadmap-ledger-updater.yaml` | post-6 |
| `seam-skill-sync-auditor` | `skills/source/skill-sync-auditor.yaml` | post-6 |
| `seam-github-publisher` | `skills/source/github-publisher.yaml` | post-6 |

Only `session-end` is in scope for Phases 1–7.

### Decision 2 — Output locations

Mixed. Each target profile declares its output destination.

| Target | Generated path (pre-apply) | Installed path (post-apply) | Tracked in repo? |
|--------|----------------------------|-----------------------------|------------------|
| Claude (OpenCode) | `skills/generated/claude/<skill>/SKILL.md` | `.opencode/skills/seam-<skill>/SKILL.md` | Yes |
| Cursor | `skills/generated/cursor/<skill>/<skill>.mdc` | `.cursor/rules/seam-<skill>.mdc` | Operator-local |
| Claude Code (`~/.claude/skills/`) | (same as OpenCode generated) | `~/.claude/skills/seam-<skill>/SKILL.md` | Operator-local |
| Generic markdown | `skills/generated/generic/<skill>/<skill>.md` | (operator-controlled) | Generated only |

### Decision 3 — Provenance v1 scope

Plain SHA-256 over a fixed field set. No signing, no Merkle, no external attestation in v1.

v1 fields embedded in every generated artifact (and in the HS/1 surface in Phase 7):

- `source_spec_sha256` — SHA-256 of `skills/source/<skill>.yaml`
- `model_profile_sha256` — SHA-256 of the target profile YAML
- `compiler_version` — semver from `seam_runtime/skills/__init__.py`
- `generated_at` — ISO-8601 UTC
- `git_sha` — `git rev-parse HEAD`, or `unknown`
- `target` — e.g. `claude`, `cursor`
- `skill` — e.g. `session-end`

Provenance v2 (signing / Merkle / transparency log) is a separate workstream that lands only after Track K's audit primitives exist.

### Decision 4 — Track placement

Track L, per `AGENT_COMPILER.md`. Track K supplies primitives the Skills Compiler optionally consumes in Phase 7. The Skills Compiler is **not** "the flagship of Track K."

## Phase ledger

| Phase | Title | Status |
|-------|-------|--------|
| 0 | Decisions doc (this file) | done — concept landed in roadmap consolidation PR |
| 1 | SkillIR + first canonical source spec (`session-end.yaml`) | planned |
| 2 | First renderer (Claude profile) + sample output + provenance header | planned |
| 3 | `seam skills compile` CLI | planned |
| 4 | Second renderer (Cursor profile) | planned |
| 5 | `seam skills audit` (read-only) | planned |
| 6 | `seam skills apply` (gated, opt-in) | planned |
| 7 | HS/1 attestation wrap + `seam skills verify` | planned |
| 8+ | Optimizer (H4), benchmark suite (H3), Track K integration | deferred |

Each row's status updates to `done` and is annotated with its HISTORY entry id when the corresponding PR lands on main.

## Anti-patterns explicitly rejected

These are restated so they cannot be rediscovered as "new ideas" mid-build:

- Combining multiple phases into one commit
- Adding Merkle proofs or ed25519 signing in v1
- Hooking into `seam trust report`, `seam secrets scan`, `seam audit log`, or any other Track K command before it exists on main
- Treating `AGENTS.md`, `REPO_LEDGER.md`, `PROJECT_STATUS.md`, or `HISTORY_INDEX.md` as direct SkillIR input
- Writing to `.opencode/skills/` without explicit `--confirm` and an apply HISTORY entry
- Calling the work a "Track K flagship"
- Hand-editing `HISTORY_INDEX.md`
- Creating empty README placeholders in `docs/security/` or `docs/contracts/`
- Adding a dashboard panel before Phase 7 lands
- Replacing the adaptive loop in `SKILL_FACTORY.md` with a static compile-and-forget pipeline

## Reconciliation note

This doc supersedes the two-file split (`SKILLS_COMPILER_BRIEF.md` + `SKILLS_COMPILER_PLAN.md`) used on the work branch. The brief's hard-rules and phase definitions, and the plan's decision table, are merged here. The work branch itself is *not* being merged in this PR — only the harvested concept and phase ledger.
