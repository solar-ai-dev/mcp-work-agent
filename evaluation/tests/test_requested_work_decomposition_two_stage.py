from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from scripts.evaluate_ru_requested_work_decomposition_two_stage import (
    EXACT_SPAN_REF_IDENTIFY_PROMPT,
    EXACT_SPAN_REF_RELATION_PROMPT,
    IDENTIFIED_RESULTS_SCHEMA,
    IDENTIFY_PROMPT,
    MATERIALIZE_PROMPT,
    REQUEST_REF_IDENTIFY_PROMPT,
    REQUEST_REF_RELATION_PROMPT,
    REQUESTED_EFFECTS,
    SEMANTIC_CARRY_DECOMPOSITION_SCHEMA,
    SEMANTIC_CARRY_IDENTIFIED_RESULTS_SCHEMA,
    SEMANTIC_CARRY_IDENTIFY_PROMPT,
    SEMANTIC_CARRY_RELATION_PROMPT,
    SEMANTIC_CARRY_RELATIONS_SCHEMA,
    SEMANTIC_STATE_DECOMPOSITION_SCHEMA,
    SEMANTIC_STATE_IDENTIFIED_RESULTS_SCHEMA,
    SEMANTIC_STATE_IDENTIFY_PROMPT,
    SEMANTIC_STATE_MATERIALIZE_PROMPT,
    SPAN_BOUND_IDENTIFIED_RESULTS_SCHEMA,
    SPAN_BOUND_IDENTIFY_PROMPT,
    SPAN_BOUND_RELATION_PROMPT,
    _closed_typed_relations_schema,
    _exact_span_ref_identified_results_schema,
    _has_exact_carry,
    _project_exact_span_ref_results,
    _project_identified_results,
    _project_request_ref_candidate,
    _project_span_bound_results,
    _request_ref_identified_results_schema,
    _request_token_catalog,
    _validate_identified_results,
    _validate_request_refs,
    _validate_request_span_bindings,
)

from google_work_agent.ports.llm.output_schema_validation import validate_output_schema


def test_stage_one_schema_contains_only_independent_results() -> None:
    properties = cast(dict[str, object], IDENTIFIED_RESULTS_SCHEMA.json_schema["properties"])
    encoded = json.dumps(IDENTIFIED_RESULTS_SCHEMA.json_schema, sort_keys=True)
    assert set(properties) == {"identified_results"}
    for forbidden in ("relation", "tool", "query", "evidence", "approval", "execution"):
        assert forbidden not in encoded.lower()


def test_two_stage_prompts_do_not_add_few_shots() -> None:
    for prompt in (
        IDENTIFY_PROMPT,
        MATERIALIZE_PROMPT,
        SEMANTIC_CARRY_IDENTIFY_PROMPT,
        SEMANTIC_CARRY_RELATION_PROMPT,
        SEMANTIC_STATE_IDENTIFY_PROMPT,
        SEMANTIC_STATE_MATERIALIZE_PROMPT,
        SPAN_BOUND_IDENTIFY_PROMPT,
        SPAN_BOUND_RELATION_PROMPT,
        REQUEST_REF_IDENTIFY_PROMPT,
        REQUEST_REF_RELATION_PROMPT,
        EXACT_SPAN_REF_IDENTIFY_PROMPT,
        EXACT_SPAN_REF_RELATION_PROMPT,
    ):
        assert "few-shot" not in prompt.read_text(encoding="utf-8").lower()


