from __future__ import annotations

import pytest
from tests.support.fakes.llm import FakeStructuredInferencePort

from google_work_agent.application.agents.request_understanding.identify_requested_work import (
    identify_requested_work,
    validate_requested_work_candidate,
)
from google_work_agent.ports.llm.structured_inference_contracts import PromptReference


def _prompt(prompt_id: str, node_name: str) -> PromptReference:
    return PromptReference(
        prompt_bundle_version="test",
        prompt_id=prompt_id,
        prompt_version="1",
        content_hash="hash",
        agent_role="request_understanding",
        subgraph_name="request_understanding",
        node_name=node_name,
        node_state="INITIAL",
        purpose=node_name,
        input_schema_version="v1",
        output_schema_version="v1",
    )


def test_identify_requested_work__exact_request_spans__bind_stable_ids() -> None:
    request = "메일을 요약하고 그 요약으로 이슈 초안을 작성해줘"
    first = "메일을 요약하고"
    second = "그 요약으로 이슈 초안을 작성해줘"
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "schema_version": 1,
                "work_units": [
                    {"request_spans": [second]},
                    {"request_spans": [first]},
                ],
            }
        ],
        validate_schema=True,
    )

    result = identify_requested_work(
        llm_runtime=runtime,
        requested_mode="LOCAL_GPU",
        prompt_ref=_prompt(
            "request_understanding.identify_requested_work",
            "identify_requested_work",
        ),
        user_request=request,
    )

    assert [unit["unit_id"] for unit in result["work_units"]] == ["work-1", "work-2"]
    assert [
        unit["request_provenance"][0]["source_text"] for unit in result["work_units"]
    ] == [first, second]


def test_requested_work_candidate__invalid_request_spans__fails_closed() -> None:
    with pytest.raises(ValueError, match="bind exactly once"):
        validate_requested_work_candidate(
            {
                "schema_version": 1,
                "work_units": [{"request_spans": ["없는 업무"]}],
            },
            user_request="메일을 요약해줘",
        )
    with pytest.raises(ValueError, match="must not overlap"):
        validate_requested_work_candidate(
            {
                "schema_version": 1,
                "work_units": [
                    {"request_spans": ["메일을 요약하고"]},
                    {"request_spans": ["요약하고"]},
                ],
            },
            user_request="메일을 요약하고 초안을 작성해줘",
        )
