"""Zero-network WANDR replay lane.

The handoff at ``docs/handoffs/2026-07-29-wandr-provider-free-replay-next.md``
requires a non-official replay adapter whose provider, network, and cost
counters are fixed at zero, over a fixed hash-pinned corpus with deterministic
identifiers, isolated boundaries, matched lane budgets, and exact provenance.

These tests hold that contract. The most important ones are negative: the
corpus pin must actually fail on drift, and a live fetch must raise rather than
quietly succeed.
"""

from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

from benchmarks.external.wandr.adapters.seam import (
    LANES,
    SeamWandrAdapter,
    ZeroNetworkViolation,
    canonical_url,
)
from benchmarks.external.wandr.corpus import (
    CorpusIntegrityError,
    available_tasks,
    load_task,
    validate_hierarchy,
)
from benchmarks.external.wandr.run import build_report, run_lane
from benchmarks.external.wandr.types import (
    KeySpec,
    ReplayCounters,
    WandrRow,
    WandrTask,
    stable_id,
)

# -- corpus integrity ----------------------------------------------------


def test_pinned_tasks_load_and_satisfy_their_hierarchy():
    assert set(available_tasks()) == {"smoke", "hierarchy"}
    for name in available_tasks():
        task = load_task(name)
        assert task.rows, f"{name} corpus is empty"
        assert validate_hierarchy(task) == [], f"{name} violates its own hierarchy"


def test_corpus_digest_drift_is_rejected(tmp_path):
    """The pin must be enforced, or 'fixed corpus' is only a claim."""
    from benchmarks.external.wandr.corpus import FIXTURE_ROOT

    manifest = json.loads((FIXTURE_ROOT / "MANIFEST.json").read_text())
    (tmp_path / "MANIFEST.json").write_text(json.dumps(manifest))
    corpus = FIXTURE_ROOT / manifest["tasks"]["smoke"]["file"]
    tampered = corpus.read_text() + json.dumps(
        {
            "item": {"topic": "injected"},
            "url": "https://replay.invalid/injected",
            "excerpts": ["injected"],
        }
    ) + "\n"
    (tmp_path / manifest["tasks"]["smoke"]["file"]).write_text(tampered)

    with pytest.raises(CorpusIntegrityError):
        load_task("smoke", root=tmp_path)

    # Explicit opt-out still parses, so re-pinning stays possible on purpose.
    assert load_task("smoke", root=tmp_path, verify=False).rows


def test_corpus_urls_are_unresolvable_by_construction():
    """Every pinned URL uses the reserved .invalid TLD (RFC 2606)."""
    for name in available_tasks():
        for row in load_task(name).rows:
            hostname = urlsplit(row.url).hostname or ""
            assert hostname == "invalid" or hostname.endswith(".invalid"), row.url


@pytest.mark.parametrize(
    "url",
    [
        "https://replay.invalid.evil.example/page",
        "https://example.com/.invalid/page",
        "https://example.com/page?marker=.invalid",
    ],
)
def test_invalid_tld_check_uses_a_hostname_boundary(url):
    hostname = urlsplit(url).hostname or ""
    assert hostname != "invalid" and not hostname.endswith(".invalid")


@pytest.mark.parametrize(
    "payload",
    [
        {"item": {"topic": "gc"}, "url": "https://replay.invalid/x"},
        {
            "item": {"topic": "gc"},
            "url": "https://replay.invalid/x",
            "excerpts": [],
        },
        {
            "item": {"topic": "gc"},
            "url": "https://replay.invalid/x",
            "excerpts": [""],
        },
    ],
)
def test_row_loader_rejects_missing_or_empty_excerpts(payload):
    with pytest.raises(ValueError, match="excerpts"):
        WandrRow.from_dict("t", payload)


@pytest.mark.parametrize("excerpts", [(), ("",), ("evidence", "")])
def test_direct_row_construction_rejects_empty_excerpts(excerpts):
    with pytest.raises(ValueError, match="excerpts"):
        WandrRow(
            task="t",
            item={"topic": "gc"},
            url="https://replay.invalid/x",
            excerpts=excerpts,
        )


# -- identifier discipline ----------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("https://replay.invalid/a/", "https://replay.invalid/a"),
        ("https://WWW.Replay.invalid/A", "https://replay.invalid/A"),
        ("https://replay.invalid/a?utm_source=x", "https://replay.invalid/a"),
        ("https://replay.invalid/a?ref=index&id=7", "https://replay.invalid/a?id=7"),
        (
            "https://replay.invalid/a?refine=sharp&refresh=yes",
            "https://replay.invalid/a?refine=sharp&refresh=yes",
        ),
        ("https://replay.invalid/a#frag", "https://replay.invalid/a"),
    ],
)
def test_canonical_url_collapses_same_document(raw, expected):
    assert canonical_url(raw) == expected


