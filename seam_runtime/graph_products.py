from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from typing import Iterable, Sequence

from .migrations import execute_script
from .mirl import utc_now

GRAPH_PRODUCT_SCHEMA_VERSION = 1
GRAPH_PRODUCT_ALGORITHM_VERSION = "graph-products/1"
ASSERTABLE_TRUST_STATES = frozenset({"supported", "verified"})
PRODUCT_KINDS = frozenset(
    {"entity_summary", "community_summary", "observation"}
)
_SPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class GraphProductFact:
    """One already-resolved graph fact offered to the derived-product core.

    The caller remains responsible for resolving canonical graph identities.
    This module independently enforces the product boundary: only current,
    supported/verified facts in the requested namespace and scope, with exact
    MIRL record and episode references, may contribute human-readable text.
    """

    ns: str
    scope: str
    record_id: str
    episode_ids: tuple[str, ...]
    subject_id: str
    subject_label: str
    predicate: str
    object_id: str | None
    object_label: str
    trust_state: str
    current: bool


@dataclass(frozen=True, slots=True)
class _Sentence:
    text: str
    record_ids: tuple[str, ...]
    episode_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Product:
    kind: str
    stable_key: str
    subject_id: str | None
    payload: dict[str, object]
    sentences: tuple[_Sentence, ...]


def init_graph_products(connection: sqlite3.Connection) -> None:
    """Create the append-only, rebuildable G4 derived-product plane."""

    execute_script(
        connection,
        """
        create table if not exists graph_product_build (
            build_seq integer primary key autoincrement,
            build_id text not null unique,
            ns text not null,
            scope text not null,
            algorithm_version text not null,
            source_fingerprint text not null,
            accepted_fact_count integer not null,
            rejected_fact_count integer not null,
            created_at text not null,
            schema_version integer not null default 1
        );
        create table if not exists graph_product (
            product_seq integer primary key autoincrement,
            product_id text not null unique,
            build_id text not null,
            ns text not null,
            scope text not null,
            kind text not null check (
                kind in ('entity_summary', 'community_summary', 'observation')
            ),
            stable_key text not null,
            subject_id text,
            version integer not null check (version >= 1),
            algorithm_version text not null,
            source_fingerprint text not null,
            payload_json text not null,
            created_at text not null,
            schema_version integer not null default 1,
            foreign key (build_id) references graph_product_build(build_id),
            unique (build_id, stable_key)
        );
        create table if not exists graph_product_sentence (
            sentence_seq integer primary key autoincrement,
            sentence_id text not null unique,
            product_id text not null,
            ordinal integer not null check (ordinal >= 1),
            sentence_text text not null check (length(trim(sentence_text)) > 0),
            supporting_record_ids_json text not null,
            supporting_episode_ids_json text not null,
            foreign key (product_id) references graph_product(product_id),
            unique (product_id, ordinal)
        );
        create index if not exists idx_graph_product_build_boundary
            on graph_product_build (ns, scope, build_seq);
        create index if not exists idx_graph_product_boundary_kind
            on graph_product (ns, scope, kind, subject_id);
        create index if not exists idx_graph_product_stable_version
            on graph_product (ns, scope, stable_key, version);
        create index if not exists idx_graph_product_sentence_product
            on graph_product_sentence (product_id, ordinal);
        create trigger if not exists graph_product_build_no_update
        before update on graph_product_build begin
            select raise(abort, 'graph_product_build is append-only');
        end;
        create trigger if not exists graph_product_build_no_delete
        before delete on graph_product_build begin
            select raise(abort, 'graph_product_build is append-only');
        end;
        create trigger if not exists graph_product_no_update
        before update on graph_product begin
            select raise(abort, 'graph_product is append-only');
        end;
        create trigger if not exists graph_product_no_delete
        before delete on graph_product begin
            select raise(abort, 'graph_product is append-only');
        end;
        create trigger if not exists graph_product_sentence_no_update
        before update on graph_product_sentence begin
            select raise(abort, 'graph_product_sentence is append-only');
        end;
        create trigger if not exists graph_product_sentence_no_delete
        before delete on graph_product_sentence begin
            select raise(abort, 'graph_product_sentence is append-only');
        end;
        """
    )


