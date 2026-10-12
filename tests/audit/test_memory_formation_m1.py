"""M1 probe controls must survive optimized Python and fail before unsafe work."""
from __future__ import annotations

import json
import runpy
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tools import memory_formation_m1 as m1


ROOT = Path(__file__).resolve().parents[2]
THIS_FILE = Path(__file__).resolve()
INVALID_CONTROLS = (
    "raw",
    "span",
    "painting_count",
    "unstated_count",
    "retrieval_context",
    "generated_answer",
    "duplicate_raw",
)
EXPECTED_CONTROL_FAILURE = {
    "raw": "compiler RAW/SPAN control failed",
    "span": "compiler RAW/SPAN control failed",
    "painting_count": "stored painting count control failed",
    "unstated_count": "unstated sentinel absence control failed",
    "retrieval_context": "retrieval context/generation control failed",
    "generated_answer": "retrieval context/generation control failed",
    "duplicate_raw": "distinct source reference control failed",
}


def _record(*, record_id, kind, attrs, evidence=()):
    return SimpleNamespace(
        id=record_id,
        kind=kind,
        attrs=attrs,
        ext={"source_metadata": None},
        t0=None,
        t1=None,
        status=SimpleNamespace(value="active"),
        evidence=list(evidence),
    )


class _Batch:
    def __init__(self, text: str, *, bad_span: bool = False, raw_count: int = 1):
        span_text = "not-present" if bad_span else text[:1]
        self.records = [
            *[
                _record(
                    record_id=f"raw-{index}",
                    kind=m1.RecordKind.RAW,
                    attrs={"content": text},
                )
                for index in range(raw_count)
            ],
            _record(
                record_id="entity",
                kind=m1.RecordKind.ENT,
                attrs={"label": "fixture-subject"},
            ),
            _record(
                record_id="claim",
                kind=m1.RecordKind.CLM,
                attrs={"object": span_text, "predicate": "fixture", "subject": "entity"},
                evidence=("span",),
            ),
            _record(
                record_id="span",
                kind=m1.RecordKind.SPAN,
                attrs={"raw_id": "raw-0", "start": 0, "end": len(span_text)},
            ),
        ]

    def by_id(self):
        return {record.id: record for record in self.records}

    def kind(self, kind):
        return [record for record in self.records if record.kind == kind]


class _Cursor:
    def __init__(self, value: int):
        self.value = value

    def fetchone(self):
        return (self.value,)


class _Connection:
    def __init__(self, mode: str):
        self.mode = mode

    def execute(self, query, params):
        if "raw_docs" in query:
            term = params[1].strip("%")
            if term == "painting":
                return _Cursor(0 if self.mode == "painting_count" else 1)
            if term == "M1_UNSTATED_SENTINEL":
                return _Cursor(1 if self.mode == "unstated_count" else 0)
            return _Cursor(1)
        return _Cursor(0)

    def close(self):
        return None


class _Store:
    def __init__(self, mode: str, direct: bool = False):
        self.mode = mode
        self.direct = direct

    def load_ir(self, ns):
        if self.direct and ns == "control":
            count = 1 if self.mode == "duplicate_raw" else 2
            return _Batch("Eve: I visited the museum.", raw_count=count)
        if self.direct and ns == "unicode":
            return _Batch(m1.SAMPLES["unicode"])
        return _Batch("painting")

    def _connect(self):
        return _Connection(self.mode)

    def rebuild_graph_products(self, namespace, scope):
        return {"built": 0}

    def graph_products(self, namespace, scope):
        return []


class _Runtime:
    def __init__(self, mode: str, direct: bool = False):
        self.mode = mode
        self.store = _Store(mode, direct=direct)
        self.embedding_model = SimpleNamespace(name="fixture-hash")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def ingest_conversation_turn(self, *args, **kwargs):
        return SimpleNamespace(document={"chunk_count": 1, "extraction_status": "fixture"})


def _execute_run(mode: str, state=None):
    if state is None:
        state = {}
    state.update({
        "adapter_constructed": False,
        "adapter_closed": False,
        "direct_runtime_constructed": False,
        "direct_runtime_exited": False,
    })

    class Adapter:
        def __init__(self, *args, **kwargs):
            state["adapter_constructed"] = True
            self.runtime = _Runtime(mode)

        def ingest_turn(self, scope, turn):
            return None

        def _runtime(self, scope):
            return self.runtime

        def answer(self, scope, query):
            return SimpleNamespace(
                retrieved_context="missing" if mode == "retrieval_context" else "painting",
                generated_answer="unexpected" if mode == "generated_answer" else None,
            )

        def close(self):
            state["adapter_closed"] = True

    class DirectRuntime(_Runtime):
        def __init__(self, *args, **kwargs):
            state["direct_runtime_constructed"] = True
            super().__init__(mode, direct=True)

        def __exit__(self, exc_type, exc, traceback):
            state["direct_runtime_exited"] = True
            return False

    def compile_fixture(text, *, allow_env_extractor):
        if text == "sample":
            if mode == "raw":
                return _Batch(text + "-corrupt")
            return _Batch(text, bad_span=mode == "span")
        return _Batch(text)

    turn = m1.ConversationTurn("Eve", "I visited the museum.", "2026-09-03")
    loaded = SimpleNamespace(conversation=[turn, turn])
    with (
        patch.object(m1, "SAMPLES", {"case": "sample", "unicode": "東京"}),
        patch.object(m1, "compile_nl", compile_fixture),
        patch.object(m1, "load_locomo_cases", return_value=[loaded]),
        patch.object(m1, "SeamLocomoAdapter", Adapter),
        patch.object(m1, "SeamRuntime", DirectRuntime),
    ):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            result = m1.run(Path(directory))
    return result, state


