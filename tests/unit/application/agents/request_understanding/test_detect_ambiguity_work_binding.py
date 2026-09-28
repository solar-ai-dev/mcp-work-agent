"""Same-Run WorkUnit authority survives the actual ambiguity Prompt projection."""

from copy import deepcopy
from typing import Any, cast

import pytest
from tests.support.fakes.llm import FakeStructuredInferencePort

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestGoalCandidateV1,
)
from google_work_agent.application.agents.request_understanding.detect_ambiguity import (
    RequestAmbiguityValidationError,
    detect_ambiguity,
)
from google_work_agent.application.prompt_runtime.load_prompt_input_contract import (
    load_prompt_input_contract,
)
from google_work_agent.application.prompt_runtime.prompt_registry import PromptRegistry
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.system.contracts.workflow_execution import (
    SelectedResourceRef,
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)

_REQUEST = "Alpha 일정 제목을 A로 바꾸고, 다른 일정 시간은 15시로 바꿔줘."


def _candidate() -> RequestGoalCandidateV1:
    split = _REQUEST.index("다른")
    return cast(
        RequestGoalCandidateV1,
        {
            "goal": _REQUEST,
            "completion_conditions": ["각 일정의 변경안을 준비한다"],
            "constraints": [
                {
                    "kind": "USER_REQUIREMENT",
                    "field": "search_terms",
                    "value": "Alpha",
                    "work_unit_ids": ["work-1"],
                    "provenance": {"source": "USER_REQUEST", "start_offset": 0, "end_offset": 5},
                }
            ],
            "requested_effect_hints": ["READ", "UPDATE"],
            "requested_resource_hints": ["CALENDAR_EVENT"],
            "analysis_requirement": "NONE",
            "effect_prohibitions": [],
            "requested_work": {
                "work_units": [
                    {
                        "unit_id": unit_id,
                        "request_provenance": [
                            {"source": "USER_REQUEST", "start_offset": start, "end_offset": end}
                        ],
                    }
                    for unit_id, start, end in [
                        ("work-1", 0, split),
                        ("work-2", split, len(_REQUEST)),
                    ]
                ],
                "work_relations": [],
            },
            "resource_responsibilities": {
                "source_reads": [
                    {
                        "resource_type": "CALENDAR_EVENT",
                        "required_information": ["event_identity", fact],
                        "target_scope": "SINGULAR",
                        "work_unit_ids": [unit_id],
                    }
                    for unit_id, fact in [("work-1", "title"), ("work-2", "start")]
                ],
                "outputs": [
                    {
                        "resource_type": "CALENDAR_EVENT",
                        "effect": "UPDATE",
                        "work_unit_ids": [unit_id],
                    }
                    for unit_id in ["work-1", "work-2"]
                ],
            },
        },
    )


def _infer(
    candidate: RequestGoalCandidateV1,
    *,
    owner: str = "NONE",
    missing_fields: list[str] | None = None,
    selected: tuple[SelectedResourceRef, ...] = (),
) -> tuple[dict[str, Any], Any]:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "missing_information_owner": owner,
                "missing_fields": missing_fields or [],
            }
        ]
    )
    request = WorkflowStartRequest(
        run_id="run-binding",
        conversation_id="conversation-binding",
        workflow_key="binding",
        entry_mode="RESOURCE_SELECTED" if selected else "AGENT_SEARCH",
        requested_mode="AUTO",
        request_text=_REQUEST,
        selected_resource_ids=tuple(item.resource_id for item in selected),
        selected_resources=selected,
        run_budget=cast(dict[str, Any], build_default_run_budget()),
        correlation=WorkflowCorrelationContext(
            request_id="request-binding",
            command_id="command-binding",
            api_contract_version="v1",
        ),
    )
    result, _ = detect_ambiguity(
        llm_runtime=runtime,
        request=request,
        goal_candidate=candidate,
        prompt_ref=PromptRegistry().lookup_for_development_smoke(
            "request_understanding.detect_ambiguity"
        ),
        retry_budget=build_default_run_budget(),
    )
    assert len(runtime.calls) == 1
    actual = cast(dict[str, Any], runtime.calls[0]["prompt_input"])
    load_prompt_input_contract().validate_projection(
        "request_understanding.detect_ambiguity", actual
    )
    return actual, result


def test_actual_ambiguity_input_preserves_existing_work_and_all_item_bindings() -> None:
    candidate = _candidate()
    original = deepcopy(candidate)
    actual, _ = _infer(candidate)
    projected = actual["goal_candidate"]
    assert projected["requested_work"] == candidate["requested_work"]
    assert projected["resource_responsibilities"] == candidate["resource_responsibilities"]
    assert projected["constraints"] == candidate["constraints"]
    assert "requested_effect_hints" not in projected
    assert "requested_resource_hints" not in projected
    assert candidate == original
    for unit in projected["requested_work"]["work_units"]:
        span = unit["request_provenance"][0]
        assert _REQUEST[span["start_offset"] : span["end_offset"]]
    projected["requested_work"]["work_units"][0]["unit_id"] = "changed-copy"
    projected["resource_responsibilities"]["source_reads"][0]["work_unit_ids"].append(
        "changed-copy"
    )
    projected["constraints"][0]["work_unit_ids"].append("changed-copy")
    assert candidate == original