def test_semantic_state_fields_are_optional_and_owner_local() -> None:
    result_item = SEMANTIC_STATE_IDENTIFIED_RESULTS_SCHEMA.json_schema["properties"][
        "identified_results"
    ]["items"]
    unit_item = SEMANTIC_STATE_DECOMPOSITION_SCHEMA.json_schema["properties"]["work_units"]["items"]
    expected_fields = {
        "source_scopes",
        "targets",
        "temporal_constraints",
        "quantity_constraints",
        "prohibitions",
        "requested_effects",
    }

    assert set(result_item["required"]) == {"result_id", "objective"}
    assert set(unit_item["required"]) == {"unit_id", "objective"}
    assert expected_fields == set(result_item["properties"]) - {"result_id", "objective"}
    assert expected_fields == set(unit_item["properties"]) - {"unit_id", "objective"}
    assert result_item["properties"]["requested_effects"]["items"]["enum"] == (REQUESTED_EFFECTS)
    encoded = json.dumps(result_item, sort_keys=True)
    for forbidden_bucket in ("metadata", "hints", "extra_context", "semantic_flags"):
        assert forbidden_bucket not in encoded


def test_stage_one_validator_rejects_duplicate_result_ids() -> None:
    errors = _validate_identified_results(
        {
            "identified_results": [
                {"result_id": "same", "objective": "첫 결과"},
                {"result_id": "same", "objective": "둘째 결과"},
            ]
        }
    )
    assert errors == ["identified result ids must be unique"]


def test_semantic_carry_state_is_optional_and_effect_free() -> None:
    result_item = SEMANTIC_CARRY_IDENTIFIED_RESULTS_SCHEMA.json_schema["properties"][
        "identified_results"
    ]["items"]
    unit_item = SEMANTIC_CARRY_DECOMPOSITION_SCHEMA.json_schema["properties"]["work_units"]["items"]
    expected_fields = {
        "source_scopes",
        "targets",
        "temporal_constraints",
        "quantity_constraints",
        "prohibitions",
    }

    assert set(result_item["required"]) == {"result_id", "objective"}
    assert set(unit_item["required"]) == {"unit_id", "objective"}
    assert expected_fields == set(result_item["properties"]) - {"result_id", "objective"}
    assert expected_fields == set(unit_item["properties"]) - {"unit_id", "objective"}
    assert "requested_effects" not in json.dumps(
        SEMANTIC_CARRY_IDENTIFIED_RESULTS_SCHEMA.json_schema
    )
    assert "requested_effects" not in json.dumps(SEMANTIC_CARRY_DECOMPOSITION_SCHEMA.json_schema)


def test_semantic_carry_stage_two_only_generates_relations() -> None:
    properties = SEMANTIC_CARRY_RELATIONS_SCHEMA.json_schema["properties"]

    assert set(properties) == {"work_relations"}
    assert SEMANTIC_CARRY_RELATIONS_SCHEMA.json_schema["required"] == ["work_relations"]


def test_span_bound_state_uses_exact_request_spans_without_effect_authority() -> None:
    result_item = SPAN_BOUND_IDENTIFIED_RESULTS_SCHEMA.json_schema["properties"][
        "identified_results"
    ]["items"]

    assert set(result_item["required"]) == {"result_id", "request_spans"}
    assert "objective" not in result_item["properties"]
    assert "requested_effects" not in json.dumps(SPAN_BOUND_IDENTIFIED_RESULTS_SCHEMA.json_schema)


def test_span_validator_requires_verbatim_user_request_substrings() -> None:
    request = "메일을 확인해서 요약하고 그 요약으로 이슈 초안을 만들어줘."

    assert not _validate_request_span_bindings(
        {
            "identified_results": [
                {"result_id": "summary", "request_spans": ["메일을 확인해서 요약하고"]},
                {
                    "result_id": "issue",
                    "request_spans": ["그 요약으로 이슈 초안을 만들어줘"],
                },
            ]
        },
        request,
    )
    assert _validate_request_span_bindings(
        {
            "identified_results": [
                {"result_id": "summary", "request_spans": ["메일을 읽고 요약한다"]}
            ]
        },
        request,
    ) == ["$.identified_results[0].request_spans[0] must be an exact user-request substring"]


