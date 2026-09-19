"""Tests for the M1 formation observation probe.

M1's audit rests on claims the probe asserts about itself: that RAW content is
preserved byte-exact, that SPAN offsets index the exact claim text, that a
known-present term is findable in storage while an unstated sentinel is not,
and that distinct source references do not collapse into one record.

Those claims lived only as bare ``assert`` statements inside the probe. Bare
asserts are stripped under ``python -O``, and nothing ran them in CI, so the
audit's evidence had no independent check at all. These tests move each claim
out of the instrument and into the suite, which is what makes the observation
auditable rather than self-reported.

The probe is an observation instrument: it reports what the current compiler
and adapter actually do. It is deliberately NOT a quality benchmark, makes no
provider calls, and uses synthetic inputs only.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from seam_runtime.mirl import RecordKind
from seam_runtime.nl import compile_nl

# Imported directly, not via importorskip: the strict-no-skip allowlist in
# tests/conftest.py does not cover an absent probe, so a skip here would fail
# the session. If the probe is missing this must surface as a collection error.
from tools import memory_formation_m1 as m1

PINNED_MODEL = (
    "st:BAAI/bge-small-en-v1.5@"
    "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
)


def _claim_semantics(observation: dict) -> list[dict]:
    """Keep behavior-bearing claim fields, excluding generated record ids."""
    return [
        {
            key: claim[key]
            for key in ("text", "predicate", "subject_label", "t0", "t1", "status")
        }
        for claim in observation["claims"]
    ]


def _compiler_semantics(observation: dict) -> dict:
    """Normalize one compiler observation without ids or timestamps."""
    return {
        "kinds": observation["kinds"],
        "raw": [
            {
                "content": raw["content"],
                "source_metadata": raw["source_metadata"],
            }
            for raw in observation["raw"]
        ],
        "claims": _claim_semantics(observation),
        "span_count": observation["span_count"],
        "span_bounds": observation["span_bounds"],
        "span_text_exact": observation["span_text_exact"],
        "raw_exact": observation["raw_exact"],
    }


@pytest.fixture(scope="module")
def compiled_samples() -> dict:
    """Compile every declared sample once; describe() is pure over the batch."""
    return {
        name: (text, compile_nl(text, allow_env_extractor=False))
        for name, text in m1.SAMPLES.items()
    }


class TestProbeDeclaresItsOwnScope:
    def test_samples_cover_the_documented_formation_signals(self):
        """Each sample exists to probe one boundary signal; none may vanish."""
        assert set(m1.SAMPLES) == {
            "bracket_alice",
            "bracket_bob",
            "colon_control",
            "unicode",
            "abbreviation",
            "newline_speakers",
            "state_changes",
        }

    def test_samples_are_synthetic_not_dataset_rows(self):
        """A probe reading real LoCoMo rows would expose the holdout."""
        for text in m1.SAMPLES.values():
            assert isinstance(text, str) and text.strip()


class TestRawContentIsPreservedExactly:
    """RAW is retained evidence. Any drift breaks every downstream backtrace."""

    def test_raw_content_is_byte_identical_to_input(self, compiled_samples):
        for name, (text, batch) in compiled_samples.items():
            raws = batch.kind(RecordKind.RAW)
            assert raws, f"{name}: no RAW record emitted"
            assert raws[0].attrs["content"] == text, f"{name}: RAW content drifted"

    def test_unicode_survives_compilation_unchanged(self, compiled_samples):
        text, batch = compiled_samples["unicode"]
        assert batch.kind(RecordKind.RAW)[0].attrs["content"] == text
        assert "東京" in batch.kind(RecordKind.RAW)[0].attrs["content"]


class TestSpanOffsetsIndexTheExactClaim:
    """A SPAN whose offsets do not reproduce its claim text is a broken anchor."""

    def test_describe_reports_span_text_exact(self, compiled_samples):
        for name, (_text, batch) in compiled_samples.items():
            observation = m1.describe(batch)
            assert observation["span_text_exact"] is True, f"{name}: span drift"

    def test_span_bounds_are_ordered_and_within_the_raw(self, compiled_samples):
        for name, (text, batch) in compiled_samples.items():
            observation = m1.describe(batch)
            for start, end in observation["span_bounds"]:
                assert 0 <= start < end <= len(text), f"{name}: bad span {start}:{end}"

    def test_span_count_matches_reported_bounds(self, compiled_samples):
        for name, (_text, batch) in compiled_samples.items():
            observation = m1.describe(batch)
            assert observation["span_count"] == len(observation["span_bounds"]), name


class TestDescribeReportsFaithfully:
    def test_describe_does_not_mutate_the_batch(self, compiled_samples):
        _text, batch = compiled_samples["bracket_alice"]
        before = [(r.id, r.kind.value) for r in batch.records]
        m1.describe(batch)
        assert [(r.id, r.kind.value) for r in batch.records] == before

    def test_describe_is_deterministic_over_one_batch(self, compiled_samples):
        _text, batch = compiled_samples["state_changes"]
        first = json.dumps(m1.describe(batch), sort_keys=True, default=str)
        second = json.dumps(m1.describe(batch), sort_keys=True, default=str)
        assert first == second

    def test_every_claim_resolves_its_subject_label(self, compiled_samples):
        """describe() dereferences subject ids; an unresolvable id would raise."""
        for name, (_text, batch) in compiled_samples.items():
            observation = m1.describe(batch)
            for claim in observation["claims"]:
                assert claim["subject_label"], f"{name}: claim missing subject label"

    def test_claims_carry_their_supporting_evidence(self, compiled_samples):
        for name, (_text, batch) in compiled_samples.items():
            observation = m1.describe(batch)
            for claim in observation["claims"]:
                assert claim["evidence"], f"{name}: claim with no evidence refs"

    def test_orphan_span_is_reported_as_inexact(self, compiled_samples):
        """A diagnostic must report malformed evidence instead of crashing."""
        _text, batch = compiled_samples["colon_control"]
        orphan = replace(batch.kind(RecordKind.SPAN)[0], id="span:orphan")
        malformed = type(batch)(records=[*batch.records, orphan])

        assert m1.describe(malformed)["span_text_exact"] is False


class TestSpeakerAttributionIsObservable:
    """M1's hypothesis is about context loss; attribution is the first signal."""

    def test_bracket_and_colon_forms_both_compile(self, compiled_samples):
        for name in ("bracket_alice", "colon_control", "newline_speakers"):
            _text, batch = compiled_samples[name]
            assert batch.kind(RecordKind.RAW), f"{name}: nothing emitted"

    def test_distinct_speakers_produce_distinct_raw_content(self, compiled_samples):
        alice = compiled_samples["bracket_alice"][1].kind(RecordKind.RAW)[0]
        bob = compiled_samples["bracket_bob"][1].kind(RecordKind.RAW)[0]
        assert alice.attrs["content"] != bob.attrs["content"]

    def test_bracketed_first_person_loses_speaker_attribution(self, compiled_samples):
        for name, expected_speaker in (
            ("bracket_alice", "Alice"),
            ("bracket_bob", "Bob"),
        ):
            observation = m1.describe(compiled_samples[name][1])
            assert [claim["subject_label"] for claim in observation["claims"]] == [
                expected_speaker,
                "I",
            ]

    def test_colon_form_keeps_speaker_attribution(self, compiled_samples):
        observation = m1.describe(compiled_samples["colon_control"][1])
        assert [claim["subject_label"] for claim in observation["claims"]] == [
            "Alice",
            "Alice",
        ]