def update_graph_products(
    connection: sqlite3.Connection,
    *,
    namespace: str,
    scope: str,
    facts: Iterable[GraphProductFact],
    min_observation_episodes: int = 2,
    max_facts: int = 10_000,
    max_sentences_per_product: int = 64,
    created_at: str | None = None,
) -> dict[str, object]:
    """Append one complete boundary snapshot, or reuse an identical snapshot.

    Rejected facts never influence product text. A new empty build is still
    appended when formerly eligible facts become ineligible, so current reads
    cannot accidentally retain stale derived products.
    """

    ns = _required(namespace, "namespace")
    product_scope = _required(scope, "scope")
    if min_observation_episodes < 2:
        raise ValueError("min_observation_episodes must be at least 2")
    if max_facts < 1:
        raise ValueError("max_facts must be positive")
    if max_sentences_per_product < 1:
        raise ValueError("max_sentences_per_product must be positive")

    offered = list(facts)
    if len(offered) > max_facts:
        raise ValueError(f"graph product rebuild exceeds max_facts={max_facts}")
    eligible = [
        normalized
        for fact in offered
        if (
            normalized := _eligible_fact(
                fact, namespace=ns, scope=product_scope
            )
        )
        is not None
    ]
    accepted = sorted(set(eligible), key=_fact_sort_key)
    source_fingerprint = _fingerprint(
        [_fact_payload(fact) for fact in accepted]
    )
    init_graph_products(connection)
    latest = connection.execute(
        "select build_id, source_fingerprint from graph_product_build "
        "where ns = ? and scope = ? and algorithm_version = ? "
        "order by build_seq desc limit 1",
        (ns, product_scope, GRAPH_PRODUCT_ALGORITHM_VERSION),
    ).fetchone()
    if latest is not None and str(latest[1]) == source_fingerprint:
        return _build_payload(connection, str(latest[0]), reused=True)

    timestamp = str(created_at or utc_now())
    build_material = {
        "algorithm_version": GRAPH_PRODUCT_ALGORITHM_VERSION,
        "ns": ns,
        "predecessor_build_id": str(latest[0]) if latest is not None else None,
        "scope": product_scope,
        "source_fingerprint": source_fingerprint,
    }
    build_id = f"gpb:{_fingerprint(build_material)[:24]}"
    products = _derive_products(
        accepted,
        min_observation_episodes=min_observation_episodes,
        max_sentences=max_sentences_per_product,
    )
    connection.execute("savepoint graph_products_update")
    try:
        connection.execute(
            "insert into graph_product_build "
            "(build_id, ns, scope, algorithm_version, source_fingerprint, "
            "accepted_fact_count, rejected_fact_count, created_at, schema_version) "
            "values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                build_id,
                ns,
                product_scope,
                GRAPH_PRODUCT_ALGORITHM_VERSION,
                source_fingerprint,
                len(accepted),
                len(offered) - len(eligible),
                timestamp,
                GRAPH_PRODUCT_SCHEMA_VERSION,
            ),
        )
        for product in products:
            product_fingerprint = _product_fingerprint(product)
            previous = connection.execute(
                "select version, source_fingerprint from graph_product "
                "where ns = ? and scope = ? and stable_key = ? "
                "order by product_seq desc limit 1",
                (ns, product_scope, product.stable_key),
            ).fetchone()
            version = 1
            if previous is not None:
                version = int(previous[0])
                if str(previous[1]) != product_fingerprint:
                    version += 1
            product_id = (
                f"gp:{_fingerprint([build_id, product.stable_key, version])[:24]}"
            )
            connection.execute(
                "insert into graph_product "
                "(product_id, build_id, ns, scope, kind, stable_key, "
                "subject_id, version, algorithm_version, source_fingerprint, "
                "payload_json, created_at, schema_version) "
                "values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    product_id,
                    build_id,
                    ns,
                    product_scope,
                    product.kind,
                    product.stable_key,
                    product.subject_id,
                    version,
                    GRAPH_PRODUCT_ALGORITHM_VERSION,
                    product_fingerprint,
                    _canonical_json(product.payload),
                    timestamp,
                    GRAPH_PRODUCT_SCHEMA_VERSION,
                ),
            )
            for ordinal, sentence in enumerate(product.sentences, 1):
                _validate_sentence(sentence)
                sentence_id = (
                    f"gps:{_fingerprint([product_id, ordinal])[:24]}"
                )
                connection.execute(
                    "insert into graph_product_sentence "
                    "(sentence_id, product_id, ordinal, sentence_text, "
                    "supporting_record_ids_json, supporting_episode_ids_json) "
                    "values (?, ?, ?, ?, ?, ?)",
                    (
                        sentence_id,
                        product_id,
                        ordinal,
                        sentence.text,
                        _canonical_json(sentence.record_ids),
                        _canonical_json(sentence.episode_ids),
                    ),
                )
        connection.execute("release savepoint graph_products_update")
    except Exception:
        connection.execute("rollback to savepoint graph_products_update")
        connection.execute("release savepoint graph_products_update")
        raise
    return _build_payload(connection, build_id, reused=False)


