"""Operator-gated PAID holdout validation for the self-improvement loop.

``run_paid_validation`` answers one question with spend: does the loop's
applied flag state (or an explicit candidate) beat the stock baseline on the
HOLDOUT split under a paid answerer + judge? It is the validation tier from
HISTORY#292/#297 - the free loop proposes and applies on dev; this measures
generalized answer quality on cases the loop never tuned on.

It never proposes, applies, or reverts anything: the output is evidence for an
operator decision, not an input to the ratchet. It must only ever be invoked
behind an explicit operator confirmation (``seam improve validate
--confirm-paid``); nothing in the repo may call it automatically.
"""

from __future__ import annotations

from dataclasses import asdict

from benchmarks.external.common.run_record import RunRecord
from seam_runtime.retrieval import RetrievalFlags, load_retrieval_flags
from seam_runtime.storage import SQLiteStore

# Judged scores are 0/0.5/1 steps over tens of holdout cases, so the smallest
# real movement is far coarser than the free context_recall signal (noise floor
# +-0.002, margin 0.005). One verdict flipping on a 25-case pass moves the
# aggregate by 0.02-0.04; treat anything inside one flip as noise.
DEFAULT_JUDGED_NOISE_MARGIN = 0.02


def run_paid_validation(
    scorer,
    store: SQLiteStore | None,
    *,
    candidate_flags: RetrievalFlags | None = None,
    noise_margin: float = DEFAULT_JUDGED_NOISE_MARGIN,
    record_path: str | None = None,
) -> dict:
    """Score baseline vs candidate flags on the supplied judged scorer.

    ``candidate_flags=None`` validates the loop's persisted applied state
    (``load_retrieval_flags(store)``) - the natural post-ratchet audit. When the
    candidate resolves equal to the stock baseline there is nothing to compare,
    so only the baseline pass runs (half the spend) and the verdict says so.

    ``record_path`` (when set) captures a FULL per-case record of the run -- both
    arms' answers, judge verdict + rationale, retrieved context + its free
    ``context_recall`` (retrieval-miss vs answerer-miss), exact token usage /
    latency / USD cost, and any ``<think>`` reasoning trace -- writing a rich
    JSON to ``record_path`` and a training-shaped JSONL beside it. This is why a
    paid run is never again reduced to six aggregate numbers.
    """
    baseline = RetrievalFlags()
    if candidate_flags is None:
        if store is None:
            raise ValueError("candidate_flags=None requires a store to read applied state from")
        candidate = load_retrieval_flags(store)
    else:
        candidate = candidate_flags

    recorder = RunRecord() if record_path else None
    if recorder is not None:
        recorder.set_meta(
            scorer=scorer.name,
            n=getattr(scorer, "cases_by_scope", None) and sum(len(v) for v in scorer.cases_by_scope.values()),
            baseline_flags=asdict(baseline),
            candidate_flags=asdict(candidate),
            noise_margin=noise_margin,
            answerer=getattr(getattr(scorer, "adapter", None), "_answerer", None),
            answerer_model=getattr(getattr(scorer, "adapter", None), "_answerer_model", None),
            judge_model=getattr(getattr(scorer, "judge", None), "model", None),
        )

    def _score(flags, arm):
        # Pass the recorder only when capturing, so a scorer with the plain
        # score(runtime, flags=) signature (e.g. a test double) still works.
        if recorder is not None:
            return scorer.score(None, flags=flags, recorder=recorder, arm=arm)
        return scorer.score(None, flags=flags)

    base_report = _score(baseline, "baseline")
    base_run = dict(getattr(scorer, "last_run", {}))

    report: dict = {
        "scorer": scorer.name,
        "n": base_report.n,
        "noise_margin": noise_margin,
        "candidate_flags": asdict(candidate),
        "baseline": {
            "aggregate": round(base_report.aggregate, 6),
            "per_category": {k: round(v, 6) for k, v in sorted(base_report.per_category.items())},
            "run": base_run,
        },
    }

    if candidate == baseline:
        report["candidate"] = None
        report["delta"] = 0.0
        report["verdict"] = "no-candidate-state"
        report["reason"] = (
            "applied/candidate flags equal the stock baseline; nothing to compare "
            "(candidate pass skipped to avoid pointless spend)"
        )
        if recorder is not None:
            report["record"] = _write_record(recorder, record_path)
        return report

    cand_report = _score(candidate, "candidate")
    cand_run = dict(getattr(scorer, "last_run", {}))
    delta = cand_report.aggregate - base_report.aggregate

    if delta > noise_margin:
        verdict = "improved"
    elif delta < -noise_margin:
        verdict = "regressed"
    else:
        verdict = "within-noise"

    report["candidate"] = {
        "aggregate": round(cand_report.aggregate, 6),
        "per_category": {k: round(v, 6) for k, v in sorted(cand_report.per_category.items())},
        "run": cand_run,
    }
    report["delta"] = round(delta, 6)
    report["per_category_delta"] = {
        cat: round(cand_report.per_category.get(cat, 0.0) - base_val, 6)
        for cat, base_val in sorted(base_report.per_category.items())
    }
    report["verdict"] = verdict
    if recorder is not None:
        report["record"] = _write_record(recorder, record_path)
    return report


def _write_record(recorder: RunRecord, record_path: str) -> dict:
    """Write rich JSON plus a quarantined audit JSONL; return paths."""
    jsonl_path = record_path[:-5] + ".jsonl" if record_path.endswith(".json") else record_path + ".jsonl"
    audit_jsonl = recorder.write_audit_jsonl(jsonl_path)
    return {
        "json": recorder.write_json(record_path),
        "audit_jsonl": audit_jsonl,
        # Compatibility alias for consumers predating the quarantine contract.
        "training_jsonl": audit_jsonl,
        "n_case_rows": len(recorder.cases),
    }
