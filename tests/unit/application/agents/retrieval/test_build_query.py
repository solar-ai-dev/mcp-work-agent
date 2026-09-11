from copy import deepcopy
from typing import Any, cast

import pytest

from google_work_agent.application.agents.retrieval.build_query import (
    QueryUnchangedAfterFailureError,
    RouteConstraintPolicy,
    build_query,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    RetrievalQueryPlanV2,
    RetrievalV2ValidationError,
    SemanticRetrievalConstraintV1,
)
from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    PersonCandidateV1,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)


@pytest.mark.parametrize("matching", [True, False])
def test_build_query__detail_then_page__uses_search_continuation(matching: bool) -> None:
    route = cast(
        InputToolRouteV1,
        {
            "route_id": "r1",
            "connector_id": "google_workspace",
            "resource_type": "GMAIL_THREAD",
            "allowed_read_tool_ids": ["gmail_search_threads", "gmail_get_thread"],
            "required": True,
            "reason_codes": ["USER_REQUEST"],
        },
    )
    policy = {"r1": RouteConstraintPolicy(frozenset({"KEYWORD"}))}
    query = {
        "route_id": "r1",
        "operation": "SEARCH",
        "reason_codes": ["USER_REQUEST"],
        "search_spec": {
            "mode": "INITIAL",
            "constraints": [
                {"kind": "KEYWORD", "terms": ["project"], "match_mode": "PHRASE"},
            ],
        },
        "detail_candidate_ref": None,
    }
    plan = {"schema_version": 2, "route_queries": [query]}
    search = build_query(plan, frozen_routes=[route], route_policies=policy)[0]
    query.update(operation="DETAIL_FETCH", search_spec=None, detail_candidate_ref="gmail_thread:t1")
    detail = build_query(
        plan,
        frozen_routes=[route],
        route_policies=policy,
        prior_plans={"r1": search},
        detail_candidate_refs=["gmail_thread:t1"],
    )[0]
    query.update(operation="NEXT_PAGE", detail_candidate_ref=None)
    summaries = [
        {
            "route_id": "r1",
            "query_identity_hash": search["query_identity_hash"] if matching else "other",
            "read_result_handle": "search-page",
            "has_next_page": True,
            "exhausted": False,
        },
        {
            "route_id": "r1",
            "query_identity_hash": detail["query_identity_hash"],
            "read_result_handle": "detail",
            "has_next_page": False,
            "exhausted": True,
        },
    ]
    if not matching:
        with pytest.raises(RetrievalV2ValidationError, match="validated prior read-result"):
            build_query(
                plan,
                frozen_routes=[route],
                route_policies=policy,
                prior_plans={"r1": detail},
                read_result_summaries=summaries,
            )
        return
    page = build_query(
        plan,
        frozen_routes=[route],
        route_policies=policy,
        prior_plans={"r1": detail},
        read_result_summaries=summaries,
    )[0]
    assert page["query_identity_hash"] == search["query_identity_hash"]
    assert page["prior_read_result_handle"] == "search-page"
    assert page["effective_constraints"] == search["effective_constraints"]


