"""No-network LoCoMo baseline failure audit tool.

Usage:
    .venv/bin/python -m benchmarks.external.locomo.audit \
        --result /tmp/seam-track-m/p4_baseline_locomo.json \
        --dataset-path /home/terrabyte/seam_benchmarks/track_m/locomo/locomo10.json \
        --output /tmp/seam-track-m/p4_baseline_locomo_audit.json \
        --markdown /tmp/seam-track-m/p4_baseline_locomo_audit.md

    # With context replay (no-paid):
    .venv/bin/python -m benchmarks.external.locomo.audit \
        --result /tmp/seam-track-m/p4_baseline_locomo.json \
        --dataset-path /home/terrabyte/seam_benchmarks/track_m/locomo/locomo10.json \
        --replay-context \
        --replay-sample 5 \
        --replay-output /tmp/seam-track-m/p4_replay.json \
        --replay-markdown /tmp/seam-track-m/p4_replay.md
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from typing import Any

from benchmarks.external.common.dataset import load_locomo_cases

BUCKET_ZERO = "zero_recall"
BUCKET_LOW = "low_recall"
BUCKET_MEDIUM = "medium_recall"
BUCKET_HIGH = "high_recall"
BUCKET_HIGH_UNKNOWN = "high_recall_unknown"
BUCKET_SUCCESS = "success"

REPLAY_BUCKETS = [
    BUCKET_ZERO, BUCKET_LOW, BUCKET_MEDIUM,
    BUCKET_HIGH_UNKNOWN, BUCKET_SUCCESS,
]


def _classify(case: dict) -> str:
    recall = case["scores"]["context_recall"]
    pred = case.get("_prediction", "")
    if recall >= 0.8:
        if isinstance(pred, str) and pred.strip().lower() == "unknown":
            return BUCKET_HIGH_UNKNOWN
        return BUCKET_HIGH
    if recall == 0.0:
        return BUCKET_ZERO
    if recall < 0.2:
        return BUCKET_LOW
    return BUCKET_MEDIUM


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _is_unknown_prediction(pred: Any) -> bool:
    """Case-insensitive unknown check."""
    if not isinstance(pred, str):
        return False
    return pred.strip().lower() == "unknown"


def _sample_cases(cases: list[dict], n: int = 15) -> list[dict]:
    if len(cases) <= n:
        return cases
    step = max(1, len(cases) // n)
    return [cases[i] for i in range(0, len(cases), step)][:n]


def _detect_context_snippets(result_cases: list[dict]) -> bool:
    """Check whether any result case contains retrieved_context data."""
    for case in result_cases:
        ctx = case.get("retrieved_context") or case.get("context")
        if isinstance(ctx, str) and ctx.strip():
            return True
    return False


def _dataset_fixture_hash(dataset_path: str) -> str:
    """SHA-256 over sorted, canonical JSON of the dataset cases — matches
    the dry-run fixture_hash from run.py."""
    cases = load_locomo_cases(dataset_path)
    payload = json.dumps(
        [{"id": c.case_id, "q": c.question} for c in cases],
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def run_audit(result_path: str, dataset_path: str) -> dict:
    with open(result_path, "r", encoding="utf-8") as fh:
        result = json.load(fh)

    result_cases: list[dict] = result["cases"]
    result_scores: dict = result.get("scores", {})

    result_ids = {c["case_id"] for c in result_cases}
    result_id_list = [c["case_id"] for c in result_cases]

    # dataset
    dataset_cases = load_locomo_cases(dataset_path)
    dataset_by_id: dict[str, Any] = {c.case_id: c for c in dataset_cases}
    dataset_ids = set(dataset_by_id.keys())

    # dataset/source integrity
    missing_from_dataset = sorted(result_ids - dataset_ids)
    extra_in_result = sorted(dataset_ids - result_ids)
    duplicate_ids = [cid for cid, count in Counter(result_id_list).items() if count > 1]

    # fixture hash
    fixture_hash = _dataset_fixture_hash(dataset_path)

    # context snippets present?
    context_snippets_present = _detect_context_snippets(result_cases)

    # prediction distribution + case-insensitive unknown metric
    pred_counter: Counter = Counter()
    unknown_ci_count = 0
    judge_error_cases: list[dict] = []
    judge_none_cases: list[dict] = []
    buckets: dict[str, list[dict]] = {
        BUCKET_ZERO: [], BUCKET_LOW: [], BUCKET_MEDIUM: [],
        BUCKET_HIGH: [], BUCKET_HIGH_UNKNOWN: [], BUCKET_SUCCESS: [],
    }

    total = len(result_cases)
    for case in result_cases:
        pred = _safe_str(case.get("_prediction", ""))
        pred_counter[pred] += 1
        if _is_unknown_prediction(case.get("_prediction")):
            unknown_ci_count += 1

        judge = case.get("judge")
        if judge is None:
            judge_none_cases.append(case)
        elif isinstance(judge, dict) and judge.get("error"):
            judge_error_cases.append(case)

        bucket = _classify(case)
        buckets[bucket].append(case)

    def _enrich(case: dict) -> dict:
        ds = dataset_by_id.get(case["case_id"])
        return {
            "case_id": case["case_id"],
            "category": case.get("category"),
            "question": ds.question if ds else None,
            "gold_answer": ds.gold_answer if ds else None,
            "context_recall": case["scores"]["context_recall"],
            "answer_em": case["scores"]["answer_em"],
            "answer_f1": case["scores"]["answer_f1"],
            "prediction": case.get("_prediction"),
            "judge_verdict": (
                case["judge"].get("verdict")
                if isinstance(case.get("judge"), dict)
                else None
            ),
            "judge_score": (
                case["judge"].get("score")
                if isinstance(case.get("judge"), dict)
                else None
            ),
            "judge_rationale": (
                case["judge"].get("rationale")
                if isinstance(case.get("judge"), dict)
                else None
            ),
            "judge_error": (
                case["judge"].get("error")
                if isinstance(case.get("judge"), dict)
                else None
            ),
        }

    samples: dict[str, list[dict]] = {}
    for name in REPLAY_BUCKETS + [BUCKET_HIGH]:
        if name in buckets:
            samples[name] = [_enrich(c) for c in _sample_cases(buckets[name])]

    # category summary
    cat_summary: dict[str, dict] = {}
    for case in result_cases:
        cat = _safe_str(case.get("category", "?"))
        if cat not in cat_summary:
            cat_summary[cat] = {
                "case_count": 0,
                "context_recall_sum": 0.0,
                "judge_score_sum": 0.0,
                "judge_score_count": 0,
                "unknown_count": 0,
            }
        cat_summary[cat]["case_count"] += 1
        cat_summary[cat]["context_recall_sum"] += case["scores"]["context_recall"]
        if isinstance(case.get("judge"), dict) and case["judge"].get("score") is not None:
            cat_summary[cat]["judge_score_sum"] += case["judge"]["score"]
            cat_summary[cat]["judge_score_count"] += 1
        if _is_unknown_prediction(case.get("_prediction")):
            cat_summary[cat]["unknown_count"] += 1

    for _cat, stats in cat_summary.items():
        n = stats["case_count"]
        stats["context_recall_mean"] = stats["context_recall_sum"] / n if n else 0.0
        stats["judge_score_mean"] = (
            stats["judge_score_sum"] / stats["judge_score_count"]
            if stats["judge_score_count"]
            else 0.0
        )

    return {
        "result_path": str(result_path),
        "dataset_path": str(dataset_path),
        "dataset_fixture_hash": fixture_hash,
        "result_case_count": total,
        "dataset_case_count": len(dataset_cases),
        "missing_from_dataset": missing_from_dataset,
        "extra_in_result": extra_in_result,
        "duplicate_ids": duplicate_ids,
        "scores_summary": result_scores,
        "category_summary": cat_summary,
        "prediction_distribution": dict(pred_counter.most_common()),
        "unknown_ci_count": unknown_ci_count,
        "bucket_counts": {k: len(v) for k, v in buckets.items()},
        "judge_error_count": len(judge_error_cases) + len(judge_none_cases),
        "judge_error_case_ids": [
            c["case_id"] for c in judge_error_cases + judge_none_cases
        ],
        "context_snippets_present": context_snippets_present,
        "samples": samples,
    }


# ---------------------------------------------------------------------------
# context replay
# ---------------------------------------------------------------------------

def _scope_for(case_id: str) -> str:
    return case_id.split("::", 1)[0]


def _context_format_kind(ctx: str) -> str:
    if not ctx or not ctx.strip():
        return "empty"
    stripped = ctx.strip()
    # Only classify as JSON if it actually parses as JSON, not just
    # because it starts with a bracket (e.g. "[Speaker timestamp]").
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            json.loads(stripped)
            return "pack_json"
        except (json.JSONDecodeError, ValueError):
            pass
    return "raw_text"


def _raw_snippet_count(ctx: str) -> int:
    """Count lines that are non-empty and not JSON structural."""
    if not ctx or not ctx.strip():
        return 0
    lines = [line for line in ctx.split("\n") if line.strip() and not line.strip().startswith(("{", "}", "[", "]"))]
    return len(lines)


def _gold_tokens_in_context(ctx: str, gold: str) -> float:
    """Compute context_recall same as scoring.context_recall: fraction of gold
    answer tokens found in the context."""
    import re
    import string

    def _normalize(text: str) -> str:
        text = text.lower()
        text = re.sub(r"\b(a|an|the)\b", " ", text)
        text = "".join(ch for ch in text if ch not in string.punctuation)
        return " ".join(text.split())

    retrieved_tokens = set(_normalize(ctx).split())
    gold_tokens = _normalize(gold).split()
    if not gold_tokens:
        return 1.0
    hits = sum(1 for tok in gold_tokens if tok in retrieved_tokens)
    return hits / len(gold_tokens)


def _preload_model() -> None:
    """Pre-load the sentence-transformers model so subsequent SeamRuntime
    instantiations reuse the cached weights instead of reloading per scope."""
    try:
        from seam_runtime.models import SentenceTransformerModel
        SentenceTransformerModel(model_name="BAAI/bge-small-en-v1.5")
    except Exception:
        pass  # will fail later in _open_runtime with a clear message


def run_context_replay(
    result_path: str,
    dataset_path: str,
    sample_n: int = 5,
    *,
    _adapter: object | None = None,
) -> list[dict]:
    """Replay retrieval for sampled failed cases without calling any API.

    Returns one dict per replayed case with full diagnostic info.
    """
    if _adapter is None:
        from benchmarks.external.locomo.adapters.seam import SeamLocomoAdapter

        owned_adapter = SeamLocomoAdapter(answerer=None)
        try:
            return run_context_replay(
                result_path,
                dataset_path,
                sample_n,
                _adapter=owned_adapter,
            )
        finally:
            owned_adapter.close()

    with open(result_path, "r", encoding="utf-8") as fh:
        result = json.load(fh)
    result_cases = result["cases"]
    dataset_cases = load_locomo_cases(dataset_path)
    dataset_by_id = {c.case_id: c for c in dataset_cases}

    # classify and bucket
    buckets: dict[str, list[dict]] = {b: [] for b in REPLAY_BUCKETS}
    for case in result_cases:
        b = _classify(case)
        if b == BUCKET_HIGH:
            b = BUCKET_SUCCESS
        buckets[b].append(case)

    # sample cases and build per-scope groups
    selected: list[dict] = []
    for bucket_name in REPLAY_BUCKETS:
        sampled = _sample_cases(buckets[bucket_name], sample_n)
        for case in sampled:
            case["_replay_bucket"] = bucket_name
        selected.extend(sampled)

    # group by scope
    scope_groups: dict[str, list[dict]] = {}
    for case in selected:
        scope = _scope_for(case["case_id"])
        scope_groups.setdefault(scope, []).append(case)

    # replay per scope — single adapter, per-scope DB isolation
    replay_rows: list[dict] = []

    adapter = _adapter

    for scope, scope_cases in scope_groups.items():
        ds_case = dataset_by_id.get(scope_cases[0]["case_id"])
        if ds_case is None:
            for case in scope_cases:
                replay_rows.append({
                    "case_id": case["case_id"],
                    "category": case.get("category"),
                    "question": None,
                    "gold_answer": None,
                    "baseline_prediction": case.get("_prediction"),
                    "baseline_context_recall": case["scores"]["context_recall"],
                    "replay_context_recall": None,
                    "retrieved_context_preview": None,
                    "retrieved_context_length": 0,
                    "context_format": "error",
                    "raw_snippet_count": 0,
                    "context_starts_with_json": False,
                    "gold_tokens_in_replayed_context": None,
                    "error": "dataset case not found",
                    "replay_bucket": case.get("_replay_bucket", "?"),
                })
            continue

        adapter.reset(scope)
        for turn in ds_case.conversation:
            try:
                adapter.ingest_turn(scope, turn)
            except Exception as exc:
                for case in scope_cases:
                    replay_rows.append({
                        "case_id": case["case_id"],
                        "category": case.get("category"),
                        "question": None,
                        "gold_answer": None,
                        "baseline_prediction": case.get("_prediction"),
                        "baseline_context_recall": case["scores"]["context_recall"],
                        "replay_context_recall": None,
                        "retrieved_context_preview": None,
                        "retrieved_context_length": 0,
                        "context_format": "error",
                        "raw_snippet_count": 0,
                        "context_starts_with_json": False,
                        "gold_tokens_in_replayed_context": None,
                        "error": f"ingest error: {exc}",
                        "replay_bucket": case.get("_replay_bucket", "?"),
                    })
                break
        else:
            # ingestion succeeded — replay each case
            for case in scope_cases:
                case_ds = dataset_by_id.get(case["case_id"])
                if case_ds is None:
                    replay_rows.append({
                        "case_id": case["case_id"],
                        "category": case.get("category"),
                        "question": None,
                        "gold_answer": None,
                        "baseline_prediction": case.get("_prediction"),
                        "baseline_context_recall": case["scores"]["context_recall"],
                        "replay_context_recall": None,
                        "retrieved_context_preview": None,
                        "retrieved_context_length": 0,
                        "context_format": "error",
                        "raw_snippet_count": 0,
                        "context_starts_with_json": False,
                        "gold_tokens_in_replayed_context": None,
                        "error": "dataset case not found for replay",
                        "replay_bucket": case.get("_replay_bucket", "?"),
                    })
                    continue
                try:
                    ans = adapter.answer(scope, case_ds.question)
                except Exception as exc:
                    replay_rows.append({
                        "case_id": case["case_id"],
                        "category": case.get("category"),
                        "question": case_ds.question if case_ds else None,
                        "gold_answer": case_ds.gold_answer if case_ds else None,
                        "baseline_prediction": case.get("_prediction"),
                        "baseline_context_recall": case["scores"]["context_recall"],
                        "replay_context_recall": None,
                        "retrieved_context_preview": None,
                        "retrieved_context_length": 0,
                        "context_format": "error",
                        "raw_snippet_count": 0,
                        "context_starts_with_json": False,
                        "gold_tokens_in_replayed_context": None,
                        "error": f"retrieval error: {exc}",
                        "replay_bucket": case.get("_replay_bucket", "?"),
                    })
                    continue

                ctx = ans.retrieved_context or ""
                ctx_len = len(ctx)
                fmt = _context_format_kind(ctx)
                snippet_count = _raw_snippet_count(ctx)
                starts_json = ctx.strip().startswith(("{", "[")) if ctx.strip() else False
                gold_token_hit = _gold_tokens_in_context(ctx, case_ds.gold_answer) if case_ds else None

                replay_rows.append({
                    "case_id": case["case_id"],
                    "category": case.get("category"),
                    "question": case_ds.question if case_ds else None,
                    "gold_answer": case_ds.gold_answer if case_ds else None,
                    "baseline_prediction": case.get("_prediction"),
                    "baseline_context_recall": case["scores"]["context_recall"],
                    "replay_context_recall": gold_token_hit,
                    "retrieved_context_preview": ctx[:1000] if ctx else "",
                    "retrieved_context_length": ctx_len,
                    "context_format": fmt,
                    "raw_snippet_count": snippet_count,
                    "context_starts_with_json": starts_json,
                    "gold_tokens_in_replayed_context": gold_token_hit is not None and gold_token_hit > 0,
                    "error": None,
                    "replay_bucket": case.get("_replay_bucket", "?"),
                })

    return replay_rows


def _summarise_replay(replay_rows: list[dict]) -> dict:
    fmt_counter = Counter(r["context_format"] for r in replay_rows)
    bucket_fmt: dict[str, Counter] = {}
    for r in replay_rows:
        b = r["replay_bucket"]
        if b not in bucket_fmt:
            bucket_fmt[b] = Counter()
        bucket_fmt[b][r["context_format"]] += 1

    gold_hits = sum(1 for r in replay_rows if r.get("gold_tokens_in_replayed_context"))
    gold_misses = sum(1 for r in replay_rows
                      if r.get("gold_tokens_in_replayed_context") is False)
    errors = sum(1 for r in replay_rows if r.get("error"))

    return {
        "replayed": len(replay_rows),
        "context_format_counts": dict(fmt_counter.most_common()),
        "gold_tokens_found": gold_hits,
        "gold_tokens_missing": gold_misses,
        "errors": errors,
        "by_bucket": {
            b: {"count": sum(v.values()), "format_counts": dict(v.most_common())}
            for b, v in bucket_fmt.items()
        },
    }


def write_replay_markdown(replay_rows: list[dict], summary: dict, md_path: str) -> None:
    lines: list[str] = []
    def a(s):
        lines.append(s)


    a("# Context Replay Report")
    a("")
    a(f"- Replayed: {summary['replayed']} cases")
    a(f"- Context format distribution: {summary['context_format_counts']}")
    a(f"- Gold tokens found in replayed context: {summary['gold_tokens_found']}")
    a(f"- Gold tokens missing: {summary['gold_tokens_missing']}")
    a(f"- Errors: {summary['errors']}")
    a("")

    a("## By Bucket")
    a("")
    a("| Bucket | Count | Formats |")
    a("|---|---|---|")
    for bucket, info in summary["by_bucket"].items():
        a(f"| {bucket} | {info['count']} | {info['format_counts']} |")
    a("")

    for row in replay_rows:
        a(f"### {row['case_id']}  ")
        a(f"- **Bucket**: {row.get('replay_bucket', '?')}  ")
        a(f"- **Category**: {row.get('category', '?')}  ")
        a(f"- **Question**: {_md_escape(row.get('question', '') or '')}  ")
        a(f"- **Gold answer**: {_md_escape(row.get('gold_answer', '') or '')}  ")
        a(f"- **Baseline prediction**: {_md_escape(row.get('baseline_prediction', '') or '')}  ")
        a(f"- **Baseline recall**: {row.get('baseline_context_recall', '?')}  ")
        a(f"- **Replay recall**: {row.get('replay_context_recall', '?')}  ")
        a(f"- **Context format**: `{row.get('context_format', '?')}`  ")
        a(f"- **Context length**: {row.get('retrieved_context_length', 0)}  ")
        a(f"- **Raw snippet count**: {row.get('raw_snippet_count', 0)}  ")
        a(f"- **Starts with JSON**: {row.get('context_starts_with_json', False)}  ")
        a(f"- **Gold tokens in context**: {row.get('gold_tokens_in_replayed_context', '?')}  ")
        if row.get("error"):
            a(f"- **Error**: {row['error']}  ")
        ctx = row.get("retrieved_context_preview", "")
        if ctx:
            a("")
            a("<details><summary>Context preview</summary>")
            a("")
            a("```")
            a(ctx[:1000])
            a("```")
            a("")
            a("</details>")
        a("")

    # hypotheses
    a("## Hypotheses After Replay")
    a("")
    a("1. **pack_json fallback is a hypothesis pending this replay, not a confirmed cause.**")
    a("2. If high_recall_unknown cases replay as raw_text with gold tokens present, the answerer prompt/conservatism is the primary block.")
    a("3. If high_recall_unknown cases replay as pack_json, the evidence closure fallback is the primary retrieval-to-context defect.")
    a("4. Zero-recall cases with empty or pack_json replay context indicate retrieval never found matching chunks.")

    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def write_replay_json(replay_rows: list[dict], summary: dict, json_path: str) -> None:
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump({"summary": summary, "cases": replay_rows}, fh, indent=2, default=str)


# ---------------------------------------------------------------------------
# markdown helpers (shared)
# ---------------------------------------------------------------------------

def _md_escape(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def write_markdown(audit: dict, md_path: str) -> None:
    lines: list[str] = []
    def a(s):
        lines.append(s)


    a("# LoCoMo Baseline Audit")
    a("")
    a(f"- Result: `{audit['result_path']}`")
    a(f"- Dataset: `{audit['dataset_path']}`")
    a(f"- Dataset fixture hash: `{audit.get('dataset_fixture_hash', 'N/A')}`")
    a(f"- Result cases: {audit['result_case_count']}")
    a(f"- Dataset cases: {audit['dataset_case_count']}")
    a(f"- Context snippets in result: {audit['context_snippets_present']}")
    a("")

    # integrity
    a("## Dataset / Source Integrity")
    a("")
    a(f"- Missing from dataset (result IDs not in dataset): {len(audit['missing_from_dataset'])}")
    a(f"- Extra in result (dataset IDs not in result): {len(audit['extra_in_result'])}")
    a(f"- Duplicate result case IDs: {len(audit['duplicate_ids'])}")
    a("")

    # scores
    a("## Score Summary")
    a("")
    ss = audit["scores_summary"]
    a("| Metric | Value |")
    a("|---|---|")
    for k in ["context_recall_mean", "answer_em_mean", "answer_f1_mean", "judge_score_mean"]:
        a(f"| {k} | {ss.get(k, '?')} |")
    a(f"| judge correct/partial/incorrect | {ss.get('correct_count', '?')} / {ss.get('partial_count', '?')} / {ss.get('incorrect_count', '?')} |")
    a("")

    # category
    a("## Category Summary")
    a("")
    a("| Cat | Cases | Recall Mean | Judge Mean | Unknown Count |")
    a("|---|---|---|---|---|")
    for cat in sorted(audit["category_summary"].keys()):
        cs = audit["category_summary"][cat]
        a(f"| {cat} | {cs['case_count']} | {cs['context_recall_mean']:.4f} | {cs['judge_score_mean']:.4f} | {cs['unknown_count']} |")
    a("")

    # predictions
    a("## Prediction Distribution")
    a("")
    a(f"- Case-insensitive 'unknown' count: {audit.get('unknown_ci_count', 'N/A')}")
    a("")
    a("| Prediction | Count |")
    a("|---|---|")
    for pred, count in sorted(audit["prediction_distribution"].items(), key=lambda x: -x[1]):
        label = _md_escape(pred) if pred else "(empty)"
        a(f"| {label} | {count} |")
    a("")

    # buckets
    a("## Bucket Counts")
    a("")
    a("| Bucket | Count |")
    a("|---|---|")
    for name, count in audit["bucket_counts"].items():
        a(f"| {name} | {count} |")
    a(f"| judge_errors | {audit['judge_error_count']} |")
    a("")

    # samples
    for bucket_name, case_samples in audit["samples"].items():
        if not case_samples:
            continue
        a(f"## Sample: {bucket_name} ({len(case_samples)} cases)")
        a("")
        a("| # | case_id | cat | recall | f1 | prediction | judge | rationale |")
        a("|---|---|---|---|---|---|---|---|")
        for i, c in enumerate(case_samples, 1):
            a(
                f"| {i} | {_md_escape(c['case_id'])} | {c.get('category', '?')} "
                f"| {c['context_recall']:.3f} | {c['answer_f1']:.3f} "
                f"| {_md_escape(c.get('prediction', ''))} "
                f"| {c.get('judge_verdict', '')} "
                f"| {_md_escape(_safe_str(c.get('judge_rationale', ''))[:120])} |"
            )

        a("")
        a("<details><summary>Show questions / gold answers</summary>")
        a("")
        a("| # | Question | Gold Answer | Prediction |")
        a("|---|---|---|---|")
        for i, c in enumerate(case_samples, 1):
            a(
                f"| {i} | {_md_escape(c.get('question', '')[:150])} "
                f"| {_md_escape(c.get('gold_answer', ''))} "
                f"| {_md_escape(c.get('prediction', ''))} |"
            )
        a("")
        a("</details>")
        a("")

    # judge errors
    if audit["judge_error_case_ids"]:
        a("## Judge Errors")
        a("")
        for cid in audit["judge_error_case_ids"]:
            a(f"- `{cid}`")
        a("")

    # top findings
    a("## Key Findings")
    a("")
    bc = audit["bucket_counts"]
    total = audit["result_case_count"]
    unknown_count = audit.get("unknown_ci_count", audit["prediction_distribution"].get("unknown", 0))
    a(f"1. **{bc['zero_recall']} cases ({bc['zero_recall']/total*100:.1f}%) have zero context recall** — retrieval returned no relevant evidence")
    a(f"2. **{bc['low_recall']} cases ({bc['low_recall']/total*100:.1f}%) have recall < 0.2** — retrieval severely degraded")
    a(f"3. **{unknown_count} cases ({unknown_count/total*100:.1f}%) predicted 'unknown'** — answerer abstention dominates")
    a(f"4. **{bc['high_recall_unknown']} cases have high recall (>=0.8) but still answer 'unknown'** — abstention is not caused by bad retrieval alone")
    a(f"5. **Context snippets present in result: {audit['context_snippets_present']}** — {'context is persisted' if audit['context_snippets_present'] else 'diagnosis of retrieval quality relies entirely on recall scores and judge rationales'}")
    a("6. **pack_json fallback as root cause is a hypothesis pending context replay** — see replay report for per-case evidence")
    a(f"7. **{audit['judge_error_count']} judge errors** — minor, but worth noting")
    a(f"8. **Dataset fixture hash**: `{audit.get('dataset_fixture_hash', 'N/A')}`")

    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="LoCoMo baseline failure audit")
    parser.add_argument("--result", required=True)
    parser.add_argument("--dataset-path", required=True)
    parser.add_argument("--output")
    parser.add_argument("--markdown")

    # replay
    parser.add_argument("--replay-context", action="store_true")
    parser.add_argument("--replay-sample", type=int, default=5)
    parser.add_argument("--replay-output")
    parser.add_argument("--replay-markdown")
    args = parser.parse_args()

    audit = run_audit(args.result, args.dataset_path)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            json.dump(audit, fh, indent=2, default=str)
        print(f"Audit JSON written to {args.output}")

    if args.markdown:
        write_markdown(audit, args.markdown)
        print(f"Audit markdown written to {args.markdown}")

    print(f"\nResult cases: {audit['result_case_count']}")
    print(f"Dataset cases: {audit['dataset_case_count']}")
    print(f"Dataset fixture hash: {audit.get('dataset_fixture_hash', 'N/A')}")
    print(f"Buckets: {audit['bucket_counts']}")
    print(f"Judge errors: {audit['judge_error_count']}")
    print(f"Unknown predictions (ci): {audit.get('unknown_ci_count', 'N/A')}")
    print(f"Context snippets in result: {audit['context_snippets_present']}")

    if args.replay_context:
        print("\n--- Context Replay ---")
        replay_rows = run_context_replay(
            args.result, args.dataset_path, sample_n=args.replay_sample,
        )
        summary = _summarise_replay(replay_rows)
        print(f"Replayed: {summary['replayed']} cases")
        print(f"Format distribution: {summary['context_format_counts']}")
        print(f"Gold tokens found: {summary['gold_tokens_found']}")
        print(f"Gold tokens missing: {summary['gold_tokens_missing']}")
        print(f"Errors: {summary['errors']}")
        print("By bucket:")
        for b, info in summary["by_bucket"].items():
            print(f"  {b}: {info['count']} cases, formats={info['format_counts']}")

        if args.replay_output:
            write_replay_json(replay_rows, summary, args.replay_output)
            print(f"\nReplay JSON written to {args.replay_output}")

        if args.replay_markdown:
            write_replay_markdown(replay_rows, summary, args.replay_markdown)
            print(f"Replay markdown written to {args.replay_markdown}")


if __name__ == "__main__":
    main()
