from __future__ import annotations

from copy import deepcopy

from evaluation.requested_work_binding_contract import (
    inline_round_trip_semantics,
    local_id_round_trip_semantics,
    normalized_decomposition,
    project_inline_work_unit_ids,
    project_local_id_bindings,
    representation_metrics,
    validate_inline_work_unit_ids,
    validate_local_id_bindings,
)

REQUEST = "메일을 요약하고 그 요약으로 이슈 초안을 만들어줘. 둘 다 외부로 보내지 마."
DECOMPOSITION = {
    "work_units": [
        {
            "unit_id": "summary",
            "objective": "메일을 요약하고",
            "request_spans": ["메일을 요약하고"],
            "source_scopes": ["메일"],
            "prohibitions": ["외부로 보내지 마"],
        },
        {
            "unit_id": "issue",
            "objective": "그 요약으로 이슈 초안을 만들어줘",
            "request_spans": ["그 요약으로 이슈 초안을 만들어줘"],
            "source_scopes": ["메일"],
            "prohibitions": ["외부로 보내지 마"],
        },
    ],
    "work_relations": [
        {
            "source_unit_id": "summary",
            "target_unit_id": "issue",
            "kind": "CONSUMES_WORK_PRODUCT",
        }
    ],
}


def test_inline_projection_keeps_semantics_with_owner_items() -> None:
    candidate = project_inline_work_unit_ids(DECOMPOSITION)

    assert validate_inline_work_unit_ids(candidate, user_request=REQUEST) == []
    assert candidate["requested_work"]["work_units"] == [
        {
            "unit_id": "summary",
            "objective": "메일을 요약하고",
            "request_spans": ["메일을 요약하고"],
        },
        {
            "unit_id": "issue",
            "objective": "그 요약으로 이슈 초안을 만들어줘",
            "request_spans": ["그 요약으로 이슈 초안을 만들어줘"],
        },
    ]
    assert candidate["semantic_items"]["source_scopes"] == [
        {"value": "메일", "work_unit_ids": ["summary", "issue"]}
    ]
    assert candidate["semantic_items"]["prohibitions"] == [
        {"value": "외부로 보내지 마", "work_unit_ids": ["summary", "issue"]}
    ]
    assert inline_round_trip_semantics(candidate) == normalized_decomposition(DECOMPOSITION)


def test_local_id_binding_round_trip_requires_an_extra_reference_layer() -> None:
    candidate = project_local_id_bindings(DECOMPOSITION)

    assert validate_local_id_bindings(candidate, user_request=REQUEST) == []
    assert local_id_round_trip_semantics(candidate) == normalized_decomposition(DECOMPOSITION)
    metrics = representation_metrics(candidate)
    assert metrics["semantic_item_count"] == 2
    assert metrics["semantic_local_id_count"] == 2
    assert metrics["binding_record_count"] == 2
    assert metrics["work_unit_reference_count"] == 4


def test_inline_validator_rejects_unknown_work_unit_reference() -> None:
    candidate = project_inline_work_unit_ids(DECOMPOSITION)
    candidate["semantic_items"]["source_scopes"][0]["work_unit_ids"] = ["missing"]

    assert validate_inline_work_unit_ids(candidate, user_request=REQUEST) == [
        "source_scopes[0].work_unit_ids contains unknown ids: ['missing']"
    ]


def test_local_id_validator_rejects_orphan_and_unbound_items() -> None:
    candidate = project_local_id_bindings(DECOMPOSITION)
    broken = deepcopy(candidate)
    broken["semantic_bindings"][0]["semantic_local_id"] = "missing"

    errors = validate_local_id_bindings(broken, user_request=REQUEST)

    assert "semantic_bindings[0] has unresolved local id" in errors
    assert any(error.endswith("is unbound") for error in errors)


def test_relation_is_validated_after_work_unit_endpoints_exist() -> None:
    candidate = project_inline_work_unit_ids(DECOMPOSITION)
    candidate["requested_work"]["work_relations"][0]["target_unit_id"] = "unknown"

    assert validate_inline_work_unit_ids(candidate, user_request=REQUEST)[0] == (
        "work_relations[0] has invalid endpoint"
    )
