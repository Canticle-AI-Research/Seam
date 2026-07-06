from __future__ import annotations

import pytest

from seam_runtime.vector_adapters import PgVectorAdapter, _validate_table_name


class TestTableNameValidation:
    def test_valid_table_names_pass(self):
        assert _validate_table_name("seam_vector_index") is None
        assert _validate_table_name("abc123") is None
        assert _validate_table_name("_leading_underscore") is None

    def test_semicolon_rejected(self):
        with pytest.raises(ValueError, match="Unsafe"):
            _validate_table_name("users; DROP TABLE x")

    def test_spaces_rejected(self):
        with pytest.raises(ValueError, match="Unsafe"):
            _validate_table_name("foo bar")

    def test_adapter_mutated_table_name_rejected_by_ensure_schema(self):
        adapter = PgVectorAdapter(dsn="postgresql:///nonexistent", model=None)  # type: ignore[arg-type]
        adapter.table_name = "users; DROP TABLE x"
        with pytest.raises(ValueError, match="Unsafe"):
            adapter.ensure_schema()
