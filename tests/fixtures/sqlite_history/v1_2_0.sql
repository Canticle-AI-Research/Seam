-- Minimized from seam_runtime/storage.py at tag v1.2.0.
pragma foreign_keys = on;

create table raw_docs (
    id text primary key,
    ns text not null,
    scope text not null,
    source_ref text,
    content text not null,
    created_at text not null
);

create table ir_records (
    id text primary key,
    kind text not null,
    ns text not null,
    scope text not null,
    status text not null,
    conf real not null,
    t0 text,
    t1 text,
    created_at text not null,
    updated_at text not null,
    payload_json text not null
);

create table ir_edges (
    id integer primary key autoincrement,
    src_id text not null,
    edge_type text not null,
    dst_id text not null
);

create table vector_index (
    record_id text not null,
    model_name text not null,
    dimension integer not null,
    source_text text not null,
    vector_json text not null,
    updated_at text not null,
    primary key (record_id, model_name)
);

insert into raw_docs values (
    'raw:legacy-source', 'legacy', 'thread', 'fixture://v1.2.0',
    'Legacy memory survives migration.', '2026-06-27T15:00:00Z'
);

insert into ir_records values (
    'ent:legacy-memory', 'ENT', 'legacy', 'thread', 'asserted', 1.0,
    null, null, '2026-06-27T15:00:00Z', '2026-06-27T15:00:00Z',
    '{"id":"ent:legacy-memory","kind":"ENT","ns":"legacy","scope":"thread","status":"asserted","conf":1.0,"attrs":{"label":"Legacy Memory","entity_type":"concept"}}'
);

insert into vector_index values (
    'ent:legacy-memory', 'fixture-vector', 2, 'Legacy Memory', '[1.0,0.0]',
    '2026-06-27T15:00:00Z'
);
