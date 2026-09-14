"""Compiled LangGraph measurement of the production READ node; provider only is synthetic."""

import json
from dataclasses import asdict, replace
from pathlib import Path
from typing import TypedDict, cast

import pytest
from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.langgraph.subgraphs.retrieval.nodes.execute_read_node import (
    execute_read_node,
)
from google_work_agent.adapters.system.json_settings import FileSettingsStore, JsonSettingsAdapter
from google_work_agent.adapters.system.memory.run_retrieval_cache import InMemoryRunRetrievalCache
from google_work_agent.application.use_cases.resource.require_resource_selection import (
    RequireResourceSelectionHandler,
    SelectedResourceReadPort,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.connector.connector_read_port import ConnectorReadResultV1, JsonValue
from google_work_agent.ports.connector.contracts.validated_connector_tool_binding import (
    ValidatedConnectorToolBindingV1,
)


class _MeasurementState(TypedDict, total=False):
    operation_inputs: dict[str, object]
    read_execution: object


@pytest.mark.parametrize(
    "target,expected_status,expected_calls", [("two", "COMPLETE", 1), ("one", "FAILED", 0)]
)
def test_resource_selection__production_read_node_in_langgraph__measures_terminal_result(
    tmp_path: Path,
    target: str,
    expected_status: str,
    expected_calls: int,
) -> None:
    settings = replace(
        JsonSettingsAdapter(store=FileSettingsStore(tmp_path / "settings.json")).get_settings(),
        selected_tasklist_ids=("two", "three"),
        google_resource_account_id="google:1",
    )
    calls: list[tuple[str, dict[str, JsonValue]]] = []

    class Provider:
        def execute_read(
            self,
            binding: ValidatedConnectorToolBindingV1,
            arguments: dict[str, JsonValue],
        ) -> ConnectorReadResultV1:
            calls.append((binding.tool_id, dict(arguments)))
            return ConnectorReadResultV1(
                1,
                binding.tool_id,
                "fixture",
                {"items": [{"resource_id": "task-2", "parent_id": target}]},
                None,
                1,
            )

    scoped = SelectedResourceReadPort(
        Provider(), RequireResourceSelectionHandler(lambda: settings, lambda _: "google:1")
    )
    binding = ValidatedConnectorToolBindingV1(
        1, "google_workspace", "TASK", "tasks_list_tasks", "READ", "input", "output", "a" * 64
    )
    inputs = {
        "plan": {
            "schema_version": 1,
            "route_id": "tasks",
            "connector_id": "google_workspace",
            "resource_type": "TASK",
            "operation_kind": "SEARCH",
            "query_identity_hash": "b" * 64,
        },
        "run_id": "resource-selection-measurement",
        "binding": binding,
        "tool_arguments": {"task_list_id": target},
        "connector_reader": scoped,
        "read_result_cache": InMemoryRunRetrievalCache(),
        "read_result_handle": "read-1",
        "run_budget": build_default_run_budget(started_at_ms=1),
        "now_ms": 2,
        "prior_query_attempts": [],
    }
    graph = StateGraph(_MeasurementState)
    graph.add_node(
        "execute_read",
        lambda state: cast(_MeasurementState, execute_read_node(state)),
    )
    graph.add_edge(START, "execute_read")
    graph.add_edge("execute_read", END)
    updates = list(
        graph.compile().stream(
            {"operation_inputs": {"execute_read": inputs}}, stream_mode="updates"
        )
    )
    result = updates[-1]["execute_read"]["read_execution"]
    path = [name for update in updates for name in update]
    assert path == ["execute_read"]
    assert result.status == expected_status and len(calls) == expected_calls
    assert result.provider_called == bool(expected_calls)
    assert result.failure_code == ("PERMISSION_DENIED" if expected_calls == 0 else None)
    print(
        json.dumps(
            {
                "fixture": True,
                "path": ["START", *path, "END"],
                "target": target,
                "connector_calls": calls,
                "result": asdict(result),
            },
            ensure_ascii=False,
        )
    )
