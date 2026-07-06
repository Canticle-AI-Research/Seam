# SEAM Repo Ledger (Public Core)

Stable, durable facts about this repository. This ledger belongs to the public `Seam_Runtime` repo and is maintained independently of the private `Seam` repo's own `REPO_LEDGER.md`.

- This repo is the Apache-2.0 public core of SEAM Runtime. See `LICENSE`, `NOTICE`, `COMMERCIAL_LICENSE.md`, and `docs/PROTECTION_MODEL.md` for the public/private boundary.
- Content here is synced from a private development repo per an explicit allow-list (`tools/release/public_manifest.py` in the private repo); this repo's own `HISTORY.md`/`HISTORY_INDEX.md`/`PROJECT_STATUS.md`/this file are never overwritten by that sync once seeded -- they are this repo's own bookkeeping trail if maintainers choose to keep using the SEAM protocol here.
- Follow `AGENTS.md` for the repo protocol (session-start read order, `HISTORY.md` append discipline, verification gates under `tools/history/` and `tools/streams/`).
