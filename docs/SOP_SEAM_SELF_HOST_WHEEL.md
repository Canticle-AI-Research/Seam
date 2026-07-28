# SOP: ship the compiled self-host as a PyPI wheel (`seam-self-host`)

Owner: Codex. Written by Claude, 2026-07-28. Status: not started.

## Objective

Make the BUSL self-host installable with `pip install seam-self-host` instead of only
`docker pull`. The wheel must ship the SEAM engine as compiled `.so` extension
modules with **no `.py` source for `seam_runtime`**, because hiding the MIRL and
HS/1 layers is the entire reason the compiled distribution exists.

Two packages end up on PyPI, both protecting MIRL:

| Role | Package | License | Contains MIRL |
| --- | --- | --- | --- |
| Paid hosted API client | `seam-client` | Apache-2.0 | No, HTTP only. Already live at 0.1.0. |
| Free self-host | `seam-self-host` | BUSL-1.1 | Yes, compiled to `.so`. No source. |

The Docker image stays. It is built from the same source and remains the
zero-dependency option; the wheel is an additional channel, not a replacement.

## Ground truth to read before starting

- `selfhost/Dockerfile` — current Nuitka **standalone** build (one executable).
- `tools/release/build_selfhost.py` — build driver, deliberately has no push mode.
- `tools/release/verify_selfhost_artifact.py` — image gate, including
  `RESERVED_CONTENT_BUDGET`.
- `tools/release/verify_distribution_boundary.py` — wheel/sdist gate, targets
  `pypi` and `private-github`.
- `public_pkg/` — the pattern for a separate publishable package with its own
  `pyproject.toml`, built by `tools/release/build_public.py`.
- `docs/SELF_HOST_SECURITY.md` — the honest protection boundary. Do not make
  claims beyond it.
- HISTORY#477 for the measured leakage baseline and why the ratchet exists.

## Hard constraints

1. **No `seam_runtime` `.py`, `.pyc`, or `.pyo` in the wheel.** Fail the build if
   any is present, the same way the Dockerfile already does.
2. **Do not remove `Private :: Do Not Upload` from the root `pyproject.toml`.**
   `verify_distribution_boundary.py:105` requires it for the `private-github`
   target and `:145` rejects it for `pypi`. Removing it breaks the private
   release gate. `seam-self-host` gets its **own** `pyproject.toml` in a new
   `selfhost_pkg/` directory, exactly like `public_pkg/`.
3. **Never raise `RESERVED_CONTENT_BUDGET` to make a build pass.** It is a
   ratchet pinned to measured reality. If the wheel legitimately exposes more or
   fewer identifiers than the image, give the wheel its **own** budget measured
   from a real build, and record the number and the reason in HISTORY.
4. **Publish nothing.** No `twine upload`, no registry push, no
   `gh workflow run` against the pypi target. The operator publishes.
5. **Delete nothing.** Module exclusions are build flags, not source removal.
6. Follow the SEAM protocol: read order at session start, HISTORY entry plus
   `python -m tools.history.closeout` at the end, all gates green.

## Step 1 — feasibility spike (do this first, do not skip)

Nuitka **module** mode must produce an importable compiled package. If it cannot
carry a package this shape, the rest of this SOP is void and you should stop and
report rather than improvise.

A ready spike lives at
`/tmp/claude-1000/-home-terrabyte-Documents-Projects-Seam/9f0cd8c7-5779-4e9b-b510-d94305b13f9e/scratchpad/wheel-spike.Dockerfile`.
If that path is gone, recreate it: compile with

```
python -m nuitka --mode=module --deployment --assume-yes-for-downloads \
  --python-flag=no_docstrings --include-package=seam_runtime \
  --output-dir=/out seam_runtime
```

then copy only the resulting `.so` into an empty directory containing **no `.py`
files at all** and prove these imports resolve:

```
import seam_runtime
import seam_runtime.mirl
import seam_runtime.selfhost
import seam_runtime.runtime
```

Report the outcome before proceeding.

- **Spike passes** → continue to step 2.
- **Spike fails** → stop. Record what failed. The fallback options, in order of
  preference, are (a) per-module `.so` files rather than one bundled module, and
  (b) shipping the existing standalone binary inside a wheel with a thin launcher.
  Do not pick one without operator input.

## Step 2 — `selfhost_pkg/` package definition

Create `selfhost_pkg/pyproject.toml` modeled on `public_pkg/pyproject.toml`:

