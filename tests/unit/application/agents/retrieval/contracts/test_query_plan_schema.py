"""Owner-local Retrieval query-plan schema scenarios."""

from collections.abc import Mapping
from copy import deepcopy
from typing import Any, cast

import pytest

from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    TemporalRangeConstraintV1,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan_schema import (
    RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
    bind_retrieval_query_plan_output_schema,
    normalize_retrieval_query_plan_candidate,
)
from google_work_agent.ports.llm.output_schema_validation import (
    validate_output_schema as _validate_output_schema,
)


def _provider_candidate(value: dict[str, Any]) -> dict[str, Any]:
    candidate = deepcopy(value)
    candidate["schema_version"] = 3
    for route_query in candidate.get("route_queries", []):
        search_spec = route_query.get("search_spec")
        if not isinstance(search_spec, dict):
            continue
        if search_spec.get("mode") == "INITIAL":
            constraints = search_spec.get("constraints")
            if isinstance(constraints, list):
                search_spec["constraints"] = {
                    (
                        item["kind"].lower()
                        if isinstance(item, dict) and isinstance(item.get("kind"), str)
                        else f"invalid_{index}"
                    ): item
                    for index, item in enumerate(constraints)
                }
            continue
        delta = search_spec.get("constraint_delta")
        if isinstance(delta, dict) and isinstance(delta.get("upsert_constraints"), list):
            delta["upsert_constraints"] = {
                (
                    item["kind"].lower()
                    if isinstance(item, dict) and isinstance(item.get("kind"), str)
                    else f"invalid_{index}"
                ): item
                for index, item in enumerate(delta["upsert_constraints"])
            }
    return candidate


def validate_output_schema(value: object, schema: Mapping[str, object]) -> list[str]:
    version = schema.get("properties", {})
    version_schema = version.get("schema_version", {}) if isinstance(version, dict) else {}
    if (
        isinstance(value, dict)
        and isinstance(version_schema, dict)
        and version_schema.get("enum") == [3]
    ):
        return _validate_output_schema(_provider_candidate(value), dict(schema))
    return _validate_output_schema(value, dict(schema))


@pytest.mark.parametrize(
    "start,end,valid",
    [
        (None, None, False),
        ("2026-09-01", None, True),
        (None, "2026-09-08", True),
        ("2026-09-01", "2026-09-08", True),
    ],
)
def test_temporal_range__partial_or_empty_bounds__preserves_contract(
    start: str | None, end: str | None, valid: bool
) -> None:
    schema = bind_retrieval_query_plan_output_schema(
        route_ids=["gmail"],
        route_operations={"gmail": ["SEARCH"]},
        supported_constraint_kinds={"gmail": ["TEMPORAL_RANGE"]},
    )
    candidate: dict[str, Any] = {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "gmail",
                "operation": "SEARCH",
                "reason_codes": ["USER_REQUEST"],
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": [
                        {
                            "kind": "TEMPORAL_RANGE",
                            "axis": "MESSAGE_TIME",
                            "start_local": start,
                            "end_local": end,
                            "timezone": "Asia/Seoul",
                        }
                    ],
                },
                "detail_candidate_ref": None,
            }
        ],
    }
    assert (not validate_output_schema(candidate, schema.json_schema)) is valid
    candidate["route_queries"][0]["search_spec"]["constraints"] = [{"start_local": start}]
    assert validate_output_schema(candidate, schema.json_schema)


def test_gmail_search_schema__empty_constraints__allows_only_gmail_route() -> None:
    gmail_schema = bind_retrieval_query_plan_output_schema(
        route_ids=["gmail"],
        route_operations={"gmail": ["SEARCH"]},
        supported_constraint_kinds={"gmail": ["CONCEPT"]},
        gmail_route_ids=["gmail"],
    )
    candidate: dict[str, Any] = {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "gmail",
                "operation": "SEARCH",
                "reason_codes": ["USER_REQUEST"],
                "search_spec": {"mode": "INITIAL", "constraints": []},
                "detail_candidate_ref": None,
            }
        ],
    }

    assert validate_output_schema(candidate, gmail_schema.json_schema) == []

    non_gmail_schema = bind_retrieval_query_plan_output_schema(
        route_ids=["calendar"],
        route_operations={"calendar": ["SEARCH"]},
        supported_constraint_kinds={"calendar": ["CONCEPT"]},
    )
    candidate["route_queries"][0]["route_id"] = "calendar"
    assert validate_output_schema(candidate, non_gmail_schema.json_schema)


