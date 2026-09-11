from __future__ import annotations

from collections.abc import Mapping
from typing import cast

import pytest
from tests.support.fakes.llm import FakeStructuredInferencePort

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.tool_routing.determine_io_resources import (
    determine_io_resources,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.application.use_cases.run.guard_run_budget import (
    build_default_run_budget,
)
from google_work_agent.domain.action.model import EffectType
from google_work_agent.ports.llm.structured_inference_contracts import PromptReference
from google_work_agent.ports.system.contracts.workflow_execution import (
    SelectedResourceRef,
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)


def _valid_output() -> dict[str, object]:
    return {
        "schema_version": 1,
        "input_resource_types": ["TASK"],
        "output_resource_types": ["TASK"],
        "output_effects": ["CREATE"],
        "disposition": "ROUTE_READY",
    }


@pytest.mark.parametrize(
    "resource_type,connector,selected_type",
    [
        ("GITHUB_ISSUE", "github", "github_issue"),
        ("TASK", "google_workspace", "task"),
        ("CALENDAR_EVENT", "google_workspace", "calendar_event"),
    ],
)
def test_selected_mutation__preserves_exact_typed_scope__without_inventing_routes(
    resource_type: str,
    connector: str,
    selected_type: str,
) -> None:
    intent = cast(
        RequestIntentV2,
        {
            "schema_version": 2,
            "meta": {"artifact_id": "intent", "revision": 1, "based_on": []},
            "goal": "modify selected resource",
            "completion_conditions": ["modified"],
            "constraints": [],
            "requested_effect_hints": ["READ", "UPDATE"],
            "requested_resource_hints": [resource_type],
            "analysis_requirement": "NONE",
            "ambiguity": {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
        },
    )
    request = WorkflowStartRequest(
        run_id="run",
        conversation_id="conversation",
        workflow_key="thread",
        entry_mode="RESOURCE_SELECTED",
        requested_mode="LOCAL_GPU",
        request_text="modify this",
        selected_resource_ids=("resource",),
        selected_resources=(SelectedResourceRef("ref", connector, selected_type, "resource"),),
        run_budget=dict(build_default_run_budget()),
        correlation=WorkflowCorrelationContext("request", "command", "v1"),
    )
    runtime = FakeStructuredInferencePort(outputs=[])
    candidate, _ = determine_io_resources(
        llm_runtime=runtime,
        tool_catalog=load_signed_tool_registry(),
        request_intent=intent,
        request=request,
        retry_budget=build_default_run_budget(),
    )
    assert candidate.input_resource_types == (resource_type,)
    assert candidate.output_pairs == ((resource_type, EffectType.UPDATE),)
    assert candidate.input_reason_codes == ((resource_type, "RESOURCE_SELECTED"),)
    assert runtime.calls == []


def test_task_create__produces_semantic_candidate__without_tool_identity() -> None:
    catalog = load_signed_tool_registry()
    intent: RequestIntentV2 = {
        "schema_version": 2,
        "meta": {"artifact_id": "intent-1", "revision": 1, "based_on": []},
        "goal": "create task",
        "completion_conditions": ["created"],
        "constraints": [],
        "requested_effect_hints": ["CREATE"],
        "requested_resource_hints": ["TASK"],
        "analysis_requirement": "REQUIRED",
        "ambiguity": {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
    }
    request = WorkflowStartRequest(
        run_id="run-1",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode="AGENT_SEARCH",
        requested_mode="AUTO",
        request_text="태스크 만들어줘",
        selected_resource_ids=(),
        run_budget=dict(build_default_run_budget()),
        correlation=WorkflowCorrelationContext(
            request_id="request-1", command_id="command-1", api_contract_version="v1"
        ),
    )
    prompt_ref = PromptReference(
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
    )
    runtime = FakeStructuredInferencePort(outputs=[])
    candidate, _ = determine_io_resources(
        llm_runtime=runtime,
        tool_catalog=catalog,
        request_intent=intent,
        request=request,
        retry_budget=build_default_run_budget(),
        prompt_ref=prompt_ref,
    )
    assert candidate.output_pairs[0][0] == "TASK"
    assert candidate.output_pairs[0][1].value == "CREATE"
    assert runtime.calls == []


@pytest.mark.parametrize("effect_hints", [["UPDATE"], ["UPDATE", "READ"]])
def test_explicit_gmail_draft_update__requires_exact_draft_read__without_llm(
    effect_hints: list[str],
) -> None:
    intent = cast(
        RequestIntentV2,
        {
            "schema_version": 2,
            "meta": {"artifact_id": "intent-draft", "revision": 1, "based_on": []},
            "goal": "update draft",
            "completion_conditions": ["updated without sending"],
            "constraints": [
                {
                    "kind": "RESOURCE",
                    "field": "draft_id",
                    "value": "r976635311795334843",
                    "provenance": {
                        "source": "USER_REQUEST",
                        "start_offset": 16,
                        "end_offset": 36,
                    },
                }
            ],
            "requested_effect_hints": effect_hints,
            "requested_resource_hints": ["GMAIL_DRAFT"],
            "analysis_requirement": "NONE",
            "ambiguity": {
                "requires_confirmation": False,
                "reason_codes": [],
                "missing_fields": [],
            },
        },
    )
    request = WorkflowStartRequest(
        run_id="run-draft",
        conversation_id="conversation",
        workflow_key="thread",
        entry_mode="AGENT_SEARCH",
        requested_mode="LOCAL_GPU",
        request_text="Gmail 초안 ID r976635311795334843를 수정해줘.",
        selected_resource_ids=(),
        selected_resources=(),
        run_budget=dict(build_default_run_budget()),
        correlation=WorkflowCorrelationContext("request", "command", "v1"),
    )
    runtime = FakeStructuredInferencePort(outputs=[])

    candidate, _ = determine_io_resources(
        llm_runtime=runtime,
        tool_catalog=load_signed_tool_registry(),
        request_intent=intent,
        request=request,
        retry_budget=build_default_run_budget(),
    )

    assert candidate.input_resource_types == ("GMAIL_DRAFT",)
    assert candidate.input_reason_codes == (("GMAIL_DRAFT", "EXPLICIT_RESOURCE_ID"),)
    assert candidate.output_pairs == (("GMAIL_DRAFT", EffectType.UPDATE),)
    assert runtime.calls == []


def test_named_gmail_draft_update__requires_search_read__without_llm() -> None:
    intent = cast(
        RequestIntentV2,
        {
            "schema_version": 2,
            "meta": {"artifact_id": "intent-draft", "revision": 1, "based_on": []},
            "goal": "update the named draft",
            "completion_conditions": ["updated without sending"],
            "constraints": [
                {
                    "kind": "USER_REQUIREMENT",
                    "field": "search_terms",
                    "value": ["Quartz 납품 회신 검토"],
                }
            ],
            "requested_effect_hints": ["UPDATE"],
            "requested_resource_hints": ["GMAIL_DRAFT"],
            "analysis_requirement": "NONE",
            "ambiguity": {
                "requires_confirmation": False,
                "reason_codes": [],
                "missing_fields": [],
            },
        },
    )
    request = WorkflowStartRequest(
        run_id="run-draft",
        conversation_id="conversation",
        workflow_key="thread",
        entry_mode="AGENT_SEARCH",
        requested_mode="LOCAL_GPU",
        request_text="임시보관함의 Quartz 납품 회신 검토 초안을 수정해줘.",
        selected_resource_ids=(),
        selected_resources=(),
        run_budget=dict(build_default_run_budget()),
        correlation=WorkflowCorrelationContext("request", "command", "v1"),
    )
    candidate, _ = determine_io_resources(
        llm_runtime=FakeStructuredInferencePort(outputs=[]),
        tool_catalog=load_signed_tool_registry(),
        request_intent=intent,
        request=request,
        retry_budget=build_default_run_budget(),
    )

    assert candidate.input_resource_types == ("GMAIL_DRAFT",)
    assert candidate.input_reason_codes == (("GMAIL_DRAFT", "REQUESTED_INPUT"),)
    assert candidate.output_pairs == (("GMAIL_DRAFT", EffectType.UPDATE),)


@pytest.mark.parametrize("effect_hints", [["SEND"], ["SEND", "READ"]])
def test_new_gmail_send__message_write_intent__skips_input_retrieval(
    effect_hints: list[str],
) -> None:
    intent = cast(
        RequestIntentV2,
        {
            "schema_version": 2,
            "meta": {"artifact_id": "intent-send", "revision": 1, "based_on": []},
            "goal": "send a new message and verify it",
            "completion_conditions": ["sent message is reread"],
            "constraints": [],
            "requested_effect_hints": effect_hints,
            "requested_resource_hints": ["GMAIL_MESSAGE"],
            "analysis_requirement": "NONE",
            "ambiguity": {
                "requires_confirmation": False,
                "reason_codes": [],
                "missing_fields": [],
            },
        },
    )
    request = WorkflowStartRequest(
        run_id="run-send",
        conversation_id="conversation",
        workflow_key="thread",
        entry_mode="AGENT_SEARCH",
        requested_mode="LOCAL_GPU",
        request_text="send a new message and reread the sent result",
        selected_resource_ids=(),
        selected_resources=(),
        run_budget=dict(build_default_run_budget()),
        correlation=WorkflowCorrelationContext("request", "command", "v1"),
    )
    runtime = FakeStructuredInferencePort(outputs=[])

    candidate, _ = determine_io_resources(
        llm_runtime=runtime,
        tool_catalog=load_signed_tool_registry(),
        request_intent=intent,
        request=request,
        retry_budget=build_default_run_budget(),
    )

    assert candidate.input_resource_types == ()
    assert candidate.output_pairs == (("GMAIL_MESSAGE", EffectType.SEND),)
    assert runtime.calls == []


def test_existing_gmail_thread_reply__thread_input_hint__routes_through_retrieval() -> None:
    intent = cast(
        RequestIntentV2,
        {
            "schema_version": 2,
            "meta": {"artifact_id": "intent-reply", "revision": 1, "based_on": []},
            "goal": "reply to an existing Gmail thread",
            "completion_conditions": ["reply is sent and reread from the same thread"],
            "constraints": [],
            "requested_effect_hints": ["READ", "SEND"],
            "requested_resource_hints": ["GMAIL_THREAD", "GMAIL_MESSAGE"],
            "analysis_requirement": "NONE",
            "ambiguity": {
                "requires_confirmation": False,
                "reason_codes": [],
                "missing_fields": [],
            },
        },
    )
    request = WorkflowStartRequest(
        run_id="run-reply",
        conversation_id="conversation",
        workflow_key="thread",
        entry_mode="AGENT_SEARCH",
        requested_mode="LOCAL_GPU",
        request_text="find the existing Gmail thread and reply to it",
        selected_resource_ids=(),
        selected_resources=(),
        run_budget=dict(build_default_run_budget()),
        correlation=WorkflowCorrelationContext("request", "command", "v1"),
    )
    runtime = FakeStructuredInferencePort(outputs=[])

    candidate, _ = determine_io_resources(
        llm_runtime=runtime,
        tool_catalog=load_signed_tool_registry(),
        request_intent=intent,
        request=request,
        retry_budget=build_default_run_budget(),
    )

    assert candidate.input_resource_types == ("GMAIL_THREAD",)
    assert candidate.output_pairs == (("GMAIL_MESSAGE", EffectType.SEND),)
    assert runtime.calls == []


@pytest.mark.parametrize("with_responsibilities", [False, True])
def test_gmail_read__message_and_thread__use_one_searchable_thread_route(
    with_responsibilities: bool,
) -> None:
    intent = cast(
        RequestIntentV2,
        {
            "schema_version": 2,
            "meta": {"artifact_id": "intent-read", "revision": 1, "based_on": []},
            "goal": "find one mail",
            "completion_conditions": ["report whether the mail exists"],
            "constraints": [],
            "requested_effect_hints": ["READ"],
            "requested_resource_hints": ["GMAIL_MESSAGE", "GMAIL_THREAD"],
            "analysis_requirement": "NONE",
            "ambiguity": {
                "requires_confirmation": False,
                "reason_codes": [],
                "missing_fields": [],
            },
            **(
                {
                    "resource_responsibilities": {
                        "source_reads": [
                            {"resource_type": "GMAIL_MESSAGE", "required_information": ["body"]},
                            {"resource_type": "GMAIL_THREAD", "required_information": ["subject"]},
                        ],
                        "outputs": [],
                    }
                }
                if with_responsibilities
                else {}
            ),
        },
    )
    request = WorkflowStartRequest(
        run_id="run-read",
        conversation_id="conversation",
        workflow_key="thread",
        entry_mode="AGENT_SEARCH",
        requested_mode="LOCAL_GPU",
        request_text="find the mail",
        selected_resource_ids=(),
        selected_resources=(),
        run_budget=dict(build_default_run_budget()),
        correlation=WorkflowCorrelationContext("request", "command", "v1"),
    )
    runtime = FakeStructuredInferencePort(outputs=[])

    candidate, _ = determine_io_resources(
        llm_runtime=runtime,
        tool_catalog=load_signed_tool_registry(),
        request_intent=intent,
        request=request,
        retry_budget=build_default_run_budget(),
    )

    assert candidate.input_resource_types == ("GMAIL_THREAD",)
    assert candidate.output_pairs == ()
    assert runtime.calls == []


def test_cross_resource_responsibilities__project_deterministically__to_input_and_output() -> None:
    intent = cast(
        RequestIntentV2,
        {
            "schema_version": 2,
            "meta": {"artifact_id": "intent-source-output", "revision": 1, "based_on": []},
            "goal": "use an existing message fact to create a task",
            "completion_conditions": ["task is created from the retrieved fact"],
            "constraints": [
                {
                    "kind": "USER_REQUIREMENT",
                    "field": "required_information",
                    "value": ["follow-up owner"],
                }
            ],
            "requested_effect_hints": ["READ", "CREATE"],
            "requested_resource_hints": ["GMAIL_THREAD", "TASK"],
            "resource_responsibilities": {
                "source_reads": [
                    {
                        "resource_type": "GMAIL_THREAD",
                        "required_information": ["follow-up owner"],
                    }
                ],
                "outputs": [{"resource_type": "TASK", "effect": "CREATE"}],
            },
            "analysis_requirement": "NONE",
            "ambiguity": {
                "requires_confirmation": False,
                "reason_codes": [],
                "missing_fields": [],
            },
        },
    )
    request = WorkflowStartRequest(
        run_id="run-source-output",
        conversation_id="conversation",
        workflow_key="thread",
        entry_mode="AGENT_SEARCH",
        requested_mode="LOCAL_GPU",
        request_text="find the owner in the mail and create a task",
        selected_resource_ids=(),
        selected_resources=(),
        run_budget=dict(build_default_run_budget()),
        correlation=WorkflowCorrelationContext("request", "command", "v1"),
    )
    runtime = FakeStructuredInferencePort(outputs=[])

    candidate, _ = determine_io_resources(
        llm_runtime=runtime,
        tool_catalog=load_signed_tool_registry(),
        request_intent=intent,
        request=request,
        retry_budget=build_default_run_budget(),
    )

    assert candidate.input_resource_types == ("GMAIL_THREAD",)
    assert candidate.output_pairs == (("TASK", EffectType.CREATE),)
    assert runtime.calls == []


def test_calendar_create__uses_exact_validated_intent__without_llm() -> None:
    catalog = load_signed_tool_registry()
    intent: RequestIntentV2 = {
        "schema_version": 2,
        "meta": {"artifact_id": "intent-calendar", "revision": 1, "based_on": []},
        "goal": "create calendar event",
        "completion_conditions": ["created"],
        "constraints": [],
        "requested_effect_hints": ["CREATE"],
        "requested_resource_hints": ["CALENDAR_EVENT"],
        "analysis_requirement": "NONE",
        "ambiguity": {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
    }
    request = WorkflowStartRequest(
        run_id="run-calendar",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode="AGENT_SEARCH",
        requested_mode="LOCAL_GPU",
        request_text="create an event",
        selected_resource_ids=(),
        selected_resources=(),
        run_budget=dict(build_default_run_budget()),
        correlation=WorkflowCorrelationContext("request-1", "command-1", "v1"),
    )
    runtime = FakeStructuredInferencePort(outputs=[])

    candidate, _ = determine_io_resources(
        llm_runtime=runtime,
        tool_catalog=catalog,
        request_intent=intent,
        request=request,
        retry_budget=build_default_run_budget(),
    )

    assert runtime.calls == []
    assert candidate.input_resource_types == ()
    assert candidate.output_pairs == (("CALENDAR_EVENT", EffectType.CREATE),)
    assert candidate.output_mode == "ACTION"


def test_semantic_revision_reuses__base_slot_and__bounded_failure_envelope() -> None:
    catalog = load_signed_tool_registry()
    intent: RequestIntentV2 = {
        "schema_version": 2,
        "meta": {"artifact_id": "intent-1", "revision": 1, "based_on": []},
        "goal": "create task",
        "completion_conditions": ["created"],
        "constraints": [],
        "requested_effect_hints": ["CREATE"],
        "requested_resource_hints": ["TASK", "CALENDAR_EVENT"],
        "analysis_requirement": "REQUIRED",
        "ambiguity": {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
    }
    request = WorkflowStartRequest(
        run_id="run-1",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode="AGENT_SEARCH",
        requested_mode="AUTO",
        request_text="create task",
        selected_resource_ids=(),
        run_budget=dict(build_default_run_budget()),
        correlation=WorkflowCorrelationContext(
            request_id="request-1", command_id="command-1", api_contract_version="v1"
        ),
    )
    prompt_ref = PromptReference(
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
    )
    runtime = FakeStructuredInferencePort(outputs=[{"schema_version": 0}, _valid_output()])

    determine_io_resources(
        llm_runtime=runtime,
        tool_catalog=catalog,
        request_intent=intent,
        request=request,
        retry_budget=build_default_run_budget(),
        prompt_ref=prompt_ref,
    )

    assert [call["prompt_ref"] for call in runtime.calls] == [prompt_ref, prompt_ref]
    revision_input = cast(Mapping[str, object], runtime.calls[1]["prompt_input"])
    assert set(revision_input) == {"base_projection", "candidate_output", "failure_record"}
    assert set(cast(Mapping[str, object], revision_input["base_projection"])) == {
        "request_intent",
        "eligible_route_capabilities",
    }
    failure_record = cast(Mapping[str, object], revision_input["failure_record"])
    assert failure_record["affected_field_paths"] == [
        "$.input_resource_types",
        "$.output_resource_types",
        "$.output_effects",
        "$.disposition",
    ]


def test_no_tool_disposition__with_input_routes__is_rejected() -> None:
    intent = cast(
        RequestIntentV2,
        {
            "schema_version": 2,
            "meta": {"artifact_id": "intent-answer", "revision": 1, "based_on": []},
            "goal": "answer without external resources",
            "completion_conditions": ["answered"],
            "constraints": [],
            "requested_effect_hints": [],
            "requested_resource_hints": ["GMAIL_THREAD", "TASK"],
            "analysis_requirement": "REQUIRED",
            "ambiguity": {
                "requires_confirmation": False,
                "reason_codes": [],
                "missing_fields": [],
            },
        },
    )
    request = WorkflowStartRequest(
        run_id="run-answer",
        conversation_id="conversation-answer",
        workflow_key="thread-answer",
        entry_mode="AGENT_SEARCH",
        requested_mode="LOCAL_GPU",
        request_text="answer without external resources",
        selected_resource_ids=(),
        selected_resources=(),
        run_budget=dict(build_default_run_budget()),
        correlation=WorkflowCorrelationContext("request-answer", "command-answer", "v1"),
    )
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "schema_version": 1,
                "input_resource_types": ["EMAIL"],
                "output_resource_types": [],
                "output_effects": [],
                "disposition": "NO_TOOL_NEEDED",
            },
            {
                "schema_version": 1,
                "input_resource_types": [],
                "output_resource_types": [],
                "output_effects": [],
                "disposition": "NO_TOOL_NEEDED",
            },
        ]
    )

    candidate, _ = determine_io_resources(
        llm_runtime=runtime,
        tool_catalog=load_signed_tool_registry(),
        request_intent=intent,
        request=request,
        retry_budget=build_default_run_budget(),
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

    assert len(runtime.calls) == 2
    assert candidate.input_resource_types == ()
    assert candidate.output_pairs == ()
    assert candidate.output_mode == "ANSWER"
    revision_input = cast(Mapping[str, object], runtime.calls[1]["prompt_input"])
    failure_record = cast(Mapping[str, object], revision_input["failure_record"])
    assert failure_record["affected_field_paths"] == ["$.input_resource_types"]


def test_semantic_route_schema__with_requested_writes__permits_only_those_effects() -> None:
    intent = cast(
        RequestIntentV2,
        {
            "schema_version": 2,
            "meta": {"artifact_id": "intent-task", "revision": 1, "based_on": []},
            "goal": "check for a duplicate and create one task",
            "completion_conditions": ["created once"],
            "constraints": [],
            "requested_effect_hints": ["READ", "CREATE"],
            "requested_resource_hints": ["TASK_LIST", "TASK"],
            "analysis_requirement": "NONE",
            "ambiguity": {
                "requires_confirmation": False,
                "reason_codes": [],
                "missing_fields": [],
            },
        },
    )
    request = WorkflowStartRequest(
        run_id="run-task",
        conversation_id="conversation-task",
        workflow_key="thread-task",
        entry_mode="AGENT_SEARCH",
        requested_mode="LOCAL_GPU",
        request_text="check for a duplicate and create one task",
        selected_resource_ids=(),
        selected_resources=(),
        run_budget=dict(build_default_run_budget()),
        correlation=WorkflowCorrelationContext("request-task", "command-task", "v1"),
    )
    runtime = FakeStructuredInferencePort(outputs=[_valid_output()], validate_schema=True)

    candidate, _ = determine_io_resources(
        llm_runtime=runtime,
        tool_catalog=load_signed_tool_registry(),
        request_intent=intent,
        request=request,
        retry_budget=build_default_run_budget(),
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

    schema = runtime.calls[0]["output_schema"].json_schema
    output_effects = cast(
        Mapping[str, object],
        cast(Mapping[str, object], schema["properties"])["output_effects"],
    )
    assert output_effects["items"] == {"enum": ["CREATE"]}
    assert candidate.input_resource_types == ("TASK",)
    assert candidate.output_pairs == (("TASK", EffectType.CREATE),)


def test_selected_analysis_read__stays_answer_only__without_llm() -> None:
    catalog = load_signed_tool_registry()
    intent: RequestIntentV2 = {
        "schema_version": 2,
        "meta": {"artifact_id": "intent-read", "revision": 1, "based_on": []},
        "goal": "read selected mail",
        "completion_conditions": ["summarized"],
        "constraints": [],
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["GMAIL_THREAD"],
        "analysis_requirement": "REQUIRED",
        "ambiguity": {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
    }
    request = WorkflowStartRequest(
        run_id="run-read",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode="RESOURCE_SELECTED",
        requested_mode="LOCAL_GPU",
        request_text="read this mail",
        selected_resource_ids=("thread-42",),
        selected_resources=(
            SelectedResourceRef("ref-thread-42", "google_workspace", "gmail_thread", "thread-42"),
        ),
        run_budget=dict(build_default_run_budget()),
        correlation=WorkflowCorrelationContext("request-1", "command-1", "v1"),
    )
    runtime = FakeStructuredInferencePort(outputs=[])

    candidate, _ = determine_io_resources(
        llm_runtime=runtime,
        tool_catalog=catalog,
        request_intent=intent,
        request=request,
        retry_budget=build_default_run_budget(),
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

    assert candidate.output_mode == "ANSWER"
    assert candidate.output_pairs == ()
    assert candidate.input_resource_types == ("GMAIL_THREAD",)
    assert candidate.input_reason_codes == (("GMAIL_THREAD", "RESOURCE_SELECTED"),)
    assert candidate.analysis_requirement == "REQUIRED"
    assert runtime.calls == []


def test_selected_simple_read__materializes_exact_route__without_llm() -> None:
    catalog = load_signed_tool_registry()
    intent: RequestIntentV2 = {
        "schema_version": 2,
        "meta": {"artifact_id": "intent-read", "revision": 1, "based_on": []},
        "goal": "read selected mail",
        "completion_conditions": ["summarized"],
        "constraints": [
            {"kind": "RESOURCE", "field": "selected_resource_id", "value": ["thread-42"]}
        ],
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["GMAIL_THREAD"],
        "analysis_requirement": "NONE",
        "ambiguity": {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
    }
    request = WorkflowStartRequest(
        run_id="run-read",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode="RESOURCE_SELECTED",
        requested_mode="LOCAL_GPU",
        request_text="read this mail",
        selected_resource_ids=("thread-42",),
        selected_resources=(
            SelectedResourceRef("ref-thread-42", "google_workspace", "gmail_thread", "thread-42"),
        ),
        run_budget=dict(build_default_run_budget()),
        correlation=WorkflowCorrelationContext("request-1", "command-1", "v1"),
    )
    runtime = FakeStructuredInferencePort(outputs=[])

    candidate, _ = determine_io_resources(
        llm_runtime=runtime,
        tool_catalog=catalog,
        request_intent=intent,
        request=request,
        retry_budget=build_default_run_budget(),
    )

    assert runtime.calls == []
    assert candidate.output_mode == "ANSWER"
    assert candidate.input_resource_types == ("GMAIL_THREAD",)
    assert candidate.input_reason_codes == (("GMAIL_THREAD", "RESOURCE_SELECTED"),)


def test_answer_only__materializes_no_tool_route__without_llm() -> None:
    catalog = load_signed_tool_registry()
    intent: RequestIntentV2 = {
        "schema_version": 2,
        "meta": {"artifact_id": "intent-read", "revision": 1, "based_on": []},
        "goal": "answer arithmetic question",
        "completion_conditions": ["answered"],
        "constraints": [],
        "requested_effect_hints": [],
        "requested_resource_hints": [],
        "analysis_requirement": "NONE",
        "ambiguity": {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
    }
    request = WorkflowStartRequest(
        run_id="run-answer",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode="AGENT_SEARCH",
        requested_mode="LOCAL_GPU",
        request_text="2 + 2",
        selected_resource_ids=(),
        selected_resources=(),
        run_budget=dict(build_default_run_budget()),
        correlation=WorkflowCorrelationContext("request-1", "command-1", "v1"),
    )
    runtime = FakeStructuredInferencePort(outputs=[])

    candidate, _ = determine_io_resources(
        llm_runtime=runtime,
        tool_catalog=catalog,
        request_intent=intent,
        request=request,
        retry_budget=build_default_run_budget(),
    )

    assert runtime.calls == []
    assert candidate.input_resource_types == ()
    assert candidate.output_pairs == ()
    assert candidate.output_mode == "ANSWER"
