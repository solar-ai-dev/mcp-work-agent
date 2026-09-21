from typing import cast

from tests.support.fakes.llm import FakeStructuredInferencePort

from google_work_agent.adapters.langgraph.subgraphs.tool_routing.nodes import (
    determine_io_resources_node as determine_node,
)
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.state import ToolRouteStateV1
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV3,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.llm.structured_inference_contracts import PromptReference
from google_work_agent.ports.system.contracts.workflow_execution import (
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)


def test_exhausted_route_validation__with_structured_failure__preserves_cause() -> None:
    intent = cast(
        RequestIntentV3,
        {
            "schema_version": 3,
            "meta": {"artifact_id": "intent-1", "revision": 1, "based_on": []},
            "goal": "reply to an existing Gmail thread",
            "completion_conditions": ["reply sent"],
            "constraints": [],
            "requested_effect_hints": ["READ", "SEND", "CREATE"],
            "requested_resource_hints": [
                "GMAIL_THREAD",
                "GMAIL_MESSAGE",
                "GMAIL_DRAFT",
            ],
            "analysis_requirement": "NONE",
            "effect_prohibitions": [],
            "requested_work": {
                "work_units": [
                    {
                        "unit_id": "work-1",
                        "request_provenance": [
                            {
                                "source": "USER_REQUEST",
                                "start_offset": 0,
                                "end_offset": len("Quartz 납품 일정 확인했다고 답장 보내줘."),
                                "source_text": "Quartz 납품 일정 확인했다고 답장 보내줘.",
                            }
                        ],
                    }
                ],
                "work_relations": [],
            },
            "ambiguity": {
                "requires_confirmation": False,
                "reason_codes": [],
                "missing_fields": [],
            },
        },
    )
    request = WorkflowStartRequest(
        run_id="run-1",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode="AGENT_SEARCH",
        requested_mode="LOCAL_GPU",
        request_text="Quartz 납품 일정 확인했다고 답장 보내줘.",
        selected_resource_ids=(),
        selected_resources=(),
        run_budget=dict(build_default_run_budget()),
        correlation=WorkflowCorrelationContext("request", "command", "v1"),
    )
    invalid = {
        "schema_version": 1,
        "input_resource_types": ["EMAIL"],
        "output_resource_types": [],
        "output_effects": ["SEND", "CREATE"],
        "disposition": "ROUTE_READY",
    }

    result = determine_node.determine_io_resources_node(
        cast(
            ToolRouteStateV1,
            {
                "request_intent": intent,
                "retry_budget": build_default_run_budget(),
                "__request__": request,
            },
        ),
        llm_runtime=FakeStructuredInferencePort(outputs=[invalid, invalid]),
        tool_catalog=load_signed_tool_registry(),
        prompt_ref=PromptReference(
            prompt_bundle_version="test",
            prompt_id="tool_routing.determine_io_resources",
            prompt_version="1",
            content_hash="hash",
            agent_role="tool_routing",
            subgraph_name="tool_routing",
            node_name="determine_io_resources",
            node_state="INITIAL",
            purpose="determine_io_resources",
            input_schema_version="v1",
            output_schema_version="v1",
        ),
    )

    failure = result["io_resource_failure"]
    assert failure is not None
    assert failure["failure_reason_code"] == "TOOL_ROUTE_REQUIRED_OUTPUT_MISSING"
    assert failure["affected_field_paths"] == [
        "$.output_resource_types",
        "$.output_effects",
    ]