def test_initial_gmail_exact_anchors__bind_keyword_values__and_recall_mode() -> None:
    schema = bind_retrieval_query_plan_output_schema(
        route_ids=["gmail"],
        route_operations={"gmail": ["SEARCH"]},
        supported_constraint_kinds={"gmail": ["KEYWORD"]},
        gmail_route_ids=["gmail"],
        initial_gmail_keyword_terms=["Atlas", "출고일"],
    )
    candidate: dict[str, Any] = {
        "schema_version": 3,
        "route_queries": [
            {
                "route_id": "gmail",
                "operation": "SEARCH",
                "reason_codes": ["USER_REQUEST"],
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": {
                        "keyword": {
                            "kind": "KEYWORD",
                            "terms": ["Atlas", "출고일"],
                            "match_mode": "ANY",
                        }
                    },
                },
                "detail_candidate_ref": None,
            }
        ],
    }

    assert validate_output_schema(candidate, schema.json_schema) == []
    candidate["route_queries"][0]["search_spec"]["constraints"]["keyword"][
        "match_mode"
    ] = "ALL"
    assert validate_output_schema(candidate, schema.json_schema)
    candidate["route_queries"][0]["search_spec"]["constraints"]["keyword"] = {
        "kind": "KEYWORD",
        "terms": ["invented"],
        "match_mode": "ANY",
    }
    assert validate_output_schema(candidate, schema.json_schema)


def test_run_relative_period__mixed_routes__binds_only_own_route() -> None:
    temporal: TemporalRangeConstraintV1 = {
        "kind": "TEMPORAL_RANGE",
        "axis": "EVENT_TIME",
        "start_local": "2026-09-01T00:00:00",
        "end_local": "2026-09-08T00:00:00",
        "timezone": "Asia/Seoul",
    }
    schema = bind_retrieval_query_plan_output_schema(
        route_ids=["gmail", "calendar"],
        route_operations={"gmail": ["SEARCH"], "calendar": ["SEARCH"]},
        supported_constraint_kinds={
            "gmail": ["TEMPORAL_RANGE", "KEYWORD"],
            "calendar": ["TEMPORAL_RANGE", "CONTAINER_REF"],
        },
        validated_container_refs={"calendar": ["primary"]},
        resolved_temporal_constraints={"gmail": temporal},
    )
    query: dict[str, Any] = {
        "route_id": "gmail",
        "operation": "SEARCH",
        "reason_codes": ["USER_REQUEST"],
        "search_spec": {"mode": "INITIAL", "constraints": [dict(temporal)]},
        "detail_candidate_ref": None,
    }
    candidate: dict[str, Any] = {
        "schema_version": 2,
        "route_queries": [query],
    }
    assert validate_output_schema(candidate, schema.json_schema) == []
    query["search_spec"]["constraints"][0]["start_local"] = "2025-09-01"
    assert validate_output_schema(candidate, schema.json_schema)
    query["route_id"] = "calendar"
    assert validate_output_schema(candidate, schema.json_schema) == []
    query["search_spec"]["constraints"] = [
        {"kind": "KEYWORD", "terms": ["일정"], "match_mode": "ANY"},
    ]
    assert validate_output_schema(candidate, schema.json_schema)


