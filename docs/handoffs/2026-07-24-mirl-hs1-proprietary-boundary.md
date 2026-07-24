---
handoff_id: 2026-07-24-mirl-hs1-proprietary-boundary
supersedes: 2026-07-23-reasoning-verification-r3
handoff_status: superseded
history: HISTORY#468
---

# Handoff: MIRL and HS/1 proprietary boundary

**Date:** 2026-07-24
**Branch:** `agent/mirl-proprietary-boundary`
**Spend:** zero provider or paid model calls.

## One-line state

New/private MIRL and HS/1 work is explicitly proprietary, the exact legacy
Apache-published versions retain their old rights, the public mirror is frozen,
and private package 2.3.0 can be released through private GitHub but is
deliberately blocked from public PyPI.

## Licensing boundary

- `LICENSE` names MIRL and HS/1 as separate Reserved Material categories and
  defines the limited authorized-contributor scope, prohibited external use,
  confidentiality, contribution, warranty, liability, and non-retroactivity
  terms.
- `LICENSES/Apache-2.0.txt` preserves the complete Apache text for unchanged
  Legacy Apache Materials incorporated into later private distributions.
- `NOTICE`, `COMMERCIAL_LICENSE.md`, `CONTRIBUTING.md`, README, status, ledger,
  roadmap, and protection-model docs carry the same split without claiming
  copyright over abstract ideas, methods, facts, or short names.
- This is an operational repository policy, not a substitute for legal advice.
  Counsel should review the terms and any file-level provenance questions.

## Frozen public boundary

- Live verification on 2026-07-24 found private
  `BlackhatShiftey/Seam`, public `BlackhatShiftey/Seam_Runtime`, and frozen
  public `main` at `0f4b40aab7fda643ce776e597f0b430faa465ca8`.
- The public manifest exposes zero synced private paths. MIRL and HS/1 have
  explicit reserved classifications, all other private paths fail closed, the
  sync command refuses every mode, and the pre-push hook refuses the public
  remote.
- No public push, archive, visibility change, history rewrite, deletion, or
  PyPI publication occurred.

## Package and release state

- `seam-runtime` is version 2.3.0 with
  `LicenseRef-SEAM-Proprietary AND Apache-2.0`, all controlling license files,
  private repository URLs, and `Private :: Do Not Upload`.
- `.github/workflows/package-release.yml` manually builds wheel and sdist,
  runs `twine check`, applies the archive-content boundary gate, smoke-installs
  the wheel, and retains reviewed artifacts. `private-github` is the default.
- The PyPI job uses Trusted Publishing/OIDC and stores no PyPI token. The
  current 2.3.0 package cannot pass that job because its wheel and sdist
  contain MIRL and HS/1 Reserved Materials and private metadata.
- GitHub environments `private-package-release` and `pypi` exist and restrict
  deployments to protected branches. The account plan rejected a wait-timer
  rule, so no wait timer or reviewer approval is claimed.
- Live PyPI remains `seam-runtime` 1.3.1 with only 1.3.0/1.3.1 releases and the
  legacy public repository URL. `server.json` remains pinned to that legacy
  Apache artifact.

## Verification

- Focused release/licensing suite: 99 passed.
- Complete `tests/audit -m "not external"` suite: 1,300 collected and passed.
- Fresh wheel and sdist: `twine check` passed; both passed
  `private-github`; both were expectedly rejected by `pypi` with 82
  MIRL/HS/1 runtime paths plus private license/metadata findings.
- Both archives contain the proprietary MIRL/HS/1 license and preserved
  `LICENSES/Apache-2.0.txt`.
- Isolated wheel install plus `seam --help` and `seam-mcp --help`: passed.
- Touched-file Ruff, workflow YAML parsing, shell syntax, hook behavior, sync
  refusal, and `git diff --check`: passed.
- No CodeRabbit upload was performed because an external diff upload would
  conflict with the new private-material policy.

## Next decisions

1. Merge the private licensing/release PR after review.
2. Obtain legal review before relying on the custom terms in a dispute or
   offering external licenses.
3. Do not upload private 2.3.0 to PyPI. Choose either a separately implemented
   public client artifact or an explicitly scoped legacy Apache maintenance
   release; each requires its own review and operator approval.
4. If a clean public artifact is approved, configure the PyPI Trusted
   Publisher for owner `BlackhatShiftey`, repository `Seam`, workflow
   `package-release.yml`, and environment `pypi`. The GitHub environment's
   protected-branch rule is already confirmed; PyPI registration remains.
