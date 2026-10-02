# SOP: LLM-as-Judge Scoring for External Memory Benchmarks

Handoff target: DeepSeek (or any contributor)
Track: I — External Memory Benchmarks
Canonical spec: `docs/roadmap/MEMORY_BENCHMARKS.md`
Sequence: **SOP 2 of 5.** Prereqs: SOP 0 (registry/runner), SOP 1 (SEAM LoCoMo adapter). Follow-ups: SOP 3 (Mem0), SOP 4 (Zep).

## 1. Goal

Add an optional `--judge` flag so the LoCoMo runner (and future comparator runners) can score answers with an LLM judge in addition to string-match. The LoCoMo paper reports both string-match F1 and LLM-judge accuracy; reporting both lets SEAM match published methodology.

After this PR:

```bash
# String-match only (default — no API key needed, 60s gate stays clean)
seam bench external --quickstart locomo

# String-match + LLM judge (requires API key in env)
ANTHROPIC_API_KEY=<key> seam bench external --quickstart locomo --judge claude
OPENAI_API_KEY=<key>    seam bench external --quickstart locomo --judge openai
```

Output JSON gains a `judge` block per case with `verdict` (`correct` | `partial` | `incorrect`), `score` (0.0 / 0.5 / 1.0), and `rationale` (one sentence).

## 2. Scope

In:
- `benchmarks/external/common/judge.py` — judge protocol + Anthropic and OpenAI implementations
- `benchmarks/external/common/scoring.py` — extended with `judge_score_mean` aggregation
- `benchmarks/external/common/runner.py` — accepts optional judge, calls it per case after the adapter answers
- `benchmarks/external/locomo/run.py` — `--judge <provider>` flag
- `seam_runtime/cli.py` — passes `--judge` through `seam bench external`
- Tests with a stub judge (no real API calls in CI)
- `benchmarks/external/README.md` — judge documentation section
- HISTORY entry

Out:
- Mem0 / Zep comparators (SOPs 3, 4)
- Custom prompt templates beyond the one default prompt
- Multi-judge ensembles
- Cost tracking dashboards

## 3. Prerequisites

- SOP 0 and SOP 1 merged on `main`
- A working LoCoMo quickstart run (verify with `seam bench external --quickstart locomo`)
- Read `docs/SOP_MODEL_INTEGRATION.md` for the SEAM pattern of optional model providers

## 4. Files to create or modify

### 4.1 `benchmarks/external/common/judge.py` (new)

```python
from __future__ import annotations
import json, os
from dataclasses import dataclass
from typing import Protocol

DEFAULT_JUDGE_PROMPT = """You are an impartial scorer for a memory-benchmark question.

Question: {question}
Gold answer: {gold}
System answer: {pred}

Score the system answer:
- "correct" if it conveys the same meaning as the gold answer (paraphrasing is fine)
- "partial" if it contains the right entity/fact but is incomplete or has minor errors
- "incorrect" if it is wrong, unsupported, or empty

Respond ONLY with strict JSON in this exact shape:
{{"verdict": "correct" | "partial" | "incorrect", "rationale": "one short sentence"}}"""

@dataclass(frozen=True)
class JudgeVerdict:
    verdict: str           # "correct" | "partial" | "incorrect"
    score: float           # 1.0 / 0.5 / 0.0
    rationale: str
    judge_name: str
    judge_model: str

class Judge(Protocol):
    name: str
    model: str
    def score(self, *, question: str, gold: str, pred: str) -> JudgeVerdict: ...

class StubJudge:
    """Deterministic judge used by tests. Marks everything correct."""
    name = "stub"
    model = "stub-1"
    def score(self, *, question, gold, pred) -> JudgeVerdict:
        return JudgeVerdict("correct", 1.0, "stub always returns correct", self.name, self.model)

class ClaudeJudge:
    name = "claude"
    def __init__(self, model: str = "claude-haiku-4-5-20251001"):
        # Lazy import so the base install does not require anthropic
        try:
            from anthropic import Anthropic
        except ImportError as exc:
            raise RuntimeError(
                "--judge claude requires the anthropic package. "
                "Install with: pip install -e .[bench-judge] (repository checkout)"
            ) from exc
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("--judge claude requires ANTHROPIC_API_KEY in the environment")
        self.model = model
        self._client = Anthropic(api_key=api_key)
    def score(self, *, question, gold, pred) -> JudgeVerdict:
        # Call self._client.messages.create with the DEFAULT_JUDGE_PROMPT.
        # Parse JSON strictly. On parse failure return verdict="incorrect", score=0.0,
        # rationale="judge returned unparseable JSON".
        ...

class OpenAIJudge:
    name = "openai"
    def __init__(self, model: str = "gpt-4o-mini"):
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "--judge openai requires the openai package. "
                "Install with: pip install -e .[bench-judge] (repository checkout)"
            ) from exc
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("--judge openai requires OPENAI_API_KEY in the environment")
        self.model = model
        self._client = OpenAI(api_key=api_key)
    def score(self, *, question, gold, pred) -> JudgeVerdict:
        # Same contract as ClaudeJudge.
        ...

def build_judge(name: str | None) -> Judge | None:
    if name is None or name == "none":
        return None
    if name == "stub":
        return StubJudge()
    if name == "claude":
        return ClaudeJudge()
    if name == "openai":
        return OpenAIJudge()
    raise ValueError(f"unknown judge: {name!r} (use stub|claude|openai|none)")
```

