# Status Stream: Deferred

> Explicitly deferred backlog — parked, not lost

_Source of truth for current state in this area. History lives in `HISTORY.md`._

Items here are deliberately parked. They are recorded so they are not rediscovered
as surprises, not because they are active.

- 133 remaining `assertTrue` -> specific-assertion replacements in
  `test_seam_all/test_seam.py` (counted 2026-08-01; the number has grown, not shrunk)
  (backlog card `roadmap:track:F:asserttrue-scrub`).
- 10 low-priority backlog items catalogued under Track F (Phase 7).
- Track H Context Streams Protocol: Phase 1 = H1 substrate, Phase 2 = H2
  retrieval-feedback subset. Design in `docs/roadmap/CONTEXT_STREAMS.md`. Broader
  stream retrieval integration (H3) remains planned.
- Legacy roadmap entries `HISTORY#028`-`HISTORY#047` are append-only planning cards.
  `#036` (holdout suites), `#037` (benchmark diff tooling), and `#046` (REST API
  surface) are implemented and superseded by `#152`, `#153`, `#154`. Use
  `ROADMAP.md` Recommended Course for current priority.
- Deferred SSRF taint-break refactor to clear CodeQL `py/full-ssrf` #3/#4
  (dismissed-as-mitigated; PR #70 hardened it). Optional, not a security gap.
- Adaptive SEAM Skill Factory foundation merged via PR #21; primitives and roadmap
  docs tracked but not an active workstream.
