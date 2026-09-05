from copy import deepcopy
from typing import cast

import pytest

from google_work_agent.application.agents.retrieval.build_query import (
    QueryUnchangedAfterFailureError,
    RouteConstraintPolicy,
    build_query,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan import RetrievalQueryPlanV2
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)


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
            "required_information": ["mail"],
            "retrieval_order": ["r1"],
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
        "mode": "INITIAL", "constraints": [
            {"kind": "KEYWORD", "terms": ["alpha", "beta"], "match_mode": "ANY"},
            {"kind": "PARTICIPANT", "participants": [
                {"role": "SENDER", "identity": "kim@example.com"},
            ], "match_mode": "ANY"},
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
        "mode": "CHANGED", "constraint_delta": {
            "upsert_constraints": spec["constraints"], "remove_constraint_kinds": [],
        },
    }
    with pytest.raises(QueryUnchangedAfterFailureError):
        build_query(reordered, frozen_routes=[route], route_policies=policies,
                    prior_plans={"r1": original})
