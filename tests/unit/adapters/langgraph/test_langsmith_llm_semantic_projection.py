from __future__ import annotations

from collections.abc import Mapping
from typing import cast

import pytest

from google_work_agent.adapters.langgraph.langsmith_llm_semantic_projection import (
    project_llm_semantic_input,
    project_llm_semantic_output,
    sanitize_llm_semantic_projection,
)


def test_detect_ambiguity_input__keeps_typed_counts__without_business_content() -> None:
    projection = project_llm_semantic_input(
        "request_understanding.detect_ambiguity",
        {
            "user_request": "그 일정 언제야?",
            "selected_resource_refs": [],
            "goal_candidate": {
                "goal": "private goal",
                "requested_effect_hints": ["READ"],
                "requested_resource_hints": ["CALENDAR_EVENT"],
                "resource_responsibilities": {
                    "source_reads": [
                        {
                            "resource_type": "CALENDAR_EVENT",
                            "required_information": ["일정의 실제 시각"],
                        }
                    ]
                },
            },
            "resolution_responsibilities": {
                "connector_owned_information": [
                    {
                        "information": "일정의 실제 시각",
                        "resource_type": "CALENDAR_EVENT",
                    }
                ],
                "resolved_resource_refs": [],
                "searchable_target_anchor_count": 1,
                "connector_owned_source_count": 1,
            },
            "confirmation_response": None,
        },
    )

    assert projection == {
        "projection_version": 1,
        "selected_resource_count": 0,
        "goal_candidate": {
            "requested_effect_hints": ["READ"],
            "requested_resource_hints": ["CALENDAR_EVENT"],
            "source_reads": {
                "count": 1,
                "items": [
                    {
                        "resource_type": "CALENDAR_EVENT",
                        "required_information_count": 1,
                    }
                ],
            },
        },
        "resolution_responsibilities": {
            "connector_owned_information_count": 1,
            "connector_owned_resource_types": ["CALENDAR_EVENT"],
            "resolved_resource_count": 0,
            "searchable_target_anchor_count": 1,
            "connector_owned_source_count": 1,
        },
        "has_confirmation_response": False,
    }
    exported = repr(projection)
    assert "그 일정 언제야" not in exported
    assert "일정의 실제 시각" not in exported
    assert "private goal" not in exported


@pytest.mark.parametrize(
    ("owner", "missing_fields"),
    [("NONE", []), ("CONNECTOR", ["event_time"]), ("USER", ["target_resource"])],
)
def test_detect_ambiguity_output__distinguishes_owner__with_safe_fields(
    owner: str, missing_fields: list[str]
) -> None:
    projection = project_llm_semantic_output(
        "request_understanding.detect_ambiguity",
        {"missing_information_owner": owner, "missing_fields": missing_fields},
    )

    assert projection["missing_information_owner"] == owner
    assert projection["missing_fields"] == {
        "count": len(missing_fields),
        **({"values": missing_fields} if missing_fields else {}),
    }


def test_detect_ambiguity_output__unsafe_fields__keep_count_only() -> None:
    projection = project_llm_semantic_output(
        "request_understanding.detect_ambiguity",
        {
            "missing_information_owner": "USER",
            "missing_fields": [
                "Atlas 일정 제목",
                "secret@example.com",
                "x" * 65,
            ],
        },
    )

    assert projection["missing_fields"] == {"count": 3}
    assert "Atlas" not in repr(projection)
    assert "secret@example.com" not in repr(projection)