def test_bound_temporal_constraint__initial_required_route__rejects_omission() -> None:
    temporal: TemporalRangeConstraintV1 = {
        "kind": "TEMPORAL_RANGE",
        "axis": "AVAILABILITY_WINDOW",
        "start_local": "2026-09-06T00:00:00",
        "end_local": "2026-09-07T00:00:00",
        "timezone": "Asia/Seoul",
    }
    schema = bind_retrieval_query_plan_output_schema(
        route_ids=["availability"],
        route_operations={"availability": ["FREEBUSY"]},
        supported_constraint_kinds={"availability": ["TEMPORAL_RANGE", "CONTAINER_REF"]},
        required_constraint_kinds={"availability": ["CONTAINER_REF"]},
        validated_container_refs={"availability": ["primary"]},
        resolved_temporal_constraints={"availability": temporal},
        required_temporal_route_ids={"availability"},
    )
    candidate: dict[str, Any] = {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "availability",
                "operation": "FREEBUSY",
                "reason_codes": ["POLICY_CALENDAR_CONFLICT_CHECK"],
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": [{"kind": "CONTAINER_REF", "container_refs": ["primary"]}],
                },
                "detail_candidate_ref": None,
            }
        ],
    }

    assert validate_output_schema(candidate, schema.json_schema)
    candidate["route_queries"][0]["search_spec"]["constraints"].append(dict(temporal))
    assert validate_output_schema(candidate, schema.json_schema) == []
    candidate["route_queries"][0]["search_spec"]["constraints"] = [dict(temporal)]
    assert validate_output_schema(candidate, schema.json_schema)


def test_bound_temporal_constraint__without_required_route__remains_optional() -> None:
    temporal: TemporalRangeConstraintV1 = {
        "kind": "TEMPORAL_RANGE",
        "axis": "MESSAGE_TIME",
        "start_local": "2026-09-06T00:00:00",
        "end_local": "2026-09-07T00:00:00",
        "timezone": "Asia/Seoul",
    }
    schema = bind_retrieval_query_plan_output_schema(
        route_ids=["gmail"],
        route_operations={"gmail": ["SEARCH"]},
        supported_constraint_kinds={"gmail": ["TEMPORAL_RANGE", "KEYWORD"]},
        resolved_temporal_constraints={"gmail": temporal},
    )
    candidate = {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "gmail",
                "operation": "SEARCH",
                "reason_codes": ["REQUESTED_INPUT"],
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": [{"kind": "KEYWORD", "terms": ["Atlas"], "match_mode": "ANY"}],
                },
                "detail_candidate_ref": None,
            }
        ],
    }

    assert validate_output_schema(candidate, schema.json_schema) == []


@pytest.mark.parametrize("changed", [False, True])
def test_bound_concept_hypothesis__current_meaning__rejects_unbounded_or_different_concept(
    changed: bool,
) -> None:
    schema = bind_retrieval_query_plan_output_schema(
        route_ids=["gmail"],
        route_operations={"gmail": ["SEARCH"]},
        supported_constraint_kinds={"gmail": ["CONCEPT", "KEYWORD"]},
        requested_concepts={"gmail": ["업무 개념"]},
        is_followup=changed,
    )
    concept = {"kind": "CONCEPT", "concept": "업무 개념", "manifestations": ["자료"]}
    spec = (
        {
            "mode": "CHANGED",
            "constraint_delta": {
                "upsert_constraints": [concept],
                "remove_constraint_kinds": [],
            },
        }
        if changed
        else {"mode": "INITIAL", "constraints": [concept]}
    )
    candidate = {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "gmail",
                "operation": "SEARCH",
                "reason_codes": ["MISSING_EVIDENCE"],
                "search_spec": spec,
                "detail_candidate_ref": None,
            }
        ],
    }
    assert validate_output_schema(candidate, schema.json_schema) == []
    concept["manifestations"] = ["하나", "둘", "셋", "넷"]
    assert validate_output_schema(candidate, schema.json_schema)
    concept["manifestations"] = ["자료"]
    concept["concept"] = "unrelated"
    assert validate_output_schema(candidate, schema.json_schema)