def test_source_work_binding_swap_changes_actual_infer_input() -> None:
    first = _candidate()
    second = deepcopy(first)
    second["resource_responsibilities"]["source_reads"][0]["work_unit_ids"] = ["work-2"]
    second["resource_responsibilities"]["source_reads"][1]["work_unit_ids"] = ["work-1"]
    actual_first, _ = _infer(first)
    actual_second, _ = _infer(second)
    assert actual_first != actual_second
    assert (
        actual_first["goal_candidate"]["resource_responsibilities"]["outputs"]
        == (actual_second["goal_candidate"]["resource_responsibilities"]["outputs"])
    )


def test_connector_information_keeps_its_existing_source_work_reference() -> None:
    candidate = _candidate()
    actual, _ = _infer(candidate)
    for item in actual["resolution_responsibilities"]["connector_owned_information"]:
        index = int(item["responsibility_path"].rsplit("[", 1)[1][:-1])
        assert (
            item["work_unit_ids"]
            == (candidate["resource_responsibilities"]["source_reads"][index]["work_unit_ids"])
        )


def test_legacy_without_work_metadata_does_not_invent_new_work_identity() -> None:
    candidate = _candidate()
    raw = cast(dict[str, Any], candidate)
    raw.pop("requested_work")
    for item in raw["constraints"]:
        item.pop("work_unit_ids")
    for collection in raw["resource_responsibilities"].values():
        for item in collection:
            item.pop("work_unit_ids")
    actual, result = _infer(candidate)
    assert "requested_work" not in actual["goal_candidate"]
    assert all(
        "work_unit_ids" not in item
        for item in (actual["goal_candidate"]["resource_responsibilities"]["source_reads"])
    )
    assert result["requires_confirmation"] is False


def test_prompt_reference_and_runtime_input_contract_declare_work_carry_version() -> None:
    slot = "request_understanding.detect_ambiguity"
    reference = PromptRegistry().lookup_for_development_smoke(slot)
    assert reference.input_schema_version == "3"
    assert reference.output_schema_version == "2"
    assert load_prompt_input_contract().entry(slot).input_schema_version == 3


def test_multi_work_user_target_gap_is_not_satisfied_by_another_work_anchor() -> None:
    candidate = _candidate()
    original = deepcopy(candidate)
    _, result = _infer(candidate, owner="USER", missing_fields=["target_resource"])
    assert result["requires_confirmation"] is True
    assert result["missing_fields"] == ["target_resource"]
    assert candidate == original


@pytest.mark.parametrize("field", ["target_resource", "event_identity"])
def test_selected_type_does_not_prove_all_same_resource_work_targets_are_resolved(
    field: str,
) -> None:
    candidate = _candidate()
    candidate["constraints"] = []
    _, result = _infer(
        candidate,
        owner="USER",
        missing_fields=[field],
        selected=(
            SelectedResourceRef("event-ref", "google_workspace", "calendar_event", "event-1"),
        ),
    )
    assert result["requires_confirmation"] is True
    assert result["missing_fields"] == [field]


@pytest.mark.parametrize("legacy", [False, True])
def test_single_work_or_legacy_target_rules_are_unchanged(legacy: bool) -> None:
    candidate = _candidate()
    candidate["requested_work"]["work_units"] = candidate["requested_work"]["work_units"][:1]
    candidate["resource_responsibilities"]["source_reads"] = candidate["resource_responsibilities"][
        "source_reads"
    ][:1]
    candidate["resource_responsibilities"]["outputs"] = candidate["resource_responsibilities"][
        "outputs"
    ][:1]
    if legacy:
        cast(dict[str, Any], candidate).pop("requested_work")
    _, result = _infer(candidate, owner="USER", missing_fields=["target_resource"])
    assert result["requires_confirmation"] is False
    candidate["constraints"] = []
    with pytest.raises(RequestAmbiguityValidationError) as error:
        _infer(
            candidate,
            owner="USER",
            missing_fields=["event_identity"],
            selected=(
                SelectedResourceRef("event-ref", "google_workspace", "calendar_event", "event-1"),
            ),
        )
    assert error.value.reason_code == "REQUEST_AMBIGUITY_TARGET_ANCHOR_CONFLICT"


@pytest.mark.parametrize("owner,missing_fields", [("NONE", []), ("CONNECTOR", ["start"])])
def test_multi_work_non_user_ambiguity_is_not_reclassified(
    owner: str, missing_fields: list[str]
) -> None:
    _, result = _infer(_candidate(), owner=owner, missing_fields=missing_fields)
    assert result == {"requires_confirmation": False, "reason_codes": [], "missing_fields": []}
