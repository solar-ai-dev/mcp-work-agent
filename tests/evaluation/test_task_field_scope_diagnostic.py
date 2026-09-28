"""Fixed synthetic Product inputs, without generation or Provider access."""

from copy import deepcopy

from scripts.task_field_scope_diagnostic import GROUPS, REQUEST, build_cases

from google_work_agent.application.agents.planning.project_task_read_answer import (
    project_task_read_answer,
)
from google_work_agent.application.agents.request_understanding.validate_intent import (
    validate_intent,
)
from google_work_agent.application.agents.retrieval.resolve_task_calendar_snapshot import (
    resolve_task_calendar_snapshot,
)


def test_fixture_preparation__fixed_full_and_partial__preserves_native_product_input() -> None:
    cases = build_cases()
    assert [case["group"] for case in cases] == list(GROUPS)
    assert [case["trial"] for case in cases] == [1, 1]
    assert [len(case["snapshots"]) for case in cases] == [2, 1]
    assert [case["prompt_input"]["coverage"] for case in cases] == ["SUFFICIENT", "PARTIAL"]
    for case in cases:
        projected = case["prompt_input"]
        intent = projected["request_intent"]
        assert projected["user_request"] == REQUEST != intent["goal"]
        assert validate_intent(
            intent, require_meta=True, provenance_sources={"USER_REQUEST": REQUEST}
        ) == intent
        assert len(intent["requested_work"]["work_units"]) == 1
        assert intent["requested_work"]["work_relations"] == []
        sources = intent["resource_responsibilities"]["source_reads"]
        assert [source["required_information"] for source in sources] == [["status"], ["due"]]
        assert all(source["work_unit_ids"] == ["work-1"] for source in sources)
        refs = [item["evidence_id"] for item in projected["evidence"]]
        assert projected["answer_outline"] == {"sections": [REQUEST], "evidence_refs": refs}
        assert projected["evidence_by_work_unit"] == [
            {"work_unit_id": "work-1", "evidence_refs": refs}
        ]
        assert "source_snapshots" not in projected
        assert "expected_answer" not in projected
        assert case["fault_profile"] is None
        assert case["component_state"]["tool_route_plan"]["output_plan"]["output_mode"] == "ANSWER"
        routes = case["component_state"]["tool_route_plan"]["input_plan"]["input_routes"]
        task_routes = [route for route in routes if route["resource_type"] == "TASK"]
        assert len(task_routes) == 1
        assert task_routes[0]["work_unit_ids"] == ["work-1"]
        # Registry may add its existing Task-list bootstrap capability; this is not a Work copy.
        assert all(route["resource_type"] in {"TASK", "TASK_LIST"} for route in routes)


def test_fixture_scope__partial_read__never_binds_missing_task_snapshot() -> None:
    full, partial = build_cases()
    a_full = full["prompt_input"]["evidence"][0]
    a_partial = partial["prompt_input"]["evidence"][0]
    assert a_full == a_partial
    assert partial["snapshots"] == {a_full["evidence_id"]: full["snapshots"][a_full["evidence_id"]]}
    assert resolve_task_calendar_snapshot(a_partial, partial["snapshots"]) == {
        "title": "작업 A", "status": "needsAction", "due": "2026-10-01"
    }
    status = partial["prompt_input"]["source_statuses"][0]
    assert status["observed_resource_count"] == 1
    assert status["status"] == "PARTIAL"
    assert status["scope_complete"] is False
    assert status["continuation_status"] == "HAS_MORE"


def test_fixture_handoff__heterogeneous_sources__never_uses_common_formatter() -> None:
    for case in build_cases():
        original = deepcopy(case)
        projected = case["prompt_input"]
        assert project_task_read_answer(
            user_request=REQUEST,
            request_intent=projected["request_intent"],
            evidence=projected["evidence"],
            source_snapshots=case["snapshots"],
            retrieval_result=case["component_state"]["retrieval_result"],
        ) is None
        assert case == original