@pytest.mark.parametrize(
    "identity, valid",
    [
        ("@default", False),
        ("primary", False),
        ("김대리", False),
        ("bonggyulim0728@gmail.com", True),
    ],
)
def test_bound_query_schema__container_alias_is_not__a_participant(
    identity: str,
    valid: bool,
) -> None:
    schema = bind_retrieval_query_plan_output_schema(
        route_ids=["gmail"],
        route_operations={"gmail": ["SEARCH"]},
        supported_constraint_kinds={"gmail": ["PARTICIPANT"]},
    )
    candidate = {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "gmail",
                "operation": "SEARCH",
                "reason_codes": ["USER_REQUEST"],
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": [
                        {
                            "kind": "PARTICIPANT",
                            "match_mode": "ALL",
                            "participants": [{"role": "SENDER", "identity": identity}],
                        }
                    ],
                },
                "detail_candidate_ref": None,
            }
        ],
    }
    assert (not validate_output_schema(candidate, schema.json_schema)) is valid


def test_v2_output__schema_rejects_legacy__v1_planner_shape() -> None:
    errors = validate_output_schema(
        {
            "schema_version": 1,
            "route_queries": [
                {
                    "route_id": "route-1",
                    "operation_kind": "SEARCH",
                    "reason_codes": ["MISSING"],
                    "constraint_delta": {"added_constraints": ["invoice"]},
                    "detail_candidate_ref": None,
                }
            ],
        },
        RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA.json_schema,
    )

    assert errors


def test_v2_output__schema_accepts__v2_root_shape() -> None:
    errors = validate_output_schema(
        {
            "schema_version": 2,
            "route_queries": [
                {
                    "route_id": "route-1",
                    "operation": "SEARCH",
                    "reason_codes": ["MISSING"],
                    "search_spec": {
                        "mode": "INITIAL",
                        "constraints": [
                            {"kind": "KEYWORD", "terms": ["invoice"], "match_mode": "ANY"}
                        ],
                    },
                    "detail_candidate_ref": None,
                }
            ],
        },
        RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA.json_schema,
    )

    assert errors == []


def test_v2_output_schema__empty_initial_constraints__rejects() -> None:
    candidate = {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "route-1",
                "operation": "SEARCH",
                "reason_codes": ["MISSING"],
                "search_spec": {"mode": "INITIAL", "constraints": []},
                "detail_candidate_ref": None,
            }
        ],
    }

    assert validate_output_schema(candidate, RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA.json_schema)


@pytest.mark.parametrize("kind", ["CONCEPT", "KEYWORD"])
@pytest.mark.parametrize("is_followup", [False, True])
def test_runtime_schema__duplicate_constraint_kind__cannot_be_provider_output(
    kind: str,
    is_followup: bool,
) -> None:
    schema = bind_retrieval_query_plan_output_schema(
        route_ids=["gmail"],
        route_operations={"gmail": ["SEARCH"]},
        supported_constraint_kinds={"gmail": ["CONCEPT", "KEYWORD"]},
        requested_concepts={"gmail": ["shipping"]},
        gmail_route_ids=["gmail"],
        is_followup=is_followup,
        removable_constraint_kinds={"gmail": ["CONCEPT", "KEYWORD"]},
    )
    constraint = (
        {"kind": "CONCEPT", "concept": "shipping", "manifestations": ["dispatch"]}
        if kind == "CONCEPT"
        else {"kind": "KEYWORD", "terms": ["Atlas"], "match_mode": "ANY"}
    )
    constraints = [constraint, dict(constraint)]
    search_spec = (
        {
            "mode": "CHANGED",
            "constraint_delta": {
                "upsert_constraints": constraints,
                "remove_constraint_kinds": [],
            },
        }
        if is_followup
        else {"mode": "INITIAL", "constraints": constraints}
    )
    candidate = {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "gmail",
                "operation": "SEARCH",
                "reason_codes": ["REQUESTED_INPUT"],
                "search_spec": search_spec,
                "detail_candidate_ref": None,
            }
        ],
    }

    candidate["schema_version"] = 3
    errors = _validate_output_schema(candidate, schema.json_schema)

    assert any("constraints must be an object" in error for error in errors)


