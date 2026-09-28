from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from google_work_agent.application.agents.planning.project_request_intent_for_work_units import (
    project_request_intent_for_work_units,
)
from google_work_agent.application.agents.request_understanding.contracts import (
    request_goal_candidate_schema as goal_schema,
)
from google_work_agent.application.agents.request_understanding.finalize_intent import (
    finalize_intent,
)


def _candidate(source_reads: list[dict[str, Any]]) -> dict[str, Any]:
    requests = ("메일의 기한으로 초안을 만들어줘.", "작업 상태로 별도 초안을 만들어줘.")
    request_text = " ".join(requests)
    unit_ids = ("work-1", "work-2")
    constraints: dict[str, Any] = {
        field: []
        for field in (
            "search_terms",
            "business_concepts",
            "person",
            "sender",
            "recipient",
            "subject",
            "period",
            "additional_constraints",
        )
    }
    constraints["coverage_requirement"] = {
        "value": "NOT_COLLECTION",
        "work_unit_ids": list(unit_ids),
    }
    requested_work = {
        "work_units": [
            {
                "unit_id": unit_id,
                "request_provenance": [
                    {
                        "source": "USER_REQUEST",
                        "start_offset": request_text.index(text),
                        "end_offset": request_text.index(text) + len(text),
                        "source_text": text,
                    }
                ],
            }
            for unit_id, text in zip(unit_ids, requests, strict=True)
        ],
        "work_relations": [],
    }
    candidate = goal_schema.validate_request_goal_candidate(
        {
            "goal": request_text,
            "completion_conditions": list(requests),
            "constraints": constraints,
            "analysis_requirement": "NONE",
        },
        resource_responsibilities={
            "source_reads": source_reads,
            "outputs": [
                {"resource_type": "GMAIL_DRAFT", "effect": "CREATE", "work_unit_ids": [unit_id]}
                for unit_id in unit_ids
            ],
        },
        effect_prohibitions={"effect_prohibitions": []},
        requested_work=requested_work,
        work_unit_ids=unit_ids,
        schema=goal_schema.identify_goal_output_schema(unit_ids),
    )
    return finalize_intent(
        candidate,
        {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
        artifact_id="intent-bound-source-information",
        user_request=request_text,
    )


def _source(resource_type: str, facts: list[str], work_unit_ids: list[str]) -> dict[str, Any]:
    return {
        "resource_type": resource_type,
        "required_information": facts,
        "target_scope": "CRITERIA",
        "work_unit_ids": work_unit_ids,
    }


def _information(intent: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in intent["constraints"] if item["field"] == "required_information"]


def test_source_information__disjoint_work_bindings__survive_planning_projection() -> None:
    sources = [
        _source("GMAIL_THREAD", ["contract deadline"], ["work-1"]),
        _source("TASK", ["current status"], ["work-2"]),
    ]
    original = deepcopy(sources)
    intent = _candidate(sources)

    assert sources == original
    assert _information(intent) == [
        {
            "kind": "USER_REQUIREMENT",
            "field": "required_information",
            "value": ["contract deadline"],
            "work_unit_ids": ["work-1"],
        },
        {
            "kind": "USER_REQUIREMENT",
            "field": "required_information",
            "value": ["current status"],
            "work_unit_ids": ["work-2"],
        },
    ]
    for unit_id, expected in (("work-1", "contract deadline"), ("work-2", "current status")):
        projected = project_request_intent_for_work_units(intent, work_unit_ids=[unit_id])
        assert [item["value"] for item in _information(projected)] == [[expected]]
        assert projected["resource_responsibilities"]["outputs"] == [
            {
                "resource_type": "GMAIL_DRAFT",
                "effect": "CREATE",
                "work_unit_ids": [unit_id],
            }
        ]


@pytest.mark.parametrize("unit_id,own_fact", [("work-1", "due"), ("work-2", "start")])
def test_source_information__shared_and_local_bindings__remain_distinct(
    unit_id: str,
    own_fact: str,
) -> None:
    intent = _candidate(
        [
            _source("GMAIL_THREAD", ["common context"], ["work-1", "work-2"]),
            _source("TASK", ["due"], ["work-1"]),
            _source("CALENDAR_EVENT", ["start"], ["work-2"]),
        ]
    )
    projected = project_request_intent_for_work_units(intent, work_unit_ids=[unit_id])

    assert [item["value"] for item in _information(projected)] == [["common context"], [own_fact]]
    assert all("provenance" not in item for item in _information(intent))
    assert _information(intent)[0]["work_unit_ids"] == ["work-1", "work-2"]


def test_source_information__same_binding__deduplicates_without_extra_constraints() -> None:
    intent = _candidate(
        [
            _source("GMAIL_THREAD", ["due", "owner"], ["work-1"]),
            _source("TASK", ["owner", "status"], ["work-1"]),
        ]
    )

    assert [item["value"] for item in _information(intent)] == [["due", "owner", "status"]]
    assert not _information(project_request_intent_for_work_units(intent, work_unit_ids=["work-2"]))


def test_source_information__no_sources__does_not_invent_requirement() -> None:
    assert not _information(_candidate([]))
