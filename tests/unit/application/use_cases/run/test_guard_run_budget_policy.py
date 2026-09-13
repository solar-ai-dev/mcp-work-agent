"""Run budget policy matrix owned by run.guard_run_budget."""

import pytest

from google_work_agent.application.use_cases.run.guard_run_budget import (
    ABSOLUTE_MAX_LLM_CALLS,
    MAX_ADDITIONAL_ACQUISITIONS,
    NORMAL_MAX_LLM_CALLS,
    PLANNING_REVISION_PER_RUN,
    RETRIEVAL_HEAVY_MAX_LLM_CALLS,
    REVISION_HEAVY_MAX_LLM_CALLS,
    BudgetDecision,
    BudgetProfile,
    BudgetReasonCode,
    approve_additional_acquisition,
    approve_planning_revision,
    approve_review_recheck,
    approve_semantic_revision,
    build_default_run_budget,
    build_semantic_failure_signature_v1,
    check_llm_call_budget,
    consume_llm_provider_calls,
    merge_run_budget_progress,
    promote_budget_profile,
    promote_run_budget_profile,
    validate_run_budget_v2,
)


def test_default_run__budget_is_valid__and_checkpoint_safe() -> None:
    budget = validate_run_budget_v2(build_default_run_budget())

    assert budget["schema_version"] == 2
    assert budget["profile"] == BudgetProfile.NORMAL.value
    assert budget["llm_calls_used"] == 0
    assert budget["started_at_ms"] == 0
    assert budget["absolute_llm_call_limit"] == ABSOLUTE_MAX_LLM_CALLS
    assert budget["max_source_page_calls"] == 50
    assert budget["schema_repairs_used_by_node"] == {}
    assert budget["semantic_revisions_used_by_failure"] == {}


def test_run_budget__with_default_policy__has_fifty_source_pages() -> None:
    assert build_default_run_budget(max_source_page_calls=51)["max_source_page_calls"] == 50
    with pytest.raises(ValueError, match="source_page_calls exceeds retrieval hard bound"):
        validate_run_budget_v2({**build_default_run_budget(), "max_source_page_calls": 51})


def test_run_budget_validator__rejects_invalid_counters__profile_and_duplicates() -> None:
    with pytest.raises(ValueError, match="run budget llm_calls_used must be non-negative"):
        validate_run_budget_v2(
            {
                **build_default_run_budget(),
                "llm_calls_used": -1,
            }
        )

    with pytest.raises(ValueError, match="run budget additional_retrieval_rounds_used exceeds"):
        validate_run_budget_v2(
            {
                **build_default_run_budget(),
                "additional_retrieval_rounds_used": MAX_ADDITIONAL_ACQUISITIONS + 1,
            }
        )

    with pytest.raises(ValueError, match="run budget planning_revisions_used exceeds"):
        validate_run_budget_v2(
            {
                **build_default_run_budget(),
                "planning_revisions_used": PLANNING_REVISION_PER_RUN + 1,
            }
        )

    with pytest.raises(
        ValueError,
        match="review_rechecks_used exceeds planning revisions",
    ):
        validate_run_budget_v2(
            {
                **build_default_run_budget(),
                "planning_revisions_used": 1,
                "review_rechecks_used": 2,
            }
        )

    with pytest.raises(ValueError, match="run budget profile is invalid"):
        validate_run_budget_v2(
            {
                **build_default_run_budget(),
                "profile": "ABSOLUTE",
            }
        )

    with pytest.raises(
        ValueError,
        match="semantic revisions must be a non-negative counter map",
    ):
        validate_run_budget_v2(
            {
                **build_default_run_budget(),
                "semantic_revisions_used_by_failure": [],
            }
        )


def test_semantic_failure_signature__is_canonicalized_by__node_and_reason_set() -> None:
    first = build_semantic_failure_signature_v1(
        node_id="review.inspect",
        failure_reason_codes=["B", "A", "B"],
    )
    second = build_semantic_failure_signature_v1(
        node_id="review.inspect",
        failure_reason_codes=["A", "B"],
    )
    third = build_semantic_failure_signature_v1(
        node_id="planning.revise_answer",
        failure_reason_codes=["A", "B"],
    )

    assert first == second
    assert first["failure_reason_codes"] == ["A", "B"]
    assert first != third


