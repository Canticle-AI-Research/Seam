# ARCHIVED — superseded Vite/React webui source

**This tree is archived. It is NOT the SEAM web dashboard.**

## Where the webui actually is

The live browser dashboard is the single self-contained file:

    seam_runtime/webui/dashboard.html   (+ seam-api.js, favicon.svg, icons.svg, branding/)

It is served by `seam webui` / `seam serve` at `http://127.0.0.1:8765/`
(`seam_runtime/server.py:webui_dir()` resolves the package's `webui/` dir; override with `SEAM_WEBUI_DIR`).

## Why this was archived (2026-06-18, HISTORY#326)

This was the top-level `webui/` Vite + React project. Its build output had
**diverged from and was older than** the served file — the canonical dashboard is
hand-authored (CDN React, inline) directly in `seam_runtime/webui/dashboard.html`,
not built from this tree. Per `RESTORE_NOTES.md` the React-pane rewrite under `src/`
was itself a documented regression that was reverted to the original shell.

Keeping it at the repo root made it look like the dashboard's source, which it is
not — that was the "which webui is real?" confusion. It is preserved here (reversible
via git history) in case the Vite shell / REST panes are ever revived.

Also removed in the same pass: `Webui-final-dash/` (untracked stray duplicate) and
`webui/dist/` + `webui/node_modules/` (untracked build/dep clutter). The stale
`/webui` npm Dependabot entry was dropped.