def test_runtime_schema__different_constraint_kinds__remain_valid_provider_output() -> None:
    schema = bind_retrieval_query_plan_output_schema(
        route_ids=["gmail"],
        route_operations={"gmail": ["SEARCH"]},
        supported_constraint_kinds={"gmail": ["CONCEPT", "KEYWORD"]},
        requested_concepts={"gmail": ["shipping"]},
        gmail_route_ids=["gmail"],
    )
    candidate = {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "gmail",
                "operation": "SEARCH",
                "reason_codes": ["REQUESTED_INPUT"],
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": [
                        {"kind": "KEYWORD", "terms": ["Atlas"], "match_mode": "ANY"},
                        {
                            "kind": "CONCEPT",
                            "concept": "shipping",
                            "manifestations": ["dispatch"],
                        },
                    ],
                },
                "detail_candidate_ref": None,
            }
        ],
    }

    assert validate_output_schema(candidate, schema.json_schema) == []


def test_provider_constraint_slots__with_typed_values__normalize_to_ordered_list() -> None:
    candidate = {
        "schema_version": 3,
        "route_queries": [
            {
                "route_id": "gmail",
                "operation": "SEARCH",
                "reason_codes": ["REQUESTED_INPUT"],
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": {
                        "concept": {
                            "kind": "CONCEPT",
                            "concept": "shipping",
                            "manifestations": ["dispatch"],
                        },
                        "keyword": {
                            "kind": "KEYWORD",
                            "terms": ["Atlas"],
                            "match_mode": "ANY",
                        },
                        "participant": {
                            "kind": "PARTICIPANT",
                            "participants": [{"role": "SENDER", "identity": "owner@example.test"}],
                            "match_mode": "ANY",
                        },
                    },
                },
                "detail_candidate_ref": None,
            }
        ],
    }

    normalized = normalize_retrieval_query_plan_candidate(candidate)

    assert normalized == {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "gmail",
                "operation": "SEARCH",
                "reason_codes": ["REQUESTED_INPUT"],
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": [
                        {
                            "kind": "PARTICIPANT",
                            "participants": [{"role": "SENDER", "identity": "owner@example.test"}],
                            "match_mode": "ANY",
                        },
                        {"kind": "KEYWORD", "terms": ["Atlas"], "match_mode": "ANY"},
                        {
                            "kind": "CONCEPT",
                            "concept": "shipping",
                            "manifestations": ["dispatch"],
                        },
                    ],
                },
                "detail_candidate_ref": None,
            }
        ],
    }


def test_provider_constraint_slots__with_distinct_concepts__keeps_separate_hypotheses() -> None:
    schema = bind_retrieval_query_plan_output_schema(
        route_ids=["gmail"],
        route_operations={"gmail": ["SEARCH"]},
        supported_constraint_kinds={"gmail": ["CONCEPT"]},
        requested_concepts={"gmail": ["shipment", "owner"]},
        gmail_route_ids=["gmail"],
    )

    for concept in ("shipment", "owner"):
        candidate = {
            "schema_version": 3,
            "route_queries": [
                {
                    "route_id": "gmail",
                    "operation": "SEARCH",
                    "reason_codes": ["BOUNDED_HYPOTHESIS"],
                    "search_spec": {
                        "mode": "INITIAL",
                        "constraints": {
                            "concept": {
                                "kind": "CONCEPT",
                                "concept": concept,
                                "manifestations": [concept],
                            }
                        },
                    },
                    "detail_candidate_ref": None,
                }
            ],
        }
        assert _validate_output_schema(candidate, schema.json_schema) == []

    schema_root = cast(dict[str, Any], schema.json_schema)
    concept_slots = schema_root["properties"]["route_queries"]["items"]["oneOf"][0][
        "properties"
    ]["search_spec"]["properties"]["constraints"]["properties"]
    assert list(concept_slots) == ["concept"]


