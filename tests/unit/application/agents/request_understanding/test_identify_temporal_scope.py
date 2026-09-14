from typing import cast

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestGoalCandidateV1,
)
from google_work_agent.application.agents.request_understanding.identify_temporal_scope import (
    identify_temporal_scope,
    needs_temporal_scope,
)
from google_work_agent.ports.llm.structured_inference_contracts import PromptReference
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort


def _candidate() -> RequestGoalCandidateV1:
    return {
        "goal": "메일 확인",
        "completion_conditions": ["요청한 자료 확인"],
        "constraints": [],
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["GMAIL_THREAD"],
        "analysis_requirement": "NONE",
    }


def _prompt_ref() -> PromptReference:
    return PromptReference(
        prompt_bundle_version="test",
        prompt_id="request_understanding.identify_temporal_scope",
        prompt_version="test",
        content_hash="test",
        agent_role="REQUEST_UNDERSTANDING",
        subgraph_name="request_understanding",
        node_name="identify_temporal_scope",
        node_state="ACTIVE",
        purpose="identify_temporal_scope",
        input_schema_version="request-temporal-scope-input-v1",
        output_schema_version="request-temporal-scope-v1",
    )


def test_temporal_scope__without_explicit_period__skips_inference() -> None:
    candidate = _candidate()

    assert needs_temporal_scope(candidate) is False
    assert identify_temporal_scope(
        llm_runtime=cast(StructuredInferencePort, object()),
        prompt_ref=_prompt_ref(),
        requested_mode="LOCAL_GPU",
        request_text="최근 메일을 확인해줘.",
        candidate=candidate,
    ) is candidate
