"""Durable, tamper-evident experiment records for the H2 improvement loop.

The H2 proposal tables answer *what may be promoted*.  This ledger answers the
earlier question: *what was tried, against which fixed evaluator, and what
happened?*  Definitions are immutable and events are append-only.  Each event
hash commits to the previous event hash, so a completed experiment retains its
baseline, rejected candidates, proposal link, and terminal outcome as one
verifiable chain.

Only bounded structured evidence belongs here.  Raw prompts, source text,
answers, provider payloads, credentials, and hidden reasoning are deliberately
outside this schema.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from collections.abc import Mapping
from typing import Final

EXPERIMENT_SCHEMA_VERSION: Final = 1
EXPERIMENT_CONTRACT_VERSION: Final = "improvement-experiment/1"
EXPERIMENT_METHOD: Final = "bounded-autoresearch/1"

EXPERIMENT_EVENT_KINDS: Final = frozenset(
    {
        "started",
        "baseline_evaluated",
        "candidate_evaluated",
        "proposal_created",
        "completed",
        "failed",
    }
)
TERMINAL_EXPERIMENT_EVENT_KINDS: Final = frozenset({"completed", "failed"})

_SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_MAX_JSON_BYTES: Final = 4 * 1024 * 1024
_FORBIDDEN_PAYLOAD_KEYS: Final = frozenset(
    {
        "answer",
        "api_key",
        "content",
        "dsn",
        "hidden_reasoning",
        "password",
        "prompt",
        "provider_payload",
        "query",
        "raw",
        "secret",
        "source_text",
    }
)

_EXPERIMENT_COLUMNS: Final = (
    ("experiment_id", "TEXT", 0, 1),
    ("created_at", "TEXT", 1, 0),
    ("contract_version", "TEXT", 1, 0),
    ("lane", "TEXT", 1, 0),
    ("method", "TEXT", 1, 0),
    ("evaluator_sha256", "TEXT", 1, 0),
    ("dataset_sha256", "TEXT", 1, 0),
    ("baseline_sha256", "TEXT", 1, 0),
    ("definition_json", "TEXT", 1, 0),
    ("definition_sha256", "TEXT", 1, 0),
)
_EVENT_COLUMNS: Final = (
    ("event_id", "INTEGER", 0, 1),
    ("experiment_id", "TEXT", 1, 0),
    ("sequence", "INTEGER", 1, 0),
    ("ts", "TEXT", 1, 0),
    ("event_kind", "TEXT", 1, 0),
    ("payload_json", "TEXT", 1, 0),
    ("previous_event_sha256", "TEXT", 0, 0),
    ("event_sha256", "TEXT", 1, 0),
)
_APPEND_ONLY_TRIGGERS: Final = {
    "improvement_experiment_no_update": (
        "improvement_experiment",
        "before update",
    ),
    "improvement_experiment_no_delete": (
        "improvement_experiment",
        "before delete",
    ),
    "improvement_experiment_event_no_update": (
        "improvement_experiment_event",
        "before update",
    ),
    "improvement_experiment_event_no_delete": (
        "improvement_experiment_event",
        "before delete",
    ),
}


def init_improvement_experiment_schema(connection) -> None:
    """Install the version-one immutable-definition and event-chain tables."""

    connection.execute(
        "create table if not exists improvement_experiment ("
        "experiment_id text primary key, "
        "created_at text not null, "
        "contract_version text not null, "
        "lane text not null, "
        "method text not null, "
        "evaluator_sha256 text not null check(length(evaluator_sha256) = 64), "
        "dataset_sha256 text not null check(length(dataset_sha256) = 64), "
        "baseline_sha256 text not null check(length(baseline_sha256) = 64), "
        "definition_json text not null, "
        "definition_sha256 text not null check(length(definition_sha256) = 64)"
        ")"
    )
    connection.execute(
        "create table if not exists improvement_experiment_event ("
        "event_id integer primary key autoincrement, "
        "experiment_id text not null, "
        "sequence integer not null check(sequence >= 1), "
        "ts text not null, "
        "event_kind text not null check(event_kind in ("
        "'started','baseline_evaluated','candidate_evaluated',"
        "'proposal_created','completed','failed')), "
        "payload_json text not null, "
        "previous_event_sha256 text, "
        "event_sha256 text not null check(length(event_sha256) = 64), "
        "unique(experiment_id, sequence), "
        "foreign key (experiment_id) references improvement_experiment(experiment_id) "
        "on delete restrict"
        ")"
    )
    connection.execute(
        "create index if not exists idx_improvement_experiment_created on improvement_experiment (created_at)"
    )
    connection.execute("create index if not exists idx_improvement_experiment_lane on improvement_experiment (lane)")
    connection.execute(
        "create index if not exists idx_improvement_experiment_event_experiment "
        "on improvement_experiment_event (experiment_id, sequence)"
    )
    connection.execute(
        """
        create trigger if not exists improvement_experiment_no_update
        before update on improvement_experiment begin
            select raise(abort, 'improvement_experiment is append-only');
        end
        """
    )
    connection.execute(
        """
        create trigger if not exists improvement_experiment_no_delete
        before delete on improvement_experiment begin
            select raise(abort, 'improvement_experiment is append-only');
        end
        """
    )
    connection.execute(
        """
        create trigger if not exists improvement_experiment_event_no_update
        before update on improvement_experiment_event begin
            select raise(abort, 'improvement_experiment_event is append-only');
        end
        """
    )
    connection.execute(
        """
        create trigger if not exists improvement_experiment_event_no_delete
        before delete on improvement_experiment_event begin
            select raise(abort, 'improvement_experiment_event is append-only');
        end
        """
    )
    errors = improvement_experiment_schema_errors(connection)
    if errors:
        raise RuntimeError(
            "improvement experiment schema is invalid: " + ", ".join(errors)
        )


def improvement_experiment_schema_errors(connection) -> tuple[str, ...]:
    """Return content-free structural errors for the durable ledger schema."""

    errors: list[str] = []

    def columns(table: str) -> tuple[tuple[str, str, int, int], ...]:
        return tuple(
            (str(row[1]), str(row[2]).upper(), int(row[3]), int(row[5]))
            for row in connection.execute(f"pragma table_info({table})").fetchall()
        )

    if columns("improvement_experiment") != _EXPERIMENT_COLUMNS:
        errors.append("definition columns")
    if columns("improvement_experiment_event") != _EVENT_COLUMNS:
        errors.append("event columns")

    foreign_keys = {
        (str(row[2]), str(row[3]), str(row[4]), str(row[6]).upper())
        for row in connection.execute(
            "pragma foreign_key_list(improvement_experiment_event)"
        ).fetchall()
    }
    if foreign_keys != {
        (
            "improvement_experiment",
            "experiment_id",
            "experiment_id",
            "RESTRICT",
        )
    }:
        errors.append("event foreign key")

    unique_event_keys: set[tuple[str, ...]] = set()
    for row in connection.execute(
        "pragma index_list(improvement_experiment_event)"
    ).fetchall():
        if int(row[2]) != 1:
            continue
        index_name = str(row[1])
        unique_event_keys.add(
            tuple(
                str(info[2])
                for info in connection.execute(
                    "select * from pragma_index_info(?) order by seqno",
                    (index_name,),
                ).fetchall()
            )
        )
    if ("experiment_id", "sequence") not in unique_event_keys:
        errors.append("event sequence uniqueness")

    expected_indexes = {
        "idx_improvement_experiment_created": ("created_at",),
        "idx_improvement_experiment_lane": ("lane",),
        "idx_improvement_experiment_event_experiment": (
            "experiment_id",
            "sequence",
        ),
    }
    for index_name, expected_columns in expected_indexes.items():
        actual_columns = tuple(
            str(row[2])
            for row in connection.execute(
                "select * from pragma_index_info(?) order by seqno",
                (index_name,),
            ).fetchall()
        )
        if actual_columns != expected_columns:
            errors.append(f"index {index_name}")

    triggers = {
        str(row[0]): (str(row[1]), " ".join(str(row[2] or "").lower().split()))
        for row in connection.execute(
            "select name, tbl_name, sql from sqlite_master "
            "where type = 'trigger' and name like 'improvement_experiment%'"
        ).fetchall()
    }
    for trigger_name, (table_name, operation) in _APPEND_ONLY_TRIGGERS.items():
        stored_table, sql = triggers.get(trigger_name, ("", ""))
        if (
            stored_table != table_name
            or operation not in sql
            or "raise(abort" not in sql
            or "append-only" not in sql
        ):
            errors.append(f"trigger {trigger_name}")

    definition_sql_row = connection.execute(
        "select sql from sqlite_master "
        "where type = 'table' and name = 'improvement_experiment'"
    ).fetchone()
    definition_sql = " ".join(
        str(definition_sql_row[0] if definition_sql_row else "").lower().split()
    )
    for field_name in (
        "evaluator_sha256",
        "dataset_sha256",
        "baseline_sha256",
        "definition_sha256",
    ):
        if f"check(length({field_name}) = 64)" not in definition_sql:
            errors.append(f"digest check {field_name}")

    event_sql_row = connection.execute(
        "select sql from sqlite_master "
        "where type = 'table' and name = 'improvement_experiment_event'"
    ).fetchone()
    event_sql = " ".join(
        str(event_sql_row[0] if event_sql_row else "").lower().split()
    )
    if "check(sequence >= 1)" not in event_sql:
        errors.append("event sequence check")
    if "check(event_kind in" not in event_sql or any(
        f"'{kind}'" not in event_sql for kind in EXPERIMENT_EVENT_KINDS
    ):
        errors.append("event kind check")
    if "check(length(event_sha256) = 64)" not in event_sql:
        errors.append("event digest check")
    return tuple(errors)


def canonical_json(value: object) -> str:
    """Return the one JSON representation used by experiment fingerprints."""

    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def json_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def experiment_definition_sha256(
    *,
    experiment_id: str,
    created_at: str,
    contract_version: str,
    lane: str,
    method: str,
    evaluator_sha256: str,
    dataset_sha256: str,
    baseline_sha256: str,
    definition: Mapping[str, object],
) -> str:
    """Commit every immutable definition column to one content hash."""

    return json_sha256(
        {
            "baseline_sha256": baseline_sha256,
            "contract_version": contract_version,
            "created_at": created_at,
            "dataset_sha256": dataset_sha256,
            "definition": dict(definition),
            "evaluator_sha256": evaluator_sha256,
            "experiment_id": experiment_id,
            "lane": lane,
            "method": method,
        }
    )


def validate_sha256(value: str, *, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def validate_experiment_id(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("experiment_id is required")
    if len(value) > 160:
        raise ValueError("experiment_id exceeds 160 characters")
    if any(ord(char) < 32 for char in value):
        raise ValueError("experiment_id contains control characters")
    return value


def validate_structured_payload(
    payload: Mapping[str, object],
    *,
    field_name: str,
) -> dict[str, object]:
    """Reject unbounded/non-JSON evidence and raw-content-shaped fields."""

    if not isinstance(payload, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    normalized = _validate_json_value(dict(payload), path=field_name)
    assert isinstance(normalized, dict)
    encoded = canonical_json(normalized).encode("utf-8")
    if len(encoded) > _MAX_JSON_BYTES:
        raise ValueError(f"{field_name} exceeds {_MAX_JSON_BYTES} bytes")
    return normalized


def event_sha256(
    *,
    experiment_id: str,
    sequence: int,
    ts: str,
    event_kind: str,
    payload: Mapping[str, object],
    previous_event_sha256: str | None,
) -> str:
    material = {
        "event_kind": event_kind,
        "experiment_id": experiment_id,
        "payload": dict(payload),
        "previous_event_sha256": previous_event_sha256,
        "sequence": sequence,
        "ts": ts,
    }
    return json_sha256(material)


def experiment_row(row: sqlite3.Row) -> dict[str, object]:
    return {
        "experiment_id": str(row["experiment_id"]),
        "created_at": str(row["created_at"]),
        "contract_version": str(row["contract_version"]),
        "lane": str(row["lane"]),
        "method": str(row["method"]),
        "evaluator_sha256": str(row["evaluator_sha256"]),
        "dataset_sha256": str(row["dataset_sha256"]),
        "baseline_sha256": str(row["baseline_sha256"]),
        "definition": json.loads(row["definition_json"]),
        "definition_sha256": str(row["definition_sha256"]),
    }


def experiment_event_row(row: sqlite3.Row) -> dict[str, object]:
    return {
        "event_id": int(row["event_id"]),
        "experiment_id": str(row["experiment_id"]),
        "sequence": int(row["sequence"]),
        "ts": str(row["ts"]),
        "event_kind": str(row["event_kind"]),
        "payload": json.loads(row["payload_json"]),
        "previous_event_sha256": row["previous_event_sha256"],
        "event_sha256": str(row["event_sha256"]),
    }


def _validate_json_value(value: object, *, path: str) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} contains a non-finite number")
        return value
    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        for key, child in value.items():
            if not isinstance(key, str) or not key:
                raise ValueError(f"{path} contains a blank or non-string key")
            if key.casefold() in _FORBIDDEN_PAYLOAD_KEYS:
                raise ValueError(f"{path} contains forbidden raw-content field {key!r}")
            normalized[key] = _validate_json_value(child, path=f"{path}.{key}")
        return normalized
    if isinstance(value, (list, tuple)):
        return [_validate_json_value(child, path=f"{path}[{index}]") for index, child in enumerate(value)]
    raise TypeError(f"{path} contains non-JSON value {type(value).__name__}")
