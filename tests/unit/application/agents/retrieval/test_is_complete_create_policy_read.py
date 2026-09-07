from typing import cast

import pytest

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    AcquisitionResultV1,
)
from google_work_agent.application.agents.retrieval.is_complete_create_policy_read import (
    is_complete_create_policy_read,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    ToolRoutePlanV2,
)


@pytest.mark.parametrize(
    "resource,inputs,reason",
    [
        ("TASK", ["TASK", "TASK_LIST"], "POLICY_TASK_DUPLICATE_CHECK"),
        (
            "CALENDAR_EVENT",
            ["CALENDAR", "CALENDAR_EVENT", "CALENDAR_FREEBUSY"],
            "POLICY_CALENDAR_CONFLICT_CHECK",
        ),
    ],
)
@pytest.mark.parametrize("incomplete", [False, True])
@pytest.mark.parametrize("explicit_policy_hints", [False, True])
def test_is_complete_create_policy_read__policy_routes__requires_every_source_complete(
    resource: str,
    inputs: list[str],
    reason: str,
    incomplete: bool,
    explicit_policy_hints: bool,
) -> None:
    result = is_complete_create_policy_read(
        request_intent=cast(
            RequestIntentV2,
            {
                "analysis_requirement": "NONE",
                "requested_effect_hints": (
                    ["READ", "CREATE"] if explicit_policy_hints else ["CREATE"]
                ),
                "requested_resource_hints": inputs if explicit_policy_hints else [resource],
            },
        ),
        tool_route_plan=cast(
            ToolRoutePlanV2,
            {
                "output_plan": {
                    "output_mode": "ACTION",
                    "output_routes": [
                        {"effect": "CREATE", "resource_type": resource},
                    ],
                },
                "input_plan": {
                    "input_routes": [
                        {
                            "route_id": item,
                            "resource_type": item,
                            "required": True,
                            "reason_codes": [reason],
                        }
                        for item in inputs
                    ]
                },
            },
        ),
        acquisition_result=cast(
            AcquisitionResultV1,
            {
                "status": "COMPLETE",
                "missing_slots": [],
                "source_summaries": [
                    {"route_id": item, "status": "FAILED" if incomplete and i == 0 else "COMPLETE"}
                    for i, item in enumerate(inputs)
                ],
            },
        ),
        confirmation_response=None,
    )
    assert result is not incomplete


def test_is_complete_create_policy_read__unrelated_requested_resource__is_not_complete() -> None:
    result = is_complete_create_policy_read(
        request_intent=cast(
            RequestIntentV2,
            {
                "analysis_requirement": "NONE",
                "requested_effect_hints": ["READ", "CREATE"],
                "requested_resource_hints": ["TASK", "TASK_LIST", "GMAIL_THREAD"],
            },
        ),
        tool_route_plan=cast(
            ToolRoutePlanV2,
            {
                "output_plan": {
                    "output_mode": "ACTION",
                    "output_routes": [
                        {"effect": "CREATE", "resource_type": "TASK"},
                    ],
                },
                "input_plan": {
                    "input_routes": [
                        {
                            "route_id": item,
                            "resource_type": item,
                            "required": True,
                            "reason_codes": ["POLICY_TASK_DUPLICATE_CHECK"],
                        }
                        for item in ("TASK", "TASK_LIST")
                    ]
                },
            },
        ),
        acquisition_result=cast(
            AcquisitionResultV1,
            {
                "status": "COMPLETE",
                "missing_slots": [],
                "source_summaries": [
                    {"route_id": item, "status": "COMPLETE"} for item in ("TASK", "TASK_LIST")
                ],
            },
        ),
        confirmation_response=None,
    )

    assert result is False
