# Claude Code subscription benchmarks

[Benchmark run records](BENCHMARK_RUN_RECORDS.md) ·
[Memory formation roadmap](roadmap/MEMORY_FORMATION.md)

Use `claude-code` for benchmark answering and judging through Claude Code's
supported Claude.ai login. The existing `claude` option uses the direct
Anthropic API and its separate billing account. They are distinct experimental
lanes; changing transport, prompts or models requires a new baseline.

The operator clarified on September 14 that the available roughly $50 is on
Claude.ai, not the API Console. It is a reported balance, not a verified
remaining allowance. Do not restore or request an API key for this lane.

## Authentication and isolation

Install Claude Code and sign in with `claude auth login` using the intended
Claude.ai account. No credential belongs in the repository or a handoff.
The transport verifies subscription authentication before inference and removes
inherited API credentials and alternate-provider overrides from its child
environment. It does not extract OAuth credentials or forward them to the
Messages API. A missing subscription login is an error, not an API fallback.

Every request is a fresh noninteractive CLI process in a temporary directory,
with a fixed system prompt, no tools, customization disabled and conversation
persistence disabled. The question/context or judge prompt travels through
stdin. Saved conversations, repository instructions, memory, hooks and MCP
tools must not enter an evaluation. `--bare` is unsuitable because it disables
OAuth authentication. No automatic model fallback is permitted.

The September 14 verified CLI was version 2.1.270. A future CLI change needs
the same isolation and response-contract tests before adopting it for a run.

## Run order

1. Freeze the model, dataset/fixture hash, selected cases, split, baseline
   revision, retrieval settings and answer/judge prompt versions.
2. Run `--dry-run` without `--allow-paid`; it checks fixture selection only.
3. Run a single bundled quickstart case with Claude Code answering and judging.
   This proves transport and recording, not formation quality or generalization.
4. Inspect both responses, served models, errors and usage before enlarging the
   run. Any error or missing result invalidates that case; do not score it as a
   genuine memory failure.
5. Establish a paid baseline on the agreed development selection before
   changing formation. Compare candidates with a fresh matched baseline and
   unchanged controls; preserve the holdout for the agreed evaluation gate.

Use the installed project Python environment. From the repository root:

```bash
python -m benchmarks.external.locomo.run \
  --quickstart --limit 1 --workers 1 \
  --answerer claude-code --answerer-model claude-haiku-4-5-20251001 \
  --judge claude-code --judge-model claude-haiku-4-5-20251001 \
  --context-budget 8000 --search-top-k 100 \
  --retrieval-mode legacy-weighted --dry-run
```

For an authorized smoke, replace `--dry-run` with `--allow-paid` and supply
`--output <durable-run.json>`. Pin cached embeddings and use the offline flags
required by the benchmark preflight. The context budget here is **characters**,
not tokens. Use fresh databases for formation comparisons; `--keep-db` skips
re-ingestion and cannot measure a changed compiler or segmentation policy.

## Cost evidence and limits

Claude Code's `total_cost_usd` is reported usage value, not a verified charge
against Claude.ai credits. Retain that distinction in the run record and
handoff. The direct transport smoke observed `costBasis=list`; the top-level
token counts also differed from the per-model totals. Do not silently replace
one with the other or use an API price estimate as a subscription debit.

The transport reserves a per-call allowance before launching a process, across
answerer and judge calls in that Python process. Failed or interrupted attempts
consume reservations too. CLI limits are best-effort request limits; an
in-flight request can overshoot. A new Python process starts a new allowance,
so these limits do not enforce a cross-process campaign or account ceiling.
Reconcile the account's actual usage separately before larger campaigns.

| Setting | Default | Meaning |
| --- | --- | --- |
| `SEAM_BENCH_CLAUDE_CODE_TOTAL_BUDGET_USD` | `1.00` | Total reservations allowed per Python process |
| `SEAM_BENCH_CLAUDE_CODE_MAX_BUDGET_USD` | `0.10` | Reservation and CLI budget for each launched call |
| `SEAM_BENCH_CLAUDE_CODE_MAX_CALLS` | `10` | Maximum launched calls, including failed attempts |
| `SEAM_BENCH_CLAUDE_CODE_TIMEOUT_SECONDS` | `120` | Timeout for one CLI operation |

Reservations are never refunded from reported costs. A $0.10 reservation
consumes $0.10 of the process allowance even when the returned usage value is
much smaller. Set the intended limits before starting a new process.

No full benchmark campaign is authorized merely by configuring this provider.
The first implementation verification uses a total smoke allowance of $1 in
reported CLI value, with individual calls limited to $0.10. The approximately
$50 balance is not an instruction to spend it all.

## Evidence and interpretation

Keep sanitized provider identity, requested/served model, usage, cost basis and
prompt/transport version with the benchmark result. Do not persist CLI session
identifiers, private conversation links, stderr, credential values or complete
raw CLI envelopes. Raw result text is admitted only through the existing
answer/judge result interfaces. Official account billing remains the authority
for actual charges.

Native strict judging and the Mem0 incumbent-relative judge remain separate.
This Claude Code lane cannot be quoted against a published API scoreboard as
if their conditions matched. No chunking improvement follows from a successful
transport smoke. Read the [benchmark traps](kb/eval-methodology/benchmark-traps.md)
before paid work.

## Provider references

Anthropic's [Agent SDK subscription guidance](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan)
states that the announced separate-credit change was paused; its current
notice says Agent SDK and `claude -p` continue using subscription limits.
[Claude usage credits](https://support.claude.com/en/articles/12429409-manage-usage-credits-for-paid-claude-plans)
cover Claude conversations and Claude Code. Recheck these provider rules when
resuming a later campaign; they do not establish this account's balance.