def test_build_query__preserves_exact__frozen_resource_type() -> None:
    route = cast(
        InputToolRouteV1,
        {
            "route_id": "r1",
            "connector_id": "google_workspace",
            "resource_type": "GMAIL_THREAD",
            "allowed_read_tool_ids": ["gmail_search_threads"],
            "required": True,
            "reason_codes": ["USER_REQUEST"],
        },
    )
    plan = cast(
        RetrievalQueryPlanV2,
        {
            "schema_version": 2,
            "route_queries": [
                {
                    "route_id": "r1",
                    "operation": "SEARCH",
                    "reason_codes": ["USER_REQUEST"],
                    "search_spec": {
                        "mode": "INITIAL",
                        "constraints": [
                            {"kind": "KEYWORD", "terms": ["alpha"], "match_mode": "ANY"}
                        ],
                    },
                    "detail_candidate_ref": None,
                }
            ],
        },
    )

    result = build_query(
        plan,
        frozen_routes=[route],
        route_policies={"r1": RouteConstraintPolicy(frozenset({"KEYWORD"}))},
    )

    assert result[0]["resource_type"] == "GMAIL_THREAD"

    # Order-only changes cannot create new query identities or provider calls.
    plan["route_queries"][0]["search_spec"] = {
        "mode": "INITIAL",
        "constraints": [
            {"kind": "KEYWORD", "terms": ["alpha", "beta"], "match_mode": "ANY"},
            {
                "kind": "PARTICIPANT",
                "participants": [
                    {"role": "SENDER", "identity": "kim@example.com"},
                ],
                "match_mode": "ANY",
            },
        ],
    }
    policies = {"r1": RouteConstraintPolicy(frozenset({"KEYWORD", "PARTICIPANT"}))}
    original = build_query(plan, frozen_routes=[route], route_policies=policies)[0]
    reordered = deepcopy(plan)
    spec = reordered["route_queries"][0]["search_spec"]
    assert spec is not None and spec["mode"] == "INITIAL"
    spec["constraints"].reverse()
    spec["constraints"][1]["terms"].reverse()
    reordered_result = build_query(reordered, frozen_routes=[route], route_policies=policies)[0]
    assert reordered_result["query_identity_hash"] == original["query_identity_hash"]
    assert reordered_result["effective_constraints"] == original["effective_constraints"]
    reordered["route_queries"][0]["search_spec"] = {
        "mode": "CHANGED",
        "constraint_delta": {
            "upsert_constraints": spec["constraints"],
            "remove_constraint_kinds": [],
        },
    }
    with pytest.raises(QueryUnchangedAfterFailureError):
        build_query(
            reordered, frozen_routes=[route], route_policies=policies, prior_plans={"r1": original}
        )


def test_build_query__phrase_order_and_repetition__define_execution_and_identity() -> None:
    route = cast(
        InputToolRouteV1,
        {
            "route_id": "r1",
            "connector_id": "google_workspace",
            "resource_type": "GMAIL_THREAD",
            "allowed_read_tool_ids": ["gmail_search_threads"],
            "required": True,
            "reason_codes": ["USER_REQUEST"],
        },
    )
    policies = {"r1": RouteConstraintPolicy(frozenset({"KEYWORD"}))}

    def phrase(terms: list[str]) -> dict[str, object]:
        return {
            "schema_version": 2,
            "route_queries": [
                {
                    "route_id": "r1",
                    "operation": "SEARCH",
                    "reason_codes": ["USER_REQUEST"],
                    "search_spec": {
                        "mode": "INITIAL",
                        "constraints": [
                            {"kind": "KEYWORD", "terms": terms, "match_mode": "PHRASE"}
                        ],
                    },
                    "detail_candidate_ref": None,
                }
            ],
        }

    original = build_query(
        phrase(["납품", "회신", "검토", "회신"]),
        frozen_routes=[route],
        route_policies=policies,
    )[0]
    reordered = build_query(
        phrase(["검토", "회신", "납품", "회신"]),
        frozen_routes=[route],
        route_policies=policies,
    )[0]
    repeated = build_query(
        phrase(["납품", "회신", "검토", "회신"]),
        frozen_routes=[route],
        route_policies=policies,
    )[0]

    assert cast(Any, original["effective_constraints"][0])["terms"] == [
        "납품",
        "회신",
        "검토",
        "회신",
    ]
    assert original["query_identity_hash"] != reordered["query_identity_hash"]
    assert original["query_identity_hash"] == repeated["query_identity_hash"]


@pytest.mark.parametrize("match_mode", ["ANY", "ALL"])
def test_build_query__unordered_keyword_modes__retain_stable_identity(match_mode: str) -> None:
    route = cast(
        InputToolRouteV1,
        {
            "route_id": "r1",
            "connector_id": "google_workspace",
            "resource_type": "GMAIL_THREAD",
            "allowed_read_tool_ids": ["gmail_search_threads"],
            "required": True,
            "reason_codes": ["USER_REQUEST"],
        },
    )
    policies = {"r1": RouteConstraintPolicy(frozenset({"KEYWORD"}))}

    def plan(terms: list[str]) -> dict[str, object]:
        return {
            "schema_version": 2,
            "route_queries": [
                {
                    "route_id": "r1",
                    "operation": "SEARCH",
                    "reason_codes": ["USER_REQUEST"],
                    "search_spec": {
                        "mode": "INITIAL",
                        "constraints": [
                            {"kind": "KEYWORD", "terms": terms, "match_mode": match_mode}
                        ],
                    },
                    "detail_candidate_ref": None,
                }
            ],
        }

    first = build_query(plan(["alpha", "beta"]), frozen_routes=[route], route_policies=policies)[0]
    second = build_query(plan(["beta", "alpha"]), frozen_routes=[route], route_policies=policies)[0]

    assert first["effective_constraints"] == second["effective_constraints"]
    assert first["query_identity_hash"] == second["query_identity_hash"]