def rebuild_graph_products(
    connection: sqlite3.Connection,
    *,
    namespace: str,
    scope: str,
    facts: Iterable[GraphProductFact],
    min_observation_episodes: int = 2,
    max_facts: int = 10_000,
    max_sentences_per_product: int = 64,
    created_at: str | None = None,
) -> dict[str, object]:
    """Explicit rebuild spelling for storage adapters and maintenance tools."""

    return update_graph_products(
        connection,
        namespace=namespace,
        scope=scope,
        facts=facts,
        min_observation_episodes=min_observation_episodes,
        max_facts=max_facts,
        max_sentences_per_product=max_sentences_per_product,
        created_at=created_at,
    )


def read_graph_products(
    connection: sqlite3.Connection,
    *,
    namespace: str,
    scope: str,
    kinds: Sequence[str] | None = None,
    subject_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, object]]:
    """Read only products from the latest complete snapshot for one boundary."""

    ns = _required(namespace, "namespace")
    product_scope = _required(scope, "scope")
    if limit < 1 or limit > 1_000:
        raise ValueError("limit must be between 1 and 1000")
    selected_kinds = sorted({_required(kind, "kind") for kind in kinds or ()})
    if any(kind not in PRODUCT_KINDS for kind in selected_kinds):
        raise ValueError("unknown graph product kind")
    init_graph_products(connection)
    build = connection.execute(
        "select build_id from graph_product_build where ns = ? and scope = ? "
        "order by build_seq desc limit 1",
        (ns, product_scope),
    ).fetchone()
    if build is None:
        return []
    where = ["build_id = ?", "ns = ?", "scope = ?"]
    params: list[object] = [str(build[0]), ns, product_scope]
    if selected_kinds:
        where.append(
            f"kind in ({','.join('?' for _ in selected_kinds)})"
        )
        params.extend(selected_kinds)
    if subject_id is not None:
        where.append("subject_id = ?")
        params.append(_required(subject_id, "subject_id"))
    rows = connection.execute(
        "select product_id from graph_product "
        f"where {' and '.join(where)} order by kind, stable_key limit ?",
        [*params, limit],
    ).fetchall()
    return [_product_payload(connection, str(row[0])) for row in rows]


def graph_product_history(
    connection: sqlite3.Connection,
    *,
    namespace: str,
    scope: str,
    stable_key: str,
    limit: int = 100,
) -> list[dict[str, object]]:
    """Read distinct content versions for one stable derived product."""

    ns = _required(namespace, "namespace")
    product_scope = _required(scope, "scope")
    key = _required(stable_key, "stable_key")
    if limit < 1 or limit > 1_000:
        raise ValueError("limit must be between 1 and 1000")
    init_graph_products(connection)
    rows = connection.execute(
        "select max(product_seq), product_id from graph_product "
        "where ns = ? and scope = ? and stable_key = ? "
        "group by version, source_fingerprint "
        "order by version desc limit ?",
        (ns, product_scope, key, limit),
    ).fetchall()
    return [_product_payload(connection, str(row[1])) for row in rows]


def _eligible_fact(
    fact: GraphProductFact,
    *,
    namespace: str,
    scope: str,
) -> GraphProductFact | None:
    try:
        ns = _required(fact.ns, "fact namespace")
        fact_scope = _required(fact.scope, "fact scope")
        record_id = _required(fact.record_id, "supporting record id")
        subject_id = _required(fact.subject_id, "subject id")
        subject_label = _required(fact.subject_label, "subject label")
        predicate = _required(fact.predicate, "predicate")
        object_label = _required(fact.object_label, "object label")
        object_id = (
            _required(fact.object_id, "object id")
            if fact.object_id is not None
            else None
        )
        episode_ids = tuple(
            sorted(
                {
                    _required(item, "supporting episode id")
                    for item in fact.episode_ids
                }
            )
        )
    except (TypeError, ValueError):
        return None
    if (
        ns != namespace
        or fact_scope != scope
        or not fact.current
        or str(fact.trust_state).strip().lower()
        not in ASSERTABLE_TRUST_STATES
        or not episode_ids
    ):
        return None
    return GraphProductFact(
        ns=ns,
        scope=fact_scope,
        record_id=record_id,
        episode_ids=episode_ids,
        subject_id=subject_id,
        subject_label=subject_label,
        predicate=predicate,
        object_id=object_id,
        object_label=object_label,
        trust_state=str(fact.trust_state).strip().lower(),
        current=True,
    )


