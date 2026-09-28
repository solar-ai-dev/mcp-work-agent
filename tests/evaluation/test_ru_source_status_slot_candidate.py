"""Explicit slot choice and existing guards; no live model or Provider calls."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
from scripts.evaluate_work_bound_source_status import (
    PROMPT_ID,
    fixed_cases,
    owner_input,
    owner_instruction,
)
from scripts.ru_source_status_slot_candidate import (
    build_slot_source_status_schema,
    normalize_slot_source_statuses,
    project_slot_source_statuses,
    slot_source_status_instruction,
    source_status_slots,
)

from google_work_agent.adapters.llm.runtime.schema_repair_scope import (
    find_out_of_scope_schema_repair_changes,
)
from google_work_agent.application.prompt_runtime.prompt_registry import PromptRegistry
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema


def _schema(case: dict[str, Any]) -> Any:
    return build_slot_source_status_schema(
        case["responsibilities"], case["prompt_input"]["requested_work"]
    ).json_schema


def _filter(value: str, text: str, source: str = "USER_REQUEST") -> dict[str, Any]:
    return {
        "decision": "STATUS_FILTER",
        "predicates": [{"value": value, "source": source, "source_text": text}],
    }


def _normalize(case: dict[str, Any], output: Any, **kwargs: Any) -> Any:
    return normalize_slot_source_statuses(
        output,
        responsibilities=case["responsibilities"],
        requested_work=case["prompt_input"]["requested_work"],
        provenance_sources=kwargs.get(
            "provenance_sources", {"USER_REQUEST": case["prompt_input"]["user_request"]}
        ),
    )


def test_slots_are_only_deduplicated_confirmed_source_work_membership() -> None:
    case = fixed_cases()[0]
    responsibilities = case["responsibilities"]
    responsibilities["source_reads"].append(deepcopy(responsibilities["source_reads"][0]))
    assert source_status_slots(responsibilities, case["prompt_input"]["requested_work"]) == {
        "slot_1": ("TASK", "work-1"),
        "slot_2": ("TASK", "work-2"),
    }
    responsibilities["source_reads"].pop(1)
    assert source_status_slots(responsibilities, case["prompt_input"]["requested_work"]) == {
        "slot_1": ("TASK", "work-1")
    }


def test_opposite_statuses_bind_without_union_or_semantic_reinterpretation() -> None:
    case = fixed_cases()[0]
    output = {
        "source_status_slots": {
            "slot_1": _filter("INCOMPLETE", "미완료 Task"),
            "slot_2": _filter("COMPLETED", "완료 Task"),
        }
    }
    normalized = _normalize(case, output)
    assert [(item["value"], item["work_unit_ids"]) for item in normalized] == [
        ("INCOMPLETE", ["work-1"]),
        ("COMPLETED", ["work-2"]),
    ]
    assert output["source_status_slots"]["slot_1"]["predicates"][0]["source_text"] == "미완료 Task"


@pytest.mark.parametrize(
    "output",
    [
        {},
        {"source_status_slots": {}},
        {"source_status_slots": {"slot_1": {"decision": "NO_FILTER"}}},
        {
            "source_status_slots": {
                "slot_1": {"decision": "STATUS_FILTER", "predicates": []},
                "slot_2": {"decision": "NO_FILTER"},
            }
        },
        {
            "source_status_slots": {
                "slot_1": {"decision": "NO_FILTER", "predicates": []},
                "slot_2": {"decision": "NO_FILTER"},
            }
        },
    ],
)
def test_missing_or_empty_decisions_are_not_defaulted_to_no_filter(output: Any) -> None:
    with pytest.raises(ValueError, match="invalid"):
        _normalize(fixed_cases()[0], output)


def test_explicit_no_filter_and_unknown_slot_resource_status_are_closed() -> None:
    case = fixed_cases()[3]
    output = {
        "source_status_slots": {
            "slot_1": {"decision": "NO_FILTER"},
            "slot_2": {"decision": "NO_FILTER"},
        }
    }
    assert _normalize(case, output) == []
    unknown = deepcopy(output)
    unknown["source_status_slots"]["slot_3"] = {"decision": "NO_FILTER"}
    assert validate_output_schema(unknown, _schema(case))
    for value in ("ANY", "CANCELLED", "OPEN"):
        invalid = deepcopy(output)
        invalid["source_status_slots"]["slot_1"] = _filter(value, "Task")
        assert validate_output_schema(invalid, _schema(case))


def test_intrinsic_draft_source_adds_no_status_slot_and_no_model_decision() -> None:
    case = fixed_cases()[0]
    for source in case["responsibilities"]["source_reads"]:
        source["resource_type"] = "GMAIL_DRAFT"
    assert (
        source_status_slots(case["responsibilities"], case["prompt_input"]["requested_work"]) == {}
    )
    assert _normalize(case, {"source_status_slots": {}}) == []
    assert validate_output_schema(
        {"source_status_slots": {"slot_1": {"decision": "NO_FILTER"}}}, _schema(case)
    )


def test_multiple_allowed_status_predicates_do_not_force_a_workunit_count() -> None:
    case = fixed_cases()[4]
    output = {"source_status_slots": {"slot_1": _filter("INCOMPLETE", "작업")}}
    output["source_status_slots"]["slot_1"]["predicates"].append(
        {"value": "COMPLETED", "source": "USER_REQUEST", "source_text": "작업"}
    )
    # Structurally expressible; these predicates are not semantically justified in CORE005.
    assert len(_normalize(case, output)) == 2


def test_existing_exact_provenance_guard_is_not_weakened() -> None:
    case = fixed_cases()[0]
    output = {
        "source_status_slots": {
            "slot_1": _filter("INCOMPLETE", "not present"),
            "slot_2": {"decision": "NO_FILTER"},
        }
    }
    with pytest.raises(ValueError, match="current-Run source"):
        _normalize(case, output)
    output["source_status_slots"]["slot_1"] = _filter(
        "INCOMPLETE", "incomplete Tasks", "CONFIRMATION_RESPONSE"
    )
    with pytest.raises(ValueError, match="unavailable"):
        _normalize(case, output)
    normalized = _normalize(
        case,
        output,
        provenance_sources={"CONFIRMATION_RESPONSE": "Please use incomplete Tasks."},
    )
    assert normalized[0]["provenance"]["source"] == "CONFIRMATION_RESPONSE"


def test_schema_and_normalizer_do_not_silently_correct_business_meaning() -> None:
    case = fixed_cases()[3]
    output = {
        "source_status_slots": {
            "slot_1": _filter("INCOMPLETE", "현재 상태"),
            "slot_2": {"decision": "NO_FILTER"},
        }
    }
    assert _normalize(case, output)[0]["value"] == "INCOMPLETE"
    # The owner evaluator must mark this semantic error; structural guards cannot infer it.


def test_product_repair_guard_preserves_other_slot_decisions() -> None:
    case = fixed_cases()[0]
    first = {
        "source_status_slots": {
            "slot_1": _filter("INCOMPLETE", "미완료 Task"),
            "slot_2": {"decision": "NO_FILTER"},
        }
    }
    first["source_status_slots"]["slot_1"]["predicates"][0].pop("source")
    repaired = deepcopy(first)
    repaired["source_status_slots"]["slot_1"]["predicates"][0]["source"] = "USER_REQUEST"
    arguments = {
        "failed_output": first,
        "affected_field_paths": ["$.source_status_slots.slot_1.predicates[0].source"],
        "output_schema": _schema(case),
    }
    assert find_out_of_scope_schema_repair_changes(repaired_output=repaired, **arguments) == ()
    repaired["source_status_slots"]["slot_2"] = _filter("COMPLETED", "완료 Task")
    assert find_out_of_scope_schema_repair_changes(repaired_output=repaired, **arguments)


def test_shape_instruction_retains_input_and_existing_examples_without_new_rules() -> None:
    registry = PromptRegistry()
    ref = registry.lookup_for_evaluation(PROMPT_ID)
    case = fixed_cases()[0]
    projection, _ = owner_input(case, "candidate", ref)
    old = owner_instruction(projection, ref, registry)
    new = slot_source_status_instruction(old)
    marker = "Allowed current-Run input projection (JSON):\n"
    assert old.partition(marker)[2] == new.partition(marker)[2]
    assert old.count("\n- ") == new.count("\n- ")
    assert "`statuses=[]`" not in new.partition(marker)[0]
    assert "`NO_FILTER`" in new.partition(marker)[0]
    assert "미완료인 항목만" in new


def test_projection_to_v26_keeps_input_and_does_not_create_output_authority() -> None:
    case = fixed_cases()[5]
    before = deepcopy(case)
    assert project_slot_source_statuses(
        {"source_status_slots": {"slot_1": {"decision": "NO_FILTER"}}},
        responsibilities=case["responsibilities"],
        requested_work=case["prompt_input"]["requested_work"],
    ) == {"statuses": []}
    assert case == before
