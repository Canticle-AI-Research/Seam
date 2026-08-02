-- Minimized from seam_runtime/storage.py and knowledge_graph.py at tag v2.4.0.
pragma foreign_keys = on;

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

create table knowledge_graph_meta (
    key text primary key,
    value text not null
);

create table knowledge_nodes (
    id text primary key,
    kind text not null,
    label text not null,
    ns text not null,
    scope text not null,
    status text not null,
    confidence real not null,
    valid_from text,
    valid_to text,
    created_at text not null,
    updated_at text not null,
    agent_id text,
    source_record_id text,
    synthetic integer not null default 0,
    properties_json text not null
);

insert into ir_records values (
    'ent:released-memory', 'ENT', 'released', 'project', 'asserted', 0.95,
    null, null, '2026-07-28T22:22:48Z', '2026-07-28T22:22:48Z',
    '{"id":"ent:released-memory","kind":"ENT","ns":"released","scope":"project","status":"asserted","conf":0.95,"attrs":{"label":"Released Memory","entity_type":"concept"}}'
);

insert into knowledge_graph_meta values ('projection_version', 'knowledge-graph/5');

insert into knowledge_nodes values (
    'ent:released-memory', 'entity', 'Released Memory', 'released', 'project',
    'asserted', 0.95, null, null, '2026-07-28T22:22:48Z',
    '2026-07-28T22:22:48Z', null, 'ent:released-memory', 0,
    '{"entity_type":"concept"}'
);
