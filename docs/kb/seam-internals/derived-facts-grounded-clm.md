# `grounded-clm/1` — derived facts at ingest (HISTORY#435)

The live architectural lever, and the one with real headroom. This is SEAM's
auditable answer to *why mem0 wins*: mem0 stores distilled facts that lexically
match questions; SEAM served only raw turns (see `../memory-systems/mem0.md` and
`../eval-methodology/benchmark-traps.md`). `grounded-clm/1` closes that gap
without giving up SEAM's provenance/auditability.

Code: `seam_runtime/derived_fact_context.py`, `seam_runtime/nl_extract.py`,
`seam_runtime/nl.py`; wired through `benchmarks/external/locomo/adapters/seam.py`
and the facade `seam_mem0_server.py`. Tests:
`tests/audit/test_derived_fact_context.py`. Default **off**.

## The three contracts (what makes it auditable, not a hallucination layer)

1. **Ingest / compile contract.** Persists ONLY explicit *singular first-person*
   claims that losslessly ground to a canonical turn and rebase to that turn's
   named speaker (`I love surfing` by Tim → `Tim likes surfing`). Everything
   uncertain fails closed to the RAW floor: third-person, possessive, plural,
   contraction, quotation, negation, conditional, reported speech, cross-clause,
   symbol-wrapped "I". Injected/custom extractor output is re-validated against
   the exact source spans before it can enter storage or vector text.
2. **Serve contract.** Eligible current/assertable CLM records render as
   `SEAM-FACT/1` beside an exact `SEAM-SOURCE/1` RAW record. The
   `raw-prefix-floor/2` splice puts 4 RAW records before each fact, so **every**
   returned prefix (not just the top-200 total) is ≤20% facts, and a fact never
   precedes its source RAW. Count/temporal projections keep precedence. Serve-
   time re-validates proposition bounds, content hash, speaker/timestamp, span
   coverage, live CLM→SPAN→RAW provenance, namespace/scope, and the frozen config
   fingerprint.
3. **Trust / reproducibility contract.** Each candidate store carries a frozen
   manifest: policy, extraction schema/prompt/decoder, Ollama model digest, cache
   identity, splice policy, exact embedding contract (`BAAI/bge-small-en-v1.5`
   rev `5c38ec7c…`, 384-dim, local-files-only). Fresh/warm mismatch, digest
   drift, shared pgvector, or a remote embedder are **refused**. Extraction cache
   is content-addressed, namespace-owner bound, replayable after restart, purged
   on final-owner delete.

## Why this is the right shape

- It attacks the *diagnosed* wall (wording distance), not a symptom. The real
  smoke produced **`John likes surfing`** grounded to its turn — literally the
  `conv4_q11` matched miss (#429/#434). A query "what sports does John like
  besides basketball" embeds close to a stored `John likes surfing` fact but far
  from the raw turn "Wow! How long have you been surfing?".
- It keeps SEAM's daylight (`../memory-systems/seam-positioning.md`): lossless,
  provenance-linked, refuses-when-uncertain — the opposite of an opaque
  extraction blob.

## Next gate (all FREE first — do not skip to paid)

1. **Extractor speed is the blocker.** Only `qwen2.5:14b` is installed
   (`ollama list`) at ~138 s/turn → a full 10-conversation preflight (~5,900
   turns) is impractical. Install/select a **faster local extractor** (operator
   decision). Candidates to weigh: a smaller qwen/llama instruct, or a
   constrained-decoding setup.
2. **Build the free coverage/precision preflight runner** (does not exist yet;
   only `preflight_event_count_context.py` does). It should report, over the
   stored #429 miss set with zero provider calls beyond local extraction:
   per-turn fact yield, grounding precision (facts that re-validate), and — the
   money metric — how many previously evidence-absent misses now have a
   `SEAM-FACT/1` that surfaces the gold. Gate a paid microgate on that.
3. **Paid answerer microgate** only after the free gate passes, on the same
   ~13 cat1 stored contexts, at the matched gpt-4o contract, with the model-
   constant check from `../eval-methodology/benchmark-traps.md#3`.

## Risks to watch

- **Displacement (#369 lesson):** facts must not crowd RAW the token-overlap
  answerer reads. The `raw-prefix-floor/2` ≤20% cap is the guard; verify it
  holds at small `limit`.
- **Precision over recall:** a wrong fact is worse than a missing one (it can
  flip a correct answer). The fail-closed ingest contract is deliberate; resist
  loosening it to chase yield.
- **This is a benchmark slice, not a product default.** Surfacing derived facts
  in the chat/MCP product is a separate, later decision.

## Broadened multi-speaker variant (default-off research, 2026-07-21)

The free representation gate showed `sentence-grounded-clm/1` reaches only 51/63
misses. Reading mem0's actual extractor (`../memory-systems/mem0.md`, source-
verified) isolated why: SEAM extracts **singular first-person only**, but the
LoCoMo corpus is multi-speaker — most gold turns state facts about a *named
other* ("Maria got a cat named Bailey"), which the first-person gate refuses.

`multi-speaker-grounded/1` (`seam_runtime/multi_speaker_facts.py`, default-off,
preflight-first) takes mem0's recall breadth — named third-party facts — while
keeping grounding as the precision mechanism instead of mem0's LLM reconcile:

1. Eligibility broadens from `first_person_declarative_evidence` to
   `declarative_evidence` (any non-question sentence with a proper noun or a
   first-person pronoun).
2. The validator keeps number/negation preservation and adds fail-closed guards
   for unresolved or ambiguous subjects, fabricated names, reported claims,
   modality/state loss, and unsupported lexical content. Sentence scope requires
   the name in the cited sentence. Turn scope permits only one unique preceding
   named antecedent and rejects multiple candidates or a differently named
   evidence subject.

These are auditable syntactic guards, not a proof of arbitrary semantic
entailment. The displacement audit therefore also requires exact candidate
coverage and zero sentinel evidence loss before this lever can move forward.

**Gate discipline:** measure coverage first, then run the exact-scope
displacement auditor (`preflight_displacement_audit.py`) to prove every expected
question is present, gold surfaces without harmful RAW displacement, and no
sentinel loses evidence. Runtime plumbing stays explicit and default-off.
