# Suite personal license and artifact review

[Report registry](INDEX.md) · [Packaging status](../status/packaging-licensing.md)

Decision record: HISTORY#651, superseding the unresolved owner decision in
[HISTORY#650's review](2026-09-19-suite-license-membership.md).
Implementation baseline: PR #266 at `2291a76cda0a5af4bf93e22df904f065d5b71579`.

## Owner decision and scope

The owner expressly selected proprietary, personal and noncommercial
self-hosting only. [LICENSE section 7B](../../LICENSE) and the
[personal license](../../LICENSES/SEAM-Suite-Personal.txt) allow an individual
to install, build, configure, run and back up the identified Suite for that
purpose. Business use, including internal deployment and unpaid business
evaluation, requires a separate written agreement through licensing@canticle.cc.

Embedded MIRL/HS/1 operation is permitted only as necessary to run Suite.
Independent reuse, redistribution, derivative implementations and hosted or
embedded services are excluded. Supported configuration, personal learning,
user-owned data and publication of personal benchmark results remain allowed.
The separate paid SDK is excluded. Exact prior Apache/BUSL grants and third-party
rights are preserved; there is no automatic conversion of this personal grant.
This records the selected terms and their implementation, not a legal opinion
on enforceability or ownership of abstract methods.

The [manifest](../../LICENSES/SEAM-Suite-manifest.json) binds the grant to
109 exact runtime file versions by path and SHA-256, including MIRL and surface
implementation. No runtime file or historical BUSL text was changed. The
previously reported BUSL closing-text discrepancy remains unresolved for that
historical license lane; it is not the basis of this new grant.

## Artifact verification

`uv build --quiet --out-dir` produced the candidate wheel and sdist named below.
Python `zipfile`/`tarfile` regular-member inspection found that each contains
all 109 manifest runtime members, identical to source. All seven declared
license files match current repository bytes. Both metadata records use
`LicenseRef-SEAM-Suite-Personal-1.0` and retain `Private :: Do Not Upload`.
The [observation record](evidence/2026-09-19-suite-license/personal-artifacts.json)
includes exact hashes, license-file lists and dependency metadata.

Twine strict validation and `tools.release.verify_private_artifacts` passed
for this pair. The existing focused audit modules
`tests/audit/test_github_issue_release_config.py` and
`tests/audit/test_mcp_registry_release.py` passed together under pytest.
After independent installation of each candidate into its own Python 3.12
environment, `python -I tests/package/smoke_installed_suite.py` passed its
four checks per environment: installed/default dependency imports, CLI entry
points, TUI mount, and HTTP health/packaged UI. These are startup checks, not
full product or benchmark qualification. No runtime behavior changed in this
licensing slice; no new runtime test was introduced.

Independent review confirmed exact manifest hashes and grant precedence, and
caught an overbroad unpaid-trial sentence; the final wording excludes unpaid
business trials while preserving personal experimentation. Current docs and
metadata now describe the selected personal grant.

## Delivery limits

This remains draft PR #266 work. The cumulative `NOT_QUALIFIED / TDD_UNPROVEN`
condition and required CI are separate from this scoped verification. TestPyPI
publisher setup, final release approval and destination qualification remain
open. No package publication, MCP registration, protected merge, paid call or
production deployment occurred. Unrelated checkout/worktree state is preserved
as listed in the [handoff](../handoffs/2026-09-19-suite-personal-license.md).

Website draft PR #29 at `13a40ea1b44a6e11f3c56daf9f3077324ee08bc9`
aligns current product copy. Its focused checks pass; broader baseline failures,
email-worker failure and owner visual acceptance remain recorded in that PR.

## Evidence manifest

| Raw artifact | SHA-256 |
| --- | --- |
| `docs/audits/evidence/2026-09-19-suite-license/personal-artifacts.json` | `11537381b5ef931af595145477bde2b957c7cb07a155a8491c23a2277142c31a` |
| `/home/terrabyte/LLM-Logs/codex/releases/20260919-personal-suite/reviewed-artifacts/seam_suite-2.4.1rc1-py3-none-any.whl` | `f357ed2ba889b9b21138a779d93a36847c0692537e087176cbd972735fdc5b23` |
| `/home/terrabyte/LLM-Logs/codex/releases/20260919-personal-suite/reviewed-artifacts/seam_suite-2.4.1rc1.tar.gz` | `89702adefaedd38b14b6693e6548e6ee1d31fc42529959729d793b5653b3e297` |
