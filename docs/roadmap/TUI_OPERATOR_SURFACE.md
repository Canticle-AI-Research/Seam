# SEAM TUI Operator Surface

The Textual TUI (`seam_runtime/tui/`) became the live dashboard in HISTORY#537.
Its first shape was a map of the runtime's *modules*: one tab per subsystem
(Memory, Retrieval, Benchmarks, Compression, Chat, Live, Provenance, Settings).
That was the right way to get a working UI onto a 3,183-line backend, and it is
the wrong long-term organisation for a memory runtime an operator uses daily.

This document specifies the target surface and the ordered slices that reach it.

## The reorganising principle

A second-brain surface should be a map of the **operator's loop**, not the
engine's module list:

```
capture  ->  recall  ->  verify  ->  curate  ->  operate
```

Measured against that loop, the first shape has two problems. Three of eight
tabs (Benchmarks, Compression, Live) are engine-development instruments that do
not take part in daily use, and the loop's two highest-value stations do not
exist at all: *what context would the agent actually receive* and *what should
this memory forget or promote*.

Every station below is reachable through APIs that already exist. This is a
presentation programme, not new engine work.

## Target tab set

| tab | loop station | primary source |
|---|---|---|
| Memory | capture / inspect | `store.list_namespaces/list_scopes/list_record_summaries`, `runtime.trace` |
| Recall | recall | `runtime.search_ir` + `runtime.assemble_context` |
| Review | verify | `sdk.promotions` / `promotion_eligibility` / `review_promotion` / `apply_promotion` / `reverse_promotion` |
| Curate | curate | `runtime.plan_scoped_delete` -> `apply_scoped_delete`, `sdk.recoverable_operations` / `resume_operation` |
| Health | operate | `runtime.check_ready`, `doctor.build_doctor_report`, `verify_vector_divergence` / `repair_vector_divergence` / `replay_vector_outbox`, workspace events |
| Engine | develop | benchmarks + compression, folded |
| Chat | use | existing chat panel, plus the injected-memory list |
| Settings | configure | `seam_runtime/config.py` registry |

