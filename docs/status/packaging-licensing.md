# Status Stream: Packaging Licensing

> Distribution shape, licensing, and the public/private boundary

_Source of truth for current state in this area. History lives in `HISTORY.md`._

## Settled

The full runtime is **private** and operates the hosted service on
operator-controlled infrastructure; it is not distributed. A public edition will be
built separately from the ground up, with separation as an architectural property
rather than a boundary retrofitted onto a codebase that was not designed for one.

Single full package with readable MIRL and HS/1 source. LICENSE, NOTICE,
COMMERCIAL_LICENSE.md, and the `Private :: Do Not Upload` tripwire are unchanged.
`package-release.yml` has no `pypi-publish` job: the full-MIRL runtime has **no PyPI
path at all**. The parameterized BUSL-1.1 text is retained, unused, for the future
public edition.

## Retained push gate

`verify_public_safe.py` + `public_manifest.py` are a secret and reserved-material
push gate — they exist because a `seam.db` snapshot once leaked (HISTORY#344). They
are not split machinery and must not be removed as such.

## Do not re-litigate

Do not re-split this private runtime. Do not re-ask the product shape.
