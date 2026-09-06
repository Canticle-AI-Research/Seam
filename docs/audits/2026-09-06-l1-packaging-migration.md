# L1 packaging and SDK migration preparation

[Back to reports](INDEX.md) · [Launch plan](../roadmap/SEAM_LAUNCH.md)

Decision and chronology: HISTORY#635. This is a packaging preparation
candidate on top of documentation PR #250, not a release qualification.
Runtime source was exported from `25518300eabf95288555ca7794e4e964656a4497`;
its runtime/build files match protected `8834601`. The separate SDK source
was inspected at `294ab08919646a03dcdceb3c777dfd7d8eabc624`.

The operator clarified that **SEAM SDK is private, with access for paying
users**. It is a distinct paid artifact from the public HTTP client. Future
paid capabilities remain unspecified. This packet changes neither existing
license texts nor package metadata, repository visibility, customer access,
or publication controls.

## Ownership and source map

The observations below were refreshed through `gh` and PyPI JSON endpoints
on 2026-09-06. Downloaded PyPI bytes matched their published SHA-256 values.
Repository access is evidence of repository permission, not PyPI ownership.
[Sanitized observations](evidence/2026-09-06-l1/source-ownership-observations.json)
retain command/status results and both published and downloaded PyPI hashes.

| Coordinate | Verified source or access | Unresolved ownership/source work |
| --- | --- | --- |
| `Canticle-AI-Research/Seam` | Public repository; current authenticated GitHub principal has ADMIN permission; protected main `8834601` | Public visibility does not establish eligibility of a new distribution |
| `Canticle-AI-Research/Seam_SDK` | Private repository; authenticated principal has admin/pull/push permission; main `294ab08` | Paying-customer provisioning and a private delivery destination need verification |
| `seam-runtime` 1.3.1 | PyPI wheel and sdist downloaded and hashed; metadata points to `BlackhatShiftey/Seam_Runtime` | PyPI owner access and source recovery unverified |
| `seam-self-host` 1.1.2 | PyPI CPython 3.12 Linux x86-64 wheel downloaded and hashed | No sdist in that release; owner access and supported data-export path unverified |
| `seam-client` 2.0.0 | PyPI wheel and sdist downloaded and hashed; sdist supplies a released source snapshot | Authoritative development repository, ownership and publication authority unverified |
| `BlackhatShiftey/Seam_Runtime` | Authenticated repository lookup returns HTTP 404; the analogous organization coordinate also returns 404 | Cause unknown; do not infer deletion, transfer, or loss of ownership |
| `canticle-seam-{suite,api,client,sdk}` | PyPI project lookups return HTTP 404 | Candidate names only; registration eligibility and ownership are unverified |
| `seam` | PyPI metadata points to the unrelated `seamapi/python` SDK | Excluded as a Canticle distribution coordinate |

The owner-access question remains pending. No credential or private session
link is required to answer it. Downloadability, author metadata, and a local
publisher configuration do not prove owner access. No upload was attempted
as an ownership test.

## Concrete artifact map

The [artifact inventory](evidence/2026-09-06-l1/artifact-inventory.json) records
every inspected wheel/sdist identity, SHA-256, Python requirement, dependency,
entrypoint, and declared license metadata. The
[archive inventory](evidence/2026-09-06-l1/archive-members.json) records every
regular member's path, length, and SHA-256. These are observations of exact
bytes, not a grant of distribution rights.

| Role | Candidate contents and format | Imports and commands | Intended destination and acceptance |
| --- | --- | --- | --- |
| Suite | Start from the existing runtime wheel plus separately resolved `dash` and `server` extras; wheel and sdist built locally for inspection. Proposed name `canticle-seam-suite` remains provisional | Preserve `seam`, `seam_runtime`, `seam`, `seam-benchmark`, `seam-dash`, `seam-tui`, `seam-server`, `seam-mcp` during migration | Owner-approved release destination after exact membership/notices and version approval; current source bundle is not automatically an eligible Suite release |
| Hosted API | Use the same qualified runtime source contract and `server` dependencies; a deployment image and pinned runtime environment remain to be specified | Existing `seam-server`/`seam serve`; opaque `/v1` interface | Operator-controlled hosting; no public server PyPI package is required; no image/deployment was built here |
| Public HTTP client | Existing Apache-2.0 `seam-client` 2.0.0 wheel/sdist as compatibility input; no runtime code included | `seam_client.SeamClient`, `AsyncSeamClient`, agent helpers; no console scripts | Existing public client coordinate until source/owner recovery and a separately approved successor; candidate `canticle-seam-client` |
| Private paid SDK | Separate `seam-sdk` 0.1.0 wheel/sdist built from the private repository; Python >=3.11, `seam_sdk`, typing marker and its existing license | `from seam_sdk import SeamSDK`; no console scripts | Customer-authorized private delivery; candidate `canticle-seam-sdk`; no public PyPI publication or automatic Suite inclusion |

