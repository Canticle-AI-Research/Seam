# SEAM positioning — where the daylight actually is

Grounded in SEAM's own runs and roadmap (HISTORY, REPO_LEDGER, memory). Use this
to decide what to build and what to *claim*.

## The honest competitive picture

- **On the mem0 harness under the paper's contract, SEAM LEADS ALL FOUR**
  (CORRECTED 2026-08-04). The paper is gpt-4o-mini throughout, so SEAM's mini
  lane is the comparator: single-hop 87.16 vs 67.13, multi-hop 88.65 vs 51.15,
  open-domain 86.46 vs 72.93, temporal 71.96 vs 55.51. Qualification: SEAM ran
  top_k=200 vs the paper's 10 -- ~1.3x in tokens, so budget-matched not
  depth-matched. The superseded claim read: SEAM tops nothing
  (HISTORY#429: cat1 87.94 vs 91.3, cat3 69.79 vs 72.7; cat4/cat2 behind on the
  mini lane). Any "we beat X" claim must hold under X's own answerer+judge, or
  it is a lenient-judge mirage (`../eval-methodology/benchmark-traps.md#4`).
- **The packaging is table stakes.** Local-first, SQLite, MCP agent memory is now
  common (mem0, Mnemosyne, Letta). Do not lead with it.

## SEAM's real daylight (lead with these)

1. **Lossless + auditable compile (MIRL).** Competitors distill lossily and
   opaquely. SEAM's `grounded-clm/1` stores derived facts that *re-validate
   against exact source spans* and fail closed when uncertain — the same query-
   matching win as mem0, but provable. This is the differentiator on the exact
   axis where the field is strong.
2. **Provenance end-to-end.** CLM→SPAN→RAW links, frozen reproducibility
   manifests (model digest, embedding revision). "Show me why this memory
   exists" is a first-class, cheap operation.
3. **Self-improvement loop.** A no-regression ratchet driven by FREE self-
   supervised probes; paid runs never required to improve. Competitors don't
   ship this.
4. **Operator surface / glassbox.** Visual KG, memory console — governing memory,
   not running agents.

## Strategic implications for retrieval work

- **Build the auditable version of the winning pattern**, don't invent a novel
  retrieval trick. The graveyard shows answer-side and single-query tricks are
  exhausted (`../seam-internals/lever-graveyard.md`). The derived-facts direction
  is right *because* it matches how the field wins, done SEAM's way.
- **Two scoreboards, never averaged** (#415): native judge/1 (strict internal
  ratchet, champion 0.7762) and the mem0-harness lenient judge (incumbent-
  relative). Improve and defend both; quote neither against the other.
- **cat3 (open-domain) is mem0's weak spot** (72.93 in the paper; SEAM 86.46).
  These are the categories where matched parity is most reachable — prioritize
  levers there over cat2, where Zep's graph sets a high bar (92.0).

## Competitors quick-map

| System | Winning mechanism | SEAM's counter |
| --- | --- | --- |
| mem0 | LLM extraction → distilled facts | `grounded-clm/1`: lossless + provenance-linked facts |
| Zep | temporal graph, validity intervals | fold validity into derived facts; Track R later |
| Letta/MemGPT | agent self-editing memory | Track P (SEAM as agent memory backend) |
| Mnemosyne | local-first SQLite MCP (positional twin) | MIRL compile + self-improve loop + provenance |
