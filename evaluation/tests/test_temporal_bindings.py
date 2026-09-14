from __future__ import annotations

from evaluation.harness.temporal_bindings import (
    load_temporal_bindings,
    validate_canonical_temporal_bindings,
)


def test_canonical_temporal_bindings_are_complete_and_deterministic() -> None:
    bindings = load_temporal_bindings()

    assert len(bindings) == 48
    assert validate_canonical_temporal_bindings() == []
    assert bindings["CASE-CORE-033"].isoformat() == "2026-08-07T09:00:00+09:00"
    assert bindings["CASE-CORE-035"].isoformat() == "2026-08-07T09:00:00+09:00"
    assert bindings["CASE-HOLDOUT-007"].isoformat() == "2026-09-02T09:00:00+09:00"