def _control_probe(mode: str) -> int:
    state = {}
    try:
        _execute_run(mode, state)
    except AssertionError as exc:
        if str(exc) != EXPECTED_CONTROL_FAILURE[mode]:
            return 4
        if mode in {"raw", "span"}:
            expected = {
                "adapter_constructed": False,
                "adapter_closed": False,
                "direct_runtime_constructed": False,
                "direct_runtime_exited": False,
            }
        elif mode == "duplicate_raw":
            expected = {
                "adapter_constructed": True,
                "adapter_closed": True,
                "direct_runtime_constructed": True,
                "direct_runtime_exited": True,
            }
        else:
            expected = {
                "adapter_constructed": True,
                "adapter_closed": True,
                "direct_runtime_constructed": False,
                "direct_runtime_exited": False,
            }
        return 0 if state == expected else 5
    return 3


@pytest.mark.parametrize("mode", INVALID_CONTROLS)
@pytest.mark.parametrize("optimized", [False, True], ids=["normal", "optimized"])
def test_invalid_control_rejected_under_normal_and_optimized_python(mode, optimized):
    command = [sys.executable]
    if optimized:
        command.append("-O")
    command += [
        "-c",
        (
            "import runpy,sys; "
            f"ns=runpy.run_path({str(THIS_FILE)!r}); "
            "raise SystemExit(ns['_control_probe'](sys.argv[1]))"
        ),
        mode,
    ]
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    assert completed.returncode == 0, (
        f"{mode} was not rejected by its expected control and cleanup boundary under "
        f"{'optimized' if optimized else 'normal'} Python; "
        f"stdout={completed.stdout!r} stderr={completed.stderr!r}"
    )


def test_describe_uses_real_record_links_and_exact_span_text():
    described = m1.describe(_Batch("painting"))
    assert described["raw"][0]["content"] == "painting"
    assert described["claims"][0]["subject_label"] == "fixture-subject"
    assert described["span_bounds"] == [[0, 1]]
    assert described["span_text_exact"] is True


def test_valid_synthetic_run_preserves_sections_and_cleanup():
    result, state = _execute_run("valid")
    assert set(result) == {
        "compiler",
        "loader",
        "adapter",
        "distinct_source_reference_control",
        "persisted_unicode",
    }
    assert state == {
        "adapter_constructed": True,
        "adapter_closed": True,
        "direct_runtime_constructed": True,
        "direct_runtime_exited": True,
    }
    assert result["adapter"]["retrieval"] == {
        "query": "What does Alice enjoy?",
        "context": "painting",
        "generated_answer": None,
    }


def test_main_failure_returns_one_without_output_or_sensitive_detail(tmp_path, capsys):
    output = tmp_path / "must-not-exist.json"
    with (
        patch.object(sys, "argv", ["memory_formation_m1.py", "--output", str(output)]),
        patch.object(m1.subprocess, "check_output", side_effect=["fixture-revision\n", ""]),
        patch.object(m1, "run", side_effect=AssertionError("fixture-private-control")),
        patch.object(m1, "TemporaryDirectory", return_value=nullcontext(str(tmp_path))),
    ):
        assert m1.main() == 1
    captured = capsys.readouterr()
    assert "fixture-private-control" not in captured.err
    assert "M1 probe failed: AssertionError; inspect privately" in captured.err
    assert not output.exists()


def test_main_valid_result_keeps_public_schema_and_offline_markers(tmp_path):
    output = tmp_path / "observations.json"
    with (
        patch.object(sys, "argv", ["memory_formation_m1.py", "--output", str(output)]),
        patch.object(m1.subprocess, "check_output", side_effect=["fixture-revision\n", ""]),
        patch.object(m1, "run", return_value={"compiler": {}, "loader": {}, "adapter": {}}),
        patch.object(m1, "TemporaryDirectory", return_value=nullcontext(str(tmp_path))),
    ):
        assert m1.main() == 0
    payload = json.loads(output.read_text())
    assert payload["schema"] == "seam-m1-formation-observations/v1"
    assert payload["revision"] == "fixture-revision"
    assert payload["synthetic_inputs_only"] is True
    assert payload["quality_benchmark"] is False
    assert payload["provider_calls"] == 0
    assert payload["website_publication"] is False