- `name = "seam-self-host"` (confirmed available on PyPI 2026-07-28, along with
  `seam-engine`, `seam-core`, `seam-selfhost`, `seam-memory`, `seam-server`).
- `version = "2.4.0"` — the BUSL grant names "version 2.4.0 or later" as the
  Licensed Work, so anything below that floor is not covered by the license.
- `license = "BUSL-1.1"`, and `license-files` must include
  `LICENSES/BUSL-1.1.txt`. An artifact that claims BUSL must carry its text.
- Runtime dependencies only: the `server` extra set (`fastapi`, `uvicorn`) plus
  `cryptography`. No dev, benchmark, or dashboard extras.
- A console entry point that starts the self-host server.
- Do **not** copy the repo-root `README.md` into the package; it is the private
  product README. Write a short `selfhost_pkg/README.md` that states plainly what the
  package is, that it contains no source, and how to run it.

## Step 3 — wheel build pipeline

Add `tools/release/build_selfhost_wheel.py`, modeled on `build_public.py`:

- Build inside Docker so the toolchain and glibc are pinned and reproducible.
  Reuse the pinned base image digests from `selfhost/Dockerfile`.
- Take `--outdir`, refuse a non-empty output directory rather than writing into
  it, and build into a `TemporaryDirectory`.
- Copy an explicit allow-list of files. Do not `iterdir()` a directory, so a new
  file dropped in is not silently shipped.
- Carry over the module exclusions from `selfhost/Dockerfile`: 18
  `--nofollow-import-to` flags plus `--include-module=seam_runtime.public_api`.
  **These are load-bearing.** `public_api` is imported lazily inside
  `selfhost.py`'s route handlers, and `conversation`, `event_count_context`,
  `tokenization`, and `retrieval_orchestrator` are imported lazily from
  `retrieval.py`, `mirl.py`, and `sdk.py`. Excluding any of those four produces a
  wheel that builds clean and then raises `ModuleNotFoundError` on the first
  remember or recall. Verified 2026-07-28.
- Run `twine check` on the output.
- Wheels are per interpreter and platform. Start with `cp312` +
  `manylinux_2_28_x86_64` only, prove the pipeline, then widen. Do not attempt a
  full matrix first.

## Step 4 — the gate

Extend `tools/release/verify_distribution_boundary.py` with a `node` target, or
add `tools/release/verify_selfhost_wheel.py` if the logic does not fit cleanly. It
must fail on:

- any `seam_runtime` `.py`/`.pyc`/`.pyo` in the wheel;
- a missing `LICENSES/BUSL-1.1.txt`;
- metadata that does not declare BUSL-1.1;
- reserved-identifier counts above the wheel's own measured budget, scanning file
  **contents**, not paths. The image gate got this wrong originally and passed a
  leaking artifact for exactly that reason; do not repeat it.

Exempt license texts from the content scan. Naming MIRL and HS/1 is precisely
what a license governing them must do.

## Step 5 — prove it runs

Do not infer this from a successful build. In a clean container with the wheel
installed and no repo checkout on the path:

- start the server;
- exercise all four routes: `/v1/health`, `/v1/memories`, `/v1/memories/recall`,
  `/v1/context`;
- confirm an unauthenticated request returns 401;
- confirm responses contain no `raw:`, `clm:`, or `mirl` substrings;
- confirm the logs show no `ModuleNotFoundError`.

Recall and remember are the routes that exercise the lazy imports. A health check
alone proves nothing.

## Open decision — do not resolve this yourself

`seam_runtime/selfhost.py` currently refuses to start without a vendor-signed
Ed25519 entitlement. That is incompatible with a **free** self-host, which is the
operator's stated product. Making the entitlement optional is a product decision,
not a cleanup. Build the wheel with the current behavior, flag the conflict in
your handoff, and let the operator decide. If it is made optional later, keep the
entitlement path working for a future paid or supported tier rather than deleting
it.

## Deliverables

1. Spike result, reported before any pipeline work.
2. `selfhost_pkg/pyproject.toml` and `selfhost_pkg/README.md`.
3. `tools/release/build_selfhost_wheel.py`.
4. The wheel gate, with tests covering both directions (a clean wheel passes, a
   wheel with source or missing BUSL fails).
5. Runtime proof from step 5, pasted as real command output.
6. Full suite green with zero skips, plus a HISTORY entry and a green closeout.
7. A PR. Do not merge it yourself.