Provenance stops being a tab and lives under the Memory table (HISTORY#540).
Live stops being a tab and becomes the activity strip on Health.

## Contracts every panel obeys

These are not style preferences. Each one is a defect class already paid for.

1. **No panel invents a retrieval or SQL path.** Data comes from a documented
   `SeamRuntime`/`SeamSDK` entry point, or from the exact `store` method the
   runtime itself delegates to, with the source location cited in a comment.
   Track S S8 must prove every shipped surface returns the same retrieval IDs
   and order as `SeamRuntime.retrieve()`; a panel with a private query path
   makes that unprovable.
2. **Blocking work runs on a worker thread** (`@work(thread=True)`) and
   marshals results back with `self.app.call_from_thread(...)`. Retrieval and
   SQLite block for real time; running them on the event loop freezes the whole
   app, which is what the pre-#537 dashboard did.
3. **Empty and error states are visible rows**, never a silently blank table.
4. **Destructive actions are two-phase**: render the plan, require an explicit
   confirm, then apply. The lifecycle API already models this as
   `plan_scoped_delete` -> `apply_scoped_delete`; the UI must not collapse it.
5. **Secrets are masked until an explicit per-field reveal.** No bulk unmask.
6. **A headless mount passing is not evidence.** Every slice is verified by
   launching the real binary under tmux at two terminal sizes. Both HISTORY#537
   defects were live while `run_test()` mounts passed.
7. **Tests keep every `textual` import inside the test body**, behind the
   `textual_required` marker. A module-scope import of an optional extra is a
   collection error that aborts the entire repository suite (HISTORY#539).

## Shared workspace selection

Slices 3 and 4 need the same three values, and several later panels need them
too: `namespace`, `scope`, and `as_of`. They are introduced **once**, in slice
3, as reactive attributes on `SeamTUI`, and panels read them rather than each
inventing a selector. `assemble_context` requires all three as keyword
arguments, so this is a hard dependency, not tidiness.

## Slices

Each slice is independently shippable, independently verifiable, and ends with
a HISTORY entry. They are ordered by dependency and by how much they unblock.

### S1 — Memory workspace (landed, HISTORY#540)

Records table on top, provenance trace directly below, one shared log. Row
selection exposes the full record id in an editable field and traces it without
changing the clipboard; an adjacent Copy ID button and `y` are the explicit
copy paths. The same field accepts pasted ids and Enter traces them. The
standalone Provenance tab is removed — keeping both would duplicate
`#prov-query` and fail the mount on duplicate ids.

### S2a — Every command carries a description, and the menu is organized

Measured: **104 of the 153 catalog commands have no description** — all 66 CLI
commands, all 27 REST routes, and 11 of 21 SDK methods. Only the dashboard
verbs (a hand-maintained dict) and the MCP tools (real metadata) are covered.

The descriptions belong **at the source, not in the TUI**. `commands.py`
derives from each surface's own metadata on purpose; an empty description is
missing upstream metadata, and filling it upstream fixes `seam --help` and the
published OpenAPI schema at the same time. `help=` on each `add_parser`,
`summary=` on each route decorator, a docstring on each SDK method — plus the
two reader fixes that make them visible (`_walk_parser` reads argparse `help=`
off the parent action, not just `description`; `_ROUTE_RE` captures the
decorator's `summary=`).

Grouping moves to **one task vocabulary shared by every surface** — Capture,
Recall, Context, Provenance, Knowledge graph, Compression, Benchmarks, Improve,
Serve & surfaces, Lifecycle & admin, Session — derived from the root command,
path prefix, or method name rather than hand-tabulated. The palette renders in
two sections: **Run** (the 20 executable dashboard verbs, grouped by task) then
**Reference** (cli/mcp/api/sdk, grouped by the same tasks, each row tagged with
its surface), so the CLI form, REST route and MCP tool for one task sit
together.

A test asserting every catalog entry has a non-empty summary is the gate that
keeps the next added command from arriving undescribed.

### S2b — Input modes, navigation, palette hardening

Three sigils set the mode, matching what the superseded dashboard did
(`dashboard.py:1175-1195`) so muscle memory survives:

| sigil | mode | whole-line paste/prefill | typed sigil |
|---|---|---|---|
| `/` | seam (default) | open/filter the command menu | open the menu |
| `!` | shell | run one shell command | latch shell mode |
| `?` | chat | send one message to the model | latch chat mode |

A whole `!`/`?`-prefixed line pasted or otherwise inserted atomically is
one-shot regardless of the current mode. A typed `!` or `?` latches immediately, and
the following keystrokes run in that mode; the application cannot both latch
on the first keypress and retrospectively treat the completed typed line as a
one-shot override. Sigils also latch from any non-text widget. Escape returns
to seam mode and focuses the command bar. Sigils typed into Settings, search,
or provenance inputs remain editable text. The mode is visible in three places,
because an invisible mode is a trap: the brand-bar status, the input placeholder,
and the input's border colour.

Both modes reuse machinery that already exists rather than adding engine work.
Shell: the `cd`/`pwd`-aware subprocess logic currently trapped inside the
superseded UI class becomes `seam_runtime/tui/shell.py`, a `ShellSession`
owning `cwd` — unit-testable without a TUI, which the original never was. This
restores a capability the previous dashboard already shipped, but deliberately
not that dashboard's full HISTORY#272 security posture: subprocess commands
run with `shell=True` unconditionally once enabled, because pipes, globs,
`&&` chaining and `~` expansion are most of why `!` is worth having, and
HISTORY#272's allowlisted `shell=False` rewrite of `dashboard.py`'s
`_run_shell_subprocess` would kill all of them — so that path is **not**
restored. What **is** restored from that same entry is its master gate:
`SEAM_DASHBOARD_ALLOW_SHELL`, off by default, already a registered `bool`
Setting in the TUI's own Settings tab (`config.py`'s "Dashboard" group), read
fresh from the environment on every `!` command so flipping the Switch takes
effect immediately with no relaunch. `cd`/`pwd` spawn no subprocess and are
unaffected by the gate, matching where HISTORY#272 put it originally (inside
`_run_shell_subprocess`, not around `cd`). It is a local operator tool once
enabled, not a new network surface. Chat: module-level `SeamChatClient`
(`dashboard.py:256`) plus `backend.orchestrator.rag(...)` for the context
prompt, the same pair the old UI used — and the reply renders **with the
memory ids it injected**, which is the S9 idea landing early because the rag
result is already in hand.

Carried in the same slice, all three found by probing the shipped binary:

- **The palette keystroke race.** Typing `/stats` at speed opens the palette
  with an EMPTY filter and the first entry highlighted, because characters
  typed between the leading `/` and the palette's mount land in
  `#command-input` and are discarded. Enter then acts on an entry the operator
  never chose. Today the first entry (`/benchmark`) takes a positional so it
  only pre-fills the input — luck, not safety. `CommandPalette` already accepts
  an `initial` filter and nothing passes it.
- **`tab <view>` does not move the visible tab.** `dashboard.py:2421` parses
  it and `:2544` sets `controller.active_tab`; the superseded UI read that back
  at `:1520-1524` and the new one never does, while `app.py`'s docstring claims
  the command still works.
- **No keyboard tab navigation.** `ctrl+s` reaches Settings; every other tab is
  mouse-only. `alt+1`..`alt+8` jump, `ctrl+left`/`ctrl+right` cycle — chosen
  over bare digits because the command input holds focus and consumes
  printable keys.

- **Keyboard tab switching.** `alt+1`..`alt+8` jump directly; `ctrl+right` /
  `ctrl+left` cycle. Chosen over bare digits because the command input holds
  focus and consumes printable keys.
- **Wire the `tab` command.** `app.py`'s docstring claims the backend's `tab`
  verb still works; it does not. The backend parses `tab runtime|benchmark`
  (`dashboard.py:2421`, `:2544`) and sets `controller.active_tab`, but the new
  UI never reads it — the old UI did (`dashboard.py:1520-1524`). Either map it
  onto `TabbedContent.active` or widen it to the real tab names and update the
  docstring. Do not leave the claim unbacked.
- **Fix the palette keystroke race.** Typing `/stats` at speed opens the
  palette with an *empty* filter and the first entry highlighted, because the
  characters typed before the palette mounts land in `#command-input` and are
  discarded. Enter then acts on an entry the operator never chose. Today the
  first entry (`/benchmark`) takes a positional, so it only pre-fills the input
  — that is luck, not safety. `action_open_palette` must take the leftover text
  out of `#command-input`, clear it, and pass it as the palette's `initial`;
  `CommandPalette.on_mount` must apply that filter (it accepts `initial` today
  and ignores it).

Exit gate: `/stats` typed at full speed filters to `/stats`; every tab is
reachable without a mouse; `tab <name>` moves the visible tab or the docstring
no longer claims it does.

### S3 — Namespace / scope rail on Memory

`MemoryRecordsPanel._load_rows` already walks `list_namespaces` ->
`list_scopes` -> `list_record_summaries` and then throws that structure away by
flattening into one list. Today `deepagent-seam` and `local.default` records
interleave with no way to separate them. For a second brain the namespace *is*
the project.

- Left rail: namespaces, each expandable to its scopes, each row carrying a
  record count. `Tree` is the right widget — the data is two levels.
- Selecting a namespace or scope sets the shared workspace selection (above)
  and filters the table.
- An "all namespaces" root keeps today's behaviour reachable.
- The count is a real count, not `len(list_record_summaries(limit=…))`. There
  is no `count_records` on `SQLiteStore`; add one there rather than counting a
  truncated page in the UI.

Exit gate: selecting a scope filters the table and updates the shared
selection; counts match `stats` output for the same namespace.

### S4 — Recall tab with context-pack preview

The highest-value new view in the product. Rename Retrieval to Recall and split
it into two stages, because they are two different questions:

- **Ranked candidates** (existing `#retrieval-table`, `runtime.search_ir`) —
  what the engine found.
- **Context pack** (`runtime.assemble_context(task=…, namespace=…, scope=…,
  as_of=…, token_budget=…)` returning `ContextPack`) — what the agent would
  actually receive. Render `token_cost` against `token_budget`, the `items` in
  pack order, and — this is the part no other surface shows —
  `omitted_candidate_ids` and `rejected_counts`, so the operator can see *what
  fell off the budget edge and why*.

`namespace`, `scope` and `as_of` come from the S3 selection. `as_of` defaults to
now, and is editable: point-in-time recall is a real SEAM capability with no UI.

Exit gate: one query renders both stages; raising the budget visibly moves ids
out of `omitted_candidate_ids` and into the pack.

### S5 — Settings redesign

The registry-driven bones are right (116 settings, 14 registry groups including
Custom Keys, `bool` -> Switch,
`enum` -> Select, validation borrowed from the owning modules). The presentation
is one flat scroll where every row is three lines tall.

- **Two-pane master/detail.** Group rail left with per-group counts and an
  "n set" badge; rows right. Turns a 115-row scroll into <= 25 rows per screen.
- **Pin a synthetic "Set" group first** — only settings whose `value_source` is
  env or file. "What have I overridden?" is the common question and there is no
  way to ask it today.
- **Move the description out of every row** into a footer detail for the
  focused row. The per-row description is what makes rows three lines; this
  roughly triples what fits on screen.
- **Collapse Provider Keys (25 rows, 27 secrets repo-wide) behind an explicit
  reveal.** It is the largest group and the least frequently changed, and it
  currently paints 25 masked inputs on first render.
- **Search switches the right pane to flat results with a group column**,
  rather than filtering inside a giant scroll.
- **Fix the silent no-op — which is worse than this document first recorded.**
  An earlier revision of this bullet claimed `_save` calls
  `apply_persisted_to_environ`. It does not, and that was doc drift against
  code which never behaved that way (traced in HISTORY#542). `_save` calls
  `config.save_persisted` and writes the file only; the separate **Reload**
  action is the sole caller of `apply_persisted_to_environ`. So there are two
  stacked gaps, not one:
  - Save reports success while the running process still holds the old value
    for settings read directly from `os.environ`, until Reload is pressed.
    The shell gate and chat client are bounded exceptions: they re-read
    `config.effective_value` before their next action, so those saved controls
    no longer require Reload.
  - Even after Reload, construction-time knobs — `SEAM_DB_PATH`, the embedding
    provider, the vector adapter — cannot take effect, because the live
    `SeamRuntime` was already built.

  Making Save apply is not a one-liner: `apply_persisted_to_environ`
  deliberately refuses to overwrite a name already present in the environment,
  which is the rule that keeps `SEAM_X=1 seam-dash` behaving like every other
  CLI. S5 must decide what Save means for a name the process already has, then
  either rebuild the runtime or badge the affected rows "takes effect on
  restart". Reporting success for a change that did not take effect is the same
  defect class as HISTORY#537's silently-unset `DEEPSEEK_API_KEY`.

Exit gate: a construction-time knob either takes effect or says it will not;
the "Set" group lists exactly the non-default values.

### S6 — Review inbox

`sdk.promotions(ns=…, scope=…, limit=…)` lists proposals; `promotion_eligibility`
explains whether one can be applied; `review_promotion(review_kind=…,
decision=…, reviewer_id=…, rationale=…)` records a human decision;
`apply_promotion` persists it as canonical MIRL; `reverse_promotion` appends a
reversal and a supersession relation.

The whole review lifecycle exists in the SDK with zero UI. This is the panel
that makes SEAM a second brain rather than a log: reasoning-derived assertions
wait for an operator instead of silently becoming truth.

Apply and reverse are destructive-adjacent and take the contract-4 treatment:
show the assertion, its evidence, and its eligibility verdict before the
confirm.

Exit gate: a proposal can be reviewed, applied, and reversed from the TUI, and
the reversal is visible in the record's provenance on the Memory tab.

### S7 — Curate: forget and retention

`plan_scoped_delete(tenant_id, namespace, scope, record_ids, idempotency_key,
actor)` returns a plan; `apply_scoped_delete(tenant_id, operation_id, actor)`
executes it; `sdk.recoverable_operations(tenant_id=…)` lists operations that
stopped part-way and `resume_operation` finishes them.

A memory system that can only accumulate is a hoarder. The runtime already
models plan -> apply, which maps exactly onto a two-phase confirm, and no
surface exposes it interactively.

The plan view must render what will be deleted **and** what references it, so
the operator is not guessing at blast radius. `idempotency_key` is generated by
the UI and shown, never hidden.

Exit gate: an interrupted delete appears in recoverable operations and can be
resumed to completion from the TUI.

### S8 — Health, with Live folded in

One page answering "is my memory intact", with the repair action beside the
diagnosis:

- `check_ready()` — readiness, raises when either persistence layer cannot
  serve a trivial read.
- `doctor.build_doctor_report()` — the report `seam doctor` prints. It is
  CLI-only today.
- `verify_vector_divergence()` / `repair_vector_divergence()` — the three
  divergence shapes (missing, stale, orphan) from HISTORY#533, with repair.
- `replay_vector_outbox()` — unacknowledged index intents.
- The existing Live workspace-event table becomes the activity strip here.

Exit gate: an induced divergence is detected, repaired, and re-verified without
leaving the TUI.

### S9 — Engine fold and Chat provenance

Benchmarks and Compression become one Engine tab; they are development
instruments, not daily stations. Chat gains the list of memories it injected
into each turn — without that it is a worse terminal for a chat available
elsewhere, and with it it is a live demonstration of retrieval quality.

## Deferred, deliberately

- **Graph panel.** `runtime.knowledge_graph` and `graph_products` are the real
  differentiator, but Track R G2 is mid-build. Hardening a UI against a moving
  contract buys rework; build it when the substrate is complete.
- **Removal of `TextualDashboardApp`** (`dashboard.py:496-2360`). Still dead
  code behind a deprecation docstring, still the only coverage of several
  dashboard behaviours through its 28 usages in `test_seam_all/test_seam.py`.
  Removal waits until those are ported or retired.
- **`dashboard.py` audit.** On the never-audited list across two consecutive
  whole-repository audits. The TUI split narrowed its role to backend plus one
  dead UI class; it did not audit it.

## Open decision

Does the TUI ship to self-host users, or is it operator-only? The settled
product shape hides MIRL behind the product surface, and the Memory table shows
MIRL kinds (ENT/CLM/RAW/PROV/SPAN) and raw canonical ids. If the TUI ships in
the self-host package, that table needs a product-level presentation with the
MIRL view behind an operator flag. If it is operator-only, it stays as is. This
decision blocks nothing before S5 but should be made before S9.