def test_identifiers_are_deterministic():
    row = WandrRow(
        task="t",
        item={"topic": "gc"},
        url="https://replay.invalid/x",
        excerpts=("e",),
    )
    assert row.source_id == stable_id("source", "t", "https://replay.invalid/x")
    assert row.episode_id == stable_id(
        "episode", "t", "topic=gc", "https://replay.invalid/x"
    )
    assert row.member_key == "topic=gc"


# -- zero-network contract ----------------------------------------------


def test_fetch_is_a_hard_error(tmp_path):
    adapter = SeamWandrAdapter(tmp_path, lane="native")
    with pytest.raises(ZeroNetworkViolation):
        adapter.fetch("https://replay.invalid/anything")
    assert adapter.counters() == {
        "provider_calls": 0,
        "network_calls": 1,
        "cost_usd": 0.0,
    }
    adapter.close()


def test_counters_report_free():
    assert ReplayCounters().is_free
    assert not ReplayCounters(provider_calls=1).is_free
    assert not ReplayCounters(network_calls=1).is_free
    assert not ReplayCounters(cost_usd=0.01).is_free


# -- adapter behaviour ---------------------------------------------------


def test_reset_removes_database_and_sqlite_sidecars(tmp_path):
    adapter = SeamWandrAdapter(tmp_path, lane="native")
    db_path = tmp_path / "scope.db"
    paths = (db_path, tmp_path / "scope.db-wal", tmp_path / "scope.db-shm")
    for path in paths:
        path.write_text(path.name)

    adapter.reset("scope")

    assert all(not path.exists() for path in paths)