def test_profile_promotion_is__monotonic_and_has__no_absolute_profile() -> None:
    assert (
        promote_budget_profile(BudgetProfile.NORMAL, BudgetProfile.REVISION_HEAVY)
        is BudgetProfile.REVISION_HEAVY
    )
    assert (
        promote_budget_profile(BudgetProfile.NORMAL, BudgetProfile.RETRIEVAL_HEAVY)
        is BudgetProfile.RETRIEVAL_HEAVY
    )
    assert (
        promote_budget_profile(BudgetProfile.REVISION_HEAVY, BudgetProfile.RETRIEVAL_HEAVY)
        is BudgetProfile.RETRIEVAL_HEAVY
    )
    assert (
        promote_budget_profile(BudgetProfile.RETRIEVAL_HEAVY, BudgetProfile.REVISION_HEAVY)
        is BudgetProfile.RETRIEVAL_HEAVY
    )


def test_llm_budget_gate__observes_profile_and_enforces__absolute_limit_only() -> None:
    budget = {
        **build_default_run_budget(),
        "llm_calls_used": NORMAL_MAX_LLM_CALLS - 1,
    }
    allow = check_llm_call_budget(budget)
    consumed = consume_llm_provider_calls(allow["run_budget"])

    assert allow["decision"] == BudgetDecision.ALLOW.value
    assert consumed["llm_calls_used"] == NORMAL_MAX_LLM_CALLS

    allow_beyond_profile = check_llm_call_budget(consumed)
    assert allow_beyond_profile["decision"] == BudgetDecision.ALLOW.value
    assert consumed["llm_call_limit"] == NORMAL_MAX_LLM_CALLS

    absolute_budget = {
        **build_default_run_budget(),
        "profile": BudgetProfile.RETRIEVAL_HEAVY.value,
        "llm_call_limit": RETRIEVAL_HEAVY_MAX_LLM_CALLS,
        "llm_calls_used": ABSOLUTE_MAX_LLM_CALLS,
    }
    deny_absolute = check_llm_call_budget(absolute_budget)
    assert deny_absolute["decision"] == BudgetDecision.DENY.value
    assert (
        deny_absolute["budget_reason_code"] == BudgetReasonCode.ABSOLUTE_LLM_LIMIT_EXHAUSTED.value
    )


def test_neither_revision_nor__retrieval_triggered_keeps__normal_observation_value() -> None:
    budget = {**build_default_run_budget(), "llm_calls_used": NORMAL_MAX_LLM_CALLS - 1}

    allow = check_llm_call_budget(budget)
    consumed = consume_llm_provider_calls(allow["run_budget"])
    next_call = check_llm_call_budget(consumed)

    assert allow["decision"] == BudgetDecision.ALLOW.value
    assert consumed["llm_calls_used"] == NORMAL_MAX_LLM_CALLS
    assert consumed["llm_call_limit"] == NORMAL_MAX_LLM_CALLS
    assert next_call["decision"] == BudgetDecision.ALLOW.value


def test_revision_and_retrieval__retain_profile_observation_and__absolute_hard_limit() -> None:
    revised = approve_planning_revision(build_default_run_budget())
    combined = approve_additional_acquisition(revised["run_budget"])
    assert combined["run_budget"]["profile"] == BudgetProfile.RETRIEVAL_HEAVY.value
    assert combined["run_budget"]["planning_revisions_used"] == 1
    assert combined["run_budget"]["additional_retrieval_rounds_used"] == 1
    assert combined["run_budget"]["llm_call_limit"] == RETRIEVAL_HEAVY_MAX_LLM_CALLS

    budget_at_profile_cap = {
        **combined["run_budget"],
        "llm_calls_used": RETRIEVAL_HEAVY_MAX_LLM_CALLS,
    }

    allow_beyond_profile_cap = check_llm_call_budget(budget_at_profile_cap)
    assert allow_beyond_profile_cap["decision"] == BudgetDecision.ALLOW.value

    budget_at_absolute_cap = {
        **combined["run_budget"],
        "llm_calls_used": ABSOLUTE_MAX_LLM_CALLS,
    }
    deny_at_absolute = check_llm_call_budget(budget_at_absolute_cap)
    assert deny_at_absolute["decision"] == BudgetDecision.DENY.value
    assert (
        deny_at_absolute["budget_reason_code"]
        == BudgetReasonCode.ABSOLUTE_LLM_LIMIT_EXHAUSTED.value
    )


