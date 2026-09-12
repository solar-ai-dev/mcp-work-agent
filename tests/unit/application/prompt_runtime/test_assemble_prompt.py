from __future__ import annotations

from pathlib import Path

import pytest
from tests.support.canonical_prompt_runtime import (
    activate_prompt_slot,
    copy_prompt_runtime_artifacts,
)

from google_work_agent.application.prompt_runtime.assemble_prompt import (
    PromptAssemblyError,
    assemble_prompt,
)
from google_work_agent.application.prompt_runtime.contracts.failure_record import (
    build_failure_record_v1,
)
from google_work_agent.application.prompt_runtime.prompt_registry import (
    DEVELOPMENT_SMOKE,
    EVALUATION,
    PromptRegistry,
)


def _active_registry(tmp_path: Path) -> PromptRegistry:
    manifest_path, contract_path = copy_prompt_runtime_artifacts(tmp_path)
    activate_prompt_slot(manifest_path, "planning.compose_answer")
    return PromptRegistry(manifest_path, contract_path)


def _projection() -> dict[str, object]:
    return {
        "user_request": "summarize",
        "request_intent": {"goal": "summary"},
        "answer_outline": {"sections": ["summary"]},
        "evidence": [],
        "temporal_constraints": [],
    }


def test_assemble_prompt__uses_registered_source__and_allowlisted_projection(
    tmp_path: Path,
) -> None:
    registry = _active_registry(tmp_path)
    prompt_ref = registry.lookup_by_id("planning.compose_answer")

    assembled = assemble_prompt(prompt_ref, _projection(), registry=registry)
    source = registry.source_text(prompt_ref.prompt_id).rstrip()

    assert assembled.startswith(f"{source}\n\n")
    assert "Product-wide context: mcp-work-agent is a workplace productivity product" in assembled
    assert "workplace productivity product, not a social companion" in assembled
    assert "Product display language is Korean" in assembled
    assert "Internal codes are metadata, never button labels" in assembled
    assert "without simulating feelings" in assembled
    assert "restrained professional voice" in assembled
    assert "precise, calm language" in assembled
    assert '"user_request":"summarize"' in assembled
    assert (
        '"answer": "회의 일정은 9월 15일 오후 4시이며 장소는 3층 회의실 B입니다."'
        in assembled
    )
    assert '"answer": "{\\"sections\\":[...]}"' in assembled
    assert '"answer": "[{\\"section_title\\":...}]"' in assembled
    assert '"answer": "```json ... ```"' in assembled


def test_output_responsibility_prompt__assembles_semantic_contrast_examples(
    tmp_path: Path,
) -> None:
    manifest_path, contract_path = copy_prompt_runtime_artifacts(tmp_path)
    prompt_id = "request_understanding.identify_output_responsibilities"
    activate_prompt_slot(manifest_path, prompt_id)
    registry = PromptRegistry(manifest_path, contract_path)
    prompt_ref = registry.lookup_by_id(prompt_id)

    assembled = assemble_prompt(
        prompt_ref,
        {
            "user_request": "이 메일에서 날짜, 시간, 장소, 요청사항만 뽑아줘.",
            "selected_resource_refs": [
                {
                    "connector_id": "google_workspace",
                    "resource_type": "gmail_thread",
                    "resource_id": "thread-1",
                }
            ],
            "goal_candidate": {"goal": "선택한 메일에서 필요한 정보를 답한다"},
            "output_candidates": [
                {"resource_type": "GMAIL_MESSAGE", "allowed_output_effects": ["SEND"]},
                {
                    "resource_type": "GMAIL_DRAFT",
                    "allowed_output_effects": ["CREATE", "UPDATE"],
                },
                {"resource_type": "TASK", "allowed_output_effects": ["CREATE"]},
            ],
            "effect_prohibitions": [
                {"effect": effect, "prohibition": "NOT_FORBIDDEN"}
                for effect in ("CREATE", "UPDATE", "SEND", "DELETE")
            ],
        },
        registry=registry,
    )

    assert prompt_ref.prompt_version == "1.0.1"
    assert "참조하거나 읽는 Source Resource와 외부 변경의 대상 Resource" in assembled
    assert "정보를 Answer로 제공하는 일은 외부 Resource를" in assembled
    assert "effect가 가능하거나 `NOT_FORBIDDEN`이라는 사실" in assembled
    assert '요청: "이 메일 내용을 요약해줘."' in assembled
    assert '요청: "이 메일 내용으로 할 일을 만들어줘."' in assembled
    assert '요청: "이 메일 읽고 그 내용으로 태스크를 만들어줘."' in assembled


def test_assemble_prompt_rejects__forbidden_previous_run__and_evaluation_fields(
    tmp_path: Path,
) -> None:
    registry = _active_registry(tmp_path)
    prompt_ref = registry.lookup_by_id("planning.compose_answer")

    for field in ("conversation_history", "previous_run_artifacts", "gold", "grader"):
        with pytest.raises(PromptAssemblyError):
            assemble_prompt(
                prompt_ref,
                {**_projection(), "request_intent": {field: "forbidden"}},
                registry=registry,
            )


