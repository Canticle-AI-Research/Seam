# SEAM private repository and MIRL/HS/1 protection boundary

Effective 2026-07-24, the private `BlackhatShiftey/Seam` repository is
proprietary and the legacy `BlackhatShiftey/Seam_Runtime` public mirror is
frozen.

`LICENSE`, `NOTICE`, and `COMMERCIAL_LICENSE.md` are the controlling terms.
This document records the repository and release controls that implement that
policy.

## Copyright boundary

MIRL's authored expression is copyrighted. Reserved material includes the
specification text, source code, schemas as expressed, documentation, examples,
tests, diagrams, fixtures, and other original works of authorship.

HS/1's authored expression is also separately named and copyrighted. Reserved
HS/1 material includes the Holographic Surface specification, container
expression, visual designs, headers and metadata as expressed, source code,
pixel packing and codecs, surface library, verification and repair logic,
documentation, examples, tests, diagrams, fixtures, and integrations.

The private boundary also covers non-public implementation and integration
material for MIRL compilation, translation, record handling, PACK and symbol
machinery, codecs and surfaces, storage, graph projection, retrieval,
vectorization, SDK/API surfaces, and evaluation.

Copyright protects original expression, not an abstract idea, fact, method,
system, or short name by itself. SEAM therefore uses repository access
controls, confidentiality, reserved trademarks, and any separately applicable
patent or contract rights alongside copyright. Policy documents must not claim
that copyright alone creates a monopoly over an abstract memory architecture.

## Legacy Apache boundary

The public repository at
`https://github.com/BlackhatShiftey/Seam_Runtime` is a legacy Apache-2.0
release. Its `main` head at the licensing freeze was:

`0f4b40aab7fda643ce776e597f0b430faa465ca8`

The exact file versions previously published there retain Apache-2.0 rights.
Those rights cannot be retracted by this policy.
`LICENSES/Apache-2.0.txt` preserves the governing Apache text for unchanged
Legacy Apache Materials incorporated into the private repository.

The legacy grant does not automatically cover:

- later private versions of a file;
- unpublished changes;
- new MIRL specifications, schemas, examples, tests, or implementations;
- private hosted, enterprise, customer, benchmark, or research material; or
- any future artifact that lacks an express public license from the owner.

Similarity of name, ancestry, interface, or purpose is not a new license grant.

## Frozen mirror control

The old private-to-public synchronization path is disabled:

- `tools/release/public_manifest.py` has no private synced paths and classifies
  obvious MIRL and HS/1 implementation surfaces as reserved;
- `tools/release/sync_public_mirror.py` fails closed for dry-run and push modes;
- `tools/release/verify_public_safe.py` blocks MIRL and HS/1 Reserved Materials and all
  private-by-default paths; and
- `tools/git-hooks/pre-push` refuses every push to the legacy
  `seam-runtime`/`Seam_Runtime` remote.

These controls prevent accidental publication. They do not rewrite public git
history and they must not be bypassed.

## Approved public SDK artifact

The operator-approved public integration surface is the independently authored
Apache-2.0 `seam-client` package under
`BlackhatShiftey/Seam_Runtime/sdk`. It is not produced by reactivating or
filtering the private mirror.

The artifact is limited to:

1. HTTP transport and bearer authentication;
2. typed public request/response models;
3. synchronous and asynchronous clients;
4. framework-neutral agent-memory lifecycle hooks;
5. public examples, tests, CI, and release automation; and
6. the stable opaque `/v1` contract documented in `docs/PUBLIC_SDK_API.md`.

It must not import, package, copy, or expose MIRL or HS/1 Reserved Materials,
private runtime modules, storage, retrieval, graph, PACK, ranking,
provenance, surface, or benchmark internals. Its own build-root allow-list and
artifact scanner must pass before every release.

The first PyPI publication also requires review and merge of both repository
boundary branches, a protected GitHub `pypi` environment, one-time PyPI
Trusted Publisher registration for the exact public workflow, and explicit
manual dispatch for the reviewed version. No long-lived PyPI token belongs in
either repository.

The private runtime must remain installable and testable from the private
repository. Protection changes must not silently weaken runtime, verification,
history, or provenance behavior.

## Contributor handling

Only expressly authorized contributors may access the private repository.
Contributors must keep non-public material inside approved systems and use it
only for approved SEAM work. Contribution rights and restrictions are stated
in `LICENSE` and `CONTRIBUTING.md`; a separate signed agreement controls if it
conflicts.

## Incident response

If private, MIRL Reserved Material, or HS/1 Reserved Material is exposed:

1. stop further distribution without copying the material elsewhere;
2. preserve a bounded audit record of the affected path, version, destination,
   and time;
3. determine whether the material was already a Legacy Apache Material or was
   newly exposed private work;
4. revoke credentials or access involved in the disclosure;
5. obtain legal advice before requesting takedown, rewriting public history,
   or making infringement claims; and
6. record the remediation in the private repository history without embedding
   the exposed material or private URLs.

No agent may delete, rewrite, archive, force-push, or change visibility of the
legacy public repository without explicit operator authorization naming the
target and action.