**Model identifiers**: keep the defaults as `claude-haiku-4-5-20251001` (cheap, fast, recent) and `gpt-4o-mini`. Allow override via `SEAM_BENCH_JUDGE_MODEL` env var (read inside each judge's `__init__`).

### 4.2 `benchmarks/external/common/runner.py` (modify)

Extend `run_benchmark` signature:

```python
def run_benchmark(
    *,
    adapter: MemorySystemAdapter,
    cases: list[BenchmarkCase],
    judge: Judge | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> RunReport: ...
```

When `judge is not None`, after the adapter answers each case, call `judge.score(question=case.question, gold=case.gold_answer, pred=answer.generated_answer or answer.retrieved_context)`. Store the verdict in the case result. Compute `judge_score_mean` across cases and include it in `scores`.

If a single judge call raises, catch and record `judge: {"error": str(exc)}` for that case. Do not abort the whole run on a transient judge failure.

### 4.3 `benchmarks/external/common/scoring.py` (modify)

Add:

```python
def aggregate_judge_scores(verdicts: list[JudgeVerdict | None]) -> dict:
    seen = [v for v in verdicts if v is not None]
    if not seen:
        return {"judge_score_mean": None, "judge_count": 0}
    return {
        "judge_score_mean": sum(v.score for v in seen) / len(seen),
        "judge_count": len(seen),
        "correct_count": sum(1 for v in seen if v.verdict == "correct"),
        "partial_count": sum(1 for v in seen if v.verdict == "partial"),
        "incorrect_count": sum(1 for v in seen if v.verdict == "incorrect"),
    }
```

### 4.4 `benchmarks/external/locomo/run.py` (modify)

Add `--judge` flag:

```python
parser.add_argument("--judge", default=None,
    choices=["none", "stub", "claude", "openai"],
    help="LLM judge in addition to string-match scoring")
parser.add_argument("--judge-model", default=None,
    help="Override the default judge model id")
```

Build via `build_judge(args.judge)` and pass to `run_benchmark`. If the user passes `--judge` without the right env var, fail fast with the message in `judge.py`.

### 4.5 `seam_runtime/cli.py` (modify)

Add `--judge` and `--judge-model` to the `seam bench external` parser. Pass them through to the LoCoMo runner.

### 4.6 `pyproject.toml` (modify)

Add an optional extra:

```toml
[project.optional-dependencies]
bench-judge = ["anthropic>=0.40", "openai>=1.0"]
```

Do not promote either dependency to base.

### 4.7 `test_seam_all/test_locomo_judge.py` (new)

Cover:
- `build_judge(None)` returns `None`
- `build_judge("stub")` returns a `StubJudge`
- `build_judge("unknown")` raises `ValueError`
- `ClaudeJudge()` without `ANTHROPIC_API_KEY` raises `RuntimeError` with a clear message (monkeypatch.delenv)
- `OpenAIJudge()` without `OPENAI_API_KEY` raises `RuntimeError`
- `run_benchmark(..., judge=StubJudge())` populates `judge_score_mean = 1.0` and includes per-case `judge.verdict == "correct"`
- A judge that raises in `score` is caught and recorded as `judge.error` in the case
- CLI: `python -m benchmarks.external.locomo.run --quickstart --judge stub` exits 0 and produces a report with `judge_score_mean` populated

Do **not** add a test that hits a real LLM provider. Live judge calls are operator-side only.

### 4.8 `benchmarks/external/README.md` (modify)

Add a "Judges" section:
- Default: string-match only
- `--judge stub`: deterministic, tests-only
- `--judge claude` / `--judge openai`: requires `seam[bench-judge]` install and API key
- Cost note: judging adds one LLM call per case. Quickstart has ~10 cases. Full LoCoMo has ~7000 Q/A pairs.

## 5. DeepSeek implementation checklist

- [ ] SOPs 0 and 1 merged on `main`; pulled latest
- [ ] Created `benchmarks/external/common/judge.py` per section 4.1
- [ ] `StubJudge` returns deterministic `correct` verdict
- [ ] `ClaudeJudge` and `OpenAIJudge` lazy-import their SDKs and fail with clear messages on missing dep or missing API key
- [ ] Both real judges read `SEAM_BENCH_JUDGE_MODEL` env override
- [ ] Extended `runner.py` with `judge` parameter and per-case error handling
- [ ] Extended `scoring.py` with `aggregate_judge_scores`
- [ ] Added `--judge` and `--judge-model` to `benchmarks/external/locomo/run.py`
- [ ] Threaded `--judge` through `seam bench external` in `seam_runtime/cli.py`
- [ ] Added `bench-judge` optional extra in `pyproject.toml`
- [ ] Wrote `test_seam_all/test_locomo_judge.py` covering all bullets in section 4.7
- [ ] No live API call in any test
- [ ] All new tests pass (`pytest test_seam_all/test_locomo_judge.py -v`)
- [ ] Full suite still passes (`pytest test_seam_all -x`)
- [ ] `seam bench external --quickstart locomo` still works with no `--judge` (string-match path unchanged)
- [ ] `seam bench external --quickstart locomo --judge stub` produces a report with `scores.judge_score_mean == 1.0`
- [ ] Updated `benchmarks/external/README.md` with the Judges section
- [ ] Appended HISTORY entry per template in section 8
- [ ] `python -m tools.history.verify_continuity` passes
- [ ] Pushed branch and opened **draft** PR titled `Phase 3+: LLM-as-judge scoring extension`

## 6. Reviewer verification checklist

- [ ] `seam bench external --quickstart locomo` (no `--judge`) still exits 0 in under 60s and produces a report identical in shape to before this PR
- [ ] `seam bench external --quickstart locomo --judge stub --output /tmp/judge.json` exits 0 and `jq '.scores.judge_score_mean, .cases[0].judge.verdict' /tmp/judge.json` shows `1.0` and `"correct"`
- [ ] `seam bench external --quickstart locomo --judge claude` (without `ANTHROPIC_API_KEY`) prints a clear error mentioning the env var and exits non-zero
- [ ] `seam bench external --quickstart locomo --judge openai` (without `OPENAI_API_KEY`) prints a clear error mentioning the env var and exits non-zero
- [ ] `pytest test_seam_all/test_locomo_judge.py -v` passes (8+ tests)
- [ ] `pytest test_seam_all -x` passes (full suite)
- [ ] `pip install -e .` from the repository checkout (without extras) succeeds and `seam bench external --quickstart locomo --judge stub` still works (StubJudge has no deps)
- [ ] `grep -RE "(sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,})" benchmarks/ test_seam_all/test_locomo_judge.py` returns nothing
- [ ] No test calls a real LLM endpoint (grep for `messages.create`, `chat.completions.create` in tests should return zero results)
- [ ] `python -m tools.history.verify_continuity` passes
- [ ] PR description ticks every box in section 5

## 7. Acceptance commands

```bash
pip install -e .

# Default path unchanged
seam bench external --quickstart locomo --output /tmp/no_judge.json
jq '.scores' /tmp/no_judge.json

# Stub judge (no API key needed)
seam bench external --quickstart locomo --judge stub --output /tmp/stub.json
jq '.scores.judge_score_mean, .cases[0].judge' /tmp/stub.json

# Real judge fails clearly without an API key
seam bench external --quickstart locomo --judge claude; echo "exit=$?"

# With the optional extra installed
pip install -e ".[bench-judge]"
# Real judge call (operator-only — costs money)
ANTHROPIC_API_KEY=<your-key> seam bench external --quickstart locomo --judge claude --output /tmp/real.json
jq '.scores' /tmp/real.json

# Tests
pytest test_seam_all/test_locomo_judge.py -v
pytest test_seam_all -x

python -m tools.history.verify_continuity
```

## 8. HISTORY entry template

```yaml
id: NNN
date: <ISO date>
agent: deepseek
status: done
topics: [benchmark, retrieval, command, protocol]
commits: [<sha>]
refs:
  - benchmarks/external/common/judge.py
  - benchmarks/external/common/runner.py
  - benchmarks/external/common/scoring.py
  - benchmarks/external/locomo/run.py
  - seam_runtime/cli.py
  - pyproject.toml
  - test_seam_all/test_locomo_judge.py
  - benchmarks/external/README.md
  - docs/SOP_EXTERNAL_BENCH_LLM_JUDGE.md
supersedes: <last benchmark-topic entry id>
tokens: ~<count>
body: |
  Added optional LLM-as-judge scoring for external memory benchmarks.
  Stub judge for tests, Claude and OpenAI judges behind seam[bench-judge]
  extra. Default path (string-match only) unchanged; 60s quickstart gate
  preserved. Per-case judge errors are recorded, not raised, so a single
  transient judge failure does not abort the run.
```

## 9. Pitfalls

- **Do not call live LLM APIs in tests.** Only the StubJudge runs in CI.
- **Do not import `anthropic` or `openai` at module top-level.** Both must be lazy-imported inside the judge's `__init__` so the base install stays clean.
- **Do not hard-fail when the judge errors on one case.** Record the error per case and continue. A run with 90% successful judge calls is more useful than a crashed run.
- **Do not promote LLM-judge scores into the SEAM benchmark gate.** External judge scores are informational and probabilistic. The `seam benchmark gate` family stays deterministic. Track K wraps external bundles with BIL provenance.
- **Do not hardcode an Anthropic or OpenAI base URL.** Both SDKs respect `ANTHROPIC_BASE_URL` and `OPENAI_BASE_URL` from env; let users point at proxies.
- **Per AGENTS.md security rules**, do not log API keys, do not write them to the report JSON, and do not commit them anywhere.

## 10. Estimated scope

~400-600 lines net. One review cycle. Adds `anthropic` and `openai` to an optional extra only.