def test_span_bound_projection_derives_objective_from_exact_spans() -> None:
    identified = [
        {
            "result_id": "issue",
            "request_spans": ["그 요약으로", "이슈 초안을 만들어줘"],
            "source_scopes": ["그 요약"],
        }
    ]

    assert _project_span_bound_results(identified) == [
        {
            "unit_id": "issue",
            "objective": "그 요약으로 이슈 초안을 만들어줘",
            "request_spans": ["그 요약으로", "이슈 초안을 만들어줘"],
            "source_scopes": ["그 요약"],
        }
    ]


def test_closed_typed_relation_schema_rejects_unknown_self_and_legacy_edges() -> None:
    schema = _closed_typed_relations_schema(["summary", "issue"]).json_schema
    valid = {
        "work_relations": [
            {
                "source_unit_id": "summary",
                "target_unit_id": "issue",
                "kind": "CONSUMES_WORK_PRODUCT",
            }
        ]
    }

    assert not validate_output_schema(valid, schema)
    planned = {
        "work_relations": [
            {
                "source_unit_id": "summary",
                "target_unit_id": "issue",
                "kind": "CONSUMES_PLANNED_SPECIFICATION",
            }
        ]
    }
    assert not validate_output_schema(planned, schema)
    for invalid in (
        {
            "work_relations": [
                {
                    "source_unit_id": "summary",
                    "target_unit_id": "summary",
                    "kind": "CONSUMES_WORK_PRODUCT",
                }
            ]
        },
        {
            "work_relations": [
                {
                    "source_unit_id": "summary",
                    "target_unit_id": "recipient@example.com",
                    "kind": "CONSUMES_WORK_PRODUCT",
                }
            ]
        },
        {
            "work_relations": [
                {
                    "source_unit_id": "summary",
                    "target_unit_id": "issue",
                    "kind": "PROVIDES_INPUT_TO",
                }
            ]
        },
    ):
        assert validate_output_schema(invalid, schema)


def test_closed_relation_schema_only_allows_empty_for_one_work_unit() -> None:
    schema = _closed_typed_relations_schema(["only"]).json_schema

    assert not validate_output_schema({"work_relations": []}, schema)
    assert validate_output_schema(
        {
            "work_relations": [
                {
                    "source_unit_id": "only",
                    "target_unit_id": "only",
                    "kind": "CONSUMES_WORK_PRODUCT",
                }
            ]
        },
        schema,
    )


def test_request_token_catalog_preserves_exact_original_text_offsets() -> None:
    request = "8월 14일 오전 10시에 일정을 만들어줘."

    tokens = _request_token_catalog(request)

    assert [token["text"] for token in tokens] == [
        "8월",
        "14일",
        "오전",
        "10시에",
        "일정을",
        "만들어줘.",
    ]
    for token in tokens:
        assert request[cast(int, token["start"]) : cast(int, token["end"])] == token["text"]


def test_request_ref_schema_is_closed_to_catalog_and_has_shared_state() -> None:
    schema = _request_ref_identified_results_schema(["T001", "T002"]).json_schema
    valid = {
        "shared_semantics": {
            "source_scope_refs": [{"start_token_id": "T001", "end_token_id": "T001"}]
        },
        "identified_results": [
            {
                "result_id": "result-1",
                "request_span_refs": [{"start_token_id": "T001", "end_token_id": "T002"}],
            }
        ],
    }

    assert not validate_output_schema(valid, schema)
    assert "objective" not in json.dumps(schema)
    assert "requested_effects" not in json.dumps(schema)
    invalid = json.loads(json.dumps(valid))
    invalid["identified_results"][0]["request_span_refs"][0]["end_token_id"] = "T999"
    assert validate_output_schema(invalid, schema)


