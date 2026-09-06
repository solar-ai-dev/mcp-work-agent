"""Observed identities, aliases and budget termination never become guessed facts."""

from typing import Any, cast

from google_work_agent.application.agents.retrieval.assess_sufficiency import (
    deterministic_sufficiency,
)
from google_work_agent.application.agents.retrieval.match_person_mention import (
    project_person_candidates,
)
from google_work_agent.application.agents.retrieval.normalize_segments import SourceSegment
from google_work_agent.application.agents.retrieval.plan_query_expansion import (
    deterministic_followup_query_plan,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget


def _intent() -> Any:
    return {
        "constraints": [{"kind": "PERSON", "field": "person", "value": "김대리"}],
        "requested_effect_hints": ["READ"],
    }


def _evidence(name: str | None, email: str, key: str) -> Any:
    return {
        "schema_version": 1,
        "evidence_id": key,
        "resource_handle": "gmail_thread:" + key,
        "segment_id": key,
        "kind": "SOURCE",
        "excerpt": "synthetic record",
        "locator": {"sender_name": name, "sender_email": email},
        "reason_codes": ["CONTEXT"],
    }


def _guard(candidates: Any, **kwargs: Any) -> Any:
    return deterministic_sufficiency(
        request_intent=_intent(),
        tool_route_plan=None,
        acquisition_result=cast(Any, {"source_summaries": []}),
        evidence_drafts=[],
        retry_budget=build_default_run_budget(),
        person_candidates=candidates,
        **kwargs,
    )


def test_observed_aliases__join_only_same_email__and_retain_provenance() -> None:
    candidates = project_person_candidates(
        _intent(),
        [
            _evidence("김하늘 대리", "first@example.test", "s1"),
            _evidence("하늘", "first@example.test", "s2"),
            _evidence(None, "first@example.test", "s3"),
            _evidence(None, "unrelated@example.test", "s4"),
        ],
    )
    assert len(candidates) == 1
    assert candidates[0]["identity"] == "first@example.test"
    assert candidates[0]["display_names"] == ["김하늘 대리", "하늘"]
    assert candidates[0]["source_segment_ids"] == ["s1", "s2", "s3"]
    assert _guard(candidates)["status"] == "NEEDS_MORE_DATA"
    assert project_person_candidates(_intent(), [], candidates) == candidates
    assert project_person_candidates(_intent(), [], candidates, ["s1", "s2", "s3"]) == []


def test_shared_surname_title__retains_distinct_identities__and_requires_confirmation() -> None:
    candidates = project_person_candidates(
        _intent(),
        [
            _evidence("김하늘 대리", "first@example.test", "s1"),
            _evidence("김바다 대리", "second@example.test", "s2"),
        ],
    )
    assert len(candidates) == 2
    assert _guard(candidates)["status"] == "NEEDS_CONFIRMATION"
    assert (
        _guard(candidates, selected_person_identities={"김대리": "invented@example.test"})["status"]
        == "NEEDS_CONFIRMATION"
    )
    assert (
        _guard(candidates, selected_person_identities={"김대리": "second@example.test"})["status"]
        == "NEEDS_MORE_DATA"
    )


def test_email_only__without_alias_provenance__does_not_resolve_mention() -> None:
    assert project_person_candidates(_intent(), [_evidence(None, "kim@example.test", "s1")]) == []


def test_candidate_discovery__survives_llm_evidence_exclusion__without_picking_one_person() -> None:
    segments = [SourceSegment(
        key, "gmail_thread:" + key, "GMAIL", "gmail_thread", key, None, "v1",
        {"sender_name": name, "sender_email": email}, "검토 자료",
    ) for key, name, email in [
        ("s1", "김하늘 대리", "first@example.test"),
        ("s2", "김바다 대리", "second@example.test"),
    ]]
    candidates = project_person_candidates(_intent(), [], source_segments=segments)
    assert len(candidates) == 2
    assert _guard(candidates)["status"] == "NEEDS_CONFIRMATION"


def test_explicit_body_contact__links_alias__without_assigning_it_to_sender() -> None:
    item = _evidence("안내 담당", "other@example.test", "s1")
    item["excerpt"] = "담당자는 김하늘 대리 <first@example.test>입니다."
    candidates = project_person_candidates(_intent(), [item])
    assert [item["identity"] for item in candidates] == ["first@example.test"]
    assert project_person_candidates(_intent(), [], candidates, ["s1"]) == []


def test_resolved_identity__changes_query_without_losing_anchor__and_deduplicates_followup() -> (
    None
):
    candidates = project_person_candidates(
        _intent(), [_evidence("김하늘 대리", "first@example.test", "s1")]
    )
    route = cast(
        Any,
        {
            "route_id": "gmail",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["gmail_search_threads"],
        },
    )
    initial = {
        "route_id": "gmail",
        "operation_kind": "SEARCH",
        "normalized_intent_constraints": [
            {"kind": "KEYWORD", "terms": ["KAN-93", "대리"], "match_mode": "ALL"}
        ],
    }
    projection = {
        "request_intent": _intent(),
        "current_round_no": 1,
        "prior_query_attempts": [initial],
        "read_result_summaries": [],
        "unresolved_sufficiency_issues": _guard(candidates)["issues"],
    }
    plan = deterministic_followup_query_plan(
        prompt_input=projection, frozen_routes=[route], person_candidates=candidates
    )
    assert plan is not None
    delta = cast(Any, plan)["route_queries"][0]["search_spec"]["constraint_delta"]
    assert delta["upsert_constraints"] == [
        {
            "kind": "PARTICIPANT",
            "participants": [{"role": "ANY", "identity": "first@example.test"}],
            "match_mode": "ALL",
        },
        {"kind": "KEYWORD", "terms": ["KAN-93"], "match_mode": "ALL"},
    ]
    projection["prior_query_attempts"].append(
        {**initial, "normalized_intent_constraints": delta["upsert_constraints"]}
    )
    assert (
        deterministic_followup_query_plan(
            prompt_input=projection, frozen_routes=[route], person_candidates=candidates
        )
        is None
    )


def test_llm_budget_exhausted__keeps_read_partial__without_relaxing_write_requirements() -> None:
    budget = build_default_run_budget()
    budget["llm_calls_used"] = budget["llm_call_limit"]
    values = dict(
        tool_route_plan=None,
        acquisition_result=cast(Any, {"source_summaries": []}),
        evidence_drafts=[_evidence(None, "fixture@example.test", "s1")],
        retry_budget=budget,
    )
    result = deterministic_sufficiency(request_intent=_intent(), **values)
    assert result is not None and result["status"] == "PARTIAL"
    assert (
        deterministic_sufficiency(
            request_intent=cast(Any, {**_intent(), "requested_effect_hints": ["CREATE"]}), **values
        )
        is None
    )
    assert budget["llm_calls_used"] == budget["llm_call_limit"]
