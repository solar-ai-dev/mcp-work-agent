import pytest

from google_work_agent.application.agents.retrieval.project_query_temporal_constraints import (
    project_query_temporal_constraints,
)


def test_query_temporal_constraints__changed_query_and_detail__retains_initial_meaning() -> None:
    target = {
        "kind": "TEMPORAL_RANGE",
        "axis": "EVENT_TIME",
        "start_local": "2026-09-01T00:00:00",
        "end_local": "2026-09-08T00:00:00",
        "timezone": "Asia/Seoul",
    }
    initial = {
        "route_id": "gmail",
        "operation_kind": "SEARCH",
        "normalized_intent_constraints": [target],
    }
    later = {
        **initial,
        "normalized_intent_constraints": [{**target, "start_local": "2026-09-04T00:00:00"}],
    }
    assert project_query_temporal_constraints(
        [initial, later, {**later, "operation_kind": "DETAIL_FETCH"}]
    ) == [target]
    assert project_query_temporal_constraints([]) == []


def test_query_temporal_constraints__partial_contract__fails_closed() -> None:
    with pytest.raises(ValueError, match="fields are invalid"):
        project_query_temporal_constraints(
            [
                {
                    "route_id": "gmail",
                    "operation_kind": "SEARCH",
                    "normalized_intent_constraints": [
                        {"kind": "TEMPORAL_RANGE", "axis": "EVENT_TIME"}
                    ],
                }
            ]
        )