def test_assemble_prompt_rejects__raw_provider_continuation__and_mcp_arguments(
    tmp_path: Path,
) -> None:
    registry = _active_registry(tmp_path)
    prompt_ref = registry.lookup_by_id("planning.compose_answer")

    for field in ("next_page_token", "provider_continuation", "mcp_arguments"):
        with pytest.raises(PromptAssemblyError):
            assemble_prompt(
                prompt_ref,
                {**_projection(), "request_intent": {field: "forbidden"}},
                registry=registry,
            )


def test_assemble_prompt__adds_bounded__failure_instruction(tmp_path: Path) -> None:
    registry = _active_registry(tmp_path)
    prompt_ref = registry.lookup_by_id("planning.compose_answer")
    failure = build_failure_record_v1(
        failure_reason_code="OUTPUT_SCHEMA_INVALID",
        failure_origin="LLM_OUTPUT",
        detected_by="RUNTIME_SCHEMA_VALIDATOR",
        runtime_disposition="RETRYABLE",
        experiment_disposition="RUN_REPAIR",
        affected_field_paths=["$.answer"],
    )

    assembled = assemble_prompt(
        prompt_ref, _projection(), failure_record=failure, registry=registry
    )

    assert "Bounded failure instruction" in assembled
    assert "preserve all unaffected fields" in assembled
    assert "return the complete corrected object" in assembled
    assert "OUTPUT_SCHEMA_INVALID" in assembled
    assert "experiment_disposition" not in assembled


def test_evaluation_and_development_scope__use_same__draft_base_source() -> None:
    registry = PromptRegistry()
    prompt_ref = registry.lookup_for_evaluation("planning.compose_answer")

    evaluation_assembled = assemble_prompt(
        prompt_ref,
        _projection(),
        registry=registry,
        execution_scope=EVALUATION,
    )
    development_assembled = assemble_prompt(
        prompt_ref,
        _projection(),
        registry=registry,
        execution_scope=DEVELOPMENT_SMOKE,
    )
    source = registry.source_text(prompt_ref.prompt_id).rstrip()

    assert evaluation_assembled.startswith(f"{source}\n\n")
    assert development_assembled == evaluation_assembled


def test_unknown_activation__scope_fails__closed() -> None:
    registry = PromptRegistry()
    prompt_ref = registry.lookup_for_evaluation("planning.compose_answer")

    with pytest.raises(PromptAssemblyError, match="unknown Prompt execution scope"):
        assemble_prompt(
            prompt_ref,
            _projection(),
            registry=registry,
            execution_scope="OTHER",  # type: ignore[arg-type]
        )


def test_development_smoke__does_not_admit__evaluation_only_fields() -> None:
    registry = PromptRegistry()
    prompt_ref = registry.lookup_for_development_smoke("planning.compose_answer")

    for field in ("gold", "grader", "expected_output", "evaluation_id"):
        with pytest.raises(PromptAssemblyError):
            assemble_prompt(
                prompt_ref,
                {**_projection(), field: "forbidden"},
                registry=registry,
                execution_scope=DEVELOPMENT_SMOKE,
            )


def test_repair_envelope__reuses_base_source__and_binds_candidate(tmp_path: Path) -> None:
    registry = _active_registry(tmp_path)
    prompt_ref = registry.lookup_by_id("planning.compose_answer")
    failure = build_failure_record_v1(
        failure_reason_code="OUTPUT_SCHEMA_INVALID",
        failure_origin="LLM_OUTPUT",
        detected_by="RUNTIME_SCHEMA_VALIDATOR",
        runtime_disposition="RETRYABLE",
        experiment_disposition="RUN_REPAIR",
        affected_field_paths=["$.answer"],
    )

    assembled = assemble_prompt(
        prompt_ref,
        {
            "base_projection": _projection(),
            "candidate_output": {"answer": 123},
            "failure_record": failure,
        },
        registry=registry,
    )

    assert "Candidate output to repair" in assembled
    assert '"answer":123' in assembled
    assert "OUTPUT_SCHEMA_INVALID" in assembled


def test_compose_prose_revision__uses_base_projection_without_raw_answer(tmp_path: Path) -> None:
    registry = _active_registry(tmp_path)
    prompt_ref = registry.lookup_by_id("planning.compose_answer")
    failure = build_failure_record_v1(
        failure_reason_code="COMPOSE_ANSWER_PROSE_INVALID",
        failure_origin="LLM_OUTPUT",
        detected_by="RUNTIME_DOMAIN_VALIDATOR",
        runtime_disposition="RETRYABLE",
        experiment_disposition="RUN_REVISION",
        affected_field_paths=["$.answer"],
    )

    assembled = assemble_prompt(
        prompt_ref,
        {
            "base_projection": _projection(),
            "candidate_output": None,
            "failure_record": failure,
        },
        registry=registry,
    )

    assert "COMPOSE_ANSWER_PROSE_INVALID" in assembled
    assert "Allowed current-Run input projection" in assembled
    assert "Candidate output to repair" not in assembled
    assert "기존의 잘못된 `answer`는 입력에 포함되지 않는다" in assembled
    assert "`answer` 필드를 만들거나 최종 사용자 답변 문장을 완성하지 않는다" in assembled
    assert "일반화된 `sections`" in assembled
