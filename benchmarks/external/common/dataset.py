from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from benchmarks.external.common.types import BenchmarkCase, ConversationTurn

QUICKSTART_FIXTURE_PATH = (
    Path(__file__).resolve().parent.parent / "locomo" / "fixtures" / "quickstart.json"
)


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def load_locomo_cases(
    path: str | Path, *, include_unanswerable: bool = False
) -> list[BenchmarkCase]:
    """Parse a LoCoMo JSON file into BenchmarkCase records.

    One case per Q/A pair.  case_id = f"{sample_id}::q{qa_index}".
    The full conversation (all sessions / dialogs flattened) is shared across
    every qa pair belonging to the same sample.

    ``include_unanswerable`` (default ``False``) controls the LoCoMo adversarial
    (category 5) questions, which carry only an ``adversarial_answer`` (a plausible
    trap) and NO real ``answer``. By default they are skipped (their empty gold
    would distort recall/judged scoring). When ``True`` they are admitted with
    ``gold_answer == ""`` so a calibration scorer can treat them as the
    unanswerable arm (the correct behavior is to abstain, not to emit the trap).
    The default-off flag keeps every existing caller byte-identical.
    """
    path = Path(path)

    with path.open("r", encoding="utf-8") as fh:
        raw: list[dict[str, Any]] = json.load(fh)

    cases: list[BenchmarkCase] = []

    for sample in raw:
        sample_id: str = sample["sample_id"]

        # --- flatten conversation into a single ordered tuple of turns ---
        conversation: list[ConversationTurn] = []
        conversation_data = sample["conversation"]
        for timestamp, dialogs in _iter_locomo_sessions(conversation_data):
            for dialog in dialogs:
                speaker = dialog["speaker"]
                text = dialog["text"]
                conversation.append(
                    ConversationTurn(speaker=speaker, text=text, timestamp=timestamp)
                )

        conversation_tuple: tuple[ConversationTurn, ...] = tuple(conversation)

        # --- one BenchmarkCase per QA pair ---
        qa_list: list[dict[str, Any]] = sample.get("qa", [])
        for qa_index, qa in enumerate(qa_list):
            raw_answer = qa.get("answer")
            has_answer = raw_answer is not None and str(raw_answer).strip() != ""
            if not has_answer:
                # No real answer. Adversarial (cat5) cases carry only an
                # `adversarial_answer`; admit them as empty-gold ONLY when
                # explicitly asked, else preserve the historical skip.
                if not (include_unanswerable and "adversarial_answer" in qa):
                    continue
            case_id = f"{sample_id}::q{qa_index}"
            question = _coerce_text(qa["question"])
            gold_answer = _coerce_text(raw_answer) if has_answer else ""
            # category may be absent, an int, or a str
            raw_category = qa.get("category")
            category: str | None = (
                str(raw_category) if raw_category is not None else None
            )

            cases.append(
                BenchmarkCase(
                    case_id=case_id,
                    conversation=conversation_tuple,
                    question=question,
                    gold_answer=gold_answer,
                    category=category,
                )
            )

    return cases


def load_quickstart_cases() -> list[BenchmarkCase]:
    """Load the bundled quickstart fixture."""
    return load_locomo_cases(QUICKSTART_FIXTURE_PATH)


def _iter_locomo_sessions(conversation_data: dict[str, Any]):
    """Yield LoCoMo sessions from fixture and official release shapes."""
    sessions = conversation_data.get("sessions")
    if isinstance(sessions, list):
        for session in sessions:
            yield session.get("date_time") or None, session.get("dialogs", [])
        return

    numbered: list[tuple[int, str | None, list[dict[str, Any]]]] = []
    for key, value in conversation_data.items():
        match = re.fullmatch(r"session_(\d+)", key)
        if not match or not isinstance(value, list):
            continue
        session_number = int(match.group(1))
        timestamp = conversation_data.get(f"session_{session_number}_date_time") or None
        numbered.append((session_number, timestamp, value))

    for _, timestamp, dialogs in sorted(numbered, key=lambda item: item[0]):
        yield timestamp, dialogs
