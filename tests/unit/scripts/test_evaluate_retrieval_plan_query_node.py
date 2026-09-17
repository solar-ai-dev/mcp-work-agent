import json
from pathlib import Path
from typing import cast

from scripts import evaluate_retrieval_plan_query_node as evaluator

from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)


def test_result_recording_preflight_and_incremental_write(tmp_path: Path) -> None:
    path = tmp_path / "node" / "result.json"
    records: list[dict[str, object]] = []
    result: dict[str, object] = {
        "binding": {"candidate_id": "fixture"},
        "summary": None,
        "cases": records,
    }
    evaluator._write_result(path, result)
    assert json.loads(path.read_text(encoding="utf-8"))["cases"] == []
    records.append({"case_id": "fixture", "outcome": "FAILED", "provider_call_count": 1})
    evaluator._write_result(path, result)
    assert json.loads(path.read_text(encoding="utf-8"))["cases"] == records


def _record(
    outcome: str,
    *,
    provider_calls: int = 0,
    first_call: str | None = None,
    semantic_revisions: int = 0,
    failure_family: str | None = None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "outcome": outcome,
        "provider_call_count": provider_calls,
        "semantic_revision_count": semantic_revisions,
        "input_tokens": 0,
        "output_tokens": 0,
        "provider_latency_ms": 0,
    }
    if first_call is not None:
        result["first_call_classification"] = first_call
    if failure_family is not None:
        result["failure_family"] = failure_family
    return result


def test_node_summary__llm_path_and_dispatch__uses_distinct_denominators() -> None:
    records = [
        *[_record("SKIP_NO_NODE_INPUT") for _ in range(17)],
        *[_record("DETERMINISTIC_VALID") for _ in range(9)],
        *[
            _record(
                "FIRST_CALL_VALID",
                provider_calls=1,
                first_call="SEMANTIC_VALID",
            )
            for _ in range(13)
        ],
        *[
            _record(
                "SEMANTIC_REVISION_RECOVERED",
                provider_calls=2,
                first_call="SCHEMA_VALID_SEMANTIC_INVALID",
                semantic_revisions=1,
            )
            for _ in range(2)
        ],
        *[
            _record(
                "FAILED",
                provider_calls=2,
                first_call="SCHEMA_VALID_SEMANTIC_INVALID",
                semantic_revisions=1,
                failure_family="EXPLICIT_ANCHOR_LOSS",
            )
            for _ in range(18)
        ],
        _record(
            "FAILED",
            first_call="PRE_DISPATCH_FAILED",
            failure_family="ROUTE_MISMATCH",
        ),
    ]

    summary = evaluator._summarize_records(
        records=records,
        split="CORE",
        duration_ms=100,
    )

    assert summary["case_count"] == 60
    assert summary["eligible_case_count"] == 43
    assert summary["deterministic_success_count"] == 9
    assert summary["llm_path_case_count"] == 34
    assert summary["llm_dispatched_case_count"] == 33
    assert summary["first_call_valid_count"] == 13
    assert summary["first_call_valid_rate"] == 13 / 34
    assert summary["first_call_dispatched_valid_rate"] == 13 / 33
    classification_counts = cast(dict[str, int], summary["first_call_classification_counts"])
    assert sum(classification_counts.values()) == 34
    assert summary["semantic_revision_attempted_count"] == 20
    assert summary["semantic_revision_still_failed_count"] == 18


def test_failure_family__duplicate_routes__classifies_over_selection() -> None:
    record: dict[str, object] = {
        "reason_code": "RETRIEVAL_QUERY_PLAN_SEMANTIC_INVALID",
        "affected_field_paths": [],
        "input_route_ids": ["gmail"],
        "candidate_outputs": [
            {
                "route_queries": [
                    {"route_id": "gmail"},
                    {"route_id": "gmail"},
                ]
            }
        ],
    }

    assert evaluator._failure_family(record) == "OVER_SELECTION"


def test_route_coverage_distinguishes_policy_business_and_access_dependencies() -> None:
    routes = cast(
        list[InputToolRouteV1],
        [
            {
                "route_id": "event",
                "resource_type": "CALENDAR_EVENT",
                "required": True,
                "reason_codes": ["POLICY_CALENDAR_CONFLICT_CHECK"],
            },
            {
                "route_id": "task",
                "resource_type": "TASK",
                "required": True,
                "reason_codes": ["REQUESTED_INPUT"],
            },
            {
                "route_id": "task-list",
                "resource_type": "TASK_LIST",
                "required": True,
                "reason_codes": ["RETRIEVAL_TASK_LIST_DISCOVERY"],
            },
        ],
    )

    summary = evaluator._route_coverage_summary(
        routes, {"route_queries": [{"route_id": "task-list"}]}
    )

    assert summary == {
        "selected_resource_types": ["TASK_LIST"],
        "missing_policy_resource_types": ["CALENDAR_EVENT"],
        "missing_business_resource_types": ["TASK"],
    }


def test_policy_composition_is_not_counted_as_first_inference_semantic_valid() -> None:
    record = _record("FIRST_CALL_VALID", provider_calls=1, first_call="SEMANTIC_VALID")
    record["first_inference_route_coverage"] = {"missing_policy_resource_types": ["CALENDAR_EVENT"]}
    record["final_route_coverage"] = {"missing_policy_resource_types": []}

    evaluator._classify_policy_coverage(record)
    summary = evaluator._summarize_records(records=[record], split="CORE", duration_ms=1)

    assert record["outcome"] == "POLICY_COMPOSITION_RECOVERED"
    assert record["first_call_classification"] == "POLICY_ROUTE_OMITTED"
    assert summary["first_call_valid_count"] == 0
    assert summary["policy_composition_recovered_count"] == 1
    assert summary["successful_case_count"] == 1


def test_unresolved_policy_route_is_not_counted_as_success() -> None:
    record = _record("FIRST_CALL_VALID", provider_calls=1, first_call="SEMANTIC_VALID")
    record["first_inference_route_coverage"] = {"missing_policy_resource_types": ["CALENDAR_EVENT"]}
    record["final_route_coverage"] = {"missing_policy_resource_types": ["CALENDAR_EVENT"]}

    evaluator._classify_policy_coverage(record)
    summary = evaluator._summarize_records(records=[record], split="CORE", duration_ms=1)

    assert record["outcome"] == "POLICY_ROUTE_UNRESOLVED"
    assert record["failure_family"] == "POLICY_ROUTE_OMISSION"
    assert summary["successful_case_count"] == 0
