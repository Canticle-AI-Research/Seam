# Contributing to SEAM

Thank you for considering a contribution to SEAM.

SEAM Runtime's public core is licensed under the Apache License 2.0.
Contributions are welcome for code, documentation, tests, benchmarks, and
project improvement. Contributions must preserve the public-core/private-module
boundary described in `LICENSE`, `NOTICE`, and `COMMERCIAL_LICENSE.md`.

## Read first

Before contributing, read:

1. `AGENTS.md` for the canonical repo protocol.
2. `PROJECT_STATUS.md` for current operating state.
3. `REPO_LEDGER.md` for stable repo decisions.
4. `docs/CODE_LAYOUT.md` for active vs archived paths.
5. `LICENSE`, `NOTICE`, and `COMMERCIAL_LICENSE.md` for license, notice, and
   commercial-boundary terms.

Normal development should stay in active paths: `seam_runtime/`, `seam.py`, `experimental/`, `tools/`, `scripts/`, `installers/`, `docs/`, tests, and root status or policy files.

Do not copy stale code or prose from archived paths back into active paths without rewriting, verifying, and recording the reason.

## Contribution grant

Unless you explicitly state otherwise, any pull request, issue text, code,
documentation, test, benchmark, design, or other contribution intentionally
submitted for inclusion in SEAM Runtime's public core is submitted under the
Apache License 2.0, without additional terms or conditions.

In plain language, you keep copyright you own in your contribution, but the
public core can use and distribute it under Apache-2.0.

Do not submit anything you do not have the right to contribute.

## Pull request expectations

A good PR should:

- explain what changed and why;
- keep active and archived paths separated;
- update `REPO_LEDGER.md` when changing stable repo policy, architecture, routing, runtime safety rules, durable workflows, or cross-agent protocol;
- update `PROJECT_STATUS.md` when changing current operating state or active focus;
- append one `HISTORY.md` entry for material changes;
- rebuild derived history, index, and snapshot artifacts when local tooling is available;
- run relevant tests or clearly state what was skipped and why; and
- avoid duplicating long continuity prose across multiple docs.

## Public-core boundary

Contributions to this repository do not grant access to private SEAM
repositories, hosted services, enterprise modules, private connectors, private
benchmark holdouts, customer-specific integrations, unreleased methods, support,
warranty, indemnity, or trademark rights. Those may be covered by separate
commercial terms outside the public core.