def _derive_products(
    facts: list[GraphProductFact],
    *,
    min_observation_episodes: int,
    max_sentences: int,
) -> list[_Product]:
    entity_facts: dict[str, list[GraphProductFact]] = {}
    labels: dict[str, str] = {}
    adjacency: dict[str, set[str]] = {}
    for fact in facts:
        labels[fact.subject_id] = fact.subject_label
        entity_facts.setdefault(fact.subject_id, []).append(fact)
        adjacency.setdefault(fact.subject_id, set())
        if fact.object_id:
            labels[fact.object_id] = fact.object_label
            entity_facts.setdefault(fact.object_id, []).append(fact)
            adjacency.setdefault(fact.object_id, set()).add(fact.subject_id)
            adjacency[fact.subject_id].add(fact.object_id)

    products: list[_Product] = []
    for entity_id in sorted(entity_facts):
        sentences = tuple(
            _fact_sentence(fact)
            for fact in sorted(entity_facts[entity_id], key=_fact_sort_key)[
                :max_sentences
            ]
        )
        products.append(
            _Product(
                kind="entity_summary",
                stable_key=f"entity:{entity_id}",
                subject_id=entity_id,
                payload={
                    "entity_id": entity_id,
                    "label": labels[entity_id],
                    "sentence_count": len(sentences),
                },
                sentences=sentences,
            )
        )

    seen: set[str] = set()
    for root in sorted(adjacency):
        if root in seen:
            continue
        pending = [root]
        members: set[str] = set()
        while pending:
            node_id = pending.pop()
            if node_id in members:
                continue
            members.add(node_id)
            pending.extend(sorted(adjacency[node_id] - members, reverse=True))
        seen.update(members)
        if len(members) < 2:
            continue
        internal = [
            fact
            for fact in facts
            if fact.object_id
            and fact.subject_id in members
            and fact.object_id in members
        ]
        sentences = tuple(
            _fact_sentence(fact)
            for fact in sorted(internal, key=_fact_sort_key)[:max_sentences]
        )
        if not sentences:
            continue
        anchor = min(members)
        products.append(
            _Product(
                kind="community_summary",
                stable_key=f"community:{anchor}",
                subject_id=None,
                payload={
                    "anchor_id": anchor,
                    "member_ids": sorted(members),
                    "sentence_count": len(sentences),
                },
                sentences=sentences,
            )
        )

    observation_groups: dict[
        tuple[str, str], list[GraphProductFact]
    ] = {}
    for fact in facts:
        key = (fact.subject_id, _normalize_text(fact.predicate).casefold())
        observation_groups.setdefault(key, []).append(fact)
    for (subject_id, predicate_key), group in sorted(
        observation_groups.items()
    ):
        episode_ids = tuple(
            sorted({episode for fact in group for episode in fact.episode_ids})
        )
        if len(episode_ids) < min_observation_episodes:
            continue
        record_ids = tuple(sorted({fact.record_id for fact in group}))
        label = min(
            (fact.subject_label for fact in group),
            key=lambda item: (_normalize_text(item).casefold(), item),
        )
        predicate = min(
            (fact.predicate for fact in group),
            key=lambda item: (_normalize_text(item).casefold(), item),
        )
        sentence = _Sentence(
            text=(
                f"{label} has recurring {predicate} evidence across "
                f"{len(episode_ids)} episodes."
            ),
            record_ids=record_ids,
            episode_ids=episode_ids,
        )
        observation_key = _fingerprint([subject_id, predicate_key])[:20]
        products.append(
            _Product(
                kind="observation",
                stable_key=f"observation:{observation_key}",
                subject_id=subject_id,
                payload={
                    "entity_id": subject_id,
                    "predicate": predicate_key,
                    "episode_count": len(episode_ids),
                    "record_count": len(record_ids),
                },
                sentences=(sentence,),
            )
        )
    return sorted(products, key=lambda item: (item.kind, item.stable_key))


def _fact_sentence(fact: GraphProductFact) -> _Sentence:
    return _Sentence(
        text=(
            f"{fact.subject_label} {_display_predicate(fact.predicate)} "
            f"{fact.object_label}."
        ),
        record_ids=(fact.record_id,),
        episode_ids=fact.episode_ids,
    )