def test_exact_span_ref_schema_changes_only_request_span_representation() -> None:
    schema = _exact_span_ref_identified_results_schema(["T001", "T002"]).json_schema
    item = schema["properties"]["identified_results"]["items"]
    span_bound_item = SPAN_BOUND_IDENTIFIED_RESULTS_SCHEMA.json_schema["properties"][
        "identified_results"
    ]["items"]

    assert set(schema["properties"]) == {"identified_results"}
    assert set(item["required"]) == {"result_id", "request_span_refs"}
    assert "shared_semantics" not in schema["properties"]
    assert "request_spans" not in item["properties"]
    assert set(item["properties"]) - {"request_span_refs"} == set(span_bound_item["properties"]) - {
        "request_spans"
    }
    assert "requested_effects" not in item["properties"]


def test_exact_span_ref_projection_preserves_v3_semantic_fields() -> None:
    request = "선택한 메일을 확인하고 다른 메일은 검색하지 마."
    tokens = _request_token_catalog(request)
    identified = [
        {
            "result_id": "result-1",
            "request_span_refs": [{"start_token_id": "T001", "end_token_id": "T003"}],
            "source_scopes": ["선택한 메일"],
            "prohibitions": ["다른 메일은 검색하지 마"],
        }
    ]

    assert _project_exact_span_ref_results(
        identified,
        request=request,
        request_tokens=tokens,
    ) == [
        {
            "unit_id": "result-1",
            "objective": "선택한 메일을 확인하고",
            "request_spans": ["선택한 메일을 확인하고"],
            "source_scopes": ["선택한 메일"],
            "prohibitions": ["다른 메일은 검색하지 마"],
        }
    ]


def test_request_ref_validator_rejects_reversed_ranges() -> None:
    tokens = _request_token_catalog("첫 업무와 둘째 업무")
    candidate = {
        "shared_semantics": {},
        "identified_results": [
            {
                "result_id": "result-1",
                "request_span_refs": [{"start_token_id": "T003", "end_token_id": "T001"}],
            }
        ],
    }

    assert _validate_request_refs(candidate, tokens) == [
        "$.identified_results[0].request_span_refs[0] start token must not follow end token"
    ]


def test_request_ref_projection_resolves_shared_and_local_meaning_once() -> None:
    request = "메일·작업·캘린더를 보고 Task를 만들고, Event와 Draft를 준비해줘."
    tokens = _request_token_catalog(request)
    identified = [
        {
            "result_id": "task",
            "request_span_refs": [{"start_token_id": "T003", "end_token_id": "T004"}],
        },
        {
            "result_id": "event-draft",
            "request_span_refs": [{"start_token_id": "T005", "end_token_id": "T007"}],
        },
    ]
    shared = {"source_scope_refs": [{"start_token_id": "T001", "end_token_id": "T001"}]}

    projected = _project_request_ref_candidate(
        shared_semantics=shared,
        identified_results=identified,
        request=request,
        request_tokens=tokens,
        work_relations=[],
    )

    assert projected == {
        "shared_semantics": {"source_scopes": ["메일·작업·캘린더를"]},
        "work_units": [
            {
                "unit_id": "task",
                "objective": "Task를 만들고,",
                "request_spans": ["Task를 만들고,"],
            },
            {
                "unit_id": "event-draft",
                "objective": "Event와 Draft를 준비해줘.",
                "request_spans": ["Event와 Draft를 준비해줘."],
            },
        ],
        "work_relations": [],
    }
    assert all("source_scopes" not in unit for unit in projected["work_units"])


def test_exact_carry_requires_ids_and_objectives_to_be_unchanged() -> None:
    identified = [
        {"result_id": "result-1", "objective": "첫 결과"},
        {"result_id": "result-2", "objective": "둘째 결과"},
    ]
    assert _has_exact_carry(
        identified,
        [
            {"unit_id": "result-1", "objective": "첫 결과"},
            {"unit_id": "result-2", "objective": "둘째 결과"},
        ],
    )
    assert not _has_exact_carry(
        identified,
        [{"unit_id": "result-1", "objective": "다르게 쓴 결과"}],
    )


