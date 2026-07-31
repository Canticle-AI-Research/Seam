# Running the mem0 harness against SEAM (the facade)

Operational reference for the incumbent-relative scoreboard. Pair with
`benchmark-traps.md` before spending.

## The setup

- **Harness:** `mem0ai/memory-benchmarks`, pinned commit `4b61c5d`, cloned to
  `/tmp/memory-benchmarks` with its own venv. Its OSS backend is an HTTP client
  over three REST endpoints.
- **Facade:** `benchmarks/external/mem0_harness/seam_mem0_server.py` implements
  `POST /memories`, `POST /search`, `DELETE /memories` on the real
  `SeamLocomoAdapter`, so the harness runs UNMODIFIED against SEAM. One namespace
  per `user_id` (`locomo:<user_id>`); `/search` returns ranked RAW turn strings
  `[Speaker YYYY-MM-DD] text`. Honors `RetrievalFlags` + env policies.
- **Dataset:** `~/seam_benchmarks/track_m/locomo/locomo10.json` (10 conversations;
  cat1 282 / cat2 321 / cat3 96 / cat4 841 / cat5 446).
- **Mandatory env:** `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
  SEAM_BENCH_RECORD_DIR=/mnt/t7/Proprietary/DATA`. Omitting the offline flags
  fails real-facade runs on a BGE load / stale-HF-token error.
- **Do NOT set `HF_HUB_CACHE`.** The default `~/.cache/huggingface` holds
  `BAAI/bge-small-en-v1.5` and loads offline (verified). The old
  `/media/terrabyte/T7/...` paths are DEAD: T7 now mounts at `/mnt/t7`, so
  `/media/terrabyte/T7` is an empty directory on the INTERNAL disk. Pointing
  `HF_HUB_CACHE` there makes huggingface_hub silently create it, find nothing,
  reach for the network, and fail every case with `OSError: couldn't connect to
  huggingface.co ... couldn't find them in the cached files` — a 200-case run
  scored 0.0 on all 200 that way on 2026-07-31.

## The two-phase run pattern

1. **FREE predict-only** (proves the round-trip, zero spend):
   `python -m benchmarks.locomo.run --project-name X --backend oss
   --mem0-host http://127.0.0.1:PORT --dataset-path <locomo10.json>
   --categories 1,3 --top-k 200 --predict-only`. Verify selection counts and
   zero-empty retrieval before spending.
2. **PAID evaluate** (reuses stored predictions): drop `--predict-only`, add
   `--answerer-model gpt-4o --judge-model gpt-4o --top-k-cutoffs 200`. Match the
   models to the *claim* you're making (`benchmark-traps.md#2/#3`).

## Gotchas learned the hard way

- **Run the facade from a CLEAN worktree** when concurrent agents have
  uncommitted runtime edits, so the memory under test is the committed code.
- **Rate limits corrupt silently:** the harness `LLMClient` returns `""` after
  shallow retries and the judge scores the empty string — BOTH directions
  (empty→WRONG, and lenient judge sometimes empty→CORRECT). Recovery recipe:
  strip any case whose `cutoff_results.top_200.generated_answer` is blank, then
  re-run `--evaluate-only` (idempotent; per-case checkpoints on disk). Throttle
  with `--max-workers 2 --rpm 8` to stay under the org gpt-4o 30K TPM cap.
- **Default answerer/judge in the harness are gpt-5** — always pass explicit
  `--answerer-model/--judge-model`.
- **Cost:** run `benchmarks.external.common.cost_report <artifact>
  --harness-root /tmp/memory-benchmarks` after; it's a LOWER BOUND
  (`benchmark-traps.md#7`). A full 378-case cat1+cat3 gpt-4o run measured
  ~$12–13.

## Free structural preflights (no provider calls)

- `preflight_event_count_context.py` — count-projection coverage over a stored
  artifact.
- **(to build)** a derived-facts coverage/precision preflight — the #435 next
  gate; see `../seam-internals/derived-facts-grounded-clm.md`.

## Key artifacts (T7, private — cite by SHA, never commit)

| Artifact | What | HISTORY |
| --- | --- | --- |
| `20260715-091018-…cat13.json` | mini-lane baseline (cat1 88.65 / cat3 86.46) | #400 |
| `20260719-161639-…cat13-matched-final.json` | matched gpt-4o (cat1 87.94 / cat3 69.79) | #429 |
| `20260719-114500-…cat24-recon-final.json` | cat2/cat4 mini recon | #426 |
