from typing import cast
from unittest.mock import Mock

import pytest
from tests.support.fakes.llm import FakeStructuredInferencePort

from google_work_agent.adapters.langgraph.main.state import GraphState, initial_graph_state
from google_work_agent.adapters.langgraph.main.supervisor_intake_rules import route_tool_routing
from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.graph import (
    RequestUnderstandingSubgraph,
)
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.nodes.validate_route_node import (
    validate_route_node,
)
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.state import ToolRouteStateV1
from google_work_agent.application.agents.state_artifact import StateArtifactMetaV1
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    ToolRoutePlanV2,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.application.use_cases.connection.check_connector_prerequisites import (
    CheckConnectorPrerequisitesHandler,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.connector.oauth_credential_port import (
    OAuthConnectionMetadata,
    OAuthCredentialPort,
)
from google_work_agent.ports.system.contracts.workflow_execution import (
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)


def test_missing_github__terminates_before_repository_confirmation__in_compiled_subgraph() -> None:
    llm = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "pv-fusion 최근 이슈 확인",
                "completion_conditions": ["이슈 확인"],
                "constraints": {
                    "search_terms": [],
                    "business_concepts": [],
                    "person": [],
                    "sender": [],
                    "recipient": [],
                    "subject": [],
                    "period": [],
                    "status": [],
                    "additional_constraints": [],
                },
                "resource_responsibilities": {
                    "source_reads": [
                        {
                            "resource_type": "GITHUB_ISSUE",
                            "required_information": [],
                        }
                    ],
                    "outputs": [],
                },
                "analysis_requirement": "NONE",
            }
        ]
    )
    port = Mock(spec=OAuthCredentialPort)
    port.get_connection_status.return_value = OAuthConnectionMetadata(
        1,
        "github",
        None,
        None,
        "DISCONNECTED",
        (),
        (),
    )
    gate = CheckConnectorPrerequisitesHandler(
        {"github": ("GitHub", port)},
        tool_catalog=load_signed_tool_registry(),
    )
    confirm = Mock(side_effect=AssertionError("initial connection failure must not suspend"))
    identifiers = iter(f"id-{index}" for index in range(100))
    subgraph = RequestUnderstandingSubgraph(
        llm_runtime=llm,
        prompt_manifest_path=None,
        prompt_execution_scope="DEVELOPMENT_SMOKE",
        id_factory=identifiers.__next__,
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        transition_run=lambda *_: None,
        merge_decision=lambda state, patch, decision: {
            **state,
            **patch,
            **decision["state_update"],
        },
        confirm_inline=confirm,
        connector_prerequisites=gate,
    ).build()
    request = WorkflowStartRequest(
        run_id="run-local",
        conversation_id="conversation-local",
        workflow_key="workflow-local",
        entry_mode="AGENT_SEARCH",
        requested_mode="LOCAL_GPU",
        request_text="pv-fusion 최근 이슈 확인해줘",
        selected_resource_ids=(),
        run_budget=build_default_run_budget(),
        correlation=WorkflowCorrelationContext("request", "command", "1"),
    )
    output = subgraph.invoke(
        initial_graph_state(
            request,
            graph_profile=GraphProfile.SIX_ROLE_BASELINE,
            graph_version="test",
            initial_target="request.identify_goal",
        )
    )
    assert output["finalize_intent"]["reason_code"] == "CONNECTOR_PREREQUISITE_UNMET"
    assert output["finalize_intent"]["result_kind"] == "PARTIAL"
    assert "GitHub" in output["finalize_intent"]["prerequisite_message"]
    assert output["user_interrupt"] is None
    assert len(llm.calls) == 1
    assert output["trace_context"]["llm_call_count"] == 1
    assert output["admitted_connector_ids"] == []
    confirm.assert_not_called()


