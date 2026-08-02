# Status Stream: Surfaces

> CLI, shell, TUI dashboard, webui, REST, MCP, SDK, installers

_Source of truth for current state in this area. History lives in `HISTORY.md`._

## Stable

- Core runtime paths: compile, verify, persist, search, context, benchmark.
- Interactive CLI shell: `seam shell` / `seam chat`, REPL memory interface with
  slash commands and prompt-ready context output.
- Textual TUI dashboard: chat panel, command palette (`/`, `!`, `?`), MIRL
  animation, independently scrollable panes, IDE-style explorer tree, status bar,
  Settings tab, live Overview health bars. `/reload` rebuilds panels without restart.
- Dashboard installers: `seam-dash` shim (Windows `.cmd` + POSIX).
- Browser dashboard served by the REST server: `seam serve` / `seam webui`. The
  static `dashboard.html` IDE shell is the shipped working UI.
- REST API: bearer-token access gate, bounded request bodies, env-configurable,
  optional `server` extra. The token is not yet a principal identity; shared
  hosted tenancy and opaque remote deletion remain Track S S6 work.
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
