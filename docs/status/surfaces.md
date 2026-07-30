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
- REST API: bearer-token protected endpoints, bounded request bodies,
  env-configurable, optional `server` extra.
- MCP agent bridge: `seam mcp stdio` / `seam-mcp`, 16 bounded documented tools over
  MCP JSON-RPC for Gemini/Claude/Cursor-style clients. `seam-mcp --ensure-pgvector`
  can auto-start pgvector.
- RAG surface: `seam ingest <path> --persist`, `seam memory search|get`,
  `seam retrieve --mode mix`.
- Linux installer modes: global (`~/.local/share/seam`) and `--dev` repo-local.

## Active / open direction

- Finish or replace the incomplete `webui/src/` React rewrite without regressing
  graphs, settings, terminal, or chat.
- Turn the SEAM CLI into a first-class agent CLI (model routing, tool execution,
  repo/context awareness, command history, guardrails) on top of SEAM memory.
- Agent Compiler workstream from `docs/roadmap/AGENT_COMPILER.md`: compile canonical
  SEAM protocol into model-specific adapters, benchmark them, audit installed skills.
- README/install polish and agent-bridge docs without breaking CLI aliases.
