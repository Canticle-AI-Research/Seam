"""Track S S5: pgvector search performs no DDL or schema-ensure operation.

Audit finding F14. ``PgVectorAdapter.search`` called ``ensure_schema()`` on
every query, so each read ran ``create extension``, ``create table``, four
``information_schema`` probes with conditional ALTERs, two ``create index``
statements, a primary-key migration, and an HNSW index build -- on a table that
may be shared with other embedding models and other runs.

These cases are provider-free: they drive the adapter against a recording fake
connection, so the clause is enforced in every lane rather than only where a
live pgvector service is available.
"""

from __future__ import annotations

import re

import pytest

from seam_runtime.mirl import MIRLRecord, RecordKind
from seam_runtime.models import HashEmbeddingModel
from seam_runtime.vector_adapters import PgVectorAdapter

_DDL = re.compile(
    r"\b(create|alter|drop|reindex|truncate|grant|revoke|comment\s+on)\b",
    re.IGNORECASE,
)
# The single exception is a session GUC assignment, which changes no schema.
_ALLOWED = re.compile(r"^\s*select\s+set_config\(", re.IGNORECASE)


def _is_ddl(statement: str) -> bool:
    if _ALLOWED.match(statement):
        return False
    return bool(_DDL.search(statement))


class _FakeCursor:
    def __init__(self, owner: "_FakeConnection") -> None:
        self._owner = owner
        self._rows: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, statement, params=None):
        self._owner.statements.append(statement)
        if self._owner.undefined_table and "from " in statement.lower():
            raise _UndefinedTable()
        lowered = statement.lower()
        if "select record_id" in lowered:
            self._rows = list(self._owner.search_rows)
        elif "information_schema" in lowered or "pg_constraint" in lowered:
            self._rows = [("present",)]
        else:
            self._rows = []
        return self

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _UndefinedTable(Exception):
    sqlstate = "42P01"


class _FakeConnection:
    def __init__(self, owner: "_Recorder") -> None:
        self._owner = owner

    @property
    def statements(self):
        return self._owner.statements

    @property
    def search_rows(self):
        return self._owner.search_rows

    @property
    def undefined_table(self):
        return self._owner.undefined_table

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return _FakeCursor(self)

    def commit(self):
        self._owner.commits += 1


class _Recorder:
    def __init__(self, *, search_rows=(), undefined_table: bool = False) -> None:
        self.statements: list[str] = []
        self.search_rows = list(search_rows)
        self.undefined_table = undefined_table
        self.commits = 0
        self.connections = 0

    def connect(self):
        self.connections += 1
        return _FakeConnection(self)

    def ddl(self) -> list[str]:
        return [statement for statement in self.statements if _is_ddl(statement)]


def _adapter(recorder: _Recorder) -> PgVectorAdapter:
    adapter = PgVectorAdapter(
        dsn="postgresql://unused/unused",
        model=HashEmbeddingModel(name="probe", dimension=8),
        table_name="seam_vector_probe",
    )
    adapter._connect = recorder.connect
    return adapter


def _record(record_id: str = "clm:one") -> MIRLRecord:
    return MIRLRecord(
        id=record_id,
        kind=RecordKind.CLM,
        ns="work",
        scope="thread",
        attrs={"subject": "ent:a", "predicate": "notes", "object": "a compiler note"},
    )


def test_search_issues_no_ddl(tmp_path) -> None:
    recorder = _Recorder(search_rows=[("clm:one", 0.9)])
    adapter = _adapter(recorder)

    hits = adapter.search("compiler", limit=5)

    assert hits == {"clm:one": 0.9}
    assert recorder.ddl() == [], f"search issued DDL: {recorder.ddl()}"
    assert not any(
        "information_schema" in statement.lower() for statement in recorder.statements
    ), "search probed the schema catalog"


def test_repeated_search_never_ensures_schema() -> None:
    recorder = _Recorder(search_rows=[("clm:one", 0.5)])
    adapter = _adapter(recorder)

    for _ in range(5):
        adapter.search("compiler", limit=3)

    assert recorder.ddl() == []
    assert recorder.commits == 0, "a read committed a transaction"


def test_search_against_a_missing_table_returns_empty_without_creating_it() -> None:
    recorder = _Recorder(undefined_table=True)
    adapter = _adapter(recorder)

    assert adapter.search("compiler", limit=5) == {}
    assert recorder.ddl() == [], "search created the missing table"


def test_search_still_raises_on_a_real_failure() -> None:
    class _Broken(_Recorder):
        def connect(self):
            raise RuntimeError("connection refused")

    adapter = _adapter(_Broken())
    with pytest.raises(RuntimeError, match="connection refused"):
        adapter.search("compiler", limit=5)


def test_ensure_schema_runs_once_per_adapter() -> None:
    recorder = _Recorder()
    adapter = _adapter(recorder)

    adapter.ensure_schema()
    first = len(recorder.ddl())
    assert first > 0, "the fixture never exercised the schema path"

    for _ in range(3):
        adapter.ensure_schema()
    assert len(recorder.ddl()) == first, "ensure_schema repeated its DDL"

    adapter.ensure_schema(force=True)
    assert len(recorder.ddl()) > first, "force did not re-run the schema work"


def test_index_records_still_ensures_schema_once() -> None:
    recorder = _Recorder()
    adapter = _adapter(recorder)

    adapter.index_records([_record("clm:one")])
    after_first = len(recorder.ddl())
    assert after_first > 0, "the first write did not establish the schema"

    adapter.index_records([_record("clm:two")])
    assert len(recorder.ddl()) == after_first, "a later write re-ran the schema work"
