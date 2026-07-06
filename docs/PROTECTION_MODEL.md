# SEAM Public Core Boundary

This document explains how SEAM Runtime can keep an Apache-2.0 public core while
holding hosted, enterprise, customer-specific, and unreleased implementation
details under separate access control.

`LICENSE`, `NOTICE`, and `COMMERCIAL_LICENSE.md` remain the controlling public
license, notice, and commercial-boundary files. This document is an operating
model for repo structure and agent workflow.

## Goals

SEAM should:

- keep the public core installable and usable under Apache-2.0;
- keep the existing CLI, dashboard, REST, MCP, benchmark, and history workflows intact;
- preserve the repo bookkeeping protocol in `AGENTS.md`, `PROJECT_STATUS.md`, `REPO_LEDGER.md`, `HISTORY.md`, `HISTORY_INDEX.md`, and `docs/CODE_LAYOUT.md`;
- avoid adding startup context bloat for future agents;
- make the public-core/private-module boundary obvious to readers and contributors; and
- keep advanced commercial modules, private benchmark holdouts, enterprise connectors, hosted-service code, and unreleased methods outside the public source tree unless intentionally released.

## Public core boundary

The public core repository is the Apache-2.0 distribution and contribution
surface. It may include:

- the installable local runtime;
- CLI and operator workflows;
- public documentation;
- public regression tests and benchmark harnesses;
- public adapters and examples;
- public protocol docs; and
- policy files that explain licensing, contribution, security, and commercial
  boundaries.

Apache-2.0 permits use, modification, redistribution, and commercial use of the
public core under the license terms. It does not grant trademark rights or
access to code, services, credentials, data, private repositories, hosted
deployments, enterprise modules, or unreleased methods outside this repository.

## Private/commercial boundary

Private or commercial repositories may hold:

- private benchmark holdouts;
- advanced compression or retrieval experiments before release;
- enterprise-only connectors;
- hosted-service deployment code;
- customer-specific integrations;
- confidential pitch material;
- unreleased architecture notes; and
- any implementation detail that should remain a trade secret or commercial-only module.

Moving future work into a private repository only protects future non-public
code. It does not retract Apache-2.0 rights already granted for public core code
that has been released.

## Public mirror sync mechanism

`tools/release/public_manifest.py` is the fail-closed source of truth for
what may leave this private repo via the `seam-runtime` git remote. Two
disjoint categories:

- **Synced paths** (`is_public_synced_path`): copied verbatim from private
  `main`'s current tree on every sync -- the installable runtime, tests,
  installers, and public-facing docs.
- **Owned paths** (`is_public_owned_path`): `HISTORY.md`, `HISTORY_INDEX.md`,
  `PROJECT_STATUS.md`, `REPO_LEDGER.md`, and `.seam/`. These are the PUBLIC
  repo's own independent bookkeeping trail, seeded once from
  `tools/release/public_seed/` and never overwritten by later syncs -- the
  private repo's actual internal incident log, competitive research, and
  strategy notes never reach the public repo through this path.

`tools/release/sync_public_mirror.py` builds one new commit on top of the
mirror's current tip from those two categories combined (fast-forward; it
never rewrites the mirror's existing history). `tools/release/verify_public_safe.py`'s
pre-push hook enforces the same allow-list as a fail-closed backstop against
anything that bypasses the sync script (e.g. a raw `git push seam-runtime
main:main`).

This replaced an earlier deny-list-only gate (secret/credential shapes and a
handful of disallowed paths) that failed *open*: any private file that
wasn't secret-shaped shipped anyway, which is how internal bookkeeping
(`HISTORY.md`, `docs/audits/`, etc.) ended up mirrored to the public repo
since its creation. That already-public history was not retroactively purged
when this router was introduced (a decision requiring a force-push on the
public repo, deferred pending explicit review) -- this section governs
*future* syncs only.

Adding a new public-facing file or directory requires adding it to
`public_manifest.py` first; nothing is public by default.

## Agent workflow rule

Do not add this document to the mandatory startup read list unless the task specifically touches licensing, commercial boundaries, contribution policy, repo protection, or public/private separation.

For normal development, agents should continue using the existing startup flow:

1. `PROJECT_STATUS.md`
2. `REPO_LEDGER.md`
3. `HISTORY_INDEX.md`
4. `docs/CODE_LAYOUT.md`
5. targeted `HISTORY.md` entries only when needed

This keeps protection policy visible without forcing future agents to load long legal or policy files during normal runtime work.

## Runtime safety rule

Protection changes must not silently change runtime behavior. A protection-only change should avoid touching:

- `seam_runtime/`
- `seam.py`
- `pyproject.toml`
- installer behavior
- dashboard behavior
- API behavior
- benchmark execution behavior
- history tooling behavior
- active test semantics

If a future protection change needs to alter runtime behavior, it must be handled as an implementation change with tests, history entry, index rebuild, and continuity verification.

## Bookkeeping rule

Protection changes are stable repo policy changes. They should:

- update `REPO_LEDGER.md` with a compact pointer;
- append one `HISTORY.md` entry;
- rebuild `HISTORY_INDEX.md` when local tooling is available;
- write a snapshot when local tooling is available; and
- state skipped verification honestly when changes are made through a connector that cannot run local repo tooling.
