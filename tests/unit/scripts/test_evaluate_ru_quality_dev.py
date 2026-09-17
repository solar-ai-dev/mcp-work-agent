from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from scripts.evaluate_ru_quality_dev import (
    DEFAULT_DATASET,
    RuEvaluationLangSmithTrace,
    classify_execution_exception,
    load_ru_cases,
    read_ru_evaluation_langsmith_configuration,
)

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestGoalSemanticValidationError,
)
from google_work_agent.ports.llm.structured_inference_contracts import (
    LLMErrorCode,
    LLMInvocationError,
)
from google_work_agent.ports.system.external_call_trace_port import (
    ExternalCallTraceFinishV1,
    ExternalCallTraceStartV1,
)


class _LangSmithClient:
    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []
        self.updated: list[dict[str, Any]] = []

    def create_run(
        self,
        name: str,
        inputs: dict[str, Any],
        run_type: str,
        **kwargs: Any,
    ) -> None:
        self.created.append(
            {"name": name, "inputs": inputs, "run_type": run_type, **kwargs}
        )

    def update_run(self, run_id: UUID, **kwargs: Any) -> None:
        self.updated.append({"run_id": run_id, **kwargs})

    def flush(self, timeout: float | None = None) -> None:
        del timeout

    def close(self, timeout: float | None = None) -> None:
        del timeout


def _dataset(path: Path) -> Path:
    rows = [
        {"case_id": "RU-A-001", "user_request": "one"},
        {"case_id": "RU-A-002", "user_request": "two"},
    ]
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )
    return path


def test_default_dataset_is_current_v2() -> None:
    assert DEFAULT_DATASET.name == "ru_quality_dev_v2.jsonl"


