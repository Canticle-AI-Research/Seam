# SEAM WebUI (A-Web Browser Dashboard)

This is the browser dashboard / REST API GUI for SEAM, built with Vite + React + TypeScript.

## Quick Start

```bash
cd experimental/webui
npm install
npm run dev
```

Open http://localhost:5173. The root app frames the finished IDE-like dashboard from `public/dashboard.html`, with REST calls proxied to the local SEAM API.

## Build

```bash
npm run build
```

Outputs to `experimental/webui/dist/`.

## Requirements

- Node.js >= 20.19 or >= 22.12
- SEAM REST API running (e.g. `python seam.py serve --port 8765`) for live endpoint data

## What works today

- **Finished dashboard shell** - IDE layout, file explorer, code editor, runtime health bars, graphs, settings overlay, terminal, command menu, and agent chat
- **REST service layer** - `public/seam-api.js` provides health, stats, compile, search, context, persist, and lossless-compress calls through the Vite proxy
- **REST panes** - the TypeScript endpoint panes remain in `src/panes/` as rework material, but the finished dashboard shell is the root UI

## Design

- Preserves the IDE-like shell from the original prototype as the first screen
- Dark theme with JetBrains Mono typography
- Activity bar on the left, main pane on the right, status bar at the bottom
- UI states: disconnected, unauthorized, loading, success, error

## Notes

- The old prototype backup lives in `experimental/webui/prototype-backup/`
- The finished static dashboard lives in `experimental/webui/public/dashboard.html`
- The regression/restoration record lives in `experimental/webui/RESTORE_NOTES.md`
- Keep secrets local; tokens are never committed
- This remains experimental until it has repeatable browser smoke tests
