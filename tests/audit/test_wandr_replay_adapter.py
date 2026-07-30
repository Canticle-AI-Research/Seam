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
from benchmarks.external.wandr.run import build_report
from benchmarks.external.wandr.types import ReplayCounters, WandrRow, stable_id

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
            assert ".invalid" in row.url, row.url


# -- identifier discipline ----------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("https://replay.invalid/a/", "https://replay.invalid/a"),
        ("https://WWW.Replay.invalid/A", "https://replay.invalid/A"),
        ("https://replay.invalid/a?utm_source=x", "https://replay.invalid/a"),
        ("https://replay.invalid/a?ref=index&id=7", "https://replay.invalid/a?id=7"),
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
    assert row.episode_id == row.episode_id
    assert row.member_key == "topic=gc"


# -- zero-network contract ----------------------------------------------


def test_fetch_is_a_hard_error(tmp_path):
    adapter = SeamWandrAdapter(tmp_path, lane="native")
    with pytest.raises(ZeroNetworkViolation):
        adapter.fetch("https://replay.invalid/anything")
    adapter.close()


def test_counters_report_free():
    assert ReplayCounters().is_free
    assert not ReplayCounters(provider_calls=1).is_free
    assert not ReplayCounters(network_calls=1).is_free
    assert not ReplayCounters(cost_usd=0.01).is_free


# -- adapter behaviour ---------------------------------------------------


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
    assert first["task"] == second["task"]
    assert first["lanes"][0]["source_recall"] == second["lanes"][0]["source_recall"]
    assert first["lanes"][0]["ingest"]["task_id"] == (
        second["lanes"][0]["ingest"]["task_id"]
    )
