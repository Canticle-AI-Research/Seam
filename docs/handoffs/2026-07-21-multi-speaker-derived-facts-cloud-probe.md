---
handoff_id: 2026-07-21-multi-speaker-derived-facts-cloud-probe
supersedes: 2026-07-21-multiscope-and-local-beam-complete
handoff_status: superseded
history: HISTORY#448
---

# Handoff: multi-speaker derived-facts lever — cloud displacement probe

**For:** the next agent (GPT/Codex) picking up the derived-facts arc.
**Date:** 2026-07-21
**Branch:** `agent/gpt4o-multi-speaker-probe`.
**Publication:** operator requested push + PR merge; see HISTORY#448.
**Paid extraction:** $2.113255 for the faithful GPT-4o run, plus approximately
$0.034030 for the stopped fidelity-check run and one synthetic smoke call
($2.147285 total observed extraction spend). No answerer or judge call ran.

## One-line state

The GPT-4o probe is complete and **promotion is parked**. GPT-4o improved
extractor yield over the local 7b (80.15% versus 73%), and the corrected strict
contract produced a small miss-side evidence gain, but even one inserted fact
per query caused four sentinel evidence losses. The blocker is the additive
top-200 row/displacement contract, not simply the model.

## Completed cloud result

The faithful run covered conversations 3/4/5: 130/130 questions, exactly 34
baseline misses and 96 sentinels. All 1,984 chunks ingested with zero failures.
GPT-4o made 1,968 extraction calls (686,738 input / 39,641 output tokens), emitted
1,305 items, and the original validator accepted 1,046 (80.15%).

The first diagnostic exposed two contract defects: the pinned upstream client
re-sorted the protected splice by the original similarity score, and the draft
validator was not conservative enough for ambiguous/compound evidence. Both are
now repaired: transport scores pin composed order, and the validator fails closed
on ambiguous antecedents, clause recombination, reporting/quotes, unsupported
content, and tense/modality/number/negation loss. This is conservative
syntactic/lexical grounding, not proof of arbitrary semantic entailment.

The authoritative zero-paid replay reused the exact stores/checkpoints and made
zero provider calls:

| lane | miss gained/lost | miss net | sentinel gained/lost | fact rows | order/ceiling | result |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| strict uncapped | 3 / 1 | +2 | 7 / 11 | 2,328 | 0 / 0 | fail |
| cap 4 | 2 / 1 | +1 | 12 / 4 | 518 | 0 / 0 | fail |
| cap 2 | 2 / 1 | +1 | 12 / 4 | 260 | 0 / 0 | fail |
| cap 1 | 2 / 1 | +1 | 12 / 4 | 130 | 0 / 0 | fail |

Cap 0 is the unchanged baseline. Since cap 1 still loses four sentinel gold
references, there is no nonzero additive fact-row setting that passed the tested
no-regression gate. Do not request a full cloud ingest or paid answerer microgate
for this shape.

Primary reproducibility artifacts remain outside git under
`/media/terrabyte/T7/Proprietary/DATA/seam-ms-gpt4o-probe.ekhTRe/`:

- strict candidate SHA-256
  `1b1ab1b366cbf2cd5c6b6f09bba1c0f3fafa0602adad00e589551c15966f4ceb`;
- strict audit SHA-256
  `aaa5704df2f7d1199ff1d90dd444ac8bed2b798d0125dce0bc3a4e40061160c2`;
- cap-1 audit SHA-256
  `4ba6fa300fcd31a6cee9747018d53562fc62f8f1b42c4bbc24da11ef00fa5a31`.

## Why this lever exists (the diagnosis)