def test_identify_goal_output__keeps_contract_shape__without_business_literals() -> None:
    projection = project_llm_semantic_output(
        "request_understanding.identify_goal",
        {
            "goal": "private natural language goal",
            "analysis_requirement": "NONE",
            "constraints": {
                "search_terms": ["private query literal"],
                "business_concepts": [],
                "person": [],
                "sender": [],
                "recipient": [],
                "subject": [],
                "period": [],
                "coverage_requirement": ["EXHAUSTIVE"],
                "additional_constraints": [],
            },
        },
    )

    assert projection["source_reads"] == {"count": 0, "items": []}
    assert projection["outputs"] == {"count": 0, "items": []}
    assert projection["constraints"] == {
        "count": 2,
        "items": [
            {"kind": "USER_REQUIREMENT", "field": "search_terms"},
            {
                "kind": "SCOPE",
                "field": "coverage_requirement",
                "coverage_requirement": ["EXHAUSTIVE"],
            },
        ],
    }
    for secret in (
        "private natural language goal",
        "private query literal",
    ):
        assert secret not in repr(projection)


def test_resource_role_output__keeps_roles__without_business_literals() -> None:
    projection = project_llm_semantic_output(
        "request_understanding.identify_resource_responsibilities",
        {
            "resource_decisions": [
                {
                    "resource_type": "TASK",
                    "role": "SOURCE",
                    "required_information": ["private task state"],
                },
                {
                    "resource_type": "CALENDAR_EVENT",
                    "role": "SOURCE",
                    "required_information": ["private event time"],
                },
                {
                    "resource_type": "GMAIL_DRAFT",
                    "role": "OUTPUT",
                    "effect": "CREATE",
                },
            ],
        },
    )

    assert projection == {
        "projection_version": 1,
        "resource_decisions": {
            "count": 3,
            "items": [
                {
                    "resource_type": "TASK",
                    "role": "SOURCE",
                    "required_information_count": 1,
                },
                {
                    "resource_type": "CALENDAR_EVENT",
                    "role": "SOURCE",
                    "required_information_count": 1,
                },
                {
                    "resource_type": "GMAIL_DRAFT",
                    "role": "OUTPUT",
                    "effect": "CREATE",
                    "required_information_count": 0,
                },
            ],
        },
    }
    assert "private task state" not in repr(projection)
    assert "private event time" not in repr(projection)


def test_source_status_projection__shows_fixed_shape__without_source_literals() -> None:
    semantic_input = project_llm_semantic_input(
        "request_understanding.identify_source_status",
        {
            "user_request": "private request",
            "selected_resource_refs": [],
            "goal_candidate": {
                "goal": "private goal",
                "constraints": {"search_terms": ["private anchor"]},
                "analysis_requirement": "NONE",
            },
            "source_reads": [
                {"resource_type": "TASK", "required_information": ["private fact"]}
            ],
            "outputs": [{"resource_type": "GMAIL_DRAFT", "effect": "CREATE"}],
            "allowed_status_values": [
                {
                    "resource_type": "TASK",
                    "values": ["ANY", "COMPLETED", "INCOMPLETE"],
                }
            ],
        },
    )
    semantic_output = project_llm_semantic_output(
        "request_understanding.identify_source_status",
        {
            "statuses": [
                {
                    "value": "COMPLETED",
                    "source_resource_type": "TASK",
                    "source": "USER_REQUEST",
                    "source_text": "private source literal",
                }
            ]
        },
    )

    assert semantic_input["source_reads"] == {
        "count": 1,
        "items": [{"resource_type": "TASK", "required_information_count": 1}],
    }
    assert semantic_input["outputs"] == {
        "count": 1,
        "items": [{"resource_type": "GMAIL_DRAFT", "effect": "CREATE"}],
    }
    assert semantic_input["allowed_status_values"] == {
        "count": 1,
        "items": [
            {
                "resource_type": "TASK",
                "values": ["ANY", "COMPLETED", "INCOMPLETE"],
            }
        ],
    }
    assert semantic_output == {
        "projection_version": 1,
        "statuses": {
            "count": 1,
            "items": [{"status_values": ["COMPLETED"], "resource_type": "TASK"}],
        },
    }
    exported = repr((semantic_input, semantic_output))
    for secret in (
        "private request",
        "private goal",
        "private anchor",
        "private fact",
        "private source literal",
    ):
        assert secret not in exported


