from scripts import evaluate_planning_compose_answer_node as evaluator


def _record(
    outcome: str,
    *,
    path_kind: str,
    provider_calls: int,
    inference_count: int,
    first_call: str,
) -> dict[str, object]:
    return {
        "outcome": outcome,
        "path_kind": path_kind,
        "provider_call_count": provider_calls,
        "llm_inference_count": inference_count,
        "first_call_classification": first_call,
        "input_tokens": 0,
        "output_tokens": 0,
        "provider_latency_ms": 0,
    }


def test_node_summary__deterministic_and_llm_paths__uses_distinct_denominators() -> None:
    records = [
        _record(
            "SEMANTIC_VALID",
            path_kind="DETERMINISTIC",
            provider_calls=0,
            inference_count=0,
            first_call="NOT_APPLICABLE_DETERMINISTIC",
        ),
        _record(
            "SEMANTIC_VALID",
            path_kind="LLM",
            provider_calls=1,
            inference_count=1,
            first_call="SEMANTIC_VALID",
        ),
        _record(
            "SEMANTIC_INVALID",
            path_kind="LLM",
            provider_calls=1,
            inference_count=1,
            first_call="SCHEMA_VALID_SEMANTIC_INVALID",
        ),
        _record(
            "SEMANTIC_VALID",
            path_kind="LLM",
            provider_calls=2,
            inference_count=2,
            first_call="REPAIR_RECOVERED",
        ),
        _record(
            "FAILED",
            path_kind="LLM",
            provider_calls=0,
            inference_count=0,
            first_call="PRE_DISPATCH_FAILED",
        ),
    ]

    summary = evaluator._summarize_records(
        records=records,
        split="CORE",
        duration_ms=100,
    )

    assert summary["node_input_count"] == 5
    assert summary["deterministic_path_count"] == 1
    assert summary["deterministic_semantic_valid_count"] == 1
    assert summary["llm_path_target_count"] == 4
    assert summary["llm_dispatched_count"] == 3
    assert summary["first_call_semantic_valid_count"] == 1
    assert summary["first_call_semantic_valid_rate"] == 1 / 4
    assert summary["first_call_dispatched_semantic_valid_rate"] == 1 / 3
    assert summary["first_call_schema_valid_semantic_invalid_count"] == 1
    assert summary["repair_attempted_count"] == 1
    assert summary["repair_recovered_count"] == 1
    assert summary["repair_still_failed_count"] == 0


def test_first_call_classification__deterministic_success__is_not_llm_success() -> None:
    classification = evaluator._first_call_classification(
        record={"outcome": "SEMANTIC_VALID"},
        path_kind="DETERMINISTIC",
        provider_calls=0,
        inference_count=0,
    )

    assert classification == "NOT_APPLICABLE_DETERMINISTIC"
