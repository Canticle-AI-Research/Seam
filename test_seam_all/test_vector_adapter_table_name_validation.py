from __future__ import annotations

import pytest

from seam_runtime.vector_adapters import PgVectorAdapter, _validate_table_name


class TestTableNameValidation:
    def test_valid_table_names_pass(self):
        """Test that valid table names pass validation."""
        assert _validate_table_name("seam_vector_index") is None
        assert _validate_table_name("abc123") is None
        assert _validate_table_name("_leading_underscore") is None
        assert _validate_table_name("ABC123") is None
        assert _validate_table_name("Table_Name_123") is None

    def test_semicolon_rejected(self):
        """Test that semicolons are rejected to prevent SQL injection."""
        with pytest.raises(ValueError, match="Invalid input"):
            _validate_table_name("users; DROP TABLE x")

    def test_spaces_rejected(self):
        """Test that spaces are rejected."""
        with pytest.raises(ValueError, match="Invalid input"):
            _validate_table_name("foo bar")

    def test_special_characters_rejected(self):
        """Test that special characters are rejected."""
        with pytest.raises(ValueError, match="Invalid input"):
            _validate_table_name("table-name")
        with pytest.raises(ValueError, match="Invalid input"):
            _validate_table_name("table.name")
        with pytest.raises(ValueError, match="Invalid input"):
            _validate_table_name("table@name")
        with pytest.raises(ValueError, match="Invalid input"):
            _validate_table_name("table$name")

    def test_empty_string_rejected(self):
        """Test that empty strings are rejected."""
        with pytest.raises(ValueError, match="Invalid input"):
            _validate_table_name("")

    def test_sql_keywords_with_injection_rejected(self):
        """Test that SQL injection attempts are rejected."""
        with pytest.raises(ValueError, match="Invalid input"):
            _validate_table_name("users' OR '1'='1")
        with pytest.raises(ValueError, match="Invalid input"):
            _validate_table_name("users--")
        with pytest.raises(ValueError, match="Invalid input"):
            _validate_table_name("users/*comment*/")

    def test_adapter_initialization_rejects_invalid_table_name(self):
        """Test that invalid table names are rejected during adapter initialization."""
        with pytest.raises(ValueError, match="Invalid input"):
            PgVectorAdapter(dsn="postgresql:///nonexistent", model=None, table_name="users; DROP TABLE x")  # type: ignore[arg-type]

    def test_adapter_mutated_table_name_rejected_by_ensure_schema(self):
        """Test that table name validation is enforced in ensure_schema."""
        adapter = PgVectorAdapter(dsn="postgresql:///nonexistent", model=None)  # type: ignore[arg-type]
        adapter.table_name = "users; DROP TABLE x"
        with pytest.raises(ValueError, match="Invalid input"):
            adapter.ensure_schema()

    def test_adapter_mutated_table_name_rejected_by_index_records(self):
        """Test that table name validation is enforced in index_records."""
        adapter = PgVectorAdapter(dsn="postgresql:///nonexistent", model=None)  # type: ignore[arg-type]
        adapter.table_name = "users; DROP TABLE x"
        with pytest.raises(ValueError, match="Invalid input"):
            adapter.index_records([])

    def test_adapter_mutated_table_name_rejected_by_search(self):
        """Test that table name validation is enforced in search."""
        adapter = PgVectorAdapter(dsn="postgresql:///nonexistent", model=None)  # type: ignore[arg-type]
        adapter.table_name = "users; DROP TABLE x"
        with pytest.raises(ValueError, match="Invalid input"):
            adapter.search("test query")

    def test_adapter_mutated_table_name_rejected_by_stale_records(self):
        """Test that table name validation is enforced in stale_records."""
        adapter = PgVectorAdapter(dsn="postgresql:///nonexistent", model=None)  # type: ignore[arg-type]
        adapter.table_name = "users; DROP TABLE x"
        with pytest.raises(ValueError, match="Invalid input"):
            adapter.stale_records([])

    def test_adapter_mutated_table_name_rejected_by_orphan_records(self):
        """Test that table name validation is enforced in orphan_records."""
        adapter = PgVectorAdapter(dsn="postgresql:///nonexistent", model=None)  # type: ignore[arg-type]
        adapter.table_name = "users; DROP TABLE x"
        with pytest.raises(ValueError, match="Invalid input"):
            adapter.orphan_records()

    def test_adapter_mutated_table_name_rejected_by_vector_count(self):
        """Test that table name validation is enforced in vector_count."""
        adapter = PgVectorAdapter(dsn="postgresql:///nonexistent", model=None)  # type: ignore[arg-type]
        adapter.table_name = "users; DROP TABLE x"
        with pytest.raises(ValueError, match="Invalid input"):
            adapter.vector_count()