The runtime's existing `seam_runtime.sdk` interface and the separately
packaged paid `seam_sdk` must retain distinct identities. The paid access
decision does not establish a new entitlement mechanism in either package.

### Exact runtime membership and notices

The [runtime membership map](evidence/2026-09-06-l1/runtime-members.json)
matches each wheel runtime file to its source bytes at `2551830` and compares
it with the downloaded GitHub `v2.4.0` wheel. Its `files` array contains 109
runtime paths: 44 unchanged, 39 changed, and 26 added relative to that wheel.
The old `selfhost`, `selfhost_entitlement`, and `selfhost_mcp` modules are absent
from this candidate. These counts exclude wheel metadata and license files;
the complete archive inventory includes them.

All candidate runtime membership rows remain `owner-review-required`.
`LICENSE` defines membership using publication, exact file versions, a
manifest, and conspicuous notices. A bounded byte search found neither
`Business Source License` nor `BUSL-1.1` in the first 2,048 bytes of the 109
runtime files. That search is not a legal classification or proof that all
forms of notice are absent. The wheel does include the five declared license
documents; metadata alone does not settle per-file membership. Preserve those
texts and resolve the map before changing the package boundary.

The downloaded GitHub release targets `01f35817810f1490c88e9f832d92c8f1aab3944d`
and has a wheel and sdist but no `SHA256SUMS.txt` asset. Its wheel differs from
the newly built candidate despite both identifying as `seam-runtime` 2.4.0.
Treat `v2.4.0` as immutable historical input; choose a fresh version for any
successor. This local build must not replace that release.

## Compatibility and migration plan

| Existing installation | Scoped evidence | Proposed migration treatment |
| --- | --- | --- |
| PyPI `seam-runtime` 1.3.1 | One synthetic SQLite fixture created with the installed legacy wheel retained the exact five record dictionaries after installing the current candidate | Stop the old process, preserve the old environment and a verified data backup, install the successor in a separate environment, migrate a copy, verify canonical records and current-read behavior before cutover. Arbitrary user databases, rollback and extras are not qualified by this fixture |
| GitHub `seam-runtime` 2.4.0 | Exact member/hash differences recorded; no in-place upgrade test from this release | Use a fresh version and explicit artifact hash. Qualify a stopped-store upgrade from the exact old wheel before promising support |
| `seam-self-host` 1.1.2 | Wheel exposes a compiled `seam_runtime` module, `seam-self-host`, and `seam-mcp`; those old implementation targets are absent in the current runtime | Keep its environment intact. Do not co-install with the replacement: distribution names differ while module/command ownership overlaps. Recover/verify an exporter and entitlement transition before offering a Suite migration; compiled legacy execution was not tested |
| Public `seam-client` 2.0.0 | Installed sync/async health, remember, recall and context work against the candidate on real loopback HTTP | Keep current imports and coordinate. Separate transport compatibility from hosted availability; extend and version the client only after source recovery |
| Private `seam-sdk` 0.1.0 | Existing nine reasoning tests and an explicit-seeding ingest/retrieval probe pass against the manually substituted current runtime | Preserve the declared legacy pin until a separate SDK parity/repin change is reviewed. Current-source overlay success does not qualify the declared Git dependency or optional extras |

For any distribution-name change, use an explicit migration to a new
environment and preserve command/import compatibility initially. Do not
publish two independently owning copies of `seam_runtime`, `seam_sdk`, or
`seam_client` into the same environment. Do not delete old releases or assume
`pip install --upgrade` crosses distribution names. A compatibility shim,
deprecation period, and successor version need an explicit design if desired.
No new install URL or unsupported `pip install canticle-seam-*` command is
advertised by this packet.