def test_previous_24_call_budget__canonicalizes_to__100_through_merge_and_promotion() -> None:
    current = validate_run_budget_v2(
        {
            **build_default_run_budget(),
            "absolute_llm_call_limit": 24,
        }
    )
    promoted = promote_run_budget_profile(current, BudgetProfile.RETRIEVAL_HEAVY)
    merged = merge_run_budget_progress(current, promoted)

    assert promoted["absolute_llm_call_limit"] == 100
    assert merged["absolute_llm_call_limit"] == 100
    assert promoted["llm_call_limit"] == RETRIEVAL_HEAVY_MAX_LLM_CALLS


def test_legacy_36_call_budget__is_canonicalized_to__the_current_100_call_ceiling() -> None:
    legacy = {
        **build_default_run_budget(),
        "absolute_llm_call_limit": 36,
    }

    canonical = validate_run_budget_v2(legacy)

    assert canonical["absolute_llm_call_limit"] == 100
    assert canonical["llm_call_limit"] == NORMAL_MAX_LLM_CALLS
    revised = approve_planning_revision(legacy)["run_budget"]
    combined = approve_additional_acquisition(revised)["run_budget"]

    assert combined["absolute_llm_call_limit"] == 100
    assert combined["llm_call_limit"] == RETRIEVAL_HEAVY_MAX_LLM_CALLS

    observed = {**combined, "llm_calls_used": 99}
    merged = merge_run_budget_progress(combined, observed)
    assert merged["absolute_llm_call_limit"] == 100
    assert merged["llm_call_limit"] == RETRIEVAL_HEAVY_MAX_LLM_CALLS
    assert check_llm_call_budget(merged)["decision"] == BudgetDecision.ALLOW.value
    assert check_llm_call_budget({**merged, "llm_calls_used": 100})["decision"] == (
        BudgetDecision.DENY.value
    )


def test_single_profile_promotion__does_not_create__a_dispatch_limit() -> None:
    revision_only = approve_planning_revision(build_default_run_budget())
    assert revision_only["run_budget"]["profile"] == BudgetProfile.REVISION_HEAVY.value

    budget_at_revision_cap = {
        **revision_only["run_budget"],
        "llm_calls_used": REVISION_HEAVY_MAX_LLM_CALLS,
    }
    allow = check_llm_call_budget(budget_at_revision_cap)
    assert allow["decision"] == BudgetDecision.ALLOW.value

    retrieval_only = approve_additional_acquisition(build_default_run_budget())
    assert retrieval_only["run_budget"]["profile"] == BudgetProfile.RETRIEVAL_HEAVY.value

    budget_at_retrieval_cap = {
        **retrieval_only["run_budget"],
        "llm_calls_used": RETRIEVAL_HEAVY_MAX_LLM_CALLS,
    }
    allow_retrieval = check_llm_call_budget(budget_at_retrieval_cap)
    assert allow_retrieval["decision"] == BudgetDecision.ALLOW.value


def test_mandatory_modify_review_reuses__planning_revision_to_allow__call_past_normal_cap() -> None:
    """G3 Final Closure A: approve_planning_revision is the same function
    runtime.py's _prepare_modify_review_state calls for a mandatory Modify
    Review re-entry. Even when a Run already exhausted NORMAL(8) on one
    ordinary pass, approve_planning_revision only checks
    planning_revisions_used (not llm_calls_used) and promotes to
    REVISION_HEAVY -- so the very next llm-call-budget check has headroom."""
    exhausted_normal = {**build_default_run_budget(), "llm_calls_used": NORMAL_MAX_LLM_CALLS}

    modify_review_budget = approve_planning_revision(exhausted_normal)
    assert modify_review_budget["decision"] == BudgetDecision.ALLOW.value
    assert modify_review_budget["run_budget"]["profile"] == BudgetProfile.REVISION_HEAVY.value

    next_call = check_llm_call_budget(modify_review_budget["run_budget"])
    assert next_call["decision"] == BudgetDecision.ALLOW.value


def test_additional_acquisition_counter__promotes_profile_and__denies_third_round() -> None:
    first = approve_additional_acquisition(build_default_run_budget())
    second = approve_additional_acquisition(first["run_budget"])
    third = approve_additional_acquisition(second["run_budget"])

    assert first["decision"] == BudgetDecision.ALLOW.value
    assert first["run_budget"]["additional_retrieval_rounds_used"] == 1
    assert first["run_budget"]["profile"] == BudgetProfile.RETRIEVAL_HEAVY.value

    assert second["decision"] == BudgetDecision.ALLOW.value
    assert second["run_budget"]["additional_retrieval_rounds_used"] == 2
    assert second["run_budget"]["profile"] == BudgetProfile.RETRIEVAL_HEAVY.value

    assert third["decision"] == BudgetDecision.DENY.value
    assert (
        third["budget_reason_code"] == BudgetReasonCode.ADDITIONAL_ACQUISITION_LIMIT_EXHAUSTED.value
    )