Reading mem0's actual source (`/home/terrabyte/BEAM/mem0`, Apache-2.0, v2.0.12)
established that mem0 wins LoCoMo with an extractor that is **recall-biased and
multi-speaker** (`ADDITIVE_EXTRACTION_PROMPT`): it extracts third-person facts
about *named others*, not just first-person, and manages precision with a
*separate downstream reconcile*, not a fail-closed gate. SEAM's live
`sentence-grounded-clm/1` is **singular-first-person only**, so on the
multi-speaker LoCoMo corpus it refuses most gold turns — the diagnosed cause of
the 51/63 reach ceiling (HISTORY#439). Full write-up:
`docs/kb/memory-systems/mem0.md` (source-verified section) and
`docs/kb/seam-internals/derived-facts-grounded-clm.md` (broadened-variant
section).

## What is built

- **`seam_runtime/multi_speaker_facts.py`** — the broadened contract
  `multi-speaker-grounded/1`: prompt, schema, eligibility (`declarative_evidence`,
  broader than first-person), and `validate_multi_speaker_fact_with_reason`.
  Takes mem0's recall breadth but keeps **grounding, not reconcile** as the
  precision mechanism. The final fail-closed checks cover a unique antecedent,
  ordered single-clause binding, names, quotes/reporting, lexical support,
  tense/modality, numbers, and negation. `ground_scope="turn"` permits only one
  unique preceding subject name. Reuses helpers from
  `sentence_grounded_facts.py`. **Explicit and default-off.**
- **`benchmarks/external/mem0_harness/preflight_multi_speaker_facts.py`** — the
  free coverage/precision/closure gate (`OllamaMultiSpeakerFactExtractor` +
  `summarize_record`). CLI: `--model`, `--ground-scope`, `--limit`, `--cache`.
- **`benchmarks/external/mem0_harness/preflight_displacement_audit.py`** — the
  displacement auditor. Diffs a **baseline** (facts-off) vs **candidate**
  (facts-on) Mem0-harness artifact and reports the 5 metrics: gold-evidence
  presence, fact placement, source-before-fact ordering, RAW pack displacement,
  and **sentinel** (previously-correct) regressions. Numeric-only output.
- Tests (all green): `tests/audit/test_multi_speaker_facts.py`,
  `tests/audit/test_multi_speaker_preflight.py`,
  `tests/audit/test_displacement_audit.py`. Ruff clean.

## What is measured (7b, local, $0)

Free coverage gate over the 63 cat1/cat3 misses from the matched artifact
`/media/terrabyte/T7/Proprietary/DATA/20260719-161639-mem0-harness-cat13-matched-final.json`,
extractor `qwen2.5-7b-1m:latest`:

| metric | sentence-scope | turn-scope | note |
| --- | --- | --- | --- |
| reach (misses with a fact) | 58/63 (+7) | 59/63 (+8) | vs sentence-grounded 51/63 |
| third-person-only reach | 2 | 2 | upside first-person can't get |
| wording closure (fact beats raw gold) | 52/63, +0.109 | 52/63, +0.106 | |
| binding precision (yield) | 0.67 | 0.73 | **fails the borrowed 0.90 gate** |

**Resolved interpretation:** the 0.90 gate measures extractor yield. GPT-4o
raised yield from 0.73 to 0.8015 but did not reach 0.90. More importantly, the
strict replay proved that accepted facts can surface useful miss evidence while
the separate-row insertion still displaces sentinel evidence. Model quality is
part of the extraction noise; the additive serving contract is the blocking
ceiling.

Historical side probe: a `gemma2:9b` coverage A/B was launched separately
(slow; gemma2:9b spills ~20% to CPU on the 8 GB RTX 2070). Any results are in
`.../scratchpad/gemma_sentence.json` / `gemma_turn.json`. `gemma4:e4b` could NOT
be pulled — ollama 0.18.3 is too old for Gemma-4.

## Executed task (operator overrode the model to GPT-4o)

Answer go/no-go with a **cloud displacement probe scoped to 3 conversations**.
This is faithful, not an approximation: LoCoMo stores are **per-conversation**, so
ingesting whole conversations gives a real (smaller-N) displacement result.

**Scope: conversations 3, 4, 5** — they hold **34 of the 63 misses (54%)** plus
**96 sentinels**, 130 questions total. (Per-conv miss counts:
`3→15, 4→12, 5→7`.)

Steps:

1. **Build the runtime policy plumbing.** Wire `multi-speaker-grounded/1` into
   `seam_runtime/derived_fact_context.py` (ingest + serve/render `SEAM-FACT/1`,
   reuse `splice_derived_facts` and the `raw-prefix-floor/2` ≤20% ceiling) and the
   facade `benchmarks/external/mem0_harness/seam_mem0_server.py`. **Mirror exactly
   how `sentence-grounded-clm/1` is wired** — read that path first. Default-off.
   ⚠️ `seam_mem0_server.py` is one of Codex's touched files — re-read it fresh and
   add only, don't revert Codex's edits.
2. **Build a GPT-4o cloud extractor** — a variant of
   `OllamaMultiSpeakerFactExtractor` that calls the OpenAI API
   (`OPENAI_API_KEY` was reused with operator approval; model `gpt-4o`;
   JSON-schema/`json_object`
   response) and validates with `validate_multi_speaker_fact_with_reason`. Same
   content-addressed cache pattern. This erases most of the 7b's yield noise, so
   it doubles as the "is extraction quality the ceiling?" answer.
3. **Produce a predict-only candidate artifact** for convs 3/4/5 with the policy
   ON, at the **matched profile** (search_top_k 300 / context_budget 60000,
   `--predict-only` so $0 on the answerer/judge; only extraction is paid).
   Approximately 1,900 eligible turns span the three conversations.
4. **Diff** baseline vs candidate:
   `python -m benchmarks.external.mem0_harness.preflight_displacement_audit <baseline> <candidate> --expected-conversations 3 4 5 --summary-only`
   (the auditor now fails unless every baseline question in the declared scope
   appears exactly once).
5. **Report go/no-go:** did facts surface gold into the served top-200? did any of
   the 96 sentinels regress? net displacement of RAW? A clean result (gold
   surfaced, zero sentinel loss) → justify the full 10-conv run + eventual paid
   microgate. A regression or no gold-surfacing → park the lever cheaply.

## Resources / environment

- Baseline artifact (facts-off, 378 cat1+cat3, has `retrieval.search_results`):
  `/media/terrabyte/T7/Proprietary/DATA/20260719-161639-mem0-harness-cat13-matched-final.json`
- Corpus: 5,882 turns, **5,768 eligible** for extraction. Full local 7b ingest ≈
  **5–10 hours** — that is why we probe cloud on a subset instead.
- Mandatory T7 env for any facade/embedder run:
  `HF_HUB_CACHE=/media/terrabyte/T7/hf-cache HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`
  plus `SEAM_BENCH_RECORD_DIR` for harness records.
- Local pgvector DSN (full harness): dbname=seam user=seam (password via
  `docker inspect seam-pgvector`), port 55432.
- mem0 reference source (patterns only, do NOT copy code — Apache-2.0):
  `/home/terrabyte/BEAM/mem0`. Also cloned: `/home/terrabyte/BEAM/hindsight`,
  `/home/terrabyte/BEAM/zep` (graph/routing lane, second priority).

## Next architecture boundary

Do not solve this by adding more rows to a saturated top-200. The next derived-
fact experiment must use a **non-displacing PACK** that preserves the complete
RAW prefix/tail it replaces, then pass the same 130-question exact-scope gate.

The graph lane reached the same conclusion from a different direction. Direct
episode-linked graph rows were redundant with broad RAW retrieval and retained
no measured changes. The next worthwhile graph slice needs query-conditioned
relational bridging through edge `source_record_id`, multi-node/path agreement,
and the same non-displacing PACK boundary. Require at least one exact gold gain
and zero loss before integrating it into the facade.

## Guardrails (retained)

- **This cloud extractor is a research PROBE, not the product path.** SEAM's
  daylight is local-first / no expensive per-turn ingest — the opposite of mem0.
  Do not ship cloud extraction as the default. If the probe wins, the production
  answer is a local fine-tune / better-fitting local model, not the API.
- **Free-then-paid discipline holds.** This probe is complete. Any full-corpus
  cloud ingest or paid answerer/judge run needs fresh operator approval.
- **No Claude/agent attribution** in commits or docs; operator-authored style.
- The cloud/API path remains benchmark-only. A future production extractor must
  remain local-first and pass the same conservative validator.

## Closeout verification

The exact affected slice collected 94 tests and passed all 94: the core runtime,
validator, displacement-audit, and facade slice passed 90/90, and the OpenAI
extractor/preflight contracts passed 4/4. Touched-file Ruff, compileall, diff
hygiene, and the exact candidate secret/session-link scan were clean.

The strict non-external suite did **not** complete and is not claimed green. It
was stopped at 12% after the sole observed failure: the LoCoMo quickstart
performance guard measured 319.99 seconds against its 180-second ceiling; no
correctness failure had appeared. The new `nl.py` behavior is gated on explicit
`multi-speaker-grounded/1`, and the `vector.py` behavior is gated on records
carrying that same policy, while the failing quickstart runs with derived facts
off. At failure time the host load was 20.5 / 22.3 / 22.8 and concurrent GPU
workloads included Ollama using approximately 6.4 GiB, so this is recorded as an
environment-contended performance failure rather than attributed to the
default-off probe. Required PR gates remain the merge authority. External
pgvector was not rerun because this slice does not change that adapter.