def _display_predicate(value: str) -> str:
    return _normalize_text(value.replace("_", " "))


def _fact_sort_key(fact: GraphProductFact) -> tuple[object, ...]:
    return (
        fact.subject_id,
        _normalize_text(fact.predicate).casefold(),
        fact.object_id or "",
        _normalize_text(fact.object_label).casefold(),
        fact.record_id,
        fact.episode_ids,
    )


def _fact_payload(fact: GraphProductFact) -> dict[str, object]:
    return {
        "episode_ids": fact.episode_ids,
        "ns": fact.ns,
        "object_id": fact.object_id,
        "object_label": fact.object_label,
        "predicate": fact.predicate,
        "record_id": fact.record_id,
        "scope": fact.scope,
        "subject_id": fact.subject_id,
        "subject_label": fact.subject_label,
        "trust_state": fact.trust_state,
    }


def _product_fingerprint(product: _Product) -> str:
    return _fingerprint(
        {
            "kind": product.kind,
            "payload": product.payload,
            "sentences": [
                {
                    "episode_ids": sentence.episode_ids,
                    "record_ids": sentence.record_ids,
                    "text": sentence.text,
                }
                for sentence in product.sentences
            ],
            "stable_key": product.stable_key,
        }
    )


def _validate_sentence(sentence: _Sentence) -> None:
    if (
        not sentence.text.strip()
        or not sentence.record_ids
        or not sentence.episode_ids
        or any(not item.strip() for item in sentence.record_ids)
        or any(not item.strip() for item in sentence.episode_ids)
    ):
        raise ValueError(
            "every graph-product sentence requires exact record and episode provenance"
        )


def _build_payload(
    connection: sqlite3.Connection,
    build_id: str,
    *,
    reused: bool,
) -> dict[str, object]:
    row = connection.execute(
        "select build_seq, build_id, ns, scope, algorithm_version, "
        "source_fingerprint, accepted_fact_count, rejected_fact_count, "
        "created_at, schema_version from graph_product_build where build_id = ?",
        (build_id,),
    ).fetchone()
    if row is None:
        raise KeyError(build_id)
    count = connection.execute(
        "select count(*) from graph_product where build_id = ?", (build_id,)
    ).fetchone()
    return {
        "build_seq": int(row[0]),
        "build_id": str(row[1]),
        "namespace": str(row[2]),
        "scope": str(row[3]),
        "algorithm_version": str(row[4]),
        "source_fingerprint": str(row[5]),
        "accepted_fact_count": int(row[6]),
        "rejected_fact_count": int(row[7]),
        "created_at": str(row[8]),
        "schema_version": int(row[9]),
        "product_count": int(count[0]),
        "reused": reused,
    }


def _product_payload(
    connection: sqlite3.Connection, product_id: str
) -> dict[str, object]:
    row = connection.execute(
        "select product_id, build_id, ns, scope, kind, stable_key, "
        "subject_id, version, algorithm_version, source_fingerprint, "
        "payload_json, created_at, schema_version "
        "from graph_product where product_id = ?",
        (product_id,),
    ).fetchone()
    if row is None:
        raise KeyError(product_id)
    sentence_rows = connection.execute(
        "select sentence_id, ordinal, sentence_text, "
        "supporting_record_ids_json, supporting_episode_ids_json "
        "from graph_product_sentence where product_id = ? order by ordinal",
        (product_id,),
    ).fetchall()
    sentences = [
        {
            "sentence_id": str(sentence[0]),
            "ordinal": int(sentence[1]),
            "text": str(sentence[2]),
            "supporting_record_ids": json.loads(str(sentence[3])),
            "supporting_episode_ids": json.loads(str(sentence[4])),
        }
        for sentence in sentence_rows
    ]
    return {
        "product_id": str(row[0]),
        "build_id": str(row[1]),
        "namespace": str(row[2]),
        "scope": str(row[3]),
        "kind": str(row[4]),
        "stable_key": str(row[5]),
        "subject_id": str(row[6]) if row[6] is not None else None,
        "version": int(row[7]),
        "algorithm_version": str(row[8]),
        "source_fingerprint": str(row[9]),
        "payload": json.loads(str(row[10])),
        "created_at": str(row[11]),
        "schema_version": int(row[12]),
        "sentences": sentences,
    }


def _required(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return _normalize_text(value)


def _normalize_text(value: str) -> str:
    return _SPACE_RE.sub(" ", value.strip())


def _canonical_json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )


def _fingerprint(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()