def test_build_query__concept_alternatives__retain_stable_identity_when_reordered() -> None:
    route = cast(
        InputToolRouteV1,
        {
            "route_id": "r1",
            "connector_id": "google_workspace",
            "resource_type": "GMAIL_THREAD",
            "allowed_read_tool_ids": ["gmail_search_threads"],
            "required": True,
            "reason_codes": ["USER_REQUEST"],
        },
    )
    policies = {"r1": RouteConstraintPolicy(frozenset({"CONCEPT"}))}

    def plan(manifestations: list[str]) -> dict[str, object]:
        return {
            "schema_version": 2,
            "route_queries": [
                {
                    "route_id": "r1",
                    "operation": "SEARCH",
                    "reason_codes": ["USER_REQUEST"],
                    "search_spec": {
                        "mode": "INITIAL",
                        "constraints": [
                            {
                                "kind": "CONCEPT",
                                "concept": "출시",
                                "manifestations": manifestations,
                            }
                        ],
                    },
                    "detail_candidate_ref": None,
                }
            ],
        }

    first = build_query(plan(["공개", "배포"]), frozen_routes=[route], route_policies=policies)[0]
    second = build_query(plan(["배포", "공개"]), frozen_routes=[route], route_policies=policies)[0]

    assert first["effective_constraints"] == second["effective_constraints"]
    assert first["query_identity_hash"] == second["query_identity_hash"]


@pytest.mark.parametrize(
    "kind",
    [
        "TEMPORAL_RANGE",
        "KEYWORD",
        "CONCEPT",
        "CONTAINER_REF",
        "RESOURCE_REF",
        "STATUS_SCOPE",
    ],
)
@pytest.mark.parametrize("remove", [False, True])
def test_build_query__changed_search__accepts_planner_semantic_revision(
    kind: str, remove: bool
) -> None:
    anchors = {
        "TEMPORAL_RANGE": {
            "kind": "TEMPORAL_RANGE",
            "axis": "MESSAGE_TIME",
            "start_local": "2026-09-01",
            "end_local": "2026-09-08",
            "timezone": "Asia/Seoul",
        },
        "PARTICIPANT": {
            "kind": "PARTICIPANT",
            "participants": [{"role": "ANY", "identity": "one@example.test"}],
            "match_mode": "ALL",
        },
        "KEYWORD": {"kind": "KEYWORD", "terms": ["exact title"], "match_mode": "PHRASE"},
        "CONCEPT": {"kind": "CONCEPT", "concept": "일정", "manifestations": ["행사"]},
        "CONTAINER_REF": {"kind": "CONTAINER_REF", "container_refs": ["owner/a"]},
        "RESOURCE_REF": {"kind": "RESOURCE_REF", "resource_refs": ["known-a"]},
        "STATUS_SCOPE": {"kind": "STATUS_SCOPE", "values": ["DRAFT"]},
    }
    changed = {
        "TEMPORAL_RANGE": {**anchors[kind], "end_local": "2026-09-09"},
        "PARTICIPANT": {
            **anchors[kind],
            "participants": [{"role": "ANY", "identity": "two@example.test"}],
        },
        "KEYWORD": {**anchors[kind], "terms": ["different"]},
        "CONCEPT": {**anchors[kind], "concept": "unrelated"},
        "CONTAINER_REF": {**anchors[kind], "container_refs": ["owner/b"]},
        "RESOURCE_REF": {**anchors[kind], "resource_refs": ["known-b"]},
        "STATUS_SCOPE": {**anchors[kind], "values": ["SENT"]},
    }[kind]
    route = cast(
        InputToolRouteV1,
        {
            "route_id": "r",
            "connector_id": "google_workspace",
            "resource_type": "GMAIL_THREAD",
            "allowed_read_tool_ids": ["gmail_search_threads"],
            "required": True,
            "reason_codes": ["USER_REQUEST"],
        },
    )
    plan = cast(
        RetrievalQueryPlanV2,
        {
            "schema_version": 2,
            "route_queries": [
                {
                    "route_id": "r",
                    "operation": "SEARCH",
                    "reason_codes": ["USER_REQUEST"],
                    "search_spec": {"mode": "INITIAL", "constraints": [anchors[kind]]},
                    "detail_candidate_ref": None,
                }
            ],
        },
    )
    kwargs = dict(
        frozen_routes=[route],
        route_policies={"r": RouteConstraintPolicy(frozenset(anchors))},
        validated_container_refs={"r": ["owner/a", "owner/b"]},
        validated_resource_refs={"r": ["known-a", "known-b"]},
    )
    prior = build_query(plan, **kwargs)[0]
    plan["route_queries"][0]["search_spec"] = {
        "mode": "CHANGED",
        "constraint_delta": {
            "upsert_constraints": [] if remove else [cast(SemanticRetrievalConstraintV1, changed)],
            "remove_constraint_kinds": [kind] if remove else [],
        },
    }
    if remove:
        result = build_query(plan, prior_plans={"r": prior}, **kwargs)[0]
        assert result["effective_constraints"] == []
        return
    result = build_query(plan, prior_plans={"r": prior}, **kwargs)[0]
    assert cast(SemanticRetrievalConstraintV1, changed) in result["effective_constraints"]