@pytest.mark.parametrize(
    "connector_id,tool_id",
    [
        ("github", "github_list_issues"),
        ("google_workspace", "gmail_get_message"),
    ],
)
@pytest.mark.parametrize("write_only", [False, True])
def test_route_node__projects_initial_connection_failure__to_terminal_handoff(
    connector_id: str,
    tool_id: str,
    write_only: bool,
) -> None:
    catalog = load_signed_tool_registry()
    # The registered entry determines the resource type; no provider call is made here.
    entry = catalog.get_required(connector_id=connector_id, tool_id=tool_id)
    meta: StateArtifactMetaV1 = {
        "artifact_id": "route",
        "revision": 1,
        "based_on": [{"artifact_id": "intent", "revision": 1}],
    }
    plan = cast(
        ToolRoutePlanV2,
        {
            "schema_version": 2,
            "tool_registry_version": entry.registry_version,
            "input_plan": {
                "schema_version": 1,
                "meta": meta,
                "input_routes": [
                    {
                        "route_id": "read",
                        "resource_type": entry.resource_type.upper(),
                        "connector_id": connector_id,
                        "allowed_read_tool_ids": [tool_id],
                        "required": True,
                        "reason_codes": [],
                    }
                ],
            },
            "output_plan": {"schema_version": 1, "meta": meta, "output_mode": "ANSWER"},
        },
    )
    if write_only:
        write = next(
            item
            for item in catalog.entries
            if item.connector_id == connector_id and item.effect == "CREATE"
        )
        plan["input_plan"]["input_routes"] = []
        plan["output_plan"] = {
            "schema_version": 1,
            "meta": meta,
            "output_mode": "ACTION",
            "output_routes": [
                {
                    "route_id": "write",
                    "resource_type": write.resource_type.upper(),
                    "connector_id": connector_id,
                    "effect": "CREATE",
                    "selected_tool_id": write.tool_id,
                    "reason_codes": [],
                }
            ],
        }
    port = Mock(spec=OAuthCredentialPort)
    port.get_connection_status.return_value = OAuthConnectionMetadata(
        1,
        connector_id,
        None,
        None,
        "DISCONNECTED",
        (),
        (),
    )
    gate = CheckConnectorPrerequisitesHandler({connector_id: ("서비스", port)})
    state = cast(ToolRouteStateV1, {"final_route": plan, "admitted_connector_ids": []})
    patch = validate_route_node(state, tool_catalog=catalog, connector_prerequisites=gate)
    assert patch["tool_route_plan"] == plan
    assert patch["admitted_connector_ids"] == []
    assert patch["prerequisite_message"] is not None
    decision = route_tool_routing(
        state=cast(GraphState, {}),
        result={
            "schema_version": 1,
            "disposition": "PREREQUISITE_UNMET",
            "tool_route_plan": plan,
            "workflow_signal": None,
            "reason_codes": ["CONNECTOR_PREREQUISITE_UNMET"],
            "prerequisite_message": patch["prerequisite_message"],
        },
    )
    assert decision["target"] == "FINALIZE"
    assert decision["state_update"]["user_interrupt"] is None
    finalize_intent = decision["state_update"]["finalize_intent"]
    assert finalize_intent is not None
    assert finalize_intent["result_kind"] == "PARTIAL"
    # Old checkpoints have no admission field: retain the existing running-Run contract.
    port.reset_mock()
    legacy = validate_route_node(
        {"final_route": plan}, tool_catalog=catalog, connector_prerequisites=gate
    )
    assert legacy["prerequisite_message"] is None
    port.get_connection_status.assert_not_called()
    port.get_connection_status.return_value = OAuthConnectionMetadata(
        1,
        connector_id,
        "account",
        None,
        "CONNECTED",
        (),
        (),
    )
    admitted = validate_route_node(state, tool_catalog=catalog, connector_prerequisites=gate)
    assert admitted["admitted_connector_ids"] == [connector_id]
    assert admitted["prerequisite_message"] is None
    port.reset_mock()
    port.get_connection_status.side_effect = AssertionError("same-Run admission survives")
    resumed = validate_route_node(
        {**state, **admitted},
        tool_catalog=catalog,
        connector_prerequisites=gate,
    )
    assert resumed["admitted_connector_ids"] == [connector_id]
    assert resumed["prerequisite_message"] is None
