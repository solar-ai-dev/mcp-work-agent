from __future__ import annotations

from typing import cast

from tests.support.fakes.llm import FakeStructuredInferencePort

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    SOURCE_STATUS_VALUES_BY_RESOURCE,
    ResourceResponsibilitiesV1,
)
from google_work_agent.application.agents.request_understanding.identify_source_status import (
    build_identify_source_status_output_schema,
    identify_source_status,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import PromptReference


def _source_status(value: str, resource_type: str, source_text: str) -> dict[str, str]:
    return {
        "value": value,
        "source_resource_type": resource_type,
        "source": "USER_REQUEST",
        "source_text": source_text,
    }


def _prompt_ref() -> PromptReference:
    return PromptReference(
        prompt_bundle_version="test",
        prompt_id="request_understanding.identify_source_status",
        prompt_version="1",
        content_hash="hash",
        agent_role="request_understanding",
        subgraph_name="request_understanding",
        node_name="identify_source_status",
        node_state="INITIAL",
        purpose="identify_source_status",
        input_schema_version="v1",
        output_schema_version="v1",
    )


def test_identify_source_status__with_unconstrained_source__exposes_no_any_choice() -> None:
    runtime = FakeStructuredInferencePort(outputs=[{"statuses": []}], validate_schema=True)
    responsibilities = cast(
        ResourceResponsibilitiesV1,
        {
            "source_reads": [
                {
                    "resource_type": "GMAIL_THREAD",
                    "required_information": ["final schedule and owner"],
                }
            ],
            "outputs": [],
        },
    )

    result = identify_source_status(
        llm_runtime=runtime,
        requested_mode="LOCAL_GPU",
        prompt_ref=_prompt_ref(),
        prompt_input={"user_request": "find the final schedule", "selected_resource_refs": []},
        goal_candidate={
            "goal": "find the final schedule",
            "completion_conditions": ["report the schedule"],
            "constraints": {},
            "analysis_requirement": "NONE",
        },
        responsibilities=responsibilities,
    )

    assert result == {"statuses": []}
    assert runtime.calls[0]["prompt_input"]["allowed_status_values"] == [
        {"resource_type": "GMAIL_THREAD", "values": ["DRAFT", "SENT"]}
    ]


def test_identify_source_status_schema__with_every_source_resource__rejects_any_value() -> None:
    responsibilities = cast(
        ResourceResponsibilitiesV1,
        {
            "source_reads": [
                {"resource_type": resource_type, "required_information": []}
                for resource_type in SOURCE_STATUS_VALUES_BY_RESOURCE
            ],
            "outputs": [],
        },
    )
    schema = build_identify_source_status_output_schema(responsibilities)

    assert schema.schema_version == "request-source-status-v2"
    for resource_type in SOURCE_STATUS_VALUES_BY_RESOURCE:
        assert validate_output_schema(
            {"statuses": [_source_status("ANY", resource_type, "any")]},
            schema.json_schema,
        )


def test_identify_source_status_schema__with_output_only_draft__rejects_source_scope() -> None:
    schema = build_identify_source_status_output_schema(
        cast(
            ResourceResponsibilitiesV1,
            {
                "source_reads": [
                    {"resource_type": "TASK", "required_information": ["readiness"]},
                    {
                        "resource_type": "CALENDAR_EVENT",
                        "required_information": ["schedule"],
                    },
                ],
                "outputs": [{"resource_type": "GMAIL_DRAFT", "effect": "CREATE"}],
            },
        )
    )

    invalid = {"statuses": [_source_status("DRAFT", "GMAIL_DRAFT", "drafts")]}
    valid = {"statuses": [_source_status("COMPLETED", "TASK", "completed")]}

    assert validate_output_schema(invalid, schema.json_schema)
    assert validate_output_schema(valid, schema.json_schema) == []


def test_identify_source_status__draft_source_only__skips_tautological_inference() -> None:
    runtime = FakeStructuredInferencePort(outputs=[], validate_schema=True)
    responsibilities = cast(
        ResourceResponsibilitiesV1,
        {
            "source_reads": [
                {
                    "resource_type": "GMAIL_DRAFT",
                    "required_information": ["current body"],
                }
            ],
            "outputs": [{"resource_type": "GMAIL_DRAFT", "effect": "UPDATE"}],
        },
    )

    result = identify_source_status(
        llm_runtime=runtime,
        requested_mode="LOCAL_GPU",
        prompt_ref=_prompt_ref(),
        prompt_input={"user_request": "update the draft", "selected_resource_refs": []},
        goal_candidate={
            "goal": "update the existing draft",
            "completion_conditions": ["preserve existing fields"],
            "constraints": {},
            "analysis_requirement": "NONE",
        },
        responsibilities=responsibilities,
    )

    schema = build_identify_source_status_output_schema(responsibilities)
    assert result == {"statuses": []}
    assert runtime.calls == []
    assert validate_output_schema(
        {"statuses": [_source_status("DRAFT", "GMAIL_DRAFT", "draft")]},
        schema.json_schema,
    )
