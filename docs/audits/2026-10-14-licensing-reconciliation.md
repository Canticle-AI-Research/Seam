# Current Suite licensing reconciliation

[Report registry](INDEX.md) · [Packaging status](../status/packaging-licensing.md)

Recorded by HISTORY#665. Implementation baseline:
`e4abc1d9c9b1afb415ad67e06a3e7bb6907ecee1` (current protected main at task start).
The recorded owner decision is carried forward from PR #266 at
`8a120381f885cdcfc90b9157bae66ea8b452a99f`; its branch-local history numbers
collide with main and are not imported as main chronology.

## First-launch terms

Suite is proprietary with free personal, noncommercial self-hosting under
[LICENSE section 7B](../../LICENSE) and
[the personal license](../../LICENSES/SEAM-Suite-Personal.txt). Business,
employment, client and organizational use, including unpaid business evaluation,
require a separate written agreement through licensing@canticle.cc.
Embedded MIRL/HS/1 operation is allowed as necessary to run Suite. Independent
reuse, modification, redistribution and hosted/embedded offerings are reserved.
The separate paid SDK is excluded. The personal grant has no automatic
open-source conversion. Supported configuration, builds, user-owned data and
publication of personal benchmark results remain permitted.

The owner clarified this is the current product's first-launch task, with no
known users to migrate. Historical license files remain byte-identical to main;
no BUSL text repair, rollback, legacy installation or user-migration project is
included. Independently applicable and third-party rights are preserved by the
existing savings clauses. Repository termination language explicitly defers the
personal grant to its own termination terms and does not override other grants.

## Current code and artifact membership

[The manifest](../../LICENSES/SEAM-Suite-manifest.json) reuses the recorded Suite
implementation scope and refreshes its path/SHA-256 bindings to exact current
main. Its `implementation_source_commit` identifies the runtime source, rather
than a future licensing commit. Runtime bytes, dependencies, commands, imports
and installation behavior are unchanged in this licensing successor.

Fresh wheel and sdist candidates are built in an external source snapshot under
`/workspace/scratch/seam-license-20261014`. Read-only archive inspection checks
exact implementation membership and hashes, source-identical license documents,
package identity and `LicenseRef-SEAM-Suite-Personal-1.0` metadata. The observation
record below contains exact hashes. Both retain `Private :: Do Not Upload`.
The private paid `seam_sdk` distribution is absent.

## Verification boundary

The existing `tests/audit/test_github_issue_release_config.py` selection passed
under `.venv/bin/python -m pytest ... -q`. Strict Twine metadata validation and
`tools.release.verify_private_artifacts` passed for the wheel/sdist pair.
These checks qualify license membership and metadata for the inspected files;
they are not full product, upgrade, hosted-service or publication qualification.
No runtime change requires a new runtime TDD claim in this scope.

A clean external installation of the exact wheel also passed installed license
metadata and every implementation hash check; its `seam --help` entrypoint
succeeded outside the source tree. The documentation/reference, local-gate
parity and history-closeout test selection passed. The dependency contract,
whitespace check and content-free secret scan passed.

Current licensing copy is aligned at the top and licensing section of README,
CONTRIBUTING, SECURITY, pricing proposal license paragraphs, product/status
pages and active roadmap descriptions. Historical design documents explicitly
route to the current personal terms. GitHub About is updated alongside protected
integration so the repo page does not retain the old BUSL marketing claim.

The documentation safeguard tracks the changed package metadata as a source
revision. Review acknowledgements cover the license-only metadata delta and
unchanged command contract, plus the authored licensing changes; they do not
claim a whole-page audit. Independent assurance and the exact-state continuity
receipt provide separate review evidence before delivery.

## Remaining product delivery

This focused successor avoids pulling unresolved dependency/release/MCP work
from PR #266 into licensing. It neither qualifies that PR's cumulative
`NOT_QUALIFIED / TDD_UNPROVEN` state nor closes it. The companion website PR #29
already carries personal-use copy; its conflicting base, broader checks and
visual acceptance remain website work. There is no package upload, MCP
registration, release, website deployment or paid provider call in this slice.
After licensing integration, the next product step is separate package/TestPyPI
qualification under the current release controls.

## Evidence manifest

| Raw artifact | SHA-256 |
| --- | --- |
| `docs/audits/evidence/2026-10-14-licensing/artifacts.json` | `4451f66893233828c6aa02cb89f38b09a6f7421bb2660d0e2d41b6e1e8b5de54` |
