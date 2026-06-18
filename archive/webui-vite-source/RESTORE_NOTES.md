# SEAM WebUI Restoration Notes

The first Vite + React REST-pane rewrite was not visually or structurally equivalent to the original dashboard prototype. It kept a small activity bar and endpoint panes, but removed the operator surface that made the WebUI useful.

## Original Surface That Must Stay

- SEAM title bar with logo, runtime identity, live status pills, and window controls.
- IDE-style left activity bar with Editor, Ingest, Memory, Agent, Benchmark, and Settings entrypoints.
- Explorer panel with Project/System tabs, runtime health bars, active file tree, and system file browser.
- Editor tab strip with multiple open files and syntax-colored code view.
- Memory surfaces: recent records, active write queue, provenance graph, subsystem stats, and full Memory tab.
- Ingest surfaces: queued/running/done file list, staged ingest progress, batch mode controls, auto-ingest/watch controls, and live ingest log.
- Benchmark surfaces: overview cards, sparklines, DB health, run log, benchmark detail expansion, and full Benchmark tab.
- Settings overlay with API/env/database/Docker/SEAM config sections, local-only placeholders, select controls, toggles, and edit-file affordances.
- Agent chat panel with model picker, message history, input composer, and loading state.
- Bottom terminal with command history, `/` menu, `!` shell prefix, `?` help, and bottom toolbar toggles.
- Bottom status bar with MIRL/runtime status, record count, recall score, Python/runtime labels, and clock.
- Cyber/terminal visual language: scanlines, compact monospace density, animated progress bars, graphs, sparklines, and glow accents.

## What The REST Rewrite Removed

- The IDE shell was replaced by five flat panes: Status, Compile, Search, Context, and Settings.
- The file explorer, editor tabs, code view, terminal, agent chat, model picker, settings overlay, memory graph, ingest workflow, benchmark dashboards, bottom toolbar, and most runtime visual indicators disappeared from the first screen.
- Settings became only API URL/token configuration instead of the broader operator configuration surface.
- The WebUI stopped matching the original dashboard's purpose as an all-in-one operator surface.

## Current Fix

- `vite.config.ts` serves `public/` as Vite static content and proxies dashboard REST endpoints to the local SEAM API.
- `src/App.tsx` frames `/dashboard.html` at `http://localhost:5173/`.
- `public/seam-api.js` provides the browser service layer for health, stats, compile, search, context, persist, and lossless-compress calls.
- The TypeScript REST panes remain in `src/panes/` as follow-up implementation material; the finished dashboard shell is the root UI.

## Bug Pass 1

- Provenance graph nodes now keep selected state instead of being hover-only.
- Clicking a graph node shows a functional detail card with summary, fields, linked nodes, and action affordances.
- The graph detail card appears in both the side Memory graph and the full Memory tab.
- Graph edges now stay highlighted for the selected node, not only during hover.
- The terminal `/` menu now opens through the `/` input path and menu items execute through a shared terminal command handler.
- Clicking a menu command now writes terminal output instead of only inserting text into the prompt.

## Bug Pass 2

- The `/` command palette is now `position: fixed` inside the iframe viewport with a high z-index, so it is not clipped by the terminal panel, editor, chat panel, or other dashboard artifacts.
- The menu has bounded height plus vertical scrolling for longer command lists.
- Commands are filterable by typing after `/`.
- Menu rows show `WIRED` or `CLI ONLY` so the UI no longer pretends every command is browser-executable.
- Browser-safe commands are wired to REST/API or UI actions: `/doctor`, `/health`, `/stats`, `/search`, `/context`, `/compile`, `/ingest`, `/memory`, `/benchmark`, `/settings`, and `/clear`.
- CLI-only commands stay blocked in-browser with an explicit warning: `/index`, `/dashboard`, `/serve`, `/mcp`, and `/surface`.

## Porting Rule

Future TypeScript work must port endpoint behavior into the original dashboard shell. Do not replace the shell with endpoint demo panes. A change is not acceptable unless the first viewport still has the IDE, graphs, settings, terminal, chat, activity bar, explorer, editor, benchmark, and memory surfaces.
