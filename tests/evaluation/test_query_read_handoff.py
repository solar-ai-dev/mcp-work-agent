"""Portable fake-Connector controls for the separate 070 component gate."""

import json
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import pytest
from scripts import verify_query_read_handoff as gate
from tests.unit.application.agents.retrieval.test_plan_query_detail_ref_binding import (
    _context,
    _detail,
)

from google_work_agent.adapters.system.json_settings import _default_settings
from google_work_agent.application.agents.retrieval.contracts.query_plan_schema import (
    bind_retrieval_query_plan_output_schema,
)
from google_work_agent.application.agents.retrieval.plan_query import _route_operations
from google_work_agent.ports.system.contracts.workflow_execution import SelectedResourceRef


def _inputs(*, shared: bool = False) -> dict[str, Any]:
    """Synthetic unit-test authority; official replay uses the hash-guarded loader."""
    context = _context(selected=True)
    context["validated_container_refs"] = {
        key: ["parent"] for key in context["validated_container_refs"]
    }
    routes = context["frozen_routes"]
    routes[1]["reason_codes"] = ["RETRIEVAL_TASK_LIST_DISCOVERY"]
    intent = context["prompt_input"]["request_intent"]
    if shared:
        parts = ("선택한 작업의 상태를 알려줘.", "같은 작업의 메모를 알려줘.")
        request = " ".join(parts)
        intent["goal"] = request
        context["prompt_input"]["user_request"] = request
        intent["requested_work"]["work_units"] = [
            {
                "unit_id": f"work-{i}",
                "request_provenance": [
                    {
                        "source": "USER_REQUEST",
                        "start_offset": request.index(part),
                        "end_offset": request.index(part) + len(part),
                        "source_text": part,
                    }
                ],
            }
            for i, part in enumerate(parts, 1)
        ]
        for route in routes:
            route["work_unit_ids"] = ["work-1", "work-2"]
        intent["resource_responsibilities"]["source_reads"][0]["work_unit_ids"] = [
            "work-1",
            "work-2",
        ]
    first = _detail("task:selected")
    ops = _route_operations(
        routes,
        validated_resource_refs=context["validated_resource_refs"],
        detail_candidate_refs=(),
        next_page_route_ids=(),
    )
    schema = bind_retrieval_query_plan_output_schema(
        route_ids=context["route_policies"],
        route_operations=ops,
        supported_constraint_kinds={
            key: value.supported_kinds for key, value in context["route_policies"].items()
        },
        validated_resource_refs=context["validated_resource_refs"],
        validated_container_refs=context["validated_container_refs"],
    )
    normalized = gate.normalize_retrieval_query_plan_candidate(first)
    plans = gate.build_query(
        normalized,
        **{
            key: context[key]
            for key in (
                "frozen_routes",
                "route_policies",
                "validated_resource_refs",
                "validated_container_refs",
            )
        },
    )
    settings = replace(
        _default_settings(),
        selected_tasklist_ids=("parent",),
        default_tasklist_id="parent",
        google_resource_account_id="test-account",
    )
    selected = SelectedResourceRef("selected-ref", "google_workspace", "task", "selected", "parent")
    return {
        "authority": {
            "context": context,
            "lineage": {
                "selected_resources": [asdict(selected)],
                "tool_route_plan": {"input_plan": {"input_routes": routes}},
            },
        },
        "first": first,
        "schema": schema.json_schema,
        "expected_fetches": plans,
        "settings": json.loads(json.dumps(asdict(settings))),
        "snapshot": {
            "resource_type": "task",
            "resource_id": "selected",
            "parent_id": "parent",
            "version": "synthetic",
            "payload": {"title": "Component fixture"},
        },
        "binding": {"head": "test-only", "inputs": "synthetic-not-069"},
    }


@pytest.mark.parametrize("shared", [False, True])
def test_read_handoff__actual_owners_preserve_identity_scope_and_work_union(shared: bool) -> None:
    inputs = _inputs(shared=shared)
    original = deepcopy(inputs)
    record: dict[str, Any] = {}
    gate.verify_controls(inputs, record, lambda: None)
    assert record["component_verdict"] == "PASS"
    assert record["synthetic_dispatches"] == len(record["synthetic_calls"]) == 1
    assert record["projected_tool"] == "tasks_get_task"
    assert record["projected_arguments"] == {"task_list_id": "parent", "task_id": "selected"}
    assert record["source_fetch_plans"][0]["detail_candidate_ref"] == "task:selected"
    assert record["source_statuses"][0]["work_unit_ids"] == (
        ["work-1", "work-2"] if shared else ["work-1"]
    )
    assert len(record["source_statuses"]) == 1  # Discovery is not a second business READ.
    assert record["source_statuses"][0]["checked_read_count"] == 1
    assert record["acquisition"]["resource_handles"] == ["task:selected"]
    assert record["component_budget"]["connector_calls_used"] == 1
    assert record["component_budget"]["detail_fetches_used"] == 1
    assert record["component_budget"]["llm_calls_used"] == 0
    assert [item["name"] for item in record["controls"]] == [
        "OUTSIDE_PARENT",
        "ACCOUNT_MISMATCH",
        "WRITE_BINDING",
        "REMOVED_TOOL",
        "CROSS_RUN_CACHE",
        "WRONG_ROUTE_CACHE",
        "WRONG_QUERY_CACHE",
        "WRONG_ROUTE_ACQUISITION",
    ]
    assert all(item["passed"] for item in record["controls"])
    assert inputs == original


