"""W4 — record_kinds symbol-keyed stats contract."""


from seam_runtime.mirl import SYMBOL_FOR_KIND, RecordKind

CANONICAL_TABLE = {
    RecordKind.ENT: "@",
    RecordKind.CLM: "#",
    RecordKind.EVT: "!",
    RecordKind.REL: ">",
    RecordKind.STA: "~",
    RecordKind.PROV: "^",
    RecordKind.RAW: "%",
    RecordKind.SYM: "=",
    RecordKind.SPAN: "§",
    RecordKind.PACK: "◇",
}


def test_symbol_for_kind_covers_all_members():
    """SYMBOL_FOR_KIND has an entry for EVERY member of RecordKind."""
    for member in RecordKind:
        assert member in SYMBOL_FOR_KIND, f"RecordKind.{member.name} missing from SYMBOL_FOR_KIND"


def test_symbol_mapping_matches_canonical():
    """The mapping matches the canonical table for known entries."""
    for kind, symbol in CANONICAL_TABLE.items():
        assert SYMBOL_FOR_KIND[kind] == symbol, f"{kind.name} expected {symbol!r}, got {SYMBOL_FOR_KIND[kind]!r}"


def test_stats_record_kinds_uses_symbol_keys(tmp_path):
    """After persisting records, store.get_stats()['record_kinds'] uses symbol keys."""
    from seam_runtime.mirl import RecordKind
    from seam_runtime.storage import SQLiteStore

    db_path = tmp_path / "test.db"
    store = SQLiteStore(str(db_path))

    # Insert records directly into ir_records to bypass validation
    now = "2026-05-19T00:00:00Z"
    conn = store._connect()
    conn.execute(
        "insert into ir_records (id, kind, ns, scope, status, conf, created_at, updated_at, payload_json) "
        "values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("ent-1", RecordKind.ENT.value, "local.default", "project", "asserted", 1.0, now, now, "{}"),
    )
    conn.execute(
        "insert into ir_records (id, kind, ns, scope, status, conf, created_at, updated_at, payload_json) "
        "values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("clm-1", RecordKind.CLM.value, "local.default", "project", "asserted", 1.0, now, now, "{}"),
    )
    conn.execute(
        "insert into ir_records (id, kind, ns, scope, status, conf, created_at, updated_at, payload_json) "
        "values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("sta-1", RecordKind.STA.value, "local.default", "project", "asserted", 1.0, now, now, "{}"),
    )
    conn.commit()
    conn.close()

    stats = store.get_stats()
    rk = stats["record_kinds"]
    assert rk == {"@": 1, "#": 1, "~": 1}, f"expected symbol keys, got {rk}"
