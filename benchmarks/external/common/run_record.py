"""Full-fidelity record for a benchmark run: one durable artifact per run so we
never again keep only the aggregate scores.

Captures, per case: the question/gold, the generated answer(s), the answerer's
reasoning trace (``<think>...</think>`` when a model exposes it), the judge
verdict + rationale, the retrieved context and its free ``context_recall``
(gold-in-context) so each case is labeled retrieval-miss vs answerer-miss, and
exact token usage / latency / USD cost. Plus run-level provenance (git SHA,
dataset hash, flags, prompts) and totals.

Two outputs:
- ``write_json``  -> the rich analysis artifact (run metadata + every case).
- ``write_training_jsonl`` -> one row per (case, arm) in a messages+reasoning
  shape for the LLM-Logs / local-model training corpus.

Nothing here makes a network call or changes scoring; it is pure capture.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from benchmarks.external.common.pricing import PRICING_SNAPSHOT, estimate_cost_usd

_THINK_RE = re.compile(r"<think>(.*?)</think>", re.DOTALL | re.IGNORECASE)

# context_recall is a fractional gold-token overlap; this threshold coarsely
# splits "evidence was present" from "evidence was missing" for the failure
# classifier. Tunable via env; the raw context_recall is always stored too.
_HIT_THRESHOLD = float(os.environ.get("SEAM_BENCH_RECALL_HIT_THRESHOLD", "0.5"))


def split_reasoning(raw: str | None) -> tuple[str, str | None]:
    """Return (visible_answer, reasoning_trace) splitting out ``<think>`` blocks.

    Models that expose chain-of-thought (deepseek-r1, qwen-thinking, ...) emit
    ``<think>...</think>`` before the answer. OpenAI/gpt-4o-mini do NOT return
    CoT text, so ``reasoning_trace`` is None for them (nothing to capture)."""
    if not raw:
        return ("", None)
    blocks = _THINK_RE.findall(raw)
    if not blocks:
        return (raw.strip(), None)
    visible = _THINK_RE.sub("", raw).strip()
    return (visible, "\n".join(b.strip() for b in blocks).strip() or None)


def classify_failure(verdict: str | None, context_recall: float | None) -> str:
    """The retrieval-miss vs answerer-miss label that turns a score into a
    diagnostic. ``correct`` short-circuits; otherwise split by whether the gold
    evidence was in the retrieved context."""
    if verdict == "correct":
        return "answered_correct"
    if verdict == "abstain":
        return "abstained"
    if context_recall is None:
        return "unknown"
    if context_recall >= _HIT_THRESHOLD:
        return "answerer_miss"  # evidence was present, answer still wrong
    return "retrieval_miss"     # evidence absent from context


def external_mount_ready(path: str) -> tuple[bool, str]:
    """Guard against silently writing to the root filesystem when an external
    drive (``/media/...`` or ``/mnt/...``) is not mounted. When such a drive is
    unmounted its mountpoint dir is removed, so a naive ``makedirs`` would
    recreate the tree on the root fs and the data would NOT land on the drive.

    Returns (ok, message). ``ok`` is False when ``path`` targets an external
    mount whose nearest existing ancestor is on the same device as ``/`` (i.e.
    the drive is not mounted). Non-external paths are always ok."""
    ap = os.path.abspath(path)
    if not (ap.startswith("/media/") or ap.startswith("/mnt/")):
        return True, ""
    ancestor = ap
    while not os.path.exists(ancestor) and ancestor != "/":
        ancestor = os.path.dirname(ancestor)
    try:
        if os.stat(ancestor).st_dev == os.stat("/").st_dev:
            return False, (
                f"record dir {path!r} is under an external mount that is not mounted "
                f"(it would resolve to the root filesystem). Mount the drive, or set "
                f"SEAM_BENCH_RECORD_DIR / --record-dir elsewhere."
            )
    except OSError:
        return True, ""
    return True, ""


def _git_sha() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _seam_version() -> str | None:
    try:
        from importlib.metadata import version
        return version("seam-runtime")
    except Exception:
        return None


@dataclass
class RunRecord:
    """Accumulates a full run. ``meta`` is free-form provenance; ``add_case``
    appends one per (case, arm)."""

    meta: dict[str, Any] = field(default_factory=dict)
    cases: list[dict[str, Any]] = field(default_factory=list)
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def set_meta(self, **kwargs: Any) -> None:
        self.meta.update({k: v for k, v in kwargs.items() if v is not None})

    def add_case(
        self,
        *,
        case_id: str,
        scope: str | None,
        category: str | None,
        arm: str,
        question: str,
        gold_answer: str,
        raw_answer: str | None,
        verdict: str | None,
        judge_score: float | None,
        judge_rationale: str | None,
        judge_model: str | None,
        retrieved_context: str | None,
        context_recall: float | None,
        candidate_count: int | None = None,
        top_score: float | None = None,
        answerer_diagnostics: dict | None = None,
        judge_usage: dict | None = None,
        retrieval_latency_ms: float | None = None,
        answer_latency_ms: float | None = None,
        judge_latency_ms: float | None = None,
    ) -> None:
        visible, reasoning = split_reasoning(raw_answer)
        diag = answerer_diagnostics or {}
        answerer_model = diag.get("model")
        a_prompt = diag.get("prompt_tokens")
        a_completion = diag.get("completion_tokens") or diag.get("output_tokens") or diag.get("eval_count")
        a_prompt = a_prompt if a_prompt is not None else diag.get("prompt_eval_count")
        answerer_cost = estimate_cost_usd(
            answerer_model, a_prompt, a_completion, cache_hit_tokens=diag.get("cache_hit_tokens")
        )
        j = judge_usage or {}
        judge_cost = estimate_cost_usd(judge_model, j.get("prompt_tokens"), j.get("completion_tokens"))
        self.cases.append({
            "case_id": case_id,
            "scope": scope,
            "category": category,
            "arm": arm,
            "question": question,
            "gold_answer": gold_answer,
            "generated_answer": visible,
            "reasoning_trace": reasoning,
            "answer_len": len(visible),
            "verdict": verdict,
            "judge_score": judge_score,
            "judge_rationale": judge_rationale,
            "judge_model": judge_model,
            "context_recall": context_recall,
            "retrieval_hit": (None if context_recall is None else context_recall >= _HIT_THRESHOLD),
            "failure_class": classify_failure(verdict, context_recall),
            "candidate_count": candidate_count,
            "top_score": top_score,
            "retrieved_context_len": len(retrieved_context or ""),
            "retrieved_context": retrieved_context,
            "answerer": {
                "model": answerer_model,
                "served_model": diag.get("served_model"),  # catches provider alias rerouting
                "provider": diag.get("provider"),
                "prompt_tokens": a_prompt,
                "completion_tokens": a_completion,
                "cache_hit_tokens": diag.get("cache_hit_tokens"),
                "reasoning_tokens": diag.get("reasoning_tokens"),
                "finish_reason": diag.get("finish_reason"),
                "cost_usd": answerer_cost,
            },
            "judge": {
                "model": judge_model,
                "prompt_tokens": j.get("prompt_tokens"),
                "completion_tokens": j.get("completion_tokens"),
                "cost_usd": judge_cost,
            },
            "latency_ms": {
                "retrieval": retrieval_latency_ms,
                "answer": answer_latency_ms,
                "judge": judge_latency_ms,
            },
        })

    def _totals(self) -> dict[str, Any]:
        by_cat_arm: dict[tuple[str, str], list[float]] = defaultdict(list)
        verdicts: dict[str, int] = defaultdict(int)
        failure_classes: dict[str, int] = defaultdict(int)
        a_cost = j_cost = 0.0
        a_tok = j_tok = 0
        n_correct = 0
        for c in self.cases:
            if c["judge_score"] is not None:
                by_cat_arm[(str(c["category"]), c["arm"])].append(c["judge_score"])
            verdicts[str(c["verdict"])] += 1
            failure_classes[c["failure_class"]] += 1
            if c["verdict"] == "correct":
                n_correct += 1
            ac = c["answerer"]["cost_usd"] or 0.0
            jc = c["judge"]["cost_usd"] or 0.0
            a_cost += ac
            j_cost += jc
            a_tok += (c["answerer"]["prompt_tokens"] or 0) + (c["answerer"]["completion_tokens"] or 0)
            j_tok += (c["judge"]["prompt_tokens"] or 0) + (c["judge"]["completion_tokens"] or 0)
        per_category = {
            f"cat{cat}:{arm}": round(sum(v) / len(v), 4)
            for (cat, arm), v in sorted(by_cat_arm.items()) if v
        }
        total_cost = a_cost + j_cost
        return {
            "n_case_rows": len(self.cases),
            "per_category_arm_judge_mean": per_category,
            "verdict_counts": dict(verdicts),
            "failure_class_counts": dict(failure_classes),
            "tokens": {"answerer": a_tok, "judge": j_tok, "total": a_tok + j_tok},
            "cost_usd": {
                "answerer": round(a_cost, 6), "judge": round(j_cost, 6),
                "total": round(total_cost, 6),
                "per_correct_answer": round(total_cost / n_correct, 6) if n_correct else None,
                "pricing_snapshot": PRICING_SNAPSHOT,
                "note": "tokens exact; prices from a table (override via SEAM_BENCH_PRICING_JSON)",
            },
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "run": {
                "started_at": self.started_at,
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "git_sha": _git_sha(),
                "seam_version": _seam_version(),
                **self.meta,
            },
            "totals": self._totals(),
            "cases": self.cases,
        }

    def write_json(self, path: str) -> str:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2, sort_keys=False)
        return path

    def write_training_jsonl(self, path: str) -> str:
        """One row per (case, arm) shaped for the LLM-Logs / local-model corpus:
        the answerer input as a user message, the model's reasoning + answer as
        the assistant turn, plus the labels a trainer/filter needs."""
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        prompts = self.meta.get("prompts", {})
        with open(path, "w") as f:
            for c in self.cases:
                prompt_template = prompts.get(c["arm"], "")
                user = (
                    prompt_template.replace("{context}", c.get("retrieved_context") or "").replace("{question}", c["question"])
                    if "{context}" in prompt_template else c["question"]
                )
                assistant = c["generated_answer"]
                if c["reasoning_trace"]:
                    assistant = f"<think>{c['reasoning_trace']}</think>\n{assistant}"
                f.write(json.dumps({
                    "case_id": c["case_id"],
                    "arm": c["arm"],
                    "category": c["category"],
                    "messages": [
                        {"role": "user", "content": user},
                        {"role": "assistant", "content": assistant},
                    ],
                    "reasoning_trace": c["reasoning_trace"],
                    "gold_answer": c["gold_answer"],
                    "verdict": c["verdict"],
                    "judge_score": c["judge_score"],
                    "context_recall": c["context_recall"],
                    "failure_class": c["failure_class"],
                }) + "\n")
        return path