@pytest.mark.parametrize(
    "constraint",
    [
        {
            "kind": "TEMPORAL_RANGE",
            "axis": "TASK_SCHEDULED_DATE",
            "start_local": "2026-09-01",
            "end_local": "2026-09-08",
            "timezone": "Asia/Seoul",
        },
        {
            "kind": "PARTICIPANT",
            "participants": [{"role": "ATTENDEE", "identity": "one@example.test"}],
            "match_mode": "ALL",
        },
    ],
)
def test_build_query__gmail_search__rejects_constraints_the_projection_cannot_lower(
    constraint: dict[str, object],
) -> None:
    route = cast(
        InputToolRouteV1,
        {
            "route_id": "r",
            "connector_id": "google_workspace",
            "resource_type": "GMAIL_THREAD",
            "allowed_read_tool_ids": ["gmail_search_threads"],
            "required": True,
            "reason_codes": ["USER_REQUEST"],
        },
    )
    plan = {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "r",
                "operation": "SEARCH",
                "reason_codes": ["USER_REQUEST"],
                "search_spec": {"mode": "INITIAL", "constraints": [constraint]},
                "detail_candidate_ref": None,
            }
        ],
    }

    with pytest.raises(RetrievalV2ValidationError):
        build_query(
            plan,
            frozen_routes=[route],
            route_policies={
                "r": RouteConstraintPolicy(
                    frozenset({"TEMPORAL_RANGE", "PARTICIPANT", "STATUS_SCOPE"})
                )
            },
        )


def test_build_query__gmail_search__retains_event_time_for_evidence_matching() -> None:
    route = cast(
        InputToolRouteV1,
        {
            "route_id": "r",
            "connector_id": "google_workspace",
            "resource_type": "GMAIL_THREAD",
            "allowed_read_tool_ids": ["gmail_search_threads"],
            "required": True,
            "reason_codes": ["USER_REQUEST"],
        },
    )
    event_time = {
        "kind": "TEMPORAL_RANGE",
        "axis": "EVENT_TIME",
        "start_local": "2026-09-01",
        "end_local": "2026-09-08",
        "timezone": "Asia/Seoul",
    }

    result = build_query(
        {
            "schema_version": 2,
            "route_queries": [
                {
                    "route_id": "r",
                    "operation": "SEARCH",
                    "reason_codes": ["USER_REQUEST"],
                    "search_spec": {"mode": "INITIAL", "constraints": [event_time]},
                    "detail_candidate_ref": None,
                }
            ],
        },
        frozen_routes=[route],
        route_policies={"r": RouteConstraintPolicy(frozenset({"TEMPORAL_RANGE"}))},
    )

    assert result[0]["effective_constraints"] == [event_time]