def test_resource_responsibility_input__shows_upstream_shape__without_literals() -> None:
    projection = project_llm_semantic_input(
        "request_understanding.identify_resource_responsibilities",
        {
            "user_request": "private request",
            "selected_resource_refs": [],
            "resource_candidates": [
                {
                    "resource_type": "GMAIL_DRAFT",
                    "allowed_roles": ["NONE", "SOURCE", "OUTPUT", "SOURCE_AND_OUTPUT"],
                    "allowed_output_effects": ["CREATE", "UPDATE"],
                }
            ],
            "goal_candidate": {
                "goal": "private goal",
                "completion_conditions": ["private completion"],
                "analysis_requirement": "NONE",
                "constraints": {
                    "search_terms": ["private project"],
                    "business_concepts": [],
                    "person": [],
                    "sender": [],
                    "recipient": ["private@example.test"],
                    "subject": [],
                    "period": [],
                    "status": [],
                    "coverage_requirement": [],
                    "additional_constraints": [],
                },
            },
        },
    )

    goal_candidate = cast(dict[str, object], projection["goal_candidate"])
    assert goal_candidate["constraints"] == {
        "count": 2,
        "items": [
            {"kind": "USER_REQUIREMENT", "field": "search_terms"},
            {"kind": "PERSON", "field": "recipient"},
        ],
    }
    assert projection["resource_candidates"] == {
        "count": 1,
        "items": [
            {
                "resource_type": "GMAIL_DRAFT",
                "allowed_roles": ["NONE", "SOURCE", "OUTPUT", "SOURCE_AND_OUTPUT"],
                "allowed_output_effects": ["CREATE", "UPDATE"],
            }
        ],
    }
    exported = repr(projection)
    assert "private project" not in exported
    assert "private@example.test" not in exported
    assert "private goal" not in exported


def test_plan_query__keeps_candidate_shape__without_query_literals_or_refs() -> None:
    semantic_input = project_llm_semantic_input(
        "retrieval.plan_query",
        {
            "input_routes": [
                {
                    "route_id": "private-route",
                    "resource_type": "GMAIL_THREAD",
                    "connector_id": "google_workspace",
                    "allowed_operations": ["SEARCH", "DETAIL_FETCH"],
                    "supported_constraint_kinds": ["KEYWORD", "TEMPORAL_RANGE"],
                    "required_constraint_kinds": ["KEYWORD"],
                }
            ],
            "current_round_no": 2,
            "prior_query_attempts": [{"query": "private query"}],
            "read_result_summaries": [{"resource_ref": "private-resource"}],
            "detail_candidate_refs": ["private-detail-ref"],
        },
    )
    semantic_output = project_llm_semantic_output(
        "retrieval.plan_query",
        {
            "route_queries": [
                {
                    "route_id": "private-route",
                    "operation": "SEARCH",
                    "reason_codes": ["INITIAL_QUERY"],
                    "detail_candidate_ref": None,
                    "search_spec": {
                        "mode": "INITIAL",
                        "constraints": [
                            {
                                "kind": "KEYWORD",
                                "terms": ["private keyword"],
                                "match_mode": "PHRASE",
                            },
                            {
                                "kind": "TEMPORAL_RANGE",
                                "axis": "EVENT_TIME",
                                "start_local": "2026-09-11",
                                "end_local": None,
                                "timezone": "Asia/Seoul",
                            },
                            {
                                "kind": "PARTICIPANT",
                                "participants": [
                                    {"role": "SENDER", "identity": "secret@example.com"}
                                ],
                                "match_mode": "ANY",
                            },
                            {
                                "kind": "CONCEPT",
                                "concept": "private concept",
                                "manifestations": ["private one", "private two"],
                            },
                        ],
                    },
                }
            ]
        },
    )

    assert semantic_input["input_routes"] == {
        "count": 1,
        "items": [
            {
                "resource_type": "GMAIL_THREAD",
                "connector_id": "google_workspace",
                "allowed_operations": ["SEARCH", "DETAIL_FETCH"],
                "supported_constraint_kinds": ["KEYWORD", "TEMPORAL_RANGE"],
                "required_constraint_kinds": ["KEYWORD"],
            }
        ],
    }
    route = semantic_output["route_queries"]
    assert isinstance(route, Mapping)
    assert route["items"][0]["search_spec"]["constraint_shapes"] == {
        "count": 4,
        "items": [
            {"kind": "KEYWORD", "match_mode": "PHRASE"},
            {"kind": "TEMPORAL_RANGE", "axis": "EVENT_TIME"},
            {"kind": "PARTICIPANT", "match_mode": "ANY", "participant_roles": ["SENDER"]},
            {"kind": "CONCEPT", "manifestation_count": 2},
        ],
    }
    exported = repr((semantic_input, semantic_output))
    for secret in (
        "private-route",
        "private query",
        "private-resource",
        "private-detail-ref",
        "private keyword",
        "2026-09-11",
        "Asia/Seoul",
        "secret@example.com",
        "private concept",
        "private one",
    ):
        assert secret not in exported


