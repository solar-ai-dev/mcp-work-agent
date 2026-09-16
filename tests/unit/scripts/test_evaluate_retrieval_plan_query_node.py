from scripts import evaluate_retrieval_plan_query_node as evaluator


def _record(
    outcome: str,
    *,
    provider_calls: int = 0,
    first_call: str | None = None,
    semantic_revisions: int = 0,
    failure_family: str | None = None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "outcome": outcome,
        "provider_call_count": provider_calls,
        "semantic_revision_count": semantic_revisions,
        "input_tokens": 0,
        "output_tokens": 0,
        "provider_latency_ms": 0,
    }
    if first_call is not None:
        result["first_call_classification"] = first_call
    if failure_family is not None:
        result["failure_family"] = failure_family
    return result


def test_node_summary__llm_path_and_dispatch__uses_distinct_denominators() -> None:
    records = [
        *[_record("SKIP_NO_NODE_INPUT") for _ in range(17)],
        *[_record("DETERMINISTIC_VALID") for _ in range(9)],
        *[
            _record(
                "FIRST_CALL_VALID",
                provider_calls=1,
                first_call="SEMANTIC_VALID",
            )
            for _ in range(13)
        ],
        *[
            _record(
                "SEMANTIC_REVISION_RECOVERED",
                provider_calls=2,
                first_call="SCHEMA_VALID_SEMANTIC_INVALID",
                semantic_revisions=1,
            )
            for _ in range(2)
        ],
        *[
            _record(
                "FAILED",
                provider_calls=2,
                first_call="SCHEMA_VALID_SEMANTIC_INVALID",
                semantic_revisions=1,
                failure_family="EXPLICIT_ANCHOR_LOSS",
            )
            for _ in range(18)
        ],
        _record(
            "FAILED",
            first_call="PRE_DISPATCH_FAILED",
            failure_family="ROUTE_MISMATCH",
        ),
    ]

    summary = evaluator._summarize_records(
        records=records,
        split="CORE",
        duration_ms=100,
    )

    assert summary["case_count"] == 60
    assert summary["eligible_case_count"] == 43
    assert summary["deterministic_success_count"] == 9
    assert summary["llm_path_case_count"] == 34
    assert summary["llm_dispatched_case_count"] == 33
    assert summary["first_call_valid_count"] == 13
    assert summary["first_call_valid_rate"] == 13 / 34
    assert summary["first_call_dispatched_valid_rate"] == 13 / 33
    assert sum(summary["first_call_classification_counts"].values()) == 34
    assert summary["semantic_revision_attempted_count"] == 20
    assert summary["semantic_revision_still_failed_count"] == 18


def test_failure_family__duplicate_routes__classifies_over_selection() -> None:
    record = {
        "reason_code": "RETRIEVAL_QUERY_PLAN_SEMANTIC_INVALID",
        "affected_field_paths": [],
        "input_route_ids": ["gmail"],
        "candidate_outputs": [
            {
                "route_queries": [
                    {"route_id": "gmail"},
                    {"route_id": "gmail"},
                ]
            }
        ],
    }

    assert evaluator._failure_family(record) == "OVER_SELECTION"