def test_build_query__gmail_search__allows_no_translatable_filter() -> None:
    route = cast(
        InputToolRouteV1,
        {
            "route_id": "r",
            "connector_id": "google_workspace",
            "resource_type": "GMAIL_THREAD",
            "allowed_read_tool_ids": ["gmail_search_threads"],
            "required": True,
            "reason_codes": ["USER_REQUEST"],
        },
    )
    plan = {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "r",
                "operation": "SEARCH",
                "reason_codes": ["USER_REQUEST"],
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": [{"kind": "STATUS_SCOPE", "values": ["ANY"]}],
                },
                "detail_candidate_ref": None,
            }
        ],
    }

    result = build_query(
        plan,
        frozen_routes=[route],
        route_policies={"r": RouteConstraintPolicy(frozenset({"STATUS_SCOPE"}))},
    )

    assert result[0]["effective_constraints"] == [{"kind": "STATUS_SCOPE", "values": ["ANY"]}]


def test_build_query__followup_hypothesis_change__preserves_explicit_constraint() -> None:
    route = cast(
        InputToolRouteV1,
        {
            "route_id": "r",
            "connector_id": "google_workspace",
            "resource_type": "GMAIL_THREAD",
            "allowed_read_tool_ids": ["gmail_search_threads"],
            "required": True,
            "reason_codes": ["USER_REQUEST"],
        },
    )
    policies = {"r": RouteConstraintPolicy(frozenset({"KEYWORD", "CONCEPT"}))}
    explicit = cast(
        SemanticRetrievalConstraintV1,
        {"kind": "KEYWORD", "terms": ["Nimbus"], "match_mode": "PHRASE"},
    )
    initial = {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "r",
                "operation": "SEARCH",
                "reason_codes": ["USER_REQUEST"],
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": [
                        explicit,
                        {"kind": "CONCEPT", "concept": "출시", "manifestations": ["공개"]},
                    ],
                },
                "detail_candidate_ref": None,
            }
        ],
    }
    prior = build_query(
        initial,
        frozen_routes=[route],
        route_policies=policies,
    )[0]
    changed = deepcopy(initial)
    changed["route_queries"][0]["search_spec"] = {
        "mode": "CHANGED",
        "constraint_delta": {
            "upsert_constraints": [
                {"kind": "CONCEPT", "concept": "출시", "manifestations": ["배포"]}
            ],
            "remove_constraint_kinds": [],
        },
    }

    result = build_query(
        changed,
        frozen_routes=[route],
        route_policies=policies,
        prior_plans={"r": prior},
    )[0]

    assert explicit in result["effective_constraints"]
    assert {
        "kind": "CONCEPT",
        "concept": "출시",
        "manifestations": ["배포"],
    } in result["effective_constraints"]


def test_build_query__same_kind_hypothesis__preserves_all_literals_and_can_change() -> None:
    route = cast(
        InputToolRouteV1,
        {
            "route_id": "r",
            "connector_id": "google_workspace",
            "resource_type": "GMAIL_THREAD",
            "allowed_read_tool_ids": ["gmail_search_threads"],
            "required": True,
            "reason_codes": ["USER_REQUEST"],
        },
    )
    policies = {"r": RouteConstraintPolicy(frozenset({"KEYWORD"}))}
    initial = {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "r",
                "operation": "SEARCH",
                "reason_codes": ["USER_REQUEST"],
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": [
                        {
                            "kind": "KEYWORD",
                            "terms": ["Cobalt", "남극", "출장"],
                            "match_mode": "ALL",
                        }
                    ],
                },
                "detail_candidate_ref": None,
            }
        ],
    }
    prior = build_query(
        initial,
        frozen_routes=[route],
        route_policies=policies,
    )[0]
    changed = deepcopy(initial)
    changed["route_queries"][0]["search_spec"] = {
        "mode": "CHANGED",
        "constraint_delta": {
            "upsert_constraints": [
                {
                    "kind": "KEYWORD",
                    "terms": ["Cobalt", "남극", "확정"],
                    "match_mode": "ALL",
                }
            ],
            "remove_constraint_kinds": [],
        },
    }

    revised = build_query(
        changed,
        frozen_routes=[route],
        route_policies=policies,
        prior_plans={"r": prior},
    )[0]

    assert revised["effective_constraints"] == [
        {"kind": "KEYWORD", "terms": ["Cobalt", "남극", "확정"], "match_mode": "ALL"}
    ]


