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
  - Canticle Cosmic UI kit: `branding/canticle-cosmic-kit/` is the reusable
    component expression layer over `branding/kit/`. It defines the more
    playful cosmic-arcade shape, spacing, effects, and accessibility contract,
    with CSS/HTML, Tailwind v4, opt-in Textual, and Lip Gloss v2 adapters plus
    a responsive gallery. It changes no live surface by itself; TUI and WebUI
    adoption remain separate reviewed work.
  - Keyboard navigation: `alt+1`..`alt+N`, `ctrl+left`/`ctrl+right`, and
    `tab <name>`. `alt+N` also works on terminals using the classic
    "Alt sends Escape" convention (xterm and descendants, `tmux send-keys
    M-3`), which deliver it as the printable character textual resolves
    `ESC`+digit to — `¡™£¢∞§¶•ª`. Those nine characters are bound alongside
    the real keycodes, and `tui/keys.py:SeamInput` declines to consume them
    so the binding survives a focused field. Nothing above textual's parser
    distinguishes them from a UK keyboard's genuine `shift+3`, so
    `SEAM_TUI_META_DIGITS=off` gives them back as literal text and leaves
    only real `alt+N` jumping.
  - Target surface and the ordered slices toward it:
    `docs/roadmap/TUI_OPERATOR_SURFACE.md`.
  `dashboard.DashboardApp` remains the backend and still owns the Rich
  `--snapshot` and `--run` modes.
  - The previous in-`dashboard.py` `TextualDashboardApp` UI is superseded and
    unreachable, kept as deprecated dead code because its 28 test usages are
    the only coverage of several dashboard behaviours. Removal is deferred.
- Dashboard installers: `seam-dash` shim (Windows `.cmd` + POSIX).
- Browser dashboard served by the REST server: `seam serve` / `seam webui`.
  The static `dashboard.html` IDE shell is a shipped prototype, not an
  operator beta. It mixes live API data with browser-local simulations,
  credentials in `localStorage`, mock fallback data, and actions that report
  success without backend acknowledgement. Its knowledge
  graph keeps **Topology** available and adds **Constellation** as an alternate
  presentation of the same canonical payload: the selected node is the north
  star, deterministic breadth-first distance sets the rings, and only real
  typed API edges draw lines. Screen proximity does not assert similarity or
  synthesize topology. The view uses `branding/kit/` colors, remains mostly
  static, and presents the final state directly under reduced motion.
- REST API: bearer-token guard when `SEAM_API_TOKEN` is configured, bounded
  request bodies, env-configurable, optional `server` extra. An unset token is
  trusted-loopback development only; automatic token provisioning remains an
  open authentication/UX policy. Protected main's token-only mode is a trusted
  single-user gate, not tenancy. The unpublished Track S S6 candidate adds
  optional in-process principal resolution and indexed opaque deletion. In
  principal mode it derives the internal tenant/namespace from the subject,
  binds handles/deletion to the canonical generation, defaults to a bounded
  process-local limiter with separate pre-parse client, non-evicting credential-
  resolver, and stable-subject budgets, requires injected hosts to declare
  their worker count, and blocks legacy private route/method shapes before
  router matching while retaining allowed CORS preflights and mounted
  `root_path` routing. Store-local writes, deletion, and compensation share a
  bounded cross-process lock. Fourteen findings across three exact-head Codex
  review cycles plus CodeRabbit lock hardening are now locally repaired with
  185 focused tests. The fourth head still needs exact-head CI, final review,
  and merge.
- MCP agent bridge: `seam mcp stdio` / `seam-mcp`, 19 bounded documented tools over
  MCP JSON-RPC for Gemini/Claude/Cursor-style clients. `seam-mcp --ensure-pgvector`
  can auto-start pgvector. The private handshake reports the installed runtime
  package version; `server.json` retains its intentional legacy compatibility
  value.
- RAG surface: `seam ingest <path> --persist`, `seam memory search|get`,
  `seam retrieve --mode mix`.
- Linux installer modes: global (`~/.local/share/seam`) and `--dev` repo-local.

## Active / open direction

- The operator-authored source was subsequently located at
  `/media/terrabyte/External2/SEAM TUI Concept.dc.html`. It is a visual
  mock/prototype, not a runnable replacement or shipped surface. A separate
  clean `feat/tui-concept-shell` worktree is porting its operator-loop concepts
  into the runtime-backed Textual app. Until that candidate passes review and
  merges, the current TUI still needs the target scope, Recall preview, Review,
  Curate, Health, and Settings workflow slices, plus provider-host and response-
  allocation policies shared with REST.
- The served browser surface is the self-contained
  `seam_runtime/webui/dashboard.html`. The former Vite/React source is archived
  at `archive/webui-vite-source/` and is not an active rewrite or source of
  runtime truth. Any future modular browser build must be re-established as a
  new verified source path rather than resumed implicitly from the archive.
- Before restyling the WebUI, remove credential persistence and simulated
  success, require backend acknowledgements, label unavailable/demo states
  explicitly, and add browser truthfulness tests. Only then capture fresh
  desktop/mobile renders for operator approval.
- Track S S6 PR #223 binds every principal-mode data operation
  to an in-process identity and adds indexed, idempotent opaque deletion without
  leaking tenant, MIRL, policy, or graph internals through `/v1`. Publication
  still requires its signed review-repair commit, repeat exact-head CI, and merge.
- S7 remains next after S6 publication; it owns admissible semantic ingest and
  exact evidence, not this surface/security slice. S7 has not started.
- Track S S8 must prove every shipped surface returns the same retrieval IDs and
  order as direct `SeamRuntime.retrieve()` under the same request.
- Turn the SEAM CLI into a first-class agent CLI (model routing, tool execution,
  repo/context awareness, command history, guardrails) on top of SEAM memory.
- Agent Compiler workstream from `docs/roadmap/AGENT_COMPILER.md`: compile canonical
  SEAM protocol into model-specific adapters, benchmark them, audit installed skills.
- README/install polish and agent-bridge docs without breaking CLI aliases.
