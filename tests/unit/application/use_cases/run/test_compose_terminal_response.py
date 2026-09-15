from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from google_work_agent.application.use_cases.run.build_terminal_message import (
    TerminalAssistantMessageInputV1,
)
from google_work_agent.application.use_cases.run.compose_terminal_response import (
    ComposeTerminalResponseCommandV1,
    ComposeTerminalResponseHandler,
    TerminalResponseInputV1,
    build_terminal_response_input,
)
from google_work_agent.ports.llm.structured_inference_contracts import (
    LLMErrorCode,
    LLMInvocationError,
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferenceResultV1


class _Inference:
    def __init__(self, output: dict[str, object] | Exception) -> None:
        self.output = output
        self.calls: list[Mapping[str, object]] = []

    def infer(
        self,
        requested_mode: str,
        prompt_ref: PromptReference,
        input_projection: Mapping[str, object],
        output_schema_ref: OutputSchemaDefinition,
    ) -> StructuredInferenceResultV1:
        del requested_mode, prompt_ref, output_schema_ref
        self.calls.append(input_projection)
        if isinstance(self.output, Exception):
            raise self.output
        return StructuredInferenceResultV1(
            schema_version=1,
            structured_output=self.output,
            provider="test",
            model="test-model",
            actual_runtime="LOCAL_GPU",
            input_tokens=10,
            output_tokens=5,
            latency_ms=7,
            fallback_reason=None,
        )


def _prompt_ref() -> PromptReference:
    return PromptReference(
        prompt_bundle_version="test",
        prompt_id="run.compose_terminal_response",
        prompt_version="1.0.0",
        content_hash="0" * 64,
        agent_role="run",
        subgraph_name="main",
        node_name="response_synthesis",
        node_state="INITIAL",
        purpose="compose_terminal_response",
        input_schema_version="1",
        output_schema_version="1",
    )


def _fallback() -> TerminalAssistantMessageInputV1:
    return TerminalAssistantMessageInputV1(
        schema_version=1,
        result_kind="SUCCESS",
        content="결정적 응답",
        reason_codes=["WRITE_VERIFIED"],
    )


def _response_input(*, no_send: bool = False) -> TerminalResponseInputV1:
    return build_terminal_response_input(
        user_request="메일 초안을 수정해 줘",
        result_kind="SUCCESS",
        actions=[
            {
                "connector_id": "google_workspace",
                "resource_type": "gmail_draft",
                "effect_type": "UPDATE",
                "status": "VERIFIED",
                "arguments": {"subject": "계획 제목", "body": "계획 본문"},
                "target_display": {"subject": "기존 초안"},
                "verification_actual": {
                    "subject": "검증된 초안",
                    "body": "검증된 본문",
                },
            }
        ],
        send_not_dispatched_current_run=no_send,
    )


def test_terminal_response_input__uses_verified_values__not_plan_arguments() -> None:
    projection = _response_input(no_send=True).to_projection()

    action = cast(list[dict[str, object]], projection["action_results"])[0]
    assert action["target_label"] == "검증된 초안"
    assert action["verified_fields"] == [
        {"field": "subject", "value": "검증된 초안"},
        {"field": "body_excerpt", "value": "검증된 본문"},
    ]
    assert "계획 제목" not in str(projection)
    assert projection["effect_observations"] == [
        {"effect_type": "SEND", "scope": "CURRENT_RUN", "dispatched": False}
    ]


def test_terminal_response_input__does_not_invent__no_dispatch_observation() -> None:
    projection = _response_input().to_projection()

    assert projection["effect_observations"] == []


def test_terminal_response_input__preserves_prior_effect__without_resource_overcount() -> None:
    response_input = build_terminal_response_input(
        user_request="초안을 만든 뒤 수정해 줘",
        result_kind="SUCCESS",
        actions=[
            {
                "connector_id": "google_workspace",
                "resource_type": "gmail_draft",
                "effect_type": "CREATE",
                "status": "VERIFIED",
                "target_display": {"subject": "하나의 초안"},
                "verification_actual": {"subject": "하나의 초안"},
            },
            {
                "connector_id": "google_workspace",
                "resource_type": "gmail_draft",
                "effect_type": "UPDATE",
                "status": "VERIFIED",
                "target_display": {"subject": "하나의 초안"},
                "verification_actual": {
                    "subject": "하나의 초안",
                    "body": "최종 본문",
                },
            },
        ],
        send_not_dispatched_current_run=False,
    )

    assert [item.effect_type for item in response_input.action_results] == [
        "CREATE",
        "UPDATE",
    ]
    assert {item.target_label for item in response_input.action_results} == {"하나의 초안"}


def test_compose_terminal_response__returns_only__sanitized_llm_prose() -> None:
    inference = _Inference(
        {"answer": "google_workspace 내부 코드 없이 검증된 초안을 수정했습니다."}
    )
    handler = ComposeTerminalResponseHandler(
        llm_runtime=inference,
        prompt_ref=_prompt_ref(),
    )

    result = handler(
        ComposeTerminalResponseCommandV1(
            schema_version=1,
            run_id="run-1",
            requested_mode="LOCAL_GPU",
            response_input=_response_input(),
            fallback_message=_fallback(),
        )
    )

    assert result.generation_mode == "LLM"
    assert "google_workspace" not in result.terminal_message.content
    assert "검증된 초안" in result.terminal_message.content
    assert len(inference.calls) == 1
    assert set(inference.calls[0]) == {
        "schema_version",
        "user_request",
        "result_kind",
        "action_results",
        "effect_observations",
        "limitations",
    }


def test_compose_terminal_response__preserves_send_limitation__for_llm_and_fallback() -> None:
    response_input = build_terminal_response_input(
        user_request="안내 메일을 보내 줘",
        result_kind="SUCCESS",
        actions=[
            {
                "connector_id": "google_workspace",
                "resource_type": "gmail_message",
                "effect_type": "SEND",
                "status": "VERIFIED",
                "target_display": {"subject": "안내"},
                "verification_actual": {
                    "subject": "안내",
                    "to": ["owner@example.test"],
                },
            }
        ],
        send_not_dispatched_current_run=False,
    )
    limitation = response_input.limitations[0]
    command = ComposeTerminalResponseCommandV1(
        schema_version=1,
        run_id="run-1",
        requested_mode="LOCAL_GPU",
        response_input=response_input,
        fallback_message=_fallback(),
    )

    llm_result = ComposeTerminalResponseHandler(
        llm_runtime=_Inference({"answer": "안내 메일을 전송했습니다."}),
        prompt_ref=_prompt_ref(),
    )(command)
    assert limitation in llm_result.terminal_message.content

    fallback_result = ComposeTerminalResponseHandler(
        llm_runtime=_Inference(
            LLMInvocationError(LLMErrorCode.PROVIDER_TIMEOUT, "timeout")
        ),
        prompt_ref=_prompt_ref(),
    )(command)
    assert limitation in fallback_result.terminal_message.content


def test_compose_terminal_response__llm_failure__keeps_success_and_falls_back() -> None:
    inference = _Inference(
        LLMInvocationError(LLMErrorCode.PROVIDER_TIMEOUT, "timeout", retryable=True)
    )
    result = ComposeTerminalResponseHandler(
        llm_runtime=inference,
        prompt_ref=_prompt_ref(),
    )(
        ComposeTerminalResponseCommandV1(
            schema_version=1,
            run_id="run-1",
            requested_mode="AUTO",
            response_input=_response_input(),
            fallback_message=_fallback(),
        )
    )

    assert result.generation_mode == "FALLBACK"
    assert result.fallback_reason == "PROVIDER_TIMEOUT"
    assert result.terminal_message == _fallback()
    assert result.terminal_message.result_kind == "SUCCESS"


def test_compose_terminal_response__malformed_answer__uses_fallback() -> None:
    result = ComposeTerminalResponseHandler(
        llm_runtime=_Inference({"answer": "ok", "next_action": "send"}),
        prompt_ref=_prompt_ref(),
    )(
        ComposeTerminalResponseCommandV1(
            schema_version=1,
            run_id="run-1",
            requested_mode="LOCAL_GPU",
            response_input=_response_input(),
            fallback_message=_fallback(),
        )
    )

    assert result.generation_mode == "FALLBACK"
    assert result.fallback_reason == "TERMINAL_RESPONSE_OUTPUT_INVALID"