@pytest.mark.parametrize(
    "changed_keyword",
    [
        {"kind": "KEYWORD", "terms": ["Cobalt", "다른 값"], "match_mode": "ALL"},
        {"kind": "KEYWORD", "terms": ["Cobalt", "남극"], "match_mode": "ANY"},
    ],
)
def test_build_query__same_kind_change_or_match_mode_revision__is_planner_owned(
    changed_keyword: dict[str, object],
) -> None:
    route = cast(
        InputToolRouteV1,
        {
            "route_id": "r",
            "connector_id": "google_workspace",
            "resource_type": "GMAIL_THREAD",
            "allowed_read_tool_ids": ["gmail_search_threads"],
            "required": True,
            "reason_codes": ["USER_REQUEST"],
        },
    )
    policies = {"r": RouteConstraintPolicy(frozenset({"KEYWORD"}))}
    initial_keyword = cast(
        SemanticRetrievalConstraintV1,
        {"kind": "KEYWORD", "terms": ["Cobalt", "남극"], "match_mode": "ALL"},
    )
    initial = {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "r",
                "operation": "SEARCH",
                "reason_codes": ["USER_REQUEST"],
                "search_spec": {"mode": "INITIAL", "constraints": [initial_keyword]},
                "detail_candidate_ref": None,
            }
        ],
    }
    prior = build_query(
        initial,
        frozen_routes=[route],
        route_policies=policies,
    )[0]
    changed = deepcopy(initial)
    changed["route_queries"][0]["search_spec"] = {
        "mode": "CHANGED",
        "constraint_delta": {
            "upsert_constraints": [changed_keyword],
            "remove_constraint_kinds": [],
        },
    }

    result = build_query(
        changed,
        frozen_routes=[route],
        route_policies=policies,
        prior_plans={"r": prior},
    )[0]

    assert result["effective_constraints"] == [changed_keyword]


def test_build_query__changed_phrase__uses_planner_order_and_repetition() -> None:
    route = cast(
        InputToolRouteV1,
        {
            "route_id": "r",
            "connector_id": "google_workspace",
            "resource_type": "GMAIL_THREAD",
            "allowed_read_tool_ids": ["gmail_search_threads"],
            "required": True,
            "reason_codes": ["USER_REQUEST"],
        },
    )
    policies = {"r": RouteConstraintPolicy(frozenset({"KEYWORD"}))}
    initial_phrase = cast(
        SemanticRetrievalConstraintV1,
        {
            "kind": "KEYWORD",
            "terms": ["Quartz", "Quartz", "납품"],
            "match_mode": "PHRASE",
        },
    )
    initial = {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "r",
                "operation": "SEARCH",
                "reason_codes": ["USER_REQUEST"],
                "search_spec": {"mode": "INITIAL", "constraints": [initial_phrase]},
                "detail_candidate_ref": None,
            }
        ],
    }
    prior = build_query(
        initial,
        frozen_routes=[route],
        route_policies=policies,
    )[0]
    changed = deepcopy(initial)
    changed["route_queries"][0]["search_spec"] = {
        "mode": "CHANGED",
        "constraint_delta": {
            "upsert_constraints": [
                {
                    "kind": "KEYWORD",
                    "terms": ["Quartz", "납품", "Quartz"],
                    "match_mode": "PHRASE",
                }
            ],
            "remove_constraint_kinds": [],
        },
    }

    result = build_query(
        changed,
        frozen_routes=[route],
        route_policies=policies,
        prior_plans={"r": prior},
    )[0]

    assert result["effective_constraints"] == [
        {
            "kind": "KEYWORD",
            "terms": ["Quartz", "납품", "Quartz"],
            "match_mode": "PHRASE",
        }
    ]