def test_callback_sanitizer__drops_unknown_keys__unsafe_values_and_objects() -> None:
    projection = sanitize_llm_semantic_projection(
        {
            "projection_version": 1,
            "selected_resource_count": 0,
            "user_request": "private request",
            "route_queries": {
                "count": 1,
                "items": [
                    {
                        "operation": "SEARCH",
                        "query_literal": "private literal",
                        "reason_codes": ["VALID", "unsafe value"],
                        "body": object(),
                    }
                ],
            },
        }
    )

    assert projection == {
        "projection_version": 1,
        "selected_resource_count": 0,
        "route_queries": {
            "count": 1,
            "items": [{"operation": "SEARCH", "reason_codes": ["VALID"]}],
        },
    }


def test_tool_route_projection__connects_candidate__and_capability_shape() -> None:
    semantic_input = project_llm_semantic_input(
        "tool_routing.determine_io_resources",
        {
            "request_intent": {
                "requested_effect_hints": ["READ"],
                "requested_resource_hints": ["GMAIL_THREAD"],
                "resource_responsibilities": {
                    "source_reads": [
                        {"resource_type": "GMAIL_THREAD", "required_information": ["secret"]}
                    ],
                    "outputs": [],
                },
            },
            "eligible_route_capabilities": [
                {
                    "connector_id": "google_workspace",
                    "resource_type": "EMAIL",
                    "read_supported": True,
                    "write_effects": ["SEND"],
                }
            ],
        },
    )
    semantic_output = project_llm_semantic_output(
        "tool_routing.determine_io_resources",
        {
            "schema_version": 1,
            "input_resource_types": ["EMAIL"],
            "output_resource_types": [],
            "output_effects": [],
            "disposition": "ROUTE_READY",
        },
    )

    assert semantic_input["eligible_route_capabilities"] == {
        "count": 1,
        "items": [
            {
                "connector_id": "google_workspace",
                "resource_type": "EMAIL",
                "read_supported": True,
                "write_effects": ["SEND"],
            }
        ],
    }
    assert semantic_output == {
        "projection_version": 1,
        "input_resource_types": ["EMAIL"],
        "output_resource_types": [],
        "output_effects": [],
        "disposition": "ROUTE_READY",
    }
    assert "secret" not in repr(semantic_input)