def test_native_reference__fails_before_synthetic_dispatch() -> None:
    inputs = _inputs()
    inputs["first"]["route_queries"][0]["detail_candidate_ref"] = "selected"
    record: dict[str, Any] = {}
    with pytest.raises(ValueError, match="schema-valid"):
        gate.verify_controls(inputs, record, lambda: None)
    assert "synthetic_calls" not in record


def test_unknown_work_binding__cannot_be_laundered_into_coverage() -> None:
    inputs = _inputs()
    inputs["authority"]["context"]["frozen_routes"][0]["work_unit_ids"] = ["foreign-work"]
    record: dict[str, Any] = {}
    saved: list[dict[str, Any]] = []
    with pytest.raises(ValueError, match="unknown WorkUnit"):
        gate.verify_controls(inputs, record, lambda: saved.append(deepcopy(record)))
    assert len(record["synthetic_calls"]) == 1
    assert record["normal_read"]["provider_called"] is True
    assert record["read_attempts"][0]["result"] == record["normal_read"]
    assert record["component_budget"]["connector_calls_used"] == 1
    assert saved[-1]["cached_read_result"]["output"]["item"] == inputs["snapshot"]
    assert "component_verdict" not in record


def test_raw__separate_exclusive_record_and_no_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "070-query-read-handoff"
    monkeypatch.setattr(gate, "OUTPUT", output)
    monkeypatch.setattr(gate, "load_inputs", lambda: _inputs())
    monkeypatch.setattr(
        gate.previous.transport, "_post_json", lambda **_: pytest.fail("HTTP forbidden")
    )
    monkeypatch.setattr(
        gate.previous.transport, "_get_json", lambda **_: pytest.fail("HTTP forbidden")
    )
    result = gate.run_gate()
    assert result["state"] == "RETURNED" and result["binding_unchanged"]
    assert result["model_calls"] == result["external_provider_calls"] == result["graph_calls"] == 0
    assert json.loads((output / "raw.json").read_text(encoding="utf-8")) == result
    before = (output / "raw.json").read_bytes()
    with pytest.raises(FileExistsError):
        gate.run_gate()
    assert (output / "raw.json").read_bytes() == before


def test_failed_component__retains_failure_without_overwriting_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gate, "OUTPUT", tmp_path / "070-query-read-handoff")
    monkeypatch.setattr(gate, "load_inputs", lambda: _inputs())

    def fail(inputs: Any, record: Any, save: Any) -> None:
        record["partial_observation"] = "kept"
        save()
        raise ValueError("test component failure")

    monkeypatch.setattr(gate, "verify_controls", fail)
    result = gate.run_gate()
    assert result["state"] == "FAILED" and result["component_verdict"] == "FAIL"
    assert result["partial_observation"] == "kept"
    assert result["failure"]["message"] == "test component failure"


def test_loader__historical_hash_mismatch_stops_before_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gate, "file_hash", lambda _: "changed")
    monkeypatch.setattr(
        gate.previous, "load_authority", lambda: pytest.fail("changed source must not be loaded")
    )
    with pytest.raises(ValueError, match="069 bytes"):
        gate.load_inputs()


@pytest.mark.parametrize("end_error", [False, True])
def test_end_binding_drift__cannot_leave_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    end_error: bool,
) -> None:
    monkeypatch.setattr(gate, "OUTPUT", tmp_path / "070-query-read-handoff")
    calls = 0

    def load() -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 2 and end_error:
            raise ValueError("end authority cannot be verified")
        inputs = _inputs()
        if calls == 2:
            inputs["binding"]["head"] = "changed"
        return inputs

    monkeypatch.setattr(gate, "load_inputs", load)
    result = gate.run_gate()
    assert result["state"] == "FAILED" and result["component_verdict"] == "FAIL"
    assert result["binding_unchanged"] is False
    assert result["failure"]["type"] == "AuthorityDrift"
    assert result["synthetic_dispatches"] == 1
