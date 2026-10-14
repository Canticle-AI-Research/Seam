# TestPyPI-first package migration

[Product map](PRODUCTS.md) · [Packaging status](status/packaging-licensing.md)

HISTORY#642 records the operator's requirement: test the renamed public
distribution on TestPyPI before any production PyPI publication. Production
uploads, legacy-release deletion, and private SDK uploads are excluded from
this preparation pass.

## Package boundaries

| Name | What it identifies | Test destination |
| --- | --- | --- |
| `seam-suite` | Self-hosted runtime, TUI, benchmark glassbox, and browser graph dashboard | Local candidate first; TestPyPI only after exact public artifact review |
| SEAM Client | Paid API service and its all-in-one WebUI | Service staging environment, not a replacement payload for the Python client wheel |
| `seam-client` | Existing Python HTTP client for the service | Separate client release process after source/owner recovery |
| `seam-sdk` | Private SDK for paying users | Local test environment or authenticated private distribution; never PyPI or TestPyPI |

The root candidate is `seam-suite` 2.4.1rc1. It keeps the existing `seam` and
`seam_runtime` imports and console commands. Install it in a fresh environment;
do not co-install older distributions that own those same paths. The candidate
includes the server/TUI dependency set by default. `[server,dash]` remains a
compatible extra selection rather than a prerequisite for normal operation.

## Current blockers

- The candidate's private-upload tripwire is removed after independent review
  of the owner-authorized Suite membership and installed behavior. The
  [manifest guard](../tools/release/verify_suite_manifest.py) checks exact source
  and archive membership; the license terms remain unchanged. Rebuild and
  verify the exact final files after a metadata change. Publisher access,
  uploaded-file verification, and broader product acceptance remain separate;
  archive scans alone do not establish them. Keep files local until the exact
  candidate and TestPyPI publishing access qualify.
- No authenticated TestPyPI publisher was established in this preparation
  session. A GitHub repository connection is not TestPyPI project ownership.
- The GitHub release workflows accept canonical Python versions, including
  `2.4.1rc1`, while retaining their operator and exact-artifact controls. They
  do not upload to TestPyPI; do not dispatch them as a test-registry upload.
- TestPyPI project names and ownership are independent of production PyPI.
  A missing project page does not prove registration eligibility.

TestPyPI is public. It is not an access-controlled registry and is not a safe
destination for the private SDK. Its database may be pruned. See the
[official TestPyPI guide](https://packaging.python.org/en/latest/guides/using-testpypi/)
and [PyPI private-package guidance](https://pypi.org/help/#how-can-i-publish-my-private-packages-to-pypi).

## Verification before any test upload

The current Suite personal-use membership is identified by
[the reviewed manifest](../LICENSES/SEAM-Suite-manifest.json) and
[license](../LICENSES/SEAM-Suite-Personal.txt). The owner has authorized completing
this TestPyPI-first candidate. Publishing access and verification of the exact
actual files remain prerequisites; production publication is separate. A
changed implementation requires refreshed membership review.

1. Build a wheel and sdist from the reviewed source in an isolated build
   directory. Record the source commit, package name/version, and both SHA-256
   hashes. Run `python -m twine check --strict` on those exact two files.
2. Run `python -m tools.release.verify_private_artifacts --expected-name
   seam-suite --expected-version 2.4.1rc1` with the exact wheel/sdist paths.
   Inspect the archive member inventory and license notices. Scanner success
   does not supersede the public membership decision above.
3. Install the exact wheel with its default dependencies in a fresh environment outside
   the source tree. Check dependency consistency, command help, installed
   module origins, MCP version/discovery, and write-then-read persistence.
   Keep test data separate from operator databases. Preserve old environments
   and backups; this is not an arbitrary legacy-upgrade qualification.
4. Bind qualification to the reviewed member inventory and exact hashes.
   The current candidate's classifier change follows independent source and
   installed-package review; verify the rebuilt files rather than uploading
   the earlier private-classifier archives. A future eligibility change needs
   its own review.
5. Configure only TestPyPI-specific publishing access. Prefer a narrowly bound
   GitHub OIDC publisher; never reuse a production token. Store credentials in
   the approved secret store, never in chat, source, reports, or artifacts.
6. The upload mechanism must use the explicit endpoint
   `https://test.pypi.org/legacy/`, an exact two-file list, and noninteractive
   operation. It must reject unexpected package names/versions, private SDK
   members, hash mismatches, and unapproved artifacts. Do not use a default
   Twine destination, upload globs, or production-workflow fallback.
7. Verify the TestPyPI project and downloaded file hashes. Install from
   TestPyPI in another clean environment and repeat the smoke checks. Obtain
   dependencies separately from the intended trusted index; do not combine
   public and private indexes indiscriminately.
8. Record test results and remaining limitations. Stop at the test registry.
   Production publication is a separate decision and cannot be inferred from
   a passing test upload, package rename, or a merged documentation PR.

## Private SDK delivery

A private registry serves versioned Python packages only to authenticated,
authorized customers. Customer entitlement, download credentials, revocation,
retention, and package integrity need an explicit service contract. Revoking
access stops future downloads; it cannot recall code already delivered.

The private `Seam_SDK` repository remains the source boundary until private
artifact delivery is selected and qualified. Do not publish a placeholder
public SDK package, copy private SDK source into Suite, or put access tokens
in install examples. SDK compatibility and its runtime dependency remain a
separate private workstream.
