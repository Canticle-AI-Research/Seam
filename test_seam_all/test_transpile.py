from __future__ import annotations

from seam_runtime.mirl import MIRLRecord
from seam_runtime.transpile import transpile_python


def _make_record(id: str) -> MIRLRecord:
    return MIRLRecord.from_dict({
        "id": id,
        "kind": "CLM",
        "ns": "test.ns",
        "scope": "thread",
        "created_at": "2026-05-18T00:00:00Z",
        "updated_at": "2026-05-18T00:00:00Z",
        "t0": "2026-05-18T00:00:00Z",
        "source_ref": "test://input",
        "source_kind": "nl",
        "text": "test record",
        "attrs": {},
        "prov": [],
        "evidence": [],
    })


class TestTranspilePython:
    def test_produces_valid_python_imports(self):
        r = _make_record("id:1")
        artifact = transpile_python([r])
        assert artifact.target == "python"
        assert "from seam import SeamRuntime" in artifact.body
        assert "runtime = SeamRuntime()" in artifact.body

    def test_includes_record_ids(self):
        r1 = _make_record("id:1")
        r2 = _make_record("id:2")
        artifact = transpile_python([r1, r2])
        assert "id:1" in artifact.body
        assert "id:2" in artifact.body

    def test_empty_records_produces_empty_list(self):
        artifact = transpile_python([])
        assert "record_ids = []" in artifact.body

    def test_error_on_invalid_target_is_ignored(self):
        # transpile_python ignores target param — hardcoded to "python"
        r = _make_record("id:1")
        artifact = transpile_python([r])
        assert artifact.target == "python"