def test_planning_revision_counter__is_shared_by__answer_and_plan_revisions() -> None:
    answer_revision = approve_planning_revision(build_default_run_budget())
    plan_revision = approve_planning_revision(answer_revision["run_budget"])
    third_revision = approve_planning_revision(plan_revision["run_budget"])

    assert answer_revision["decision"] == BudgetDecision.ALLOW.value
    assert answer_revision["run_budget"]["planning_revisions_used"] == 1
    assert answer_revision["run_budget"]["profile"] == BudgetProfile.REVISION_HEAVY.value

    assert plan_revision["decision"] == BudgetDecision.ALLOW.value
    assert plan_revision["run_budget"]["planning_revisions_used"] == 2
    assert plan_revision["run_budget"]["profile"] == BudgetProfile.REVISION_HEAVY.value

    assert third_revision["decision"] == BudgetDecision.DENY.value
    assert (
        third_revision["budget_reason_code"]
        == BudgetReasonCode.PLANNING_REVISION_LIMIT_EXHAUSTED.value
    )


def test_review_recheck_requires__revision_and_allows__once_per_revision() -> None:
    no_revision = approve_review_recheck(build_default_run_budget())
    first_revision = approve_planning_revision(build_default_run_budget())
    first_recheck = approve_review_recheck(first_revision["run_budget"])
    second_recheck = approve_review_recheck(first_recheck["run_budget"])
    second_revision = approve_planning_revision(first_recheck["run_budget"])
    recheck_after_second_revision = approve_review_recheck(second_revision["run_budget"])

    assert no_revision["decision"] == BudgetDecision.DENY.value
    assert (
        no_revision["budget_reason_code"] == BudgetReasonCode.REVIEW_RECHECK_LIMIT_EXHAUSTED.value
    )

    assert first_recheck["decision"] == BudgetDecision.ALLOW.value
    assert first_recheck["run_budget"]["review_rechecks_used"] == 1

    assert second_recheck["decision"] == BudgetDecision.DENY.value
    assert (
        second_recheck["budget_reason_code"]
        == BudgetReasonCode.REVIEW_RECHECK_LIMIT_EXHAUSTED.value
    )

    assert second_revision["run_budget"]["planning_revisions_used"] == 2
    assert recheck_after_second_revision["decision"] == BudgetDecision.ALLOW.value
    assert recheck_after_second_revision["run_budget"]["review_rechecks_used"] == 2


def test_semantic_same_failure__gate_denies_same_node__and_reason_set_only() -> None:
    signature = build_semantic_failure_signature_v1(
        node_id="review.inspect",
        failure_reason_codes=["PLAN_REQUIRED_ACTION_MISSING", "EVIDENCE_SUPPORTED"],
    )
    same_signature_different_order = build_semantic_failure_signature_v1(
        node_id="review.inspect",
        failure_reason_codes=["EVIDENCE_SUPPORTED", "PLAN_REQUIRED_ACTION_MISSING"],
    )
    different_node = build_semantic_failure_signature_v1(
        node_id="planning.revise_answer",
        failure_reason_codes=["PLAN_REQUIRED_ACTION_MISSING", "EVIDENCE_SUPPORTED"],
    )

    first = approve_semantic_revision(build_default_run_budget(), signature=signature)
    same = approve_semantic_revision(first["run_budget"], signature=same_signature_different_order)
    different = approve_semantic_revision(first["run_budget"], signature=different_node)

    assert first["decision"] == BudgetDecision.ALLOW.value
    assert len(first["run_budget"]["semantic_revisions_used_by_failure"]) == 1

    assert same["decision"] == BudgetDecision.DENY.value
    assert (
        same["budget_reason_code"] == BudgetReasonCode.SEMANTIC_SAME_FAILURE_LIMIT_EXHAUSTED.value
    )

    assert different["decision"] == BudgetDecision.ALLOW.value
    assert len(different["run_budget"]["semantic_revisions_used_by_failure"]) == 2


def test_budget_profile__constants_match__frozen_contract() -> None:
    assert NORMAL_MAX_LLM_CALLS == 14
    assert REVISION_HEAVY_MAX_LLM_CALLS == 18
    assert RETRIEVAL_HEAVY_MAX_LLM_CALLS == 20
    assert ABSOLUTE_MAX_LLM_CALLS == 100