### Private SDK work before customer delivery

At `294ab08`, base and optional `pgvector`/`chroma` dependencies all pin
runtime `6b746ad95139b8c0dd298a18ca87e0d9a207fce3` through Git SSH. This asks
customers to resolve the runtime source repository. A paid SDK delivery design
must explicitly decide the runtime artifact customers receive and the access
they need; an SDK purchase must not silently grant development-repository
access. The current pin was inspected, not installed or repinned.

Independent AST and diff inspection found two differences between the SDK
copy and current `seam_runtime/sdk.py`: private retrieval defaults
`semantic_graph_seeding=True` and rejects `None`, while current runtime accepts
and defaults to `None`; private retrieval also omits `leg_weights` when
recording the decision. The nine existing private SDK tests make no retrieval
calls. A follow-up in the private SDK repository must test omitted/true/false/
None seeding and weighted replay, then update all dependency pins together.
No private SDK source is copied into this repository by this packet.

The public client has no methods for correction/deletion, the opaque agent-turn
lifecycle, admission/current-history controls, or workspace/project partition
arguments exposed by newer server contracts. Its agent helpers are client-side
remember/context conveniences; they do not implement the server's turn
lifecycle. The passing legacy subset must not be presented as full API parity.

## Candidate verification

All build outputs and environments live outside the working tree at
`/home/terrabyte/.local/share/seam/packaging/l1-20260906`. The tracked evidence
contains hashes, inventories, the probe source, observed results and dependency
versions; it contains no SDK implementation, live user data or credentials.

- `uv build` exported runtime `2551830` and private SDK `294ab08` to separate
  wheel/sdist pairs. Builds retain original package names and versions.
- `python -m tools.release.verify_private_artifacts --expected-name NAME
  --expected-version VERSION WHEEL SDIST` passed for the runtime candidate,
  SDK candidate and downloaded public client pair. This proves path/content
  scan compliance, not rights, private destination visibility or release approval.
- A fresh CPython 3.13.12 environment installed the current runtime with
  `dash,server`, the downloaded client, and the SDK with `--no-deps` to probe
  an explicit runtime substitution. `uv pip check` passed; it does not attest
  that the SDK's Git origin/pin was installed.
- [The install probe](evidence/2026-09-06-l1/qualify_installs.py.txt), run from
  outside all source trees, passed the two local SDK retrieval calls with
  `semantic_graph_seeding=False`; real sync/async HTTP operations; session
  exclusion and unauthenticated rejection; and four CLI `--help` calls.
  [Its log](evidence/2026-09-06-l1/install-smoke.log) records installed-module
  origin. The HTTP server was stopped afterward. This was token-only trusted
  single-user mode, not hosted tenancy or production qualification.
- `runtime-env/bin/python -m pytest -q SDK_SOURCE/tests/test_reasoning_graph.py`
  exited zero with nine tests, no skips, against the installed SDK/runtime
  overlay. [Test output](evidence/2026-09-06-l1/sdk-tests.log) is retained.
- The probe's `legacy-write` then `upgrade-read` phases passed across installed
  1.3.1/current wheels with exact synthetic record-dictionary equality.
  [The observation](evidence/2026-09-06-l1/upgrade-observation.json) and
  [legacy fixture](evidence/2026-09-06-l1/legacy-records.json) bound this result.

Initial probe authoring used nonexistent `candidates`/`to_line` attributes and
an unsupported legacy constructor keyword; the probe was corrected to the
actual interfaces before these results. Those were harness errors, not runtime
regressions. No runtime implementation or test suite was changed. No model,
paid provider, production database, package upload or deployment was used.
The dependency snapshot describes this environment only; minimum Python,
Windows/macOS, optional vector backends, GUI acceptance, whole-database
upgrade coverage and reproducible builds remain unqualified.

## Release controls and remaining blockers

The current release workflows build and inspect root archives, bind checksums
and exact preparation-run bytes, and require a configured operator to publish.
Live GitHub metadata shows `private-package-release` restricted to protected
branches but with no required-reviewer rule. Repository default workflow
permissions were read-only. A label containing "private" does not restrict
who can fetch a published asset from the public destination.

