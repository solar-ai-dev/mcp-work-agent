import pytest

from google_work_agent.application.agents.planning.select_required_output_routes import (
    select_required_output_routes,
)


def _route(route_id: str) -> dict[str, object]:
    return {"route_id": route_id, "resource_type": "GITHUB_ISSUE", "effect": "UPDATE"}


def test_partial_no_action__in_planning__keeps_only_required_route() -> None:
    plan = {"output_mode": "ACTION", "output_routes": [_route("close"), _route("update")]}
    analysis = {
        "route_action_necessities": [
            {
                "route_id": "close",
                "status": "NOT_REQUIRED",
                "reason": "already closed",
                "evidence_refs": ["ev-1"],
                "candidate_refs": [],
            },
            {
                "route_id": "update",
                "status": "REQUIRED",
                "reason": "body differs",
                "evidence_refs": ["ev-1"],
                "candidate_refs": [],
            },
        ]
    }

    selected = select_required_output_routes(plan, work_analysis=analysis)

    assert selected["output_routes"] == [_route("update")]


def test_all_routes_not_required__in_planning__produces_empty_action_set() -> None:
    plan = {"output_mode": "ACTION", "output_routes": [_route("close")]}
    analysis = {
        "route_action_necessities": [
            {
                "route_id": "close",
                "status": "NOT_REQUIRED",
                "reason": "already closed",
                "evidence_refs": ["ev-1"],
                "candidate_refs": [],
            }
        ]
    }

    assert select_required_output_routes(plan, work_analysis=analysis)["output_routes"] == []


def test_undetermined_route__in_planning__is_not_reinterpreted() -> None:
    plan = {"output_mode": "ACTION", "output_routes": [_route("close")]}
    analysis = {
        "route_action_necessities": [
            {
                "route_id": "close",
                "status": "UNDETERMINED",
                "reason": "observation incomplete",
                "evidence_refs": [],
                "candidate_refs": [],
            }
        ]
    }

    with pytest.raises(ValueError, match="undetermined"):
        select_required_output_routes(plan, work_analysis=analysis)


@pytest.mark.parametrize(
    "assessments",
    [
        [],
        [
            {
                "route_id": "other",
                "status": "NOT_REQUIRED",
                "reason": "wrong route",
                "evidence_refs": ["ev-1"],
                "candidate_refs": [],
            }
        ],
        [
            {
                "route_id": "close",
                "status": "UNKNOWN",
                "reason": "invalid status",
                "evidence_refs": ["ev-1"],
                "candidate_refs": [],
            }
        ],
    ],
)
def test_invalid_route_assessment__in_planning__fails_closed(
    assessments: list[dict[str, object]],
) -> None:
    plan = {"output_mode": "ACTION", "output_routes": [_route("close")]}

    with pytest.raises(ValueError, match="route action necessit"):
        select_required_output_routes(
            plan,
            work_analysis={"route_action_necessities": assessments},
        )
