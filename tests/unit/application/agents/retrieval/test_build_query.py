from copy import deepcopy
from typing import cast

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


@pytest.mark.parametrize("kind", ["TEMPORAL_RANGE", "PARTICIPANT", "KEYWORD", "CONCEPT",
                                 "CONTAINER_REF", "RESOURCE_REF", "STATUS_SCOPE"])
@pytest.mark.parametrize("remove", [False, True])
def test_build_query__changed_search__protects_anchor_values(kind: str, remove: bool) -> None:
    anchors = {
        "TEMPORAL_RANGE": {"kind": "TEMPORAL_RANGE", "axis": "EVENT_TIME",
                           "start_local": "2026-09-01", "end_local": "2026-09-08",
                           "timezone": "Asia/Seoul"},
        "PARTICIPANT": {"kind": "PARTICIPANT", "participants": [
            {"role": "ANY", "identity": "one@example.test"}], "match_mode": "ALL"},
        "KEYWORD": {"kind": "KEYWORD", "terms": ["exact title"], "match_mode": "PHRASE"},
        "CONCEPT": {"kind": "CONCEPT", "concept": "일정", "manifestations": ["행사"]},
        "CONTAINER_REF": {"kind": "CONTAINER_REF", "container_refs": ["owner/a"]},
        "RESOURCE_REF": {"kind": "RESOURCE_REF", "resource_refs": ["known-a"]},
        "STATUS_SCOPE": {"kind": "STATUS_SCOPE", "values": ["DRAFT"]},
    }
    changed = {
        "TEMPORAL_RANGE": {**anchors[kind], "axis": "MESSAGE_TIME"},
        "PARTICIPANT": {**anchors[kind], "participants": [
            {"role": "ANY", "identity": "two@example.test"}]},
        "KEYWORD": {**anchors[kind], "terms": ["different"]},
        "CONCEPT": {**anchors[kind], "concept": "unrelated"},
        "CONTAINER_REF": {**anchors[kind], "container_refs": ["owner/b"]},
        "RESOURCE_REF": {**anchors[kind], "resource_refs": ["known-b"]},
        "STATUS_SCOPE": {**anchors[kind], "values": ["SENT"]},
    }[kind]
    route = cast(InputToolRouteV1, {"route_id": "r", "connector_id": "google_workspace",
        "resource_type": "GMAIL_THREAD", "allowed_read_tool_ids": ["gmail_search_threads"],
        "required": True, "reason_codes": ["USER_REQUEST"]})
    plan = cast(RetrievalQueryPlanV2, {"schema_version": 2, "route_queries": [{
        "route_id": "r", "operation": "SEARCH", "reason_codes": ["USER_REQUEST"],
        "search_spec": {"mode": "INITIAL", "constraints": [anchors[kind]]},
        "detail_candidate_ref": None}], "required_information": ["evidence"],
        "retrieval_order": ["r"]})
    kwargs = dict(frozen_routes=[route], route_policies={"r": RouteConstraintPolicy(
        frozenset(anchors))}, validated_container_refs={"r": ["owner/a", "owner/b"]},
        validated_resource_refs={"r": ["known-a", "known-b"]})
    prior = build_query(plan, **kwargs)[0]
    plan["route_queries"][0]["search_spec"] = {"mode": "CHANGED", "constraint_delta": {
        "upsert_constraints": [] if remove else [cast(SemanticRetrievalConstraintV1, changed)],
        "remove_constraint_kinds": [kind] if remove else [],
    }}
    with pytest.raises(RetrievalV2ValidationError, match="protected"):
        build_query(plan, prior_plans={"r": prior}, **kwargs)


@pytest.mark.parametrize("provenance,identity,allowed", [
    (["segment"], "known@example.test", True),
    ([], "known@example.test", False),
    (["segment"], "guessed@example.test", False),
])
def test_build_query__person_promotion__requires_candidate_evidence(
    provenance: list[str], identity: str, allowed: bool,
) -> None:
    route = cast(InputToolRouteV1, {"route_id": "r", "connector_id": "google_workspace",
        "resource_type": "GMAIL_THREAD", "allowed_read_tool_ids": ["gmail_search_threads"],
        "required": True, "reason_codes": ["USER_REQUEST"]})
    plan = cast(RetrievalQueryPlanV2, {"schema_version": 2, "route_queries": [{
        "route_id": "r", "operation": "SEARCH", "reason_codes": ["USER_REQUEST"],
        "search_spec": {"mode": "INITIAL", "constraints": [
            {"kind": "KEYWORD", "terms": ["대리", "exact project"], "match_mode": "ALL"},
        ]}, "detail_candidate_ref": None}], "required_information": ["person evidence"],
        "retrieval_order": ["r"]})
    policies = {"r": RouteConstraintPolicy(frozenset({"KEYWORD", "PARTICIPANT"}))}
    prior = build_query(plan, frozen_routes=[route], route_policies=policies)[0]
    plan["route_queries"][0]["search_spec"] = {"mode": "CHANGED", "constraint_delta": {
        "upsert_constraints": [
            {"kind": "KEYWORD", "terms": ["exact project"], "match_mode": "ALL"},
            {"kind": "PARTICIPANT", "participants": [{"role": "ANY", "identity": identity}],
             "match_mode": "ALL"},
        ], "remove_constraint_kinds": [],
    }}
    candidates = [cast(PersonCandidateV1, {"mention": "김대리", "identity": "known@example.test",
        "source_segment_ids": provenance})]
    if not allowed:
        with pytest.raises(RetrievalV2ValidationError, match="protected"):
            build_query(plan, frozen_routes=[route], route_policies=policies,
                        prior_plans={"r": prior}, person_candidates=candidates)
    else:
        result = build_query(plan, frozen_routes=[route], route_policies=policies,
                             prior_plans={"r": prior}, person_candidates=candidates)[0]
        assert {"kind": "KEYWORD", "terms": ["exact project"], "match_mode": "ALL"} in (
            result["effective_constraints"]
        )