class TestUnpunctuatedInputHasNoSizeBound:
    """Characterize the current missing cap without treating trim as a cap."""

    def test_long_unpunctuated_text_forms_one_9999_character_span(self):
        long_text = "word " * 2000
        batch = compile_nl(long_text, allow_env_extractor=False)
        spans = batch.kind(RecordKind.SPAN)
        assert len(spans) == 1
        assert (spans[0].attrs["start"], spans[0].attrs["end"]) == (0, 9999)
        assert spans[0].attrs["end"] - spans[0].attrs["start"] == len(long_text) - 1
        assert batch.kind(RecordKind.RAW)[0].attrs["content"] == long_text


class TestRecordedEvidenceIsReproducible:
    """M1's acceptance rests on its observations being reproducible.

    The committed evidence was recorded at revision 614141c5. Re-running the
    probe on a later commit must reproduce the same observations, or the audit
    describes a state the repository no longer has. This is the check that
    distinguishes a recorded claim from a verified one.

    Requires the pinned local embedding model; the adapter section exercises
    real retrieval. CI provides the sbert extra (the LoCoMo quickstart job
    depends on it), so this must not be skip-gated.
    """

    EVIDENCE = Path("docs/audits/evidence/2026-09-13-memory-formation-m1/observations.json")
    EVIDENCE_SHA256 = "85a3096c0010d5875ad7ea630704f4936be10350ee9141a604c3a8148550b8df"

    @pytest.fixture(scope="class")
    @classmethod
    def recorded(cls) -> dict:
        return json.loads(cls.EVIDENCE.read_text(encoding="utf-8"))

    @pytest.fixture(scope="class")
    @classmethod
    def reproduced(cls, tmp_path_factory) -> dict:
        settings = {
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_HUB_DISABLE_PROGRESS_BARS": "1",
            "SEAM_PGVECTOR_DSN": "",
            "SEAM_NL_REGEX_ENRICH": "",
            "SEAM_BENCH_ENTITY_AGG": "",
            "SEAM_AGENT": "",
            "SEAM_RECORD_RETRIEVAL_EVENTS": "",
        }
        with patch.dict(os.environ, settings):
            return m1.run(tmp_path_factory.mktemp("m1-probe"))

    def test_historical_evidence_hash_is_unchanged(self):
        assert hashlib.sha256(self.EVIDENCE.read_bytes()).hexdigest() == self.EVIDENCE_SHA256

    def test_evidence_declares_its_schema(self, recorded):
        assert recorded["schema"] == "seam-m1-formation-observations/v1"
        assert recorded["synthetic_inputs_only"] is True
        assert recorded["quality_benchmark"] is False
        assert recorded["provider_calls"] == 0

    @pytest.mark.parametrize("sample", sorted(m1.SAMPLES))
    def test_compiler_semantics_reproduce_without_generated_ids(
        self, recorded, reproduced, sample
    ):
        assert _compiler_semantics(reproduced["compiler"][sample]) == _compiler_semantics(
            recorded["compiler"][sample]
        )

    def test_long_unpunctuated_missing_bound_reproduces(self, recorded, reproduced):
        expected = {
            "input_recipe": "word plus space repeated 2000 times",
            "input_characters": 10000,
            "span_count": 1,
            "maximum_span_characters": 9999,
            "raw_exact": True,
        }
        assert reproduced["compiler"]["unpunctuated_long"] == expected
        assert recorded["compiler"]["unpunctuated_long"] == expected

    def test_unicode_zero_proposition_and_chunk_accounting_reproduce(
        self, recorded, reproduced
    ):
        for result in (recorded, reproduced):
            compiler = result["compiler"]["unicode"]
            assert compiler["kinds"] == {"PROV": 1, "RAW": 1}
            assert compiler["claims"] == []
            assert compiler["span_count"] == 0
            assert compiler["raw_exact"] is True

            persisted = result["persisted_unicode"]
            assert persisted["kinds"] == {"PROV": 1, "RAW": 1}
            assert persisted["claims"] == []
            assert persisted["span_count"] == 0
            assert persisted["ingest_chunk_count"] == 1
            assert persisted["ingest_extraction_status"] == "compiled"

    def test_abbreviation_and_newline_segmentation_reproduce(self, recorded, reproduced):
        for result in (recorded, reproduced):
            abbreviation = result["compiler"]["abbreviation"]
            assert [claim["text"] for claim in abbreviation["claims"]] == [
                "Dr.",
                "Chen moved to Oslo.",
                "She works there.",
            ]
            assert [claim["subject_label"] for claim in abbreviation["claims"]] == [
                "Dr",
                "Chen",
                "She",
            ]

            newline = result["compiler"]["newline_speakers"]
            assert newline["span_count"] == 1
            assert _claim_semantics(newline) == [
                {
                    "text": "Alice: I like tea\nBob: I like coffee",
                    "predicate": "content",
                    "subject_label": "Alice",
                    "t0": None,
                    "t1": None,
                    "status": "asserted",
                }
            ]

    def test_temporal_prose_has_no_structured_time_records(self, recorded, reproduced):
        for result in (recorded, reproduced):
            state_changes = result["compiler"]["state_changes"]
            assert "EVT" not in state_changes["kinds"]
            assert "STA" not in state_changes["kinds"]
            assert [claim["predicate"] for claim in state_changes["claims"]] == [
                "content",
                "content",
            ]
            assert all(
                claim["t0"] is None and claim["t1"] is None
                for claim in state_changes["claims"]
            )
            assert all(
                claim["t0"] is None and claim["t1"] is None
                for claim in result["adapter"]["claims"]
            )
            assert all(
                raw["source_metadata"] is None for raw in result["adapter"]["raw"]
            )

    def test_storage_text_column_checks_reproduce(self, recorded, reproduced):
        """The finding: blip_caption metadata never reaches storage."""
        assert reproduced["adapter"]["text_column_checks"] == recorded["adapter"]["text_column_checks"]

    def test_known_present_control_is_found(self, reproduced):
        """Validates the negative checks: a term that IS stored must be found."""
        checks = reproduced["adapter"]["text_column_checks"]
        assert checks["painting"] == 1, "negative checks are vacuous if this fails"
        assert checks["museum"] == 1

    def test_unstated_sentinel_is_absent(self, reproduced):
        assert reproduced["adapter"]["text_column_checks"]["M1_UNSTATED_SENTINEL"] == 0

    def test_caption_metadata_is_dropped(self, reproduced):
        """M1's context-loss finding, stated as an executable expectation."""
        assert reproduced["adapter"]["text_column_checks"]["M1_CAPTION_CEDAR"] == 0

    def test_loader_collapses_distinct_dialogue_ids(self, recorded, reproduced):
        """Distinct dia_ids with identical text load as equal turns."""
        for result in (recorded, reproduced):
            loader = result["loader"]
            assert loader["distinct_input_dialogue_ids"] == ["D1:1", "D1:2"]
            assert loader["loaded_turns_equal"] is True
            assert len(loader["output_turns"]) == 2
            assert loader["output_turns"][0] == loader["output_turns"][1]
            assert set(loader["output_turns"][0]) == {"speaker", "text", "timestamp"}

    def test_duplicate_loaded_events_collapse_to_one_raw(self, recorded, reproduced):
        for result in (recorded, reproduced):
            museum_raws = [
                raw
                for raw in result["adapter"]["raw"]
                if "visited the museum" in raw["content"]
            ]
            assert len(museum_raws) == 1

    def test_distinct_source_refs_stay_distinct(self, reproduced):
        """The control: distinct source references must NOT collapse."""
        assert len(reproduced["distinct_source_reference_control"]["raw"]) == 2

    def test_adapter_first_person_claims_share_one_persisted_subject(
        self, recorded, reproduced
    ):
        for result in (recorded, reproduced):
            claims = {claim["text"]: claim for claim in result["adapter"]["claims"]}
            painting = claims["I enjoy painting."]
            hiking = claims["I enjoy hiking."]
            assert painting["subject_label"] == hiking["subject_label"] == "I"
            assert painting["subject_id"] == hiking["subject_id"]

    def test_graph_projection_counts_reproduce(self, recorded, reproduced):
        assert reproduced["adapter"]["graph_edge_count"] == recorded["adapter"]["graph_edge_count"]
        assert reproduced["adapter"]["canonical_relation_rows"] == recorded["adapter"]["canonical_relation_rows"]

    def test_graph_product_build_semantics_reproduce(self, recorded, reproduced):
        fields = (
            "algorithm_version",
            "accepted_fact_count",
            "rejected_fact_count",
            "product_count",
            "reused",
        )
        for field in fields:
            assert reproduced["adapter"]["graph_product_build"][field] == recorded[
                "adapter"
            ]["graph_product_build"][field]
        assert reproduced["adapter"]["graph_product_build"]["accepted_fact_count"] == 5
        assert reproduced["adapter"]["graph_product_build"]["product_count"] == 14

    def test_shared_first_person_attribution_reaches_graph_observation(
        self, recorded, reproduced
    ):
        for result in (recorded, reproduced):
            products = result["adapter"]["graph_products"]
            observations = [product for product in products if product["kind"] == "observation"]
            assert len(observations) == 1
            observation = observations[0]
            assert observation["payload"] == {
                "entity_id": observation["subject_id"],
                "episode_count": 2,
                "predicate": "content",
                "record_count": 2,
            }
            assert len(observation["sentences"]) == 1
            sentence = observation["sentences"][0]
            assert sentence["text"] == "I has recurring content evidence across 2 episodes."
            assert len(set(sentence["supporting_episode_ids"])) == 2
            claim_text_by_id = {
                claim["id"]: claim["text"] for claim in result["adapter"]["claims"]
            }
            assert {
                claim_text_by_id[record_id]
                for record_id in sentence["supporting_record_ids"]
            } == {"I enjoy painting.", "I enjoy hiking."}

    def test_embedding_model_identity_is_pinned(self, recorded, reproduced):
        assert reproduced["adapter"]["embedding_model"] == recorded["adapter"]["embedding_model"]
        assert reproduced["adapter"]["embedding_model"] == PINNED_MODEL

    def test_retrieval_is_evidence_only_not_generation(self, reproduced):
        retrieval = reproduced["adapter"]["retrieval"]
        assert retrieval["generated_answer"] is None, "probe must not generate answers"
        assert "painting" in retrieval["context"]