Keep the current scanners and exact-artifact checks. Before dispatch, verify
the intended destination/access rules, approver, immutability setting and exact
required CI on the reviewed successor. A workflow flag asserting immutability
is not independent proof of the GitHub setting. No workflows were dispatched
or changed here.

| Blocker | Owner and next concrete action |
| --- | --- |
| PyPI ownership, successor names and client development source | Operator confirms owner access and legacy repository disposition; recover the authoritative client source before changing it |
| Suite file/version grant and version collision | Operator reviews exact membership/notices and chooses a new version and authorized destination; packaging owner then builds that exact candidate |
| Paid SDK compatibility and delivery | Private SDK owner adds retrieval parity tests, repairs the two observed drifts, qualifies all pins/extras and customer artifact access in a separate private change |
| Public client feature coverage | Client owner adds versioned wrappers/tests for the intended newer public contract after source recovery |
| Compiled self-host migration | Packaging owner verifies legacy export/restore, credentials/entitlement transition and a separate-environment cutover before promising compatibility |
| Full release/deployment qualification | Complete applicable L2-L6/S9/S10 work, supported-platform and upgrade matrix, independent review, exact-head CI and explicit publication authority |

This prepares a reviewable L1 packet and local artifact candidates while
retaining those release blockers. R2 remains the next runtime slice; it does
not depend on silently resolving customer packaging decisions.

## Evidence manifest

The following tracked evidence captures the inspected bytes and scoped
observations. Archive paths inside inventories are relative to the external
artifact directory above. Each downloaded/built archive has its own full
SHA-256 in the artifact inventory; every member hash is in
the archive inventory. Local wheel/sdist files are retained externally and
are not published with this report.

| Artifact | SHA-256 |
| --- | --- |
| `docs/audits/evidence/2026-09-06-l1/archive-members.json` | `5c6e1a869b0c86cd47c2f80a5e20ab0a032076f3f5b9cfa20831ed5e54bd8d77` |
| `docs/audits/evidence/2026-09-06-l1/artifact-inventory.json` | `ff647dc9c26b87bdd35b3b833264c59517944bd8d91c5551224c3538cfb2469a` |
| `docs/audits/evidence/2026-09-06-l1/github-metadata.json` | `a3e64a4e9fba1a27df0b391d9460f80b354deb436c43eb9544bed3d23708653c` |
| `docs/audits/evidence/2026-09-06-l1/install-smoke.log` | `09ebe7ce070ce235616b98784cf0b36425eeb79c100d79bcf288bae43a4ebffe` |
| `docs/audits/evidence/2026-09-06-l1/installed-requirements.txt` | `8b0a47c8dc678eed82553e20f9f2142f8bfd3e2518af89fa711ac8e1d772dc43` |
| `docs/audits/evidence/2026-09-06-l1/legacy-records.json` | `f1a9cadd86a6c0787191c9562de082d000c4283d1889e924e46960cfa0f7b563` |
| `docs/audits/evidence/2026-09-06-l1/qualify_installs.py.txt` | `8edde36d2d1e226f91150dfdf307606f3806ae74ef6ab5e7b804cf9abf792514` |
| `docs/audits/evidence/2026-09-06-l1/runtime-build.log` | `9035f30895ad0d1236dea1e3b6b175d28b8fdf3ec3e89f65c47de5a98d0310fb` |
| `docs/audits/evidence/2026-09-06-l1/runtime-members.json` | `6a3c37ffd6e5ab4d7b838f512a037010e06947169aa2f759dc507982eaa1f7d5` |
| `docs/audits/evidence/2026-09-06-l1/sdk-tests.log` | `585ba42829657b9e2d56f8614be6c3365a8405474eed008559511ab50f2ffcfb` |
| `docs/audits/evidence/2026-09-06-l1/upgrade-observation.json` | `627ba125dffd20b0b560c5e96b2d3d81793b71bf71bfecb680fec4c827990911` |
| `docs/audits/evidence/2026-09-06-l1/source-ownership-observations.json` | `c0a4ffb44af0a3ea4259c96f6ecf5055df0a1d0da0c3e348ce471a5c144c2c6f` |
