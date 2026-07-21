"""BEAM benchmark runner for SEAM.

The complete BEAM release has 100 conversations and 2,000 questions across
four scales. The 1M track itself has 35 conversations and 700 questions.
BEAM-10M is explicitly deferred and cannot be run accidentally.

Usage:
    python -m benchmarks.external.beam.run --track 1m --dataset-path /path/to/beam-dir --dry-run
    python -m benchmarks.external.beam.run --track 1m \
        --harness-root /path/to/memory-benchmarks --project-name seam-beam \
        --mem0-host http://127.0.0.1:8900 --predict-only

The full dataset is not bundled; point --dataset-path at a local BEAM release directory.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Iterable

from benchmarks.external.common.types import BenchmarkCase, ConversationTurn
from benchmarks.external.mem0_harness.upstream_runner import (
    execute_upstream_plan,
    plan_upstream_run,
    render_plan,
)

EXPECTED_BY_TRACK = {
    "1m": {"conversations": 35, "questions": 700},
    "10m": {"conversations": 10, "questions": 200},
}
BEAM_QUESTION_TYPES = (
    "abstention",
    "contradiction_resolution",
    "event_ordering",
    "information_extraction",
    "instruction_following",
    "knowledge_update",
    "multi_session_reasoning",
    "preference_following",
    "summarization",
    "temporal_reasoning",
)
BEAM_TRACK_DIRS = {
    "1m": "1M",
    "10m": "10M",
}


def _scan_beam_dataset(dataset_path: str, track: str):
    """Scan a BEAM dataset directory and return case metadata.

    BEAM datasets are directory-based. Each conversation is in a subdirectory
    with session files and a questions JSON file.
    """
    root = Path(dataset_path)
    if not root.is_dir():
        raise FileNotFoundError(f"BEAM dataset directory not found: {dataset_path}")

    conversations = []
    total_questions = 0

    for entry in sorted(root.iterdir()):
        if entry.is_dir():
            qa_files = list(entry.glob("questions*.json")) + list(entry.glob("qa*.json"))
            conv_questions = 0
            for qf in qa_files:
                try:
                    with open(qf, "r", encoding="utf-8") as fh:
                        qa_data = json.load(fh)
                    if isinstance(qa_data, list):
                        conv_questions += len(qa_data)
                    elif isinstance(qa_data, dict):
                        conv_questions += len(qa_data.get("questions", qa_data.get("qa", [])))
                except Exception:
                    pass
            conversations.append({
                "dir": entry.name,
                "question_count": conv_questions,
            })
            total_questions += conv_questions

    return conversations, total_questions


def _resolve_official_local_track_root(dataset_path: str | Path, track: str) -> Path:
    """Resolve a released BEAM checkout, chats directory, or scale directory."""
    root = Path(dataset_path)
    if not root.is_dir():
        raise FileNotFoundError(f"BEAM dataset directory not found: {dataset_path}")
    track_dir = BEAM_TRACK_DIRS[track]
    candidates = (
        root,
        root / track_dir,
        root / "chats" / track_dir,
        root / "test_chats" / track_dir,
    )
    for candidate in candidates:
        if candidate.name.casefold() != track_dir.casefold() and candidate == root:
            continue
        if candidate.is_dir() and any(
            child.is_dir()
            and (child / "chat.json").is_file()
            and (child / "probing_questions" / "probing_questions.json").is_file()
            for child in candidate.iterdir()
        ):
            return candidate.resolve()
    raise ValueError(
        f"official local BEAM {track_dir} layout not found under {root}; expected "
        f"chats/{track_dir}/<conversation>/chat.json and probing_questions/probing_questions.json"
    )


def _source_manifest_hash(files: Iterable[tuple[str, bytes]]) -> str:
    digest = hashlib.sha256()
    _update_source_manifest(digest, files)
    return digest.hexdigest()


def _update_source_manifest(
    digest,
    files: Iterable[tuple[str, bytes]],
) -> int:
    count = 0
    for relative_path, payload in files:
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(payload).digest())
        count += 1
    return count


def _official_local_conversation_dirs(track_root: Path) -> list[Path]:
    return sorted(
        (
            child
            for child in track_root.iterdir()
            if child.is_dir()
            and (child / "chat.json").is_file()
            and (child / "probing_questions" / "probing_questions.json").is_file()
        ),
        key=lambda path: _beam_plan_sort_key(path.name),
    )


def _load_official_local_conversation(
    conversation_dir: Path,
    *,
    dataset_format: str = "official-local-repo",
) -> tuple[list[BenchmarkCase], tuple[tuple[str, bytes], ...]]:
    chat_path = conversation_dir / "chat.json"
    questions_path = conversation_dir / "probing_questions" / "probing_questions.json"
    chat_bytes = chat_path.read_bytes()
    questions_bytes = questions_path.read_bytes()
    try:
        chat = json.loads(chat_bytes)
    except json.JSONDecodeError as exc:
        raise ValueError(f"BEAM {chat_path} is not valid JSON: {exc}") from exc
    try:
        probing_questions = json.loads(questions_bytes)
    except json.JSONDecodeError as exc:
        raise ValueError(f"BEAM {questions_path} is not valid JSON: {exc}") from exc
    row = {
        "conversation_id": conversation_dir.name,
        "chat": chat,
        "probing_questions": probing_questions,
    }
    cases = _cases_from_beam_rows([row], dataset_format=dataset_format)
    source_files = (
        (f"{conversation_dir.name}/chat.json", chat_bytes),
        (
            f"{conversation_dir.name}/probing_questions/probing_questions.json",
            questions_bytes,
        ),
    )
    return cases, source_files


def _scan_official_local_dataset(dataset_path: str | Path, track: str) -> dict:
    """Fully validate the local released layout without retaining the full corpus."""
    track_root = _resolve_official_local_track_root(dataset_path, track)
    conversations: list[dict] = []
    category_counts: Counter[str] = Counter()
    source_digest = hashlib.sha256()
    source_file_count = 0
    total_questions = 0
    total_turns = 0
    for conversation_dir in _official_local_conversation_dirs(track_root):
        cases, conversation_files = _load_official_local_conversation(conversation_dir)
        question_count = len(cases)
        conversation_turns = len(cases[0].conversation) if cases else 0
        if conversation_turns == 0:
            raise ValueError(f"BEAM {conversation_dir.name} has an empty chat")
        conversations.append(
            {
                "dir": conversation_dir.name,
                "question_count": question_count,
                "turn_count": conversation_turns,
            }
        )
        total_questions += question_count
        total_turns += conversation_turns
        category_counts.update(case.category for case in cases)
        source_file_count += _update_source_manifest(source_digest, conversation_files)
    return {
        "conversations": conversations,
        "total_questions": total_questions,
        "total_turns": total_turns,
        "category_counts": category_counts,
        "fixture_hash": source_digest.hexdigest(),
        "source_root": str(track_root),
        "source_file_count": source_file_count,
    }


def _load_beam_cases(dataset_path: str | Path, track: str | None = None) -> list[BenchmarkCase]:
    path = Path(dataset_path)
    if path.is_dir():
        if track is None:
            normalized_name = path.name.casefold()
            track = next(
                (
                    key
                    for key, dirname in BEAM_TRACK_DIRS.items()
                    if dirname.casefold() == normalized_name
                ),
                None,
            )
        if track is None:
            raise ValueError(
                "loading a BEAM repository or chats root requires "
                "track='1m' or track='10m'"
            )
        track_root = _resolve_official_local_track_root(path, track)
        cases: list[BenchmarkCase] = []
        for conversation_dir in _official_local_conversation_dirs(track_root):
            conversation_cases, _ = _load_official_local_conversation(conversation_dir)
            cases.extend(conversation_cases)
        return cases
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if isinstance(payload, dict):
        rows = payload.get("rows", [])
    elif isinstance(payload, list):
        rows = payload
    else:
        raise ValueError("BEAM JSON root must be a rows object or list")
    if not isinstance(rows, list):
        raise ValueError("BEAM rows must be a list")
    return _cases_from_beam_rows(rows, dataset_format="official-hf-rows")


def _cases_from_beam_rows(rows: list, *, dataset_format: str) -> list[BenchmarkCase]:
    cases: list[BenchmarkCase] = []
    seen_case_ids: set[str] = set()
    for row_index, item in enumerate(rows):
        if not isinstance(item, dict):
            raise ValueError(f"BEAM row {row_index} must be an object")
        row = item.get("row", item)
        if not isinstance(row, dict):
            raise ValueError(f"BEAM row {row_index} payload must be an object")
        conversation_id = str(row.get("conversation_id", f"conversation-{row_index}"))
        conversation = tuple(_iter_beam_turns(row.get("chat", [])))
        if not conversation:
            raise ValueError(f"BEAM {conversation_id} has an empty or unsupported chat")
        questions = _parse_probing_questions(row.get("probing_questions", {}))
        row_case_count = 0
        for category, category_questions in questions.items():
            if not isinstance(category_questions, list):
                raise ValueError(
                    f"BEAM {conversation_id} category {category!r} must contain a list"
                )
            for question_index, question_data in enumerate(category_questions):
                if not isinstance(question_data, dict):
                    raise ValueError(
                        f"BEAM {conversation_id} category {category!r} has a malformed question"
                    )
                case_id = f"{conversation_id}::{category}::{question_index}"
                if case_id in seen_case_ids:
                    raise ValueError(f"duplicate BEAM case id: {case_id}")
                seen_case_ids.add(case_id)
                question = str(
                    question_data.get("question", question_data.get("question_text", ""))
                ).strip()
                if not question:
                    raise ValueError(f"BEAM {case_id} has an empty question")
                nuggets = _beam_rubric_nuggets(question_data)
                if not nuggets:
                    raise ValueError(f"BEAM {case_id} has no rubric nuggets")
                cases.append(
                    BenchmarkCase(
                        case_id=case_id,
                        conversation=conversation,
                        question=question,
                        gold_answer=_beam_gold_answer(question_data),
                        category=str(category),
                        metadata={
                            "dataset_format": dataset_format,
                            "conversation_id": conversation_id,
                            "rubric_nuggets": tuple(nuggets),
                            "user_profile": row.get("user_profile", {}),
                        },
                    )
                )
                row_case_count += 1
        if row_case_count == 0:
            raise ValueError(f"BEAM {conversation_id} has no probing questions")
    return cases


def _iter_beam_turns(chat):
    for batch in _beam_batches(chat):
        for turn in batch:
            if not isinstance(turn, dict):
                continue
            speaker = str(turn.get("role", turn.get("speaker", ""))).strip()
            text = str(turn.get("content", turn.get("text", ""))).strip()
            if not speaker or not text:
                continue
            yield ConversationTurn(
                speaker=speaker,
                text=text,
                timestamp=turn.get("time_anchor"),
            )


def _beam_batches(chat):
    """Normalize the three official HF chat encodings used by BEAM."""
    if not isinstance(chat, list) or not chat:
        return []
    first = chat[0]
    if isinstance(first, list):
        return chat
    if isinstance(first, dict) and "turns" in first:
        return [_flatten_beam_turns(batch.get("turns", [])) for batch in chat]
    if isinstance(first, dict) and ("role" in first or "content" in first):
        return [chat]
    if isinstance(first, dict):
        batches = []
        for session in chat:
            if not isinstance(session, dict):
                continue
            for key in sorted(session, key=_beam_plan_sort_key):
                for batch in session.get(key) or []:
                    if isinstance(batch, dict):
                        batches.append(_flatten_beam_turns(batch.get("turns", [])))
        return batches
    return []


def _flatten_beam_turns(turns):
    flattened = []
    for item in turns if isinstance(turns, list) else []:
        if isinstance(item, list):
            flattened.extend(item)
        elif isinstance(item, dict):
            flattened.append(item)
    return flattened


def _beam_plan_sort_key(value: str):
    tail = value.rsplit("-", 1)[-1]
    return (0, int(tail)) if tail.isdigit() else (1, value)


def _parse_probing_questions(value):
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    parsed = ast.literal_eval(value)
    if not isinstance(parsed, dict):
        raise ValueError("BEAM probing_questions must parse to a dict")
    return parsed


def _beam_rubric_nuggets(question_data: dict) -> list[str]:
    rubric = question_data.get("rubric", {})
    if isinstance(rubric, dict):
        values = rubric.get("nuggets", [])
        return [
            str(item.get("description", "")).strip()
            if isinstance(item, dict)
            else str(item).strip()
            for item in values
            if (item.get("description") if isinstance(item, dict) else item)
        ]
    if isinstance(rubric, list):
        return [str(item).strip() for item in rubric if str(item).strip()]
    return [str(rubric).strip()] if str(rubric).strip() else []


def _beam_gold_answer(question_data: dict) -> str:
    for key in ("answer", "ideal_answer", "ideal_response", "ideal_summary", "expected_compliance"):
        value = question_data.get(key)
        if value:
            answer = str(value)
            break
    else:
        answer = ""
    rubric = _beam_rubric_nuggets(question_data)
    if rubric:
        rubric_lines = "\n".join(f"- {item}" for item in rubric)
        return f"{answer}\nRubric:\n{rubric_lines}" if answer else f"Rubric:\n{rubric_lines}"
    return answer


def _dry_run_report(
    conversations,
    total_questions,
    dataset_path,
    track,
    judge_name,
    *,
    cases: list[BenchmarkCase] | None = None,
    executable_format: bool,
    category_counts: Counter[str] | None = None,
    fixture_hash: str | None = None,
    source_root: str | None = None,
    source_file_count: int | None = None,
    total_turns: int | None = None,
    dataset_format: str | None = None,
):
    issues = []
    expected = EXPECTED_BY_TRACK.get(track, {})
    expected_conversations = expected.get("conversations")
    expected_questions = expected.get("questions")
    if expected_conversations is not None and len(conversations) != expected_conversations:
        issues.append(
            f"Expected {expected_conversations} conversations, found {len(conversations)}"
        )
    if expected_questions is not None and total_questions != expected_questions:
        issues.append(
            f"Expected {expected_questions} questions, found {total_questions}"
        )
    category_counts = category_counts or Counter(case.category for case in cases or [])
    missing_types = [
        question_type
        for question_type in BEAM_QUESTION_TYPES
        if question_type not in category_counts
    ]
    if executable_format and missing_types:
        issues.append(f"Missing BEAM question types: {missing_types}")
    if not executable_format:
        issues.append(
            "Directory scan is structural only and cannot preserve official chat payloads"
        )
    if fixture_hash is None:
        payload = json.dumps(
            {
                "conversations": conversations,
                "cases": [
                    {
                        "case_id": case.case_id,
                        "question": case.question,
                        "category": case.category,
                        "metadata": case.metadata,
                    }
                    for case in cases or []
                ],
            },
            sort_keys=True,
            default=list,
        )
        fixture_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return {
        "dataset_path": str(dataset_path),
        "benchmark": "beam",
        "track": track,
        "conversation_count": len(conversations),
        "expected_conversations": expected_conversations,
        "total_questions": total_questions,
        "expected_questions": expected_questions,
        "fixture_hash": fixture_hash,
        "source_root": source_root,
        "source_file_count": source_file_count,
        "total_turns": total_turns,
        "question_types": dict(category_counts),
        "missing_question_types": missing_types,
        "dataset_format": dataset_format
        or ("official-hf-rows" if executable_format else "directory-scan-only"),
        "execution_contract": "pinned-upstream-memory-benchmarks-only",
        "estimated_judge_calls": total_questions if judge_name and judge_name not in ("none", "stub") else 0,
        "judge": judge_name or "none",
        "mode": "dry-run",
        "valid": len(issues) == 0,
        "validation_issues": issues,
    }


def _conversation_summary_from_cases(cases: list[BenchmarkCase]) -> tuple[list[dict], int]:
    counts: dict[str, int] = {}
    for case in cases:
        scope = _beam_scope_id(case)
        counts[scope] = counts.get(scope, 0) + 1
    conversations = [
        {"dir": scope, "question_count": count}
        for scope, count in sorted(counts.items())
    ]
    return conversations, len(cases)


def _beam_scope_id(case: BenchmarkCase) -> str:
    return case.case_id.split("::", 1)[0]


def main() -> None:
    parser = argparse.ArgumentParser(description="BEAM benchmark runner for SEAM")
    parser.add_argument("--track", required=True, choices=["1m", "10m"],
                        help="BEAM track (10m is deferred)")
    parser.add_argument("--dataset-path", help="Dry-run input: directory scan or exported Hugging Face rows JSON")
    parser.add_argument("--dry-run", action="store_true", help="Validate dataset and print counts without executing")
    parser.add_argument("--plan", action="store_true", help="Print upstream readiness without executing")
    parser.add_argument("--judge", choices=["none", "stub", "claude", "openai"], default=None)
    parser.add_argument("--judge-model", default=None)
    parser.add_argument("--answerer-model", default="gpt-4o")
    parser.add_argument("--provider", choices=["openai", "anthropic", "azure"], default="openai")
    parser.add_argument("--harness-root", help="Pinned mem0ai/memory-benchmarks checkout")
    parser.add_argument("--project-name", help="Upstream run identifier")
    parser.add_argument("--mem0-host", default="http://127.0.0.1:8900")
    parser.add_argument("--predict-only", action="store_true", help="Free ingest+search only; skip answerer and judge")
    parser.add_argument("--allow-paid", action="store_true", help="Acknowledge provider-paid answerer/judge execution")
    parser.add_argument("--allow-10m", action="store_true", help="Explicitly authorize the separately deferred 10M track")
    parser.add_argument("--allow-download", action="store_true", help="Explicitly authorize a missing BEAM cache download")
    parser.add_argument("--dataset-cache-dir", default="/tmp/seam-upstream-benchmarks/beam-data")
    parser.add_argument("--conversations", default=None, help="Upstream conversation indices; defaults to full selected track")
    parser.add_argument("--top-k", type=int, default=200)
    parser.add_argument("--top-k-cutoffs", default="50,200")
    parser.add_argument("--output-dir", default="/tmp/seam-upstream-benchmarks/beam")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()

    if args.dry_run:
        if not args.dataset_path:
            parser.error("--dry-run requires --dataset-path")
        dataset_path = Path(args.dataset_path)
        if not dataset_path.exists():
            parser.error("BEAM dataset path not found")
        if dataset_path.is_dir():
            try:
                _resolve_official_local_track_root(dataset_path, args.track)
            except ValueError:
                conversations, total_questions = _scan_beam_dataset(
                    str(dataset_path), args.track
                )
                cases = None
                executable_format = False
                report_kwargs = {}
            else:
                try:
                    local_scan = _scan_official_local_dataset(dataset_path, args.track)
                except ValueError as exc:
                    parser.error(str(exc))
                conversations = local_scan["conversations"]
                total_questions = local_scan["total_questions"]
                cases = None
                executable_format = True
                report_kwargs = {
                    "category_counts": local_scan["category_counts"],
                    "fixture_hash": local_scan["fixture_hash"],
                    "source_root": local_scan["source_root"],
                    "source_file_count": local_scan["source_file_count"],
                    "total_turns": local_scan["total_turns"],
                    "dataset_format": "official-local-repo",
                }
        else:
            try:
                cases = _load_beam_cases(dataset_path)
            except ValueError as exc:
                parser.error(str(exc))
            if args.limit is not None:
                cases = cases[: args.limit]
            conversations, total_questions = _conversation_summary_from_cases(cases)
            executable_format = True
            report_kwargs = {
                "fixture_hash": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
                "source_root": str(dataset_path.resolve()),
                "source_file_count": 1,
                "total_turns": sum(
                    {
                        _beam_scope_id(case): len(case.conversation)
                        for case in cases
                    }.values()
                ),
            }
        report = _dry_run_report(
            conversations,
            total_questions,
            args.dataset_path,
            args.track,
            args.judge,
            cases=cases,
            executable_format=executable_format,
            **report_kwargs,
        )
        print(json.dumps(report, indent=2))
        raise SystemExit(0 if report["valid"] else 1)
    if args.limit is not None:
        parser.error("--limit is dry-run-only; use --conversations for upstream execution")
    if not args.harness_root or not args.project_name:
        parser.error(
            "competitive execution requires --harness-root and --project-name; "
            "the local generic scorer is intentionally disabled"
        )
    if not args.predict_only and args.judge in {None, "none", "stub"}:
        parser.error("scored execution requires --judge openai or --judge claude")
    judge_provider = (
        "anthropic" if args.judge == "claude" else args.judge
        if args.judge in {"openai"}
        else None
    )
    default_conversations = "0-34" if args.track == "1m" else "0-9"
    plan = plan_upstream_run(
        benchmark="beam",
        harness_root=args.harness_root,
        project_name=args.project_name,
        mem0_host=args.mem0_host,
        predict_only=args.predict_only,
        top_k=args.top_k,
        top_k_cutoffs=args.top_k_cutoffs,
        workers=args.workers,
        output_dir=args.output_dir,
        answerer_model=args.answerer_model,
        judge_model=args.judge_model or "gpt-4o",
        provider=args.provider,
        judge_provider=judge_provider,
        dataset_cache_dir=args.dataset_cache_dir,
        chat_size=args.track,
        conversations=args.conversations or default_conversations,
    )
    print(render_plan(plan))
    if args.plan:
        raise SystemExit(0 if plan.ready and not plan.requires_download else 1)
    try:
        return_code = execute_upstream_plan(
            plan,
            allow_paid=args.allow_paid,
            allow_beam_10m=args.allow_10m,
            allow_download=args.allow_download,
        )
    except RuntimeError as exc:
        parser.error(str(exc))
    raise SystemExit(return_code)


if __name__ == "__main__":
    main()