def test_langsmith_configuration_is_explicit_and_reads_local_key(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.local"
    env_file.write_text("LANGSMITH_API_KEY=test-secret\n", encoding="utf-8")

    assert read_ru_evaluation_langsmith_configuration(
        project_name="ru-quality",
        experiment_id="smoke-1",
        environment={},
        env_file=env_file,
    ) == ("test-secret", "ru-quality", "smoke-1")

    with pytest.raises(ValueError, match="automatic LangSmith tracing"):
        read_ru_evaluation_langsmith_configuration(
            project_name="ru-quality",
            experiment_id="smoke-1",
            environment={"LANGSMITH_TRACING": "true"},
            env_file=env_file,
        )


def test_evaluation_trace_has_root_and_llm_child_without_business_payload() -> None:
    client = _LangSmithClient()
    trace = RuEvaluationLangSmithTrace(
        api_key="test-key",
        project_name="ru-quality",
        experiment_id="smoke-1",
        case_id="RU-B-002",
        code_sha="a" * 40,
        model_id="qwen3.5:9b",
        model_digest="b" * 64,
        runtime_mode="LOCAL_GPU",
        product_run_id="run-123",
        client=client,
    )
    root_run_id = uuid4()
    trace.on_chain_start(
        None,
        {"user_request": "raw-user-secret"},
        run_id=root_run_id,
        metadata={"product_run_id": "run-123"},
    )
    handle = trace.begin_external_call(
        ExternalCallTraceStartV1(
            schema_version=1,
            domain_run_id="run-123",
            call_kind="LLM_INFERENCE",
            operation="INFER_STRUCTURED",
            provider="ollama",
            model_id="qwen3.5:9b",
            prompt_id="request_understanding.identify_goal",
            prompt_version="1.0.0",
            prompt_content_hash="c" * 64,
            output_schema_id="request-goal-candidate-v1",
            safe_semantic_input={"request": "raw-user-secret"},
        )
    )
    assert handle is not None
    trace.finish_external_call(
        handle,
        ExternalCallTraceFinishV1(
            schema_version=1,
            status="COMPLETED",
            duration_ms=12,
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
            safe_semantic_output={"completion": "raw-provider-secret"},
        ),
    )
    trace.on_chain_end(
        {"request_intent": {"goal": "raw-provider-secret"}},
        run_id=root_run_id,
    )

    assert [run["run_type"] for run in client.created] == ["chain", "llm"]
    assert all(run["inputs"] == {} for run in client.created)
    root_metadata = client.created[0]["extra"]["metadata"]
    child_metadata = client.created[1]["extra"]["metadata"]
    assert root_metadata == {
        "experiment_id": "smoke-1",
        "case_id": "RU-B-002",
        "code_sha": "a" * 40,
        "model_id": "qwen3.5:9b",
        "model_digest": "b" * 64,
        "runtime_mode": "LOCAL_GPU",
        "domain_run_id": "run-123",
    }
    assert child_metadata["prompt_id"] == "request_understanding.identify_goal"
    assert client.created[1]["parent_run_id"] == root_run_id
    serialized = json.dumps(
        {"created": client.created, "updated": client.updated},
        default=str,
    )
    assert "raw-user-secret" not in serialized
    assert "raw-provider-secret" not in serialized


def test_loader_requires_explicit_selection_and_preserves_requested_order(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path / "cases.jsonl")

    selected = load_ru_cases(dataset, case_ids=("RU-A-002", "RU-A-001"))

    assert [row["case_id"] for row in selected] == ["RU-A-002", "RU-A-001"]
    with pytest.raises(ValueError, match="either"):
        load_ru_cases(dataset)
    with pytest.raises(ValueError, match="unknown case IDs"):
        load_ru_cases(dataset, case_ids=("RU-Z-999",))


def test_loader_only_runs_all_cases_after_explicit_all(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path / "cases.jsonl")

    selected = load_ru_cases(dataset, run_all=True)

    assert [row["case_id"] for row in selected] == ["RU-A-001", "RU-A-002"]


def test_semantic_validator_failure_has_dedicated_category() -> None:
    error = RequestGoalSemanticValidationError(
        "bad source binding",
        reason_code="REQUEST_STATUS_PROVENANCE_MISMATCH",
        affected_field_paths=("constraints.status",),
    )

    projection = classify_execution_exception(error)

    assert projection["category"] == "RU_SEMANTIC_CONTRACT"
    assert projection["reason_code"] == "REQUEST_STATUS_PROVENANCE_MISMATCH"


def test_provider_timeout_is_separate_from_runtime_failure() -> None:
    error = LLMInvocationError(LLMErrorCode.PROVIDER_TIMEOUT, "timed out")

    projection = classify_execution_exception(error)

    assert projection["category"] == "TIMEOUT"
    assert projection["reason_code"] == "PROVIDER_TIMEOUT"


def test_source_status_semantic_value_error_is_not_runtime_failure() -> None:
    projection = classify_execution_exception(
        ValueError("source status provenance source is unavailable")
    )

    assert projection["category"] == "RU_SEMANTIC_CONTRACT"
    assert projection["reason_code"] == "EVAL_SOURCE_STATUS_PROVENANCE_UNAVAILABLE"
    assert projection["affected_field_paths"] == ["$.source_statuses.statuses[].source"]


def test_empty_constraint_semantic_value_error_is_not_runtime_failure() -> None:
    projection = classify_execution_exception(
        ValueError(
            "request goal candidate is invalid: "
            "$.constraints.additional_constraints[0].value[0] has no semantic text"
        )
    )

    assert projection["category"] == "RU_SEMANTIC_CONTRACT"
    assert projection["reason_code"] == "EVAL_RU_SEMANTIC_TEXT_INVALID"
    assert projection["affected_field_paths"] == [
        "$.constraints.additional_constraints[0].value[0]"
    ]


def test_unrecognized_value_error_remains_runtime_failure() -> None:
    projection = classify_execution_exception(ValueError("unrelated runtime failure"))

    assert projection["category"] == "RUNTIME_FAILURE"
    assert projection["reason_code"] == "ValueError"