def test_exact_carry_includes_optional_semantic_fields() -> None:
    identified = [
        {
            "result_id": "result-1",
            "objective": "초안을 준비한다",
            "source_scopes": ["Atlas 메일", "Atlas 작업"],
            "targets": ["qhdrbdhkdwks@naver.com"],
            "prohibitions": ["보내지 않는다"],
            "requested_effects": ["DRAFT"],
        }
    ]
    carried = [
        {
            "unit_id": "result-1",
            "objective": "초안을 준비한다",
            "source_scopes": ["Atlas 메일", "Atlas 작업"],
            "targets": ["qhdrbdhkdwks@naver.com"],
            "prohibitions": ["보내지 않는다"],
            "requested_effects": ["DRAFT"],
        }
    ]

    assert _has_exact_carry(identified, carried)
    carried[0]["prohibitions"] = []
    assert not _has_exact_carry(identified, carried)


def test_semantic_carry_projects_stage_one_without_llm_rewriting() -> None:
    identified = [
        {
            "result_id": "result-1",
            "objective": "선택한 자료를 요약한다",
            "source_scopes": ["선택한 메일"],
            "targets": ["사용자"],
            "temporal_constraints": ["오늘"],
            "quantity_constraints": ["하나"],
            "prohibitions": ["다른 메일을 검색하지 않는다"],
        }
    ]

    projected = _project_identified_results(identified)

    assert projected == [
        {
            "unit_id": "result-1",
            "objective": "선택한 자료를 요약한다",
            "source_scopes": ["선택한 메일"],
            "targets": ["사용자"],
            "temporal_constraints": ["오늘"],
            "quantity_constraints": ["하나"],
            "prohibitions": ["다른 메일을 검색하지 않는다"],
        }
    ]
    assert _has_exact_carry(identified, projected)
    assert "requested_effects" not in projected[0]


def test_prompt_paths_are_evaluation_candidates() -> None:
    expected_parent = Path(
        "evaluation/prompt_candidates/ru-requested-work-decomposition-two-stage-v1/sources"
    )
    assert IDENTIFY_PROMPT.parent == expected_parent
    assert MATERIALIZE_PROMPT.parent == expected_parent
    semantic_parent = Path(
        "evaluation/prompt_candidates/"
        "ru-requested-work-decomposition-two-stage-semantic-state-v1/sources"
    )
    assert SEMANTIC_STATE_IDENTIFY_PROMPT.parent == semantic_parent
    assert SEMANTIC_STATE_MATERIALIZE_PROMPT.parent == semantic_parent
    carry_parent = Path(
        "evaluation/prompt_candidates/"
        "ru-requested-work-decomposition-two-stage-semantic-carry-v2/sources"
    )
    assert SEMANTIC_CARRY_IDENTIFY_PROMPT.parent == carry_parent
    assert SEMANTIC_CARRY_RELATION_PROMPT.parent == carry_parent
    span_parent = Path(
        "evaluation/prompt_candidates/"
        "ru-requested-work-decomposition-two-stage-span-bound-v3/sources"
    )
    assert SPAN_BOUND_IDENTIFY_PROMPT.parent == span_parent
    assert SPAN_BOUND_RELATION_PROMPT.parent == span_parent
    request_ref_parent = Path(
        "evaluation/prompt_candidates/"
        "ru-requested-work-decomposition-two-stage-request-ref-v4/sources"
    )
    assert REQUEST_REF_IDENTIFY_PROMPT.parent == request_ref_parent
    assert REQUEST_REF_RELATION_PROMPT.parent == request_ref_parent
    exact_span_ref_parent = Path(
        "evaluation/prompt_candidates/"
        "ru-requested-work-decomposition-two-stage-exact-span-ref-v5/sources"
    )
    assert EXACT_SPAN_REF_IDENTIFY_PROMPT.parent == exact_span_ref_parent
    assert EXACT_SPAN_REF_RELATION_PROMPT.parent == exact_span_ref_parent
