# Status Stream: Packaging Licensing

> Distribution shape, licensing, and the public/private boundary

_Source of truth for current state in this area. History lives in `HISTORY.md`._

## Settled

The full runtime is **private** and operates the hosted service on
operator-controlled infrastructure; it is not distributed. A public edition will be
built separately from the ground up, with separation as an architectural property
rather than a boundary retrofitted onto a codebase that was not designed for one.

Single full package with readable MIRL and HS/1 source. The root license is
permanently proprietary and the `Private :: Do Not Upload` tripwire remains.
`package-release.yml` has no `pypi-publish` job: the full-MIRL runtime has **no
PyPI path at all**.

BUSL is historical, not prospective. Exact previously published artifacts keep
their shipped terms; the last BUSL parameters were copied unchanged to
`LICENSES/HISTORICAL/BUSL-1.1.txt` as explicitly classified evidence while the
original tracked license file remains preserved. Future source-distributed
SEAM SDK/Node products are intended to use PolyForm Shield in separate
repositories. No qualifying Node repository, manifest, or released artifact is
recorded by this canonical repository yet, so the Node feature/pricing documents
are prospective strategy, not an available grant or release route. The thin
public client remains Apache-2.0. This private package carries neither Shield
nor a current BUSL grant.

## Retained push gate

`verify_public_safe.py` + `public_manifest.py` are a secret and reserved-material
push gate — they exist because a `seam.db` snapshot once leaked (HISTORY#344). They
are not split machinery and must not be removed as such.

## Do not re-litigate

Do not re-split this private runtime. Do not re-ask the product shape.
