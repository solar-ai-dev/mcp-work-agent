"""Confirmation must not erase already-resolved ownership while merging equal values."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, cast

import pytest

from google_work_agent.application.agents.planning.project_request_intent_for_work_units import (
    project_request_intent_for_work_units,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    ConstraintV1,
    RequestGoalCandidateV1,
)
from google_work_agent.application.agents.request_understanding.finalize_intent import (
    finalize_intent,
)
from google_work_agent.application.agents.request_understanding.identify_goal import (
    _merge_confirmation_constraints,
    _same_confirmation_constraint,
)

_ADDRESS = "same@example.test"
_REQUEST = f"Prepare report draft to {_ADDRESS}. Prepare notice draft."


def _recipient(work_ids: list[str]) -> ConstraintV1:
    return {
        "kind": "EMAIL",
        "field": "recipient",
        "value": _ADDRESS,
        "work_unit_ids": work_ids,
    }


def _prior() -> RequestGoalCandidateV1:
    spans = [f"Prepare report draft to {_ADDRESS}.", "Prepare notice draft."]
    units = [
        {
            "unit_id": f"work-{index + 1}",
            "request_provenance": [
                {
                    "source": "USER_REQUEST",
                    "start_offset": _REQUEST.index(span),
                    "end_offset": _REQUEST.index(span) + len(span),
                    "source_text": span,
                }
            ],
        }
        for index, span in enumerate(spans)
    ]
    return cast(
        RequestGoalCandidateV1,
        {
            "goal": _REQUEST,
            "completion_conditions": ["Prepare both drafts without sending."],
            "constraints": [_recipient(["work-1"])],
            "requested_effect_hints": ["CREATE"],
            "requested_resource_hints": ["GMAIL_DRAFT"],
            "analysis_requirement": "NONE",
            "effect_prohibitions": [{"effect": "SEND", "work_unit_ids": ["work-1", "work-2"]}],
            "requested_work": {"work_units": units, "work_relations": []},
            "resource_responsibilities": {
                "source_reads": [],
                "outputs": [
                    {"resource_type": "GMAIL_DRAFT", "effect": "CREATE", "work_unit_ids": [unit_id]}
                    for unit_id in ("work-1", "work-2")
                ],
            },
        },
    )


@pytest.mark.parametrize("work_ids", [["work-2"], ["work-1", "work-2"]])
def test_equal_recipient_with_distinct_work_binding_survives_finalize_and_planning(
    work_ids: list[str],
) -> None:
    prior = _prior()
    resolved = cast(RequestGoalCandidateV1, {**prior, "constraints": [_recipient(work_ids)]})
    before = deepcopy((prior, resolved))

    merged = _merge_confirmation_constraints(prior, resolved, confirmation_text=_ADDRESS)
    finalized = finalize_intent(
        merged,
        {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
        artifact_id="confirmation-binding",
        user_request=_REQUEST,
        confirmation_response_text=_ADDRESS,
    )
    projected = project_request_intent_for_work_units(finalized, work_unit_ids=["work-2"])

    assert len(merged["constraints"]) == 2
    assert merged["constraints"][0]["work_unit_ids"] == ["work-1"]
    assert merged["constraints"][1]["work_unit_ids"] == work_ids
    assert len(projected["constraints"]) == 1
    assert projected["constraints"][0]["value"] == _ADDRESS
    assert projected["constraints"][0]["work_unit_ids"] == ["work-2"]
    assert projected["constraints"][0]["provenance"]["source"] == "CONFIRMATION_RESPONSE"
    assert (prior, resolved) == before


def test_equal_binding_with_reordered_ids_is_still_deduplicated() -> None:
    prior = _prior()
    prior["constraints"] = [_recipient(["work-1", "work-2"])]
    resolved = cast(
        RequestGoalCandidateV1,
        {
            **prior,
            "constraints": [_recipient(["work-2", "work-1"])],
        },
    )
    result = _merge_confirmation_constraints(prior, resolved, confirmation_text=_ADDRESS)
    assert result["constraints"] == prior["constraints"]


def test_distinct_current_run_provenance_is_not_collapsed() -> None:
    prior = _prior()
    start = _REQUEST.index(_ADDRESS)
    prior["constraints"][0]["provenance"] = {
        "source": "USER_REQUEST",
        "start_offset": start,
        "end_offset": start + len(_ADDRESS),
    }
    confirmed = _recipient(["work-1"])
    confirmed["provenance"] = {
        "source": "CONFIRMATION_RESPONSE",
        "start_offset": 0,
        "end_offset": len(_ADDRESS),
    }
    resolved = cast(RequestGoalCandidateV1, {**prior, "constraints": [confirmed]})
    result = _merge_confirmation_constraints(prior, resolved, confirmation_text=_ADDRESS)
    assert result["constraints"] == [prior["constraints"][0], confirmed]


def test_source_resource_and_provenance_are_part_of_constraint_identity() -> None:
    status: ConstraintV1 = {
        "kind": "SCOPE",
        "field": "status",
        "value": "SENT",
        "source_resource_type": "GMAIL_THREAD",
        "work_unit_ids": ["work-1"],
        "provenance": {
            "source": "USER_REQUEST",
            "start_offset": 0,
            "end_offset": 4,
            "source_text": "sent",
        },
    }
    assert _same_confirmation_constraint(status, deepcopy(status))
    changed_resource = cast(ConstraintV1, {**status, "source_resource_type": "GMAIL_MESSAGE"})
    assert not _same_confirmation_constraint(status, changed_resource)
    changed_span = deepcopy(status)
    changed_span["provenance"]["start_offset"] = 10
    changed_span["provenance"]["end_offset"] = 14
    assert not _same_confirmation_constraint(status, changed_span)


def test_confirmed_values_do_not_reopen_goal_output_status_or_prohibitions() -> None:
    prior = _prior()
    prefix = "Find completed tasks. "
    request_text = prefix + _REQUEST
    prior["goal"] = request_text
    for unit in prior["requested_work"]["work_units"]:
        for span in unit["request_provenance"]:
            span["start_offset"] += len(prefix)
            span["end_offset"] += len(prefix)
    prior["requested_work"]["work_units"][0]["request_provenance"].insert(
        0,
        {
            "source": "USER_REQUEST",
            "start_offset": 0,
            "end_offset": len(prefix) - 1,
            "source_text": prefix[:-1],
        },
    )
    prior["requested_effect_hints"] = ["READ", "CREATE"]
    prior["requested_resource_hints"].append("TASK")
    prior["resource_responsibilities"]["source_reads"] = [
        {
            "resource_type": "TASK",
            "required_information": ["requested tasks"],
            "target_scope": "CRITERIA",
            "work_unit_ids": ["work-1"],
        }
    ]
    prior["constraints"].append(
        {
            "kind": "USER_REQUIREMENT",
            "field": "required_information",
            "value": ["requested tasks"],
            "work_unit_ids": ["work-1"],
        }
    )
    status_start = request_text.index("completed")
    status = cast(
        ConstraintV1,
        {
            "kind": "SCOPE",
            "field": "status",
            "value": "COMPLETED",
            "source_resource_type": "TASK",
            "work_unit_ids": ["work-1"],
            "provenance": {
                "source": "USER_REQUEST",
                "start_offset": status_start,
                "end_offset": status_start + len("completed"),
                "source_text": "completed",
            },
        },
    )
    prior["constraints"].append(status)
    resolved = cast(
        RequestGoalCandidateV1,
        {
            **prior,
            "goal": "must not overwrite prior goal",
            "completion_conditions": ["must not overwrite prior conditions"],
            "effect_prohibitions": [],
            "constraints": [
                _recipient(["work-2"]),
                {**status, "value": "INCOMPLETE"},
                {
                    "kind": "RESOURCE",
                    "field": "title",
                    "value": "unconfirmed",
                    "work_unit_ids": ["work-2"],
                },
            ],
        },
    )
    result = _merge_confirmation_constraints(
        prior, resolved, confirmation_text=f"{_ADDRESS} INCOMPLETE"
    )
    finalized = finalize_intent(
        result,
        {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
        artifact_id="preserved-source-status",
        user_request=request_text,
        confirmation_response_text=f"{_ADDRESS} INCOMPLETE",
    )
    assert [item for item in finalized["constraints"] if item["field"] == "status"] == [status]
    assert result["constraints"] == [*prior["constraints"], _recipient(["work-2"])]
    for field in (
        "goal",
        "completion_conditions",
        "resource_responsibilities",
        "effect_prohibitions",
        "requested_work",
        "analysis_requirement",
    ):
        assert cast(dict[str, Any], result)[field] == cast(dict[str, Any], prior)[field]


def test_only_confirmation_bound_list_values_are_merged() -> None:
    prior = _prior()
    resolved = cast(
        RequestGoalCandidateV1,
        {
            **prior,
            "constraints": [
                {**_recipient(["work-2"]), "value": [_ADDRESS, "not-confirmed@test.invalid"]}
            ],
        },
    )
    result = _merge_confirmation_constraints(prior, resolved, confirmation_text=_ADDRESS)
    assert result["constraints"][-1] == {**_recipient(["work-2"]), "value": [_ADDRESS]}


@pytest.mark.parametrize("confirmation_text", [None, ""])
def test_absent_confirmation_preserves_the_original_candidate(
    confirmation_text: str | None,
) -> None:
    prior = _prior()
    assert (
        _merge_confirmation_constraints(prior, deepcopy(prior), confirmation_text=confirmation_text)
        is prior
    )