def test_build_query__same_manifestation__is_allowed_when_effective_query_changes() -> None:
    route = cast(
        InputToolRouteV1,
        {
            "route_id": "r",
            "connector_id": "google_workspace",
            "resource_type": "GMAIL_THREAD",
            "allowed_read_tool_ids": ["gmail_search_threads"],
            "required": True,
            "reason_codes": ["USER_REQUEST"],
        },
    )
    policies = {"r": RouteConstraintPolicy(frozenset({"CONCEPT", "KEYWORD"}))}
    initial = {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "r",
                "operation": "SEARCH",
                "reason_codes": ["USER_REQUEST"],
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": [
                        {"kind": "CONCEPT", "concept": "출시", "manifestations": ["공개"]}
                    ],
                },
                "detail_candidate_ref": None,
            }
        ],
    }
    prior = build_query(initial, frozen_routes=[route], route_policies=policies)[0]
    changed = deepcopy(initial)
    changed["route_queries"][0]["search_spec"] = {
        "mode": "CHANGED",
        "constraint_delta": {
            "upsert_constraints": [
                {"kind": "KEYWORD", "terms": ["Nimbus"], "match_mode": "PHRASE"}
            ],
            "remove_constraint_kinds": [],
        },
    }

    result = build_query(
        changed,
        frozen_routes=[route],
        route_policies=policies,
        prior_plans={"r": prior},
    )[0]

    assert {"kind": "CONCEPT", "concept": "출시", "manifestations": ["공개"]} in result[
        "effective_constraints"
    ]
    assert result["query_identity_hash"] != prior["query_identity_hash"]


@pytest.mark.parametrize(
    "provenance,identity,allowed",
    [
        (["segment"], "known@example.test", True),
        ([], "known@example.test", False),
        (["segment"], "guessed@example.test", False),
    ],
)
def test_build_query__person_promotion__requires_candidate_evidence(
    provenance: list[str],
    identity: str,
    allowed: bool,
) -> None:
    route = cast(
        InputToolRouteV1,
        {
            "route_id": "r",
            "connector_id": "google_workspace",
            "resource_type": "GMAIL_THREAD",
            "allowed_read_tool_ids": ["gmail_search_threads"],
            "required": True,
            "reason_codes": ["USER_REQUEST"],
        },
    )
    plan = cast(
        RetrievalQueryPlanV2,
        {
            "schema_version": 2,
            "route_queries": [
                {
                    "route_id": "r",
                    "operation": "SEARCH",
                    "reason_codes": ["USER_REQUEST"],
                    "search_spec": {
                        "mode": "INITIAL",
                        "constraints": [
                            {
                                "kind": "KEYWORD",
                                "terms": ["대리", "exact project"],
                                "match_mode": "ALL",
                            },
                        ],
                    },
                    "detail_candidate_ref": None,
                }
            ],
        },
    )
    policies = {"r": RouteConstraintPolicy(frozenset({"KEYWORD", "PARTICIPANT"}))}
    prior = build_query(plan, frozen_routes=[route], route_policies=policies)[0]
    plan["route_queries"][0]["search_spec"] = {
        "mode": "CHANGED",
        "constraint_delta": {
            "upsert_constraints": [
                {"kind": "KEYWORD", "terms": ["exact project"], "match_mode": "ALL"},
                {
                    "kind": "PARTICIPANT",
                    "participants": [{"role": "ANY", "identity": identity}],
                    "match_mode": "ALL",
                },
            ],
            "remove_constraint_kinds": [],
        },
    }
    candidates = [
        cast(
            PersonCandidateV1,
            {
                "mention": "김대리",
                "identity": "known@example.test",
                "source_segment_ids": provenance,
            },
        )
    ]
    if not allowed:
        with pytest.raises(RetrievalV2ValidationError, match="validated evidence"):
            build_query(
                plan,
                frozen_routes=[route],
                route_policies=policies,
                prior_plans={"r": prior},
                person_candidates=candidates,
            )
    else:
        result = build_query(
            plan,
            frozen_routes=[route],
            route_policies=policies,
            prior_plans={"r": prior},
            person_candidates=candidates,
        )[0]
        assert {"kind": "KEYWORD", "terms": ["exact project"], "match_mode": "ALL"} in (
            result["effective_constraints"]
        )
