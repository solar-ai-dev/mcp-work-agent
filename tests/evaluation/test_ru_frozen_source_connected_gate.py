"""No-model component gate: historical success must not authorize changed inputs."""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any

import pytest
from scripts.ru_frozen_source_connected_gate import (
    DEFAULT_AUTHORITY,
    DEFAULT_DATASET,
    DEFAULT_FIXTURE,
    DEFAULT_SOURCE,
    ExactRecordedInference,
    NewSemanticCallRequired,
    build_report,
    fixture_route_inventory,
)


def _schema() -> Any:
    return SimpleNamespace(
        json_schema={
            "type": "object",
            "required": ["statuses"],
            "additionalProperties": False,
            "properties": {"statuses": {"type": "array", "maxItems": 0}},
        }
    )


def _record() -> dict[str, Any]:
    return {
        "prompt_id": "request_understanding.identify_source_status",
        "input": {"user_request": "자료를 확인해줘", "source_reads": ["TASK"]},
        "structured_output": {"statuses": []},
    }


def test_exact_response_replays_without_fabricating_inference_usage() -> None:
    record = _record()
    port = ExactRecordedInference([record])
    response = port.infer(
        "LOCAL_GPU", SimpleNamespace(prompt_id=record["prompt_id"]), record["input"], _schema()
    )
    assert response.structured_output == record["structured_output"]
    assert response.input_tokens == response.output_tokens == response.latency_ms == 0
    assert response.provider == "RECORDED_RAW_REPLAY"
    response.structured_output["statuses"].append("changed")
    assert record["structured_output"] == {"statuses": []}


def test_changed_source_cannot_reuse_old_empty_status_decision() -> None:
    record = _record()
    port = ExactRecordedInference([record])
    projection = {**record["input"], "source_reads": ["TASK", "CALENDAR_EVENT"]}
    with pytest.raises(NewSemanticCallRequired) as raised:
        port.infer(
            "LOCAL_GPU", SimpleNamespace(prompt_id=record["prompt_id"]), projection, _schema()
        )
    assert raised.value.boundary["new_model_calls"] == 0
    assert raised.value.boundary["input_sha256"] not in raised.value.boundary["prior_input_sha256"]


def test_recorded_output_invalid_under_current_schema_does_not_replay() -> None:
    record = _record()
    record["structured_output"] = {}
    port = ExactRecordedInference([record])
    with pytest.raises(NewSemanticCallRequired):
        port.infer(
            "LOCAL_GPU", SimpleNamespace(prompt_id=record["prompt_id"]), record["input"], _schema()
        )


def test_unknown_prompt_does_not_generate_ambiguity_or_sufficiency() -> None:
    port = ExactRecordedInference([_record()])
    with pytest.raises(NewSemanticCallRequired):
        port.infer(
            "LOCAL_GPU", SimpleNamespace(prompt_id="retrieval.assess_sufficiency"), {}, _schema()
        )


def test_fixture_inventory_reports_empty_business_source_without_fake_acquisition() -> None:
    fixture = {
        "resource_packs": {
            "synthetic": {
                "resources": [
                    {"resource_type": "task", "resource_id": "task-1", "status": "needsAction"}
                ]
            }
        }
    }
    routes = [
        {
            "route_id": "draft",
            "resource_type": "GMAIL_DRAFT",
            "work_unit_ids": ["work-1"],
            "required": True,
            "reason_codes": ["REQUESTED_INPUT"],
        },
        {
            "route_id": "task",
            "resource_type": "TASK",
            "work_unit_ids": ["work-1"],
            "required": True,
            "reason_codes": ["RETRIEVAL_TASK_DETAIL"],
        },
        {
            "route_id": "freebusy",
            "resource_type": "CALENDAR_FREEBUSY",
            "work_unit_ids": ["work-1"],
            "required": True,
            "reason_codes": ["POLICY_CALENDAR_CONFLICT_CHECK"],
        },
    ]
    before = deepcopy(fixture)
    result = fixture_route_inventory(routes, fixture, ["synthetic"])
    assert result[0]["business_required"]
    assert result[0]["snapshot_object_count"] == 0
    assert result[0]["empty_required_inventory_risk"]
    assert result[1]["snapshot_object_count"] == 1
    assert not result[1]["business_required"]
    assert result[2]["snapshot_object_count"] is None
    assert not result[2]["empty_required_inventory_risk"]
    assert fixture == before
    assert all("status" not in row and "evidence" not in row for row in result)


@pytest.fixture(scope="module")
def local_recorded_report() -> Any:
    if not all(
        path.exists()
        for path in (DEFAULT_SOURCE, DEFAULT_AUTHORITY, DEFAULT_DATASET, DEFAULT_FIXTURE)
    ):
        pytest.skip("local raw artifacts are ignored; model-free unit tests remain portable")
    return build_report(DEFAULT_SOURCE, DEFAULT_AUTHORITY, DEFAULT_DATASET, DEFAULT_FIXTURE)


@pytest.mark.parametrize(
    "case_id", ["CASE-CORE-001", "CASE-CORE-013", "CASE-CORE-023", "CASE-CORE-027"]
)
def test_real_frozen_authorities_stop_before_new_status_and_control_compiles(
    local_recorded_report: Any,
    case_id: str,
) -> None:
    report = local_recorded_report
    row = next(item for item in report["cases"] if item["case_id"] == case_id)
    assert report["new_model_calls"] == report["provider_reads"] == report["provider_writes"] == 0
    assert row["candidate_continuation"]["disposition"] == "NEW_SEMANTIC_CALL_REQUIRED"
    assert row["candidate_continuation"]["boundary"]["prompt_id"] == (
        "request_understanding.identify_source_status"
    )
    assert row["unchanged_v4_compiled_control"]["disposition"] == "COMPILED_CONTROL_RETURNED"
    assert not row["candidate_compiled_tool_route_executed"]
    assert row["business_result"] == "NOT_EVALUATED"


def test_actual_v20_draft_is_business_required_but_absent_in_case_packs(
    local_recorded_report: Any,
) -> None:
    for case_id in ("CASE-CORE-013", "CASE-CORE-023"):
        row = next(item for item in local_recorded_report["cases"] if item["case_id"] == case_id)
        inventory = row["deterministic_components"]["fixture_inventory"]
        draft = next(item for item in inventory if item["resource_type"] == "GMAIL_DRAFT")
        assert draft["business_required"]
        assert draft["snapshot_object_count"] == 0
        assert draft["empty_required_inventory_risk"]
    answer = next(
        item for item in local_recorded_report["cases"] if item["case_id"] == "CASE-CORE-027"
    )
    assert answer["validated_source_output_merge"]["outputs"] == []
    assert {
        item["resource_type"] for item in answer["deterministic_components"]["input_routes"]
    } >= {"GMAIL_THREAD", "TASK", "CALENDAR_EVENT", "CALENDAR_FREEBUSY"}