def test_evidence_sufficiency_and_answer_projection__keeps_counts__and_decisions() -> None:
    evidence = project_llm_semantic_output(
        "retrieval.select_evidence",
        {
            "schema_version": 3,
            "segment_assessments": {
                "private-segment-1": {"role": "SUPPORTS", "relevance_reason": "secret"},
                "private-segment-2": {"role": "EXCLUDED", "relevance_reason": "secret"},
            },
        },
    )
    sufficiency = project_llm_semantic_output(
        "retrieval.assess_sufficiency",
        {
            "schema_version": 2,
            "status": "NEEDS_MORE_DATA",
            "issues": [
                {
                    "slot": "latest_message",
                    "issue_type": "MISSING",
                    "required": True,
                    "resolution_source": "GOOGLE",
                    "safety_critical": False,
                    "reason_codes": ["LATEST_MESSAGE_REQUIRED"],
                }
            ],
        },
    )
    answer = project_llm_semantic_output(
        "planning.compose_answer",
        {
            "schema_version": 2,
            "answer": "private user-visible answer",
            "evidence_refs": ["private-evidence"],
        },
    )

    assert evidence == {
        "projection_version": 1,
        "segment_assessment_count": 2,
        "role_counts": [
            {"role": "EXCLUDED", "count": 1},
            {"role": "SUPPORTS", "count": 1},
        ],
    }
    assert sufficiency == {
        "projection_version": 1,
        "status": "NEEDS_MORE_DATA",
        "issues": {
            "count": 1,
            "items": [
                {
                    "field": "latest_message",
                    "issue_type": "MISSING",
                    "required": True,
                    "resolution_source": "GOOGLE",
                    "safety_critical": False,
                    "reason_codes": ["LATEST_MESSAGE_REQUIRED"],
                }
            ],
        },
    }
    assert answer == {
        "projection_version": 1,
        "has_answer": True,
        "answer_char_count": 27,
        "evidence_ref_count": 1,
    }
    exported = repr((evidence, sufficiency, answer))
    assert "private-segment" not in exported
    assert "private user-visible answer" not in exported
    assert "private-evidence" not in exported


def test_sufficiency_input__projects_bounded_pagination_facts_without_payloads() -> None:
    projection = project_llm_semantic_input(
        "retrieval.assess_sufficiency",
        {
            "request_intent": {
                "completion_conditions": ["private condition 1", "private condition 2"],
                "requested_effect_hints": ["READ"],
                "requested_resource_hints": ["GMAIL_THREAD"],
                "resource_responsibilities": {
                    "source_reads": [
                        {
                            "resource_type": "GMAIL_THREAD",
                            "required_information": ["private information"],
                        }
                    ],
                    "outputs": [],
                },
            },
            "selected_evidence": [{"resource_ref": "private-resource"}],
            "source_statuses": [
                {
                    "resource_type": "GMAIL_THREAD",
                    "status": "SUCCESS",
                    "failure_kind": "NONE",
                }
            ],
            "budget_state": {
                "additional_rounds_used": 1,
                "additional_rounds_remaining": 2,
            },
            "temporal_constraints": [],
            "read_result_summaries": [
                {
                    "has_next_page": True,
                    "exhausted": False,
                    "result_count": 20,
                    "page_state_hash": "private-page-token-hash",
                    "read_result_handle": "private-read-result",
                },
                {
                    "has_next_page": False,
                    "exhausted": True,
                    "result_count": 3,
                    "query_literal": "private query literal",
                },
            ],
        },
    )

    assert projection["completion_condition_count"] == 2
    assert projection["read_result_summary_count"] == 2
    assert projection["has_next_page_count"] == 1
    assert projection["exhausted_count"] == 1
    assert projection["result_count_total"] == 23
    assert projection["selected_evidence_count"] == 1
    assert projection["source_statuses"] == {
        "count": 1,
        "items": [
            {
                "resource_type": "GMAIL_THREAD",
                "status": "SUCCESS",
                "failure_kind": "NONE",
            }
        ],
    }
    assert projection["budget_state"] == {
        "additional_rounds_used": 1,
        "additional_rounds_remaining": 2,
    }
    exported = repr(projection)
    for private_value in (
        "private condition",
        "private information",
        "private-resource",
        "private-page-token-hash",
        "private-read-result",
        "private query literal",
    ):
        assert private_value not in exported