def test_followup_runtime_schema__changed_search__requires_non_empty_delta() -> None:
    schema = bind_retrieval_query_plan_output_schema(
        route_ids=["route-1"],
        route_operations={"route-1": ["SEARCH"]},
        supported_constraint_kinds={"route-1": ["KEYWORD"]},
        is_followup=True,
    )
    candidate: dict[str, Any] = {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "route-1",
                "operation": "SEARCH",
                "reason_codes": ["MISSING"],
                "search_spec": {
                    "mode": "CHANGED",
                    "constraint_delta": {
                        "upsert_constraints": [
                            {"kind": "KEYWORD", "terms": ["invoice"], "match_mode": "ANY"}
                        ],
                        "remove_constraint_kinds": [],
                    },
                },
                "detail_candidate_ref": None,
            }
        ],
    }

    assert validate_output_schema(candidate, schema.json_schema) == []
    candidate["route_queries"][0]["search_spec"] = {
        "mode": "INITIAL",
        "constraints": [{"kind": "KEYWORD", "terms": ["invoice"], "match_mode": "ANY"}],
    }
    assert validate_output_schema(candidate, schema.json_schema)
    candidate["route_queries"][0]["search_spec"] = {
        "mode": "CHANGED",
        "constraint_delta": {
            "upsert_constraints": [],
            "remove_constraint_kinds": [],
        },
    }
    assert validate_output_schema(candidate, schema.json_schema)


def test_followup_runtime_schema__no_removable_kind__requires_upsert_only() -> None:
    schema = bind_retrieval_query_plan_output_schema(
        route_ids=["gmail"],
        route_operations={"gmail": ["SEARCH"]},
        supported_constraint_kinds={"gmail": ["KEYWORD", "CONCEPT"]},
        removable_constraint_kinds={"gmail": []},
        is_followup=True,
    )
    candidate: dict[str, Any] = {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "gmail",
                "operation": "SEARCH",
                "reason_codes": ["MISSING_DATE"],
                "search_spec": {
                    "mode": "CHANGED",
                    "constraint_delta": {
                        "upsert_constraints": [
                            {"kind": "CONCEPT", "concept": "출시", "manifestations": ["공개"]}
                        ],
                        "remove_constraint_kinds": [],
                    },
                },
                "detail_candidate_ref": None,
            }
        ],
    }

    assert validate_output_schema(candidate, schema.json_schema) == []
    candidate["route_queries"][0]["search_spec"]["constraint_delta"]["remove_constraint_kinds"] = [
        "KEYWORD"
    ]
    assert validate_output_schema(candidate, schema.json_schema)


@pytest.mark.parametrize(
    ("term", "valid"),
    [
        ("Quartz 납품: 10시 확인!", True),
        ('Quartz" OR from:other@example.test', False),
        ("Quartz\n납품", False),
        (r"Quartz\\납품", False),
    ],
)
def test_gmail_runtime_schema__keyword_literal__matches_serializer_contract(
    term: str,
    valid: bool,
) -> None:
    schema = bind_retrieval_query_plan_output_schema(
        route_ids=["gmail"],
        route_operations={"gmail": ["SEARCH"]},
        supported_constraint_kinds={"gmail": ["KEYWORD"]},
        gmail_route_ids=["gmail"],
    )
    candidate = {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "gmail",
                "operation": "SEARCH",
                "reason_codes": ["USER_REQUEST"],
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": [{"kind": "KEYWORD", "terms": [term], "match_mode": "PHRASE"}],
                },
                "detail_candidate_ref": None,
            }
        ],
    }

    assert (not validate_output_schema(candidate, schema.json_schema)) is valid


def test_constraint_union__rejects_extra_fields__for_declared_kind() -> None:
    errors = validate_output_schema(
        {
            "schema_version": 2,
            "route_queries": [
                {
                    "route_id": "calendar-read",
                    "operation": "SEARCH",
                    "reason_codes": ["POLICY_PRECONDITION"],
                    "search_spec": {
                        "mode": "INITIAL",
                        "constraints": [
                            {
                                "kind": "CONTAINER_REF",
                                "container_refs": ["calendar:primary"],
                                "calendar_id": "primary",
                            }
                        ],
                    },
                    "detail_candidate_ref": None,
                }
            ],
        },
        RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA.json_schema,
    )

    assert "$.route_queries[0].search_spec.constraints[0].calendar_id is not allowed" in errors
    assert not any(".participants is required" in error for error in errors)


