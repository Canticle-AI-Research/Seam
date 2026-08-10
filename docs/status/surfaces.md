# Status Stream: Surfaces

> CLI, shell, TUI dashboard, webui, REST, MCP, SDK, installers

_Source of truth for current state in this area. History lives in `HISTORY.md`._

## Stable

- Core runtime paths: compile, verify, persist, search, context, benchmark.
- Interactive CLI shell: `seam shell` / `seam chat`, REPL memory interface with
  slash commands and prompt-ready context output.
- Textual TUI dashboard, `seam_runtime/tui/` (HISTORY#537, #540): seven tabs,
  `/` command palette derived at runtime from the backend's own parser across
  five surfaces, worker-backed structured panels, and a registry-driven
  Settings tab with masked secrets. Blocking work runs on a worker thread, so
  retrieval and chat no longer freeze the UI. `seam dashboard`, `seam-dash`,
  and `seam-tui` all reach it through `dashboard.run_dashboard`.
  - Memory is a page rather than a tab of one table (HISTORY#540): the record
    table, the provenance trace beneath it, and one shared log. Selecting a row
    exposes its full id in an editable field and traces it below without
    changing the clipboard; the adjacent Copy ID button and `y` shortcut are
    explicit copy paths. The standalone Provenance tab is gone — two
    `#prov-query` widgets cannot coexist.
  - The `/` menu is organized by task, not by surface (HISTORY#541): a Run
    section of the 20 executable dashboard verbs, then Reference covering
    cli/mcp/api/sdk under the same eleven task names with a per-row surface
    tag. All 153 entries carry a description, enforced by a census test.
    REST summaries live on the route decorators and therefore in the OpenAPI
    schema; CLI text is the existing `help=`, now actually read.
  - Three input modes (HISTORY#542): `/` seam commands, `!` shell, `?` chat.
    A typed sigil latches immediately and following keystrokes use that mode;
    a whole prefixed line pasted into the field runs once without changing an
    existing mode. Escape returns to seam and the command bar. The mode shows in the brand bar, the
    placeholder, and the input border. Shell execution stays behind
    HISTORY#272's `SEAM_DASHBOARD_ALLOW_SHELL` gate, off by default and
    toggleable from the Settings tab; `cd`/`pwd` work regardless. Chat reuses
    `SeamChatClient` and renders the memory ids it injected.
  - Canticle/SEAM identity kit: `branding/kit/` is the canonical reusable
    token, SVG, terminal-lockup, motion, and provenance contract. The TUI is
    its first consumer: the Canticle prompt/cursor square and SEAM product
    wordmark type on at launch, then settle into the header. Motion supports
    `full`, `reduced`, and `off` through `SEAM_TUI_MOTION`; only `full` blinks
    the cursor, while reduced/off keep it statically visible. Older retro,
    blue/ice, and glitch assets remain historical; WebUI adoption is deferred
    to an operator-present design session.
  - Keyboard navigation: `alt+1`..`alt+N`, `ctrl+left`/`ctrl+right`, and
    `tab <name>`. `alt+N` is unavailable on terminals using the classic
    "Alt sends Escape" convention; the other two paths always work.
  - Target surface and the ordered slices toward it:
    `docs/roadmap/TUI_OPERATOR_SURFACE.md`.
  `dashboard.DashboardApp` remains the backend and still owns the Rich
  `--snapshot` and `--run` modes.
  - The previous in-`dashboard.py` `TextualDashboardApp` UI is superseded and
    unreachable, kept as deprecated dead code because its 28 test usages are
    the only coverage of several dashboard behaviours. Removal is deferred.
- Dashboard installers: `seam-dash` shim (Windows `.cmd` + POSIX).
- Browser dashboard served by the REST server: `seam serve` / `seam webui`. The
  static `dashboard.html` IDE shell is the shipped working UI.
- REST API: bearer-token guard when `SEAM_API_TOKEN` is configured, bounded
  request bodies, env-configurable, optional `server` extra. An unset token is
  trusted-loopback development only; automatic token provisioning and
  principal identity are not yet implemented. Shared hosted tenancy and opaque
  remote deletion remain Track S S6 work.
- MCP agent bridge: `seam mcp stdio` / `seam-mcp`, 19 bounded documented tools over
  MCP JSON-RPC for Gemini/Claude/Cursor-style clients. `seam-mcp --ensure-pgvector`
  can auto-start pgvector. The private handshake reports the installed runtime
  package version; `server.json` retains its intentional legacy compatibility
  value.
- RAG surface: `seam ingest <path> --persist`, `seam memory search|get`,
  `seam retrieve --mode mix`.
- Linux installer modes: global (`~/.local/share/seam`) and `--dev` repo-local.

## Active / open direction

- The served browser surface is the self-contained
  `seam_runtime/webui/dashboard.html`. The former Vite/React source is archived
  at `archive/webui-vite-source/` and is not an active rewrite or source of
  runtime truth. Any future modular browser build must be re-established as a
  new verified source path rather than resumed implicitly from the archive.
- Track S S6 must bind every authenticated data operation to a principal and
  add an idempotent opaque deletion/retention contract without leaking tenant,
  MIRL, policy, or graph internals through `/v1`.
- Track S S8 must prove every shipped surface returns the same retrieval IDs and
  order as direct `SeamRuntime.retrieve()` under the same request.
- Turn the SEAM CLI into a first-class agent CLI (model routing, tool execution,
  repo/context awareness, command history, guardrails) on top of SEAM memory.
- Agent Compiler workstream from `docs/roadmap/AGENT_COMPILER.md`: compile canonical
  SEAM protocol into model-specific adapters, benchmark them, audit installed skills.
- README/install polish and agent-bridge docs without breaking CLI aliases.
