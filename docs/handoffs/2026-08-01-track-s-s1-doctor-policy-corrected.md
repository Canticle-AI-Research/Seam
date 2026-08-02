---
handoff_id: 2026-08-01-track-s-s1-doctor-policy-corrected
supersedes: 2026-08-01-track-s-s2-locally-qualified
handoff_status: current
history: HISTORY#524
---

# Track S S1 doctor policy corrected after S2 qualification

**Date:** 2026-08-01

**Branch:** `feat/track-s-s2-migration-spine`

**Base:** `origin/main@94375e8`

## Current state

S0, S1, and S2 remain locally qualified. A post-qualification audit found one
S1 dependency-policy contradiction: `seam doctor` treated opt-in-only Chroma as
a required core package even though the canonical dependency contract requires
only Rich and tiktoken. That contradiction is corrected and independently
guarded. S3 remains the exact next move.

## Correction

- `seam_runtime.doctor.REQUIRED_DEPENDENCIES` is now exactly `rich` and
  `tiktoken`, matching `pyproject.toml`'s declared `project.dependencies`.
- Chroma remains visible in the doctor dependency inventory, but its absence is
  informational and cannot make a policy-compliant core install fail.
- Dependency probing treats import-system refusal as absence rather than
  crashing doctor.
- The audit guard resolves `[tool.seam.dependency-contract].runtime-source`
  independently instead of copying doctor's expected list.
- A hermetic subprocess blocks `chromadb` and every `chromadb.*` import before
  importing SEAM, then runs the real doctor report and proves `PASS` with no
  missing required dependencies.
- The legacy CLI tests now simulate absent Chroma and assert both pretty and
  JSON output against the canonical project dependency source.

## Evidence

- Before the fix, the same absent-Chroma probe reproduced `FAIL` with Chroma as
  the sole missing required dependency. After the fix it reports `PASS`,
  required dependencies `rich` and `tiktoken`, and Chroma unavailable.
- Fourteen focused doctor, Chroma-policy, dependency-contract, and stash tests
  passed.
- All 1,572 selected strict non-external audit tests passed; 23 external tests
  were explicitly deselected, not skipped.
- The canonical dependency verifier, Ruff, Python compilation, diff hygiene,
  and content-free secret/session scan passed.
- Final CodeRabbit review of the three-file repair reported zero findings.

## Honest boundaries

- The complete repository suite and pgvector external lane were not rerun for
  this narrow correction; S2's previously recorded full non-external evidence
  remains unchanged.
- No provider-paid benchmark, artifact build, publish, deploy, or release ran.
- Protected-main CI and merge remain the publication boundary.

## Exact next move

Implement S3 durable supersession and guarded reprojection. Preserve the S1
rule that optional adapters cannot enter a default health gate, and keep S2's
central migration spine as the sole durable layout-change path.