def test_failed_ingest_is_retryable_and_only_then_marked_seen(tmp_path):
    class FailOnceRuntime:
        def __init__(self):
            self.calls = 0

        def ingest_conversation_turn(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("transient ingest failure")

        def close(self):
            return None

    adapter = SeamWandrAdapter(tmp_path, lane="native")
    runtime = FailOnceRuntime()
    adapter._runtimes["scope"] = runtime
    row = WandrRow(
        task="task",
        item={"topic": "retry"},
        url="https://replay.invalid/retry",
        excerpts=("retry evidence",),
    )

    with pytest.raises(RuntimeError, match="transient ingest failure"):
        adapter.ingest_row("scope", row)
    assert adapter._provenance["scope"][row.member_key] == []

    source_id = adapter.ingest_row("scope", row)

    assert runtime.calls == 2
    assert adapter._provenance["scope"][row.member_key] == [source_id]
    adapter.close()


def test_recovered_source_ref_must_already_be_canonical(tmp_path, monkeypatch):
    adapter = SeamWandrAdapter(tmp_path, lane="native")

    def result_with(source_ref):
        record = SimpleNamespace(attrs={"source_ref": source_ref})
        return SimpleNamespace(candidates=[SimpleNamespace(record=record)])

    noncanonical = "https://replay.invalid/source?utm_source=corrupt"
    monkeypatch.setattr(adapter, "retrieve", lambda *args, **kwargs: result_with(noncanonical))
    assert adapter.recovered_sources("scope", "task", "topic=x") == []

    canonical = "https://replay.invalid/source"
    monkeypatch.setattr(adapter, "retrieve", lambda *args, **kwargs: result_with(canonical))
    assert adapter.recovered_sources("scope", "task", "topic=x") == [
        stable_id("source", "task", canonical)
    ]


def test_hierarchy_counts_canonical_source_urls():
    task = WandrTask(
        name="canonical-hierarchy",
        key_hierarchy=(KeySpec(name="topic", required=1), KeySpec(name="url", required=2)),
        rows=(
            WandrRow(
                task="canonical-hierarchy",
                item={"topic": "same-page"},
                url="https://replay.invalid/source?utm_source=one",
                excerpts=("one",),
            ),
            WandrRow(
                task="canonical-hierarchy",
                item={"topic": "same-page"},
                url="https://replay.invalid/source?utm_source=two",
                excerpts=("two",),
            ),
        ),
    )

    assert validate_hierarchy(task) == [
        "topic=same-page: 1 url(s) < required 2"
    ]


def test_adapter_pins_hash_embeddings_and_disables_env_extractor(
    tmp_path, monkeypatch
):
    from seam_runtime import nl_extract
    from seam_runtime.models import HashEmbeddingModel

    monkeypatch.setenv("SEAM_EMBEDDING_PROVIDER", "openai")
    monkeypatch.setenv("SEAM_NL_EXTRACTOR", "ollama")

    def unexpected_env_extractor():
        raise AssertionError("provider-capable env extractor was consulted")

    monkeypatch.setattr(nl_extract, "extractor_from_env", unexpected_env_extractor)
    adapter = SeamWandrAdapter(tmp_path, lane="native")
    try:
        row = WandrRow(
            task="task",
            item={"topic": "offline"},
            url="https://replay.invalid/offline",
            excerpts=("offline evidence",),
        )
        adapter.ingest_row("scope", row)

        assert isinstance(adapter._runtime("scope").embedding_model, HashEmbeddingModel)
        assert adapter.counters() == {
            "provider_calls": 0,
            "network_calls": 0,
            "cost_usd": 0.0,
        }
    finally:
        adapter.close()


def test_ingest_deduplicates_canonical_sources(tmp_path):
    """The hierarchy corpus carries a tracking-param variant and an exact dupe."""
    task = load_task("hierarchy")
    adapter = SeamWandrAdapter(tmp_path, lane="native")
    try:
        report = adapter.ingest_task("hierarchy", task)
        assert report["rows"] == 10
        assert report["unique_sources"] == 8
        assert report["duplicates_collapsed"] == 2

        # Re-ingest is idempotent: no new sources appear.
        again = adapter.ingest_task("hierarchy", task)
        assert again["unique_sources"] == 8
    finally:
        adapter.close()


def test_submission_matches_upstream_shape(tmp_path):
    task = load_task("smoke")
    adapter = SeamWandrAdapter(tmp_path, lane="native")
    try:
        rows = adapter.submit("smoke", task)
        assert rows
        for row in rows:
            assert set(row) == {"item", "url", "excerpts", "answer"}
            assert isinstance(row["excerpts"], list) and row["excerpts"]
            assert all(
                isinstance(excerpt, str) and excerpt for excerpt in row["excerpts"]
            )
            assert row["url"] == canonical_url(row["url"])

        out = adapter.write_submission("smoke", task, tmp_path / "results_smoke.jsonl")
        lines = [json.loads(line) for line in out.read_text().splitlines()]
        assert len(lines) == len(rows)
    finally:
        adapter.close()


def test_namespaces_isolate_scopes(tmp_path):
    adapter = SeamWandrAdapter(tmp_path, lane="native")
    try:
        assert adapter.namespace("smoke") != adapter.namespace("hierarchy")
        assert adapter.namespace("smoke").startswith("wandr:")
    finally:
        adapter.close()


def test_unknown_lane_rejected(tmp_path):
    with pytest.raises(ValueError):
        SeamWandrAdapter(tmp_path, lane="nonsense")


# -- end-to-end lane + ablation -----------------------------------------


def test_run_lane_resets_a_persistent_scope_before_ingest(tmp_path):
    stale_ref = "https://replay.invalid/stale-source"
    adapter = SeamWandrAdapter(tmp_path / "native", lane="native")
    try:
        adapter.ingest_row(
            "smoke",
            WandrRow(
                task="smoke",
                item={"topic": "stale"},
                url=stale_ref,
                excerpts=("must not survive the next lane run",),
            ),
        )
    finally:
        adapter.close()

    run_lane(load_task("smoke"), "native", tmp_path)

    with sqlite3.connect(tmp_path / "native" / "smoke.db") as connection:
        stale_rows = connection.execute(
            "select count(*) from raw_docs where source_ref = ?", (stale_ref,)
        ).fetchone()[0]
    assert stale_rows == 0


def test_replay_is_free_deterministic_and_recovers_provenance(tmp_path):
    task = load_task("hierarchy")
    report = build_report(task, list(LANES), tmp_path)

    assert report["official_pipeline_executed"] is False
    assert report["free_lane_verified"] is True
    assert report["cost"] == {
        "provider_calls": 0,
        "network_calls": 0,
        "cost_usd": 0.0,
    }

    for lane in report["lanes"]:
        assert lane["source_recall"] == pytest.approx(1.0)
        assert lane["batch_recovery_ok"] is True, "evidence did not survive reopen"
        for member in lane["per_member"]:
            assert member["missing"] == []

    # Matched budgets across lanes, so any delta is graph-attributable.
    assert report["ablation"]["verdict"] == "parity"
    assert report["ablation"]["delta"] == pytest.approx(0.0)


def test_report_is_reproducible(tmp_path):
    """Same corpus, same identifiers — determinism is a stated requirement."""
    task = load_task("smoke")
    first = build_report(task, ["native"], tmp_path / "a")
    second = build_report(task, ["native"], tmp_path / "b")
    assert first == second
