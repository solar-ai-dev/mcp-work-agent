from __future__ import annotations

import pytest
from tests.support.fakes.llm import FakeStructuredInferencePort

from google_work_agent.application.agents.request_understanding.identify_requested_work import (
    validate_requested_work_candidate,
)
from google_work_agent.application.agents.request_understanding.identify_work_relations import (
    identify_work_relations,
    relation_decision_output_schema,
    relation_decision_pairs,
    validate_relation_decisions,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import PromptReference


def _prompt() -> PromptReference:
    return PromptReference(
        prompt_bundle_version="test",
        prompt_id="request_understanding.identify_work_relations",
        prompt_version="1",
        content_hash="hash",
        agent_role="request_understanding",
        subgraph_name="request_understanding",
        node_name="identify_work_relations",
        node_state="INITIAL",
        purpose="identify_work_relations",
        input_schema_version="v1",
        output_schema_version="v1",
    )


def _two_units() -> dict[str, object]:
    return {
        "work_units": [
            {
                "unit_id": "work-1",
                "request_provenance": [
                    {
                        "source": "USER_REQUEST",
                        "start_offset": 0,
                        "end_offset": 6,
                        "source_text": "메일 요약",
                    }
                ],
            },
            {
                "unit_id": "work-2",
                "request_provenance": [
                    {
                        "source": "USER_REQUEST",
                        "start_offset": 9,
                        "end_offset": 14,
                        "source_text": "초안 작성",
                    }
                ],
            },
        ],
        "work_relations": [],
    }


def test_relation_owner__single_work_unit__skips_llm() -> None:
    requested_work = validate_requested_work_candidate(
        {
            "schema_version": 1,
            "work_units": [{"request_spans": ["메일을 요약해줘"]}],
        },
        user_request="메일을 요약해줘",
    )
    runtime = FakeStructuredInferencePort(outputs=[])

    assert identify_work_relations(
        llm_runtime=runtime,
        requested_mode="LOCAL_GPU",
        prompt_ref=_prompt(),
        user_request="메일을 요약해줘",
        requested_work=requested_work,
        constraints=[],
        source_responsibilities=[],
        output_responsibilities=[],
    ) == []
    assert runtime.calls == []


def test_relation_owner__exhaustive_pairs__use_fixed_kind() -> None:
    requested_work = _two_units()
    outputs = [
        {
            "resource_type": "GITHUB_ISSUE",
            "effect": "CREATE",
            "work_unit_ids": ["work-1"],
        }
    ]
    pairs = relation_decision_pairs(
        requested_work,  # type: ignore[arg-type]
        output_responsibilities=outputs,
    )
    assert pairs == [
        {
            "source_work_unit_id": "work-1",
            "target_work_unit_id": "work-2",
            "allowed_relation_kind": "CONSUMES_PLANNED_SPECIFICATION",
        },
        {
            "source_work_unit_id": "work-2",
            "target_work_unit_id": "work-1",
            "allowed_relation_kind": "CONSUMES_WORK_PRODUCT",
        },
    ]
    candidate = {
        "schema_version": 1,
        "relation_decisions": [
            {
                "source_work_unit_id": "work-1",
                "target_work_unit_id": "work-2",
                "disposition": "CONSUMES_PLANNED_SPECIFICATION",
            },
            {
                "source_work_unit_id": "work-2",
                "target_work_unit_id": "work-1",
                "disposition": "NONE",
            },
        ],
    }
    runtime = FakeStructuredInferencePort(outputs=[candidate], validate_schema=True)

    assert identify_work_relations(
        llm_runtime=runtime,
        requested_mode="LOCAL_GPU",
        prompt_ref=_prompt(),
        user_request="메일 요약 후 초안 작성",
        requested_work=requested_work,  # type: ignore[arg-type]
        constraints=[],
        source_responsibilities=[],
        output_responsibilities=outputs,
    ) == [
        {
            "source_work_unit_id": "work-1",
            "target_work_unit_id": "work-2",
            "kind": "CONSUMES_PLANNED_SPECIFICATION",
        }
    ]
    assert len(runtime.calls) == 1


def test_relation_owner__wrong_kind__fails_closed() -> None:
    pairs = relation_decision_pairs(
        _two_units(),  # type: ignore[arg-type]
        output_responsibilities=[
            {
                "resource_type": "GITHUB_ISSUE",
                "effect": "CREATE",
                "work_unit_ids": ["work-1"],
            }
        ],
    )
    candidate = {
        "schema_version": 1,
        "relation_decisions": [
            {
                "source_work_unit_id": "work-1",
                "target_work_unit_id": "work-2",
                "disposition": "CONSUMES_WORK_PRODUCT",
            },
            {
                "source_work_unit_id": "work-2",
                "target_work_unit_id": "work-1",
                "disposition": "NONE",
            },
        ],
    }

    assert validate_output_schema(candidate, relation_decision_output_schema(pairs).json_schema)
    with pytest.raises(ValueError, match="relation candidate is invalid"):
        validate_relation_decisions(candidate, pairs=pairs)
