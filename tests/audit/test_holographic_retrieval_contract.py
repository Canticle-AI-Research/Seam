from __future__ import annotations

import pytest

from seam_runtime.holographic import context_surface, encode_surface, query_surface
from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind


def test_mirl_surface_query_and_context_fail_closed_on_invalid_ir(tmp_path):
    invalid = IRBatch(
        [
            MIRLRecord(
                id="clm:invalid",
                kind=RecordKind.CLM,
                ns="work",
                scope="thread",
                attrs={},
            )
        ]
    )
    surface = tmp_path / "invalid-mirl.seam.png"
    encode_surface(
        invalid.to_text().encode("utf-8"),
        surface,
        mode="bw1",
        payload_format="MIRL",
    )

    with pytest.raises(ValueError):
        query_surface(surface, "anything")
    with pytest.raises(ValueError):
        context_surface(surface, "anything")