def test_runtime_binding__rejects_unvalidated__container_ref() -> None:
    schema = bind_retrieval_query_plan_output_schema(
        route_ids=["calendar-read"],
        route_operations={"calendar-read": ["SEARCH"]},
        supported_constraint_kinds={"calendar-read": ["TEMPORAL_RANGE", "CONTAINER_REF"]},
        validated_container_refs={"calendar-read": ["primary"]},
    )
    candidate: dict[str, Any] = {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "calendar-read",
                "operation": "SEARCH",
                "reason_codes": ["POLICY_PRECONDITION"],
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": [
                        {"kind": "CONTAINER_REF", "container_refs": ["calendar:primary"]}
                    ],
                },
                "detail_candidate_ref": None,
            }
        ],
    }

    assert validate_output_schema(candidate, schema.json_schema)
    candidate["route_queries"][0]["search_spec"]["constraints"][0]["container_refs"] = ["primary"]
    assert validate_output_schema(candidate, schema.json_schema) == []


@pytest.mark.parametrize("is_followup", [False, True])
def test_runtime_binding__query_round__accepts_only_current_mode(is_followup: bool) -> None:
    schema = bind_retrieval_query_plan_output_schema(
        route_ids=["r"],
        route_operations={"r": ["SEARCH"]},
        supported_constraint_kinds={"r": ["KEYWORD"]},
        is_followup=is_followup,
    )
    constraint = {"kind": "KEYWORD", "terms": ["exact"], "match_mode": "PHRASE"}
    initial = {"mode": "INITIAL", "constraints": [constraint]}
    changed = {
        "mode": "CHANGED",
        "constraint_delta": {
            "upsert_constraints": [constraint],
            "remove_constraint_kinds": [],
        },
    }
    query = {
        "route_id": "r",
        "operation": "SEARCH",
        "reason_codes": ["USER_REQUEST"],
        "search_spec": changed if is_followup else initial,
        "detail_candidate_ref": None,
    }
    candidate = {
        "schema_version": 2,
        "route_queries": [query],
    }
    assert validate_output_schema(candidate, schema.json_schema) == []
    query["search_spec"] = initial if is_followup else changed
    assert validate_output_schema(candidate, schema.json_schema)


def test_temporal_constraint__rejects_offset_bearing__local_value() -> None:
    candidate = {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "calendar-read",
                "operation": "SEARCH",
                "reason_codes": ["POLICY_PRECONDITION"],
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": [
                        {
                            "kind": "TEMPORAL_RANGE",
                            "axis": "EVENT_TIME",
                            "start_local": "2026-09-05T15:00:00+09:00",
                            "end_local": "2026-09-05T15:30:00+09:00",
                            "timezone": "Asia/Seoul",
                        }
                    ],
                },
                "detail_candidate_ref": None,
            }
        ],
    }

    assert validate_output_schema(candidate, RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA.json_schema)


@pytest.mark.parametrize(
    ("operation", "search_spec", "detail_candidate_ref"),
    [
        ("SEARCH", {"mode": "INITIAL", "constraints": []}, "candidate-1"),
        ("FREEBUSY", {"mode": "INITIAL", "constraints": []}, "candidate-1"),
        ("DETAIL_FETCH", {"mode": "INITIAL", "constraints": []}, "candidate-1"),
        ("NEXT_PAGE", {"mode": "INITIAL", "constraints": []}, None),
        ("NEXT_PAGE", None, "candidate-1"),
    ],
)
def test_operation_union__with_mismatched_fields__rejects_candidate(
    operation: str,
    search_spec: object,
    detail_candidate_ref: str | None,
) -> None:
    errors = validate_output_schema(
        {
            "schema_version": 2,
            "route_queries": [
                {
                    "route_id": "route-1",
                    "operation": operation,
                    "reason_codes": ["USER_REQUEST"],
                    "search_spec": search_spec,
                    "detail_candidate_ref": detail_candidate_ref,
                }
            ],
        },
        RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA.json_schema,
    )

    assert errors
