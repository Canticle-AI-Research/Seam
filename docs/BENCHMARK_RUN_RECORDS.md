# Benchmark run records — full-fidelity capture

Every judged benchmark run can emit one durable artifact so a paid run is never
again reduced to a handful of aggregate numbers. Introduced in HISTORY#366 after
a ~$1–1.5 cat1/cat3 paid A/B kept only six summary figures (HISTORY#365).

## What gets captured

**Per case, per arm** (`cases[]` in the JSON):

| field | source | cost |
|---|---|---|
| question, gold_answer, category, scope, arm | dataset | free |
| `generated_answer` | answerer | (paid arm) |
| `reasoning_trace` | `<think>…</think>` split from the raw answer | free |
| `verdict`, `judge_score`, `judge_rationale` | judge | (paid arm) |
| `retrieved_context`, `retrieved_context_len`, `candidate_count`, `top_score` | adapter | free |
| `context_recall` | `context_recall(context, gold)` — was the gold *in* what the answerer saw | free |
| `retrieval_hit`, **`failure_class`** | derived join | free |
| `answerer.{prompt,completion,reasoning}_tokens`, `cost_usd` | provider usage × price table | free |
| `judge.{prompt,completion}_tokens`, `cost_usd` | provider usage × price table | free |
| `latency_ms.{retrieval,answer,judge}` | timers | free |

**`failure_class`** is the headline signal: it splits every wrong answer into
`retrieval_miss` (the gold evidence was absent from the retrieved context) vs
`answerer_miss` (the evidence was present, the answerer still got it wrong). That
turns an expensive score into a diagnostic that tells you which layer to fix.

**Run level** (`run`): timestamp, git SHA, SEAM version, dataset + flags +
prompts + models. **`totals`**: per-category/arm judged means, verdict counts,
`failure_class_counts`, total tokens, exact USD cost, and **cost-per-correct**.

### Cost is tokens-exact, table-priced
Token counts come straight from each provider response (exact). Prices come from
`benchmarks/external/common/pricing.py` — an approximate, env-overridable table
(`SEAM_BENCH_PRICING_JSON`). An unpriced model yields `cost_usd = null`, never a
fabricated number.

### Reasoning traces (`<think>`)
OpenAI models (gpt-4o-mini, o-series) do **not** return chain-of-thought text —
only a `reasoning_tokens` count. Real reasoning traces come from:
- **DeepSeek's API** — `--answerer deepseek` (default model `deepseek-v4-pro`;
  cheaper `deepseek-v4-flash` also available via `--answerer-model`). Always use
  an explicit `deepseek-v4-*` id — the `deepseek-reasoner`/`deepseek-chat`
  aliases are DEPRECATED (DeepSeek retires them 2026-07-24) and silently route
  to `deepseek-v4-flash`'s thinking/non-thinking modes (confirmed live: a call
  requesting `deepseek-reasoner` came back reporting `response.model ==
  "deepseek-v4-flash"`). The API returns reasoning in a `reasoning_content`
  field, which the answerer folds into `<think>…</think>` so the recorder
  captures it, and `served_model` records what actually answered (catches
  future rerouting). Requires `DEEPSEEK_API_KEY`; **paid**, and the data does
  transit DeepSeek's API.
- **Local reasoning models** — deepseek-r1 / qwen-thinking via ollama (`--answerer
  ollama --answerer-model deepseek-r1:8b`). Free and fully on-machine; emits
  `<think>` in the text directly.

`reasoning_trace` is `null` for models that hide it (OpenAI).

## Where records are saved

The output directory resolves in this order: `--record-dir` → `$SEAM_BENCH_RECORD_DIR`
→ `benchmarks/runs/records`. A **mount guard** refuses to write when the target is
under an unmounted external drive (`/media`, `/mnt`) — otherwise the data would
silently land on the root filesystem instead of the drive. On this machine
`SEAM_BENCH_RECORD_DIR` is set to a private external drive so records never enter
the repo.

## Outputs

- **`<path>.json`** — the rich analysis artifact (run + totals + every case).
- **`<path>.jsonl`** — one row per (case, arm) as `{messages:[user, assistant], reasoning_trace, gold_answer, verdict, context_recall, failure_class}`, shaped for the LLM-Logs / local-model training corpus.

Records land in `benchmarks/runs/records/` (gitignored — bulky, operator-controlled).

## How to enable

- **`seam improve validate`**: on by default. `--record-dir <dir>` to relocate,
  `--no-record` to disable.
- **Programmatic**: `run_paid_validation(scorer, store, record_path=...)`, or pass
  a `RunRecord` to `JudgedLocomoScorer.score(..., recorder=rec, arm=...)`.

Capture is pure instrumentation — it never changes scoring or makes a network
call, so a run with recording is byte-identical in its scores to one without.
