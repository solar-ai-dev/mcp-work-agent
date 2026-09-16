"""Project allowlisted LLM decisions for privacy-safe LangSmith inspection."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from enum import Enum
from typing import Final, TypeGuard

LANGSMITH_LLM_SEMANTIC_PROJECTION_VERSION: Final = 1
_MAX_PROJECTION_BYTES: Final = 8 * 1024
_MAX_COLLECTION_ITEMS: Final = 12
_MAX_DEPTH: Final = 12
_SAFE_VALUE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_SAFE_FIELD_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{0,63}")
_SUPPORTED_PROMPTS = frozenset(
    {
        "request_understanding.identify_goal",
        "request_understanding.identify_effect_prohibitions",
        "request_understanding.identify_source_dependencies",
        "request_understanding.identify_output_responsibilities",
        "request_understanding.identify_source_status",
        "request_understanding.detect_ambiguity",
        "retrieval.plan_query",
        "tool_routing.determine_io_resources",
        "retrieval.select_evidence",
        "retrieval.select_evidence.revise",
        "retrieval.assess_sufficiency",
        "planning.compose_answer",
    }
)
_ALLOWED_PROJECTION_KEYS = frozenset(
    {
        "projection_version",
        "projection_status",
        "selected_resource_count",
        "has_confirmation_response",
        "has_request_reconsideration",
        "analysis_requirement",
        "completion_condition_count",
        "requested_effect_hints",
        "requested_resource_hints",
        "source_reads",
        "outputs",
        "allowed_status_values",
        "statuses",
        "constraints",
        "count",
        "items",
        "resource_type",
        "required_information_count",
        "effect",
        "kind",
        "field",
        "status_values",
        "coverage_requirement",
        "goal_candidate",
        "source_candidates",
        "output_candidates",
        "source_dependencies",
        "output_responsibilities",
        "effect_candidates",
        "effect_prohibitions",
        "prohibition",
        "dependency",
        "target_scope",
        "read_tool_ids",
        "owned_fact_kinds",
        "allowed_output_effects",
        "resolution_responsibilities",
        "connector_owned_information_count",
        "connector_owned_source_count",
        "connector_owned_resource_types",
        "resolved_resource_count",
        "searchable_target_anchor_count",
        "missing_information_owner",
        "missing_fields",
        "values",
        "input_routes",
        "connector_id",
        "allowed_operations",
        "supported_constraint_kinds",
        "required_constraint_kinds",
        "has_current_round",
        "prior_query_attempt_count",
        "read_result_summary_count",
        "has_next_page_count",
        "exhausted_count",
        "result_count_total",
        "detail_candidate_count",
        "route_queries",
        "operation",
        "reason_codes",
        "detail_candidate_ref_present",
        "search_spec",
        "mode",
        "constraint_shapes",
        "match_mode",
        "axis",
        "participant_roles",
        "manifestation_count",
        "remove_constraint_kinds",
        "request_intent",
        "eligible_route_capabilities",
        "input_resource_types",
        "output_resource_types",
        "output_effects",
        "disposition",
        "ranked_segment_count",
        "sufficiency_feedback_count",
        "temporal_constraint_shapes",
        "segment_assessment_count",
        "role_counts",
        "selected_evidence_count",
        "source_statuses",
        "status",
        "failure_kind",
        "budget_state",
        "issues",
        "issue_type",
        "required",
        "resolution_source",
        "safety_critical",
        "evidence_count",
        "outline_evidence_count",
        "collection_result_count",
        "missing_information_count",
        "has_answer",
        "answer_char_count",
        "evidence_ref_count",
        "read_supported",
        "write_effects",
        "role",
        "additional_rounds_used",
        "additional_rounds_remaining",
    }
)


def project_llm_semantic_input(prompt_id: str, value: object) -> dict[str, object]:
    """Return one bounded input decision projection for a supported Prompt."""

    mapping = _prompt_mapping(value)
    if prompt_id not in _SUPPORTED_PROMPTS or mapping is None:
        return _unavailable()
    if prompt_id == "request_understanding.identify_source_status":
        result = _project_source_status_input(mapping)
    elif prompt_id == "request_understanding.identify_effect_prohibitions":
        result = _project_effect_prohibition_input(mapping)
    elif prompt_id == "request_understanding.identify_source_dependencies":
        result = _project_source_dependency_input(mapping)
    elif prompt_id == "request_understanding.identify_output_responsibilities":
        result = _project_output_responsibility_input(mapping)
    elif prompt_id in {
        "request_understanding.identify_goal",
    }:
        result = _project_identify_input(mapping)
    elif prompt_id == "request_understanding.detect_ambiguity":
        result = _project_ambiguity_input(mapping)
    elif prompt_id == "retrieval.plan_query":
        result = _project_query_input(mapping)
    elif prompt_id == "tool_routing.determine_io_resources":
        result = _project_tool_route_input(mapping)
    elif prompt_id.startswith("retrieval.select_evidence"):
        result = _project_evidence_input(mapping)
    elif prompt_id == "retrieval.assess_sufficiency":
        result = _project_sufficiency_input(mapping)
    else:
        result = _project_compose_answer_input(mapping)
    return _bounded(result)


def project_llm_semantic_output(prompt_id: str, value: object) -> dict[str, object]:
    """Return one bounded provider-candidate projection for a supported Prompt."""

    mapping = _mapping(value)
    if prompt_id not in _SUPPORTED_PROMPTS or mapping is None:
        return _unavailable()
    if prompt_id == "request_understanding.identify_goal":
        result = _project_goal_candidate(mapping)
    elif prompt_id == "request_understanding.identify_effect_prohibitions":
        result = _project_effect_prohibition_candidate(mapping)
    elif prompt_id == "request_understanding.identify_source_dependencies":
        result = _project_source_dependency_candidate(mapping)
    elif prompt_id == "request_understanding.identify_output_responsibilities":
        result = _project_output_responsibility_candidate(mapping)
    elif prompt_id == "request_understanding.identify_source_status":
        result = _project_source_status_candidate(mapping)
    elif prompt_id == "request_understanding.detect_ambiguity":
        result = _project_ambiguity_output(mapping)
    elif prompt_id == "retrieval.plan_query":
        result = _project_query_output(mapping)
    elif prompt_id == "tool_routing.determine_io_resources":
        result = _project_tool_route_output(mapping)
    elif prompt_id.startswith("retrieval.select_evidence"):
        result = _project_evidence_output(mapping)
    elif prompt_id == "retrieval.assess_sufficiency":
        result = _project_sufficiency_output(mapping)
    else:
        result = _project_compose_answer_output(mapping)
    return _bounded(result)


def sanitize_llm_semantic_projection(value: object) -> dict[str, object] | None:
    """Apply the callback boundary's independent allowlist and size limits."""

    mapping = _mapping(value)
    if mapping is None:
        return None
    sanitized = _sanitize_mapping(mapping, depth=0)
    if not sanitized:
        return None
    encoded = json.dumps(sanitized, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > _MAX_PROJECTION_BYTES:
        return {
            "projection_version": LANGSMITH_LLM_SEMANTIC_PROJECTION_VERSION,
            "projection_status": "TRUNCATED",
        }
    return sanitized


def _project_identify_input(value: Mapping[object, object]) -> dict[str, object]:
    result: dict[str, object] = {
        "projection_version": LANGSMITH_LLM_SEMANTIC_PROJECTION_VERSION,
        "selected_resource_count": _count(value.get("selected_resource_refs")),
        "has_confirmation_response": _present(value.get("confirmation_response")),
        "has_request_reconsideration": _present(value.get("request_reconsideration")),
    }
    goal_candidate = _mapping(value.get("goal_candidate"))
    if goal_candidate is not None:
        result["goal_candidate"] = _project_goal_candidate(goal_candidate)
    return result


def _project_source_dependency_input(value: Mapping[object, object]) -> dict[str, object]:
    result = _project_identify_input(value)
    candidates = _sequence(value.get("source_candidates"))
    items: list[dict[str, object]] = []
    for raw_candidate in candidates[:_MAX_COLLECTION_ITEMS]:
        candidate = _mapping(raw_candidate)
        if candidate is None:
            continue
        projected: dict[str, object] = {
            "read_tool_ids": _safe_values(candidate.get("read_tool_ids")),
            "owned_fact_kinds": _safe_values(candidate.get("owned_fact_kinds")),
        }
        _copy_safe_scalar(candidate, projected, "resource_type")
        items.append(projected)
    result["source_candidates"] = {"count": len(candidates), "items": items}
    return result


def _project_output_responsibility_input(
    value: Mapping[object, object],
) -> dict[str, object]:
    result = _project_identify_input(value)
    candidates = _sequence(value.get("output_candidates"))
    items: list[dict[str, object]] = []
    for raw_candidate in candidates[:_MAX_COLLECTION_ITEMS]:
        candidate = _mapping(raw_candidate)
        if candidate is None:
            continue
        projected: dict[str, object] = {
            "allowed_output_effects": _safe_values(candidate.get("allowed_output_effects"))
        }
        _copy_safe_scalar(candidate, projected, "resource_type")
        items.append(projected)
    result["output_candidates"] = {"count": len(candidates), "items": items}
    result["effect_prohibitions"] = _project_effect_prohibition_items(
        value.get("effect_prohibitions")
    )
    return result


def _project_effect_prohibition_input(
    value: Mapping[object, object],
) -> dict[str, object]:
    result = _project_identify_input(value)
    candidates = _sequence(value.get("effect_candidates"))
    result["effect_candidates"] = {
        "count": len(candidates),
        "items": [
            projected
            for raw_candidate in candidates[:_MAX_COLLECTION_ITEMS]
            if (candidate := _mapping(raw_candidate)) is not None
            if (effect := _safe_string(candidate.get("effect"))) is not None
            for projected in ({"effect": effect},)
        ],
    }
    return result


def _project_effect_prohibition_candidate(
    value: Mapping[object, object],
) -> dict[str, object]:
    return {
        "projection_version": LANGSMITH_LLM_SEMANTIC_PROJECTION_VERSION,
        "effect_prohibitions": _project_effect_prohibition_items(value.get("effect_prohibitions")),
    }


def _project_effect_prohibition_items(value: object) -> dict[str, object]:
    decisions = _sequence(value)
    items: list[dict[str, object]] = []
    for raw_decision in decisions[:_MAX_COLLECTION_ITEMS]:
        decision = _mapping(raw_decision)
        if decision is None:
            continue
        projected: dict[str, object] = {}
        for name in ("effect", "prohibition"):
            _copy_safe_scalar(decision, projected, name)
        items.append(projected)
    return {"count": len(decisions), "items": items}


def _project_goal_candidate(value: Mapping[object, object]) -> dict[str, object]:
    result: dict[str, object] = {
        "projection_version": LANGSMITH_LLM_SEMANTIC_PROJECTION_VERSION,
    }
    _copy_safe_scalar(value, result, "analysis_requirement")
    for name in ("requested_effect_hints", "requested_resource_hints"):
        result[name] = _safe_values(value.get(name))

    responsibilities = _mapping(value.get("resource_responsibilities"))
    if responsibilities is not None:
        result["source_reads"] = _project_source_reads(responsibilities.get("source_reads"))
        result["outputs"] = _project_outputs(responsibilities.get("outputs"))
    else:
        result["source_reads"] = {"count": 0, "items": []}
        result["outputs"] = {"count": 0, "items": []}
    result["constraints"] = _project_goal_constraints(value.get("constraints"))
    return result


def _project_source_dependency_candidate(
    value: Mapping[object, object],
) -> dict[str, object]:
    decisions = _sequence(value.get("source_dependencies"))
    items: list[dict[str, object]] = []
    for raw_decision in decisions[:_MAX_COLLECTION_ITEMS]:
        decision = _mapping(raw_decision)
        if decision is None:
            continue
        projected: dict[str, object] = {
            "required_information_count": _count(decision.get("required_information"))
        }
        for name in ("resource_type", "dependency", "target_scope"):
            _copy_safe_scalar(decision, projected, name)
        items.append(projected)
    return {
        "projection_version": LANGSMITH_LLM_SEMANTIC_PROJECTION_VERSION,
        "source_dependencies": {"count": len(decisions), "items": items},
    }


def _project_output_responsibility_candidate(
    value: Mapping[object, object],
) -> dict[str, object]:
    decisions = _sequence(value.get("output_responsibilities"))
    items: list[dict[str, object]] = []
    for raw_decision in decisions[:_MAX_COLLECTION_ITEMS]:
        decision = _mapping(raw_decision)
        if decision is None:
            continue
        projected: dict[str, object] = {}
        for name in ("resource_type", "effect"):
            _copy_safe_scalar(decision, projected, name)
        items.append(projected)
    return {
        "projection_version": LANGSMITH_LLM_SEMANTIC_PROJECTION_VERSION,
        "output_responsibilities": {"count": len(decisions), "items": items},
    }


def _project_source_status_input(value: Mapping[object, object]) -> dict[str, object]:
    allowed_items: list[dict[str, object]] = []
    allowed_values = _sequence(value.get("allowed_status_values"))
    for raw_item in allowed_values[:_MAX_COLLECTION_ITEMS]:
        item = _mapping(raw_item)
        if item is None:
            continue
        projected: dict[str, object] = {"values": _safe_values(item.get("values"))}
        _copy_safe_scalar(item, projected, "resource_type")
        allowed_items.append(projected)
    goal = _mapping(value.get("goal_candidate"))
    return {
        "projection_version": LANGSMITH_LLM_SEMANTIC_PROJECTION_VERSION,
        "selected_resource_count": _count(value.get("selected_resource_refs")),
        "goal_candidate": _project_goal_candidate({} if goal is None else goal),
        "source_reads": _project_source_reads(value.get("source_reads")),
        "outputs": _project_outputs(value.get("outputs")),
        "allowed_status_values": {
            "count": len(allowed_values),
            "items": allowed_items,
        },
        "has_confirmation_response": _present(value.get("confirmation_response")),
    }


def _project_source_status_candidate(value: Mapping[object, object]) -> dict[str, object]:
    status_items: list[dict[str, object]] = []
    statuses = _sequence(value.get("statuses"))
    for raw_status in statuses[:_MAX_COLLECTION_ITEMS]:
        status = _mapping(raw_status)
        if status is None:
            continue
        projected: dict[str, object] = {"status_values": _safe_values([status.get("value")])}
        resource_type = _safe_string(status.get("source_resource_type"))
        if resource_type is not None:
            projected["resource_type"] = resource_type
        status_items.append(projected)
    return {
        "projection_version": LANGSMITH_LLM_SEMANTIC_PROJECTION_VERSION,
        "statuses": {"count": len(statuses), "items": status_items},
    }


def _project_ambiguity_input(value: Mapping[object, object]) -> dict[str, object]:
    goal = _mapping(value.get("goal_candidate"))
    responsibilities = _mapping(value.get("resolution_responsibilities"))
    goal_projection: dict[str, object] = {
        "requested_effect_hints": _safe_values(
            None if goal is None else goal.get("requested_effect_hints")
        ),
        "requested_resource_hints": _safe_values(
            None if goal is None else goal.get("requested_resource_hints")
        ),
        "source_reads": _project_source_reads(_source_reads(goal)),
    }
    connector_owned = (
        []
        if responsibilities is None
        else _sequence(responsibilities.get("connector_owned_information"))
    )
    resolved = (
        []
        if responsibilities is None
        else _sequence(responsibilities.get("resolved_resource_refs"))
    )
    connector_types = sorted(
        {
            safe
            for item in connector_owned
            if (item_mapping := _mapping(item)) is not None
            if (safe := _safe_string(item_mapping.get("resource_type"))) is not None
        }
    )
    resolution_projection: dict[str, object] = {
        "connector_owned_information_count": len(connector_owned),
        "connector_owned_resource_types": connector_types[:_MAX_COLLECTION_ITEMS],
        "resolved_resource_count": len(resolved),
    }
    if responsibilities is not None:
        for name in ("searchable_target_anchor_count", "connector_owned_source_count"):
            count = responsibilities.get(name)
            if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
                resolution_projection[name] = count
    return {
        "projection_version": LANGSMITH_LLM_SEMANTIC_PROJECTION_VERSION,
        "selected_resource_count": _count(value.get("selected_resource_refs")),
        "goal_candidate": goal_projection,
        "resolution_responsibilities": resolution_projection,
        "has_confirmation_response": _present(value.get("confirmation_response")),
    }


def _project_ambiguity_output(value: Mapping[object, object]) -> dict[str, object]:
    result: dict[str, object] = {
        "projection_version": LANGSMITH_LLM_SEMANTIC_PROJECTION_VERSION,
    }
    _copy_safe_scalar(value, result, "missing_information_owner")
    result["missing_fields"] = _safe_field_values(value.get("missing_fields"))
    return result


def _project_query_input(value: Mapping[object, object]) -> dict[str, object]:
    route_items: list[dict[str, object]] = []
    routes = _sequence(value.get("input_routes"))
    for item in routes[:_MAX_COLLECTION_ITEMS]:
        route = _mapping(item)
        if route is None:
            continue
        projected: dict[str, object] = {}
        for name in ("resource_type", "connector_id"):
            _copy_safe_scalar(route, projected, name)
        for name in (
            "allowed_operations",
            "supported_constraint_kinds",
            "required_constraint_kinds",
        ):
            projected[name] = _safe_values(route.get(name))
        route_items.append(projected)
    result: dict[str, object] = {
        "projection_version": LANGSMITH_LLM_SEMANTIC_PROJECTION_VERSION,
        "input_routes": {"count": len(routes), "items": route_items},
        "has_current_round": "current_round_no" in value,
        "prior_query_attempt_count": _count(value.get("prior_query_attempts")),
        "read_result_summary_count": _count(value.get("read_result_summaries")),
    }
    if "detail_candidate_refs" in value:
        result["detail_candidate_count"] = _count(value.get("detail_candidate_refs"))
    return result


def _project_query_output(value: Mapping[object, object]) -> dict[str, object]:
    route_queries = _sequence(value.get("route_queries"))
    items: list[dict[str, object]] = []
    for raw_query in route_queries[:_MAX_COLLECTION_ITEMS]:
        query = _mapping(raw_query)
        if query is None:
            continue
        projected: dict[str, object] = {
            "reason_codes": _safe_values(query.get("reason_codes")),
            "detail_candidate_ref_present": _present(query.get("detail_candidate_ref")),
        }
        _copy_safe_scalar(query, projected, "operation")
        search_spec = _mapping(query.get("search_spec"))
        if search_spec is not None:
            search_projection: dict[str, object] = {}
            _copy_safe_scalar(search_spec, search_projection, "mode")
            constraints = search_spec.get("constraints")
            delta = _mapping(search_spec.get("constraint_delta"))
            if delta is not None:
                constraints = delta.get("upsert_constraints")
                search_projection["remove_constraint_kinds"] = _safe_values(
                    delta.get("remove_constraint_kinds")
                )
            search_projection["constraint_shapes"] = _project_query_constraints(constraints)
            projected["search_spec"] = search_projection
        items.append(projected)
    return {
        "projection_version": LANGSMITH_LLM_SEMANTIC_PROJECTION_VERSION,
        "route_queries": {"count": len(route_queries), "items": items},
    }


def _project_tool_route_input(value: Mapping[object, object]) -> dict[str, object]:
    intent = _mapping(value.get("request_intent"))
    capabilities = _sequence(value.get("eligible_route_capabilities"))
    capability_items: list[dict[str, object]] = []
    for raw_item in capabilities[:_MAX_COLLECTION_ITEMS]:
        item = _mapping(raw_item)
        if item is None:
            continue
        projected: dict[str, object] = {}
        for name in ("resource_type", "connector_id"):
            _copy_safe_scalar(item, projected, name)
        if isinstance(item.get("read_supported"), bool):
            projected["read_supported"] = item["read_supported"]
        for name in ("allowed_operations", "output_effects", "write_effects"):
            if name in item:
                projected[name] = _safe_values(item.get(name))
        capability_items.append(projected)
    return {
        "projection_version": LANGSMITH_LLM_SEMANTIC_PROJECTION_VERSION,
        "request_intent": _project_intent_summary(intent),
        "eligible_route_capabilities": {
            "count": len(capabilities),
            "items": capability_items,
        },
        "has_confirmation_response": _present(value.get("confirmation_response")),
    }


def _project_tool_route_output(value: Mapping[object, object]) -> dict[str, object]:
    result: dict[str, object] = {
        "projection_version": LANGSMITH_LLM_SEMANTIC_PROJECTION_VERSION,
        "input_resource_types": _safe_values(value.get("input_resource_types")),
        "output_resource_types": _safe_values(value.get("output_resource_types")),
        "output_effects": _safe_values(value.get("output_effects")),
    }
    _copy_safe_scalar(value, result, "disposition")
    return result


def _project_evidence_input(value: Mapping[object, object]) -> dict[str, object]:
    return {
        "projection_version": LANGSMITH_LLM_SEMANTIC_PROJECTION_VERSION,
        "request_intent": _project_intent_summary(_mapping(value.get("request_intent"))),
        "ranked_segment_count": _count(value.get("ranked_segments")),
        "sufficiency_feedback_count": _count(value.get("sufficiency_feedback")),
        "temporal_constraint_shapes": _project_query_constraints(value.get("temporal_constraints")),
        "has_confirmation_response": _present(value.get("confirmation_response")),
    }


def _project_evidence_output(value: Mapping[object, object]) -> dict[str, object]:
    assessments = _mapping(value.get("segment_assessments"))
    role_counts: dict[str, int] = {}
    if assessments is not None:
        for raw_assessment in list(assessments.values())[:_MAX_COLLECTION_ITEMS]:
            assessment = _mapping(raw_assessment)
            if assessment is None:
                continue
            role = _safe_string(assessment.get("role"))
            if role is not None:
                role_counts[role] = role_counts.get(role, 0) + 1
    return {
        "projection_version": LANGSMITH_LLM_SEMANTIC_PROJECTION_VERSION,
        "segment_assessment_count": 0 if assessments is None else len(assessments),
        "role_counts": [
            {"role": role, "count": count} for role, count in sorted(role_counts.items())
        ],
    }


def _project_sufficiency_input(value: Mapping[object, object]) -> dict[str, object]:
    statuses = _sequence(value.get("source_statuses"))
    read_result_summaries = _sequence(value.get("read_result_summaries"))
    status_items: list[dict[str, object]] = []
    for raw_item in statuses[:_MAX_COLLECTION_ITEMS]:
        item = _mapping(raw_item)
        if item is None:
            continue
        projected: dict[str, object] = {}
        for name in ("resource_type", "status", "failure_kind"):
            _copy_safe_scalar(item, projected, name)
        status_items.append(projected)
    return {
        "projection_version": LANGSMITH_LLM_SEMANTIC_PROJECTION_VERSION,
        "request_intent": _project_intent_summary(_mapping(value.get("request_intent"))),
        "completion_condition_count": _completion_condition_count(value.get("request_intent")),
        "selected_evidence_count": _count(value.get("selected_evidence")),
        "source_statuses": {"count": len(statuses), "items": status_items},
        "budget_state": _safe_number_mapping(value.get("budget_state")),
        "temporal_constraint_shapes": _project_query_constraints(value.get("temporal_constraints")),
        "read_result_summary_count": len(read_result_summaries),
        "has_next_page_count": _true_field_count(
            read_result_summaries,
            field="has_next_page",
        ),
        "exhausted_count": _true_field_count(
            read_result_summaries,
            field="exhausted",
        ),
        "result_count_total": _nonnegative_integer_field_total(
            read_result_summaries,
            field="result_count",
        ),
        "has_confirmation_response": _present(value.get("confirmation_response")),
    }


def _completion_condition_count(value: object) -> int:
    intent = _mapping(value)
    return 0 if intent is None else _count(intent.get("completion_conditions"))


def _true_field_count(values: Sequence[object], *, field: str) -> int:
    return sum(
        1
        for raw_item in values
        if (item := _mapping(raw_item)) is not None and item.get(field) is True
    )


def _nonnegative_integer_field_total(values: Sequence[object], *, field: str) -> int:
    total = 0
    for raw_item in values:
        item = _mapping(raw_item)
        if item is None:
            continue
        count = item.get(field)
        if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
            total += count
    return total


def _project_sufficiency_output(value: Mapping[object, object]) -> dict[str, object]:
    issues = _sequence(value.get("issues"))
    issue_items: list[dict[str, object]] = []
    for raw_item in issues[:_MAX_COLLECTION_ITEMS]:
        item = _mapping(raw_item)
        if item is None:
            continue
        projected: dict[str, object] = {
            "required": bool(item.get("required")),
            "safety_critical": bool(item.get("safety_critical")),
            "reason_codes": _safe_values(item.get("reason_codes")),
        }
        for name in ("issue_type", "resolution_source"):
            _copy_safe_scalar(item, projected, name)
        field = _safe_field_identifier(item.get("slot"))
        if field is not None:
            projected["field"] = field
        issue_items.append(projected)
    result: dict[str, object] = {
        "projection_version": LANGSMITH_LLM_SEMANTIC_PROJECTION_VERSION,
        "issues": {"count": len(issues), "items": issue_items},
    }
    _copy_safe_scalar(value, result, "status")
    return result


def _project_compose_answer_input(value: Mapping[object, object]) -> dict[str, object]:
    outline = _mapping(value.get("answer_outline"))
    return {
        "projection_version": LANGSMITH_LLM_SEMANTIC_PROJECTION_VERSION,
        "request_intent": _project_intent_summary(_mapping(value.get("request_intent"))),
        "evidence_count": _count(value.get("evidence")),
        "outline_evidence_count": _count(None if outline is None else outline.get("evidence_refs")),
        "temporal_constraint_shapes": _project_query_constraints(value.get("temporal_constraints")),
        "collection_result_count": _count(value.get("collection_results")),
        "missing_information_count": _count(value.get("missing_information")),
        "has_confirmation_response": _present(value.get("confirmation_response")),
    }


def _project_compose_answer_output(value: Mapping[object, object]) -> dict[str, object]:
    answer = value.get("answer")
    return {
        "projection_version": LANGSMITH_LLM_SEMANTIC_PROJECTION_VERSION,
        "has_answer": isinstance(answer, str) and bool(answer.strip()),
        "answer_char_count": len(answer) if isinstance(answer, str) else 0,
        "evidence_ref_count": _count(value.get("evidence_refs")),
    }


def _project_intent_summary(value: Mapping[object, object] | None) -> dict[str, object]:
    if value is None:
        return {
            "requested_effect_hints": [],
            "requested_resource_hints": [],
            "source_reads": {"count": 0, "items": []},
            "outputs": {"count": 0, "items": []},
        }
    responsibilities = _mapping(value.get("resource_responsibilities"))
    return {
        "requested_effect_hints": _safe_values(value.get("requested_effect_hints")),
        "requested_resource_hints": _safe_values(value.get("requested_resource_hints")),
        "source_reads": _project_source_reads(
            None if responsibilities is None else responsibilities.get("source_reads")
        ),
        "outputs": _project_outputs(
            None if responsibilities is None else responsibilities.get("outputs")
        ),
    }


def _safe_number_mapping(value: object) -> dict[str, object]:
    mapping = _mapping(value)
    if mapping is None:
        return {}
    return {
        key: item
        for key, item in mapping.items()
        if isinstance(key, str)
        and key in {"additional_rounds_used", "additional_rounds_remaining"}
        and isinstance(item, int)
        and not isinstance(item, bool)
        and item >= 0
    }


def _safe_field_identifier(value: object) -> str | None:
    return value if isinstance(value, str) and _SAFE_FIELD_IDENTIFIER.fullmatch(value) else None


def _project_source_reads(value: object) -> dict[str, object]:
    sequence = _sequence(value)
    items: list[dict[str, object]] = []
    for raw_item in sequence[:_MAX_COLLECTION_ITEMS]:
        item = _mapping(raw_item)
        if item is None:
            continue
        projected: dict[str, object] = {
            "required_information_count": _count(item.get("required_information"))
        }
        for name in ("resource_type", "target_scope"):
            _copy_safe_scalar(item, projected, name)
        items.append(projected)
    return {"count": len(sequence), "items": items}


def _project_outputs(value: object) -> dict[str, object]:
    sequence = _sequence(value)
    items: list[dict[str, object]] = []
    for raw_item in sequence[:_MAX_COLLECTION_ITEMS]:
        item = _mapping(raw_item)
        if item is None:
            continue
        projected: dict[str, object] = {}
        for name in ("resource_type", "effect"):
            _copy_safe_scalar(item, projected, name)
        items.append(projected)
    return {"count": len(sequence), "items": items}


def _project_goal_constraints(value: object) -> dict[str, object]:
    mapping = _mapping(value)
    if mapping is not None:
        items: list[dict[str, object]] = []
        kind_by_field = {
            "search_terms": "USER_REQUIREMENT",
            "business_concepts": "USER_REQUIREMENT",
            "person": "PERSON",
            "sender": "PERSON",
            "recipient": "PERSON",
            "subject": "RESOURCE",
            "period": "DATE",
            "status": "SCOPE",
            "coverage_requirement": "SCOPE",
        }
        for field, kind in kind_by_field.items():
            raw_values = mapping.get(field)
            if field == "coverage_requirement" and raw_values == "NOT_COLLECTION":
                continue
            values = (
                [raw_values]
                if field == "coverage_requirement" and isinstance(raw_values, str)
                else _sequence(raw_values)
            )
            if not values:
                continue
            projected: dict[str, object] = {"kind": kind, "field": field}
            if field == "status":
                projected["status_values"] = [
                    status
                    for item in values
                    if (item_mapping := _mapping(item)) is not None
                    if (status := _safe_string(item_mapping.get("value"))) is not None
                ][:_MAX_COLLECTION_ITEMS]
            elif field == "coverage_requirement":
                projected["coverage_requirement"] = _safe_values(values)
            items.append(projected)
        for raw_item in _sequence(mapping.get("additional_constraints")):
            item = _mapping(raw_item)
            if item is None:
                continue
            projected = {}
            for name in ("kind", "field"):
                _copy_safe_scalar(item, projected, name)
            items.append(projected)
        return {"count": len(items), "items": items[:_MAX_COLLECTION_ITEMS]}

    sequence = _sequence(value)
    constraint_items: list[dict[str, object]] = []
    for raw_item in sequence[:_MAX_COLLECTION_ITEMS]:
        item = _mapping(raw_item)
        if item is None:
            continue
        projected_constraint: dict[str, object] = {}
        for name in ("kind", "field"):
            _copy_safe_scalar(item, projected_constraint, name)
        if item.get("field") == "status":
            projected_constraint["status_values"] = _safe_values(item.get("value"))
        elif item.get("field") == "coverage_requirement":
            value = item.get("value")
            projected_constraint["coverage_requirement"] = _safe_values(
                [value] if isinstance(value, str) else value
            )
        constraint_items.append(projected_constraint)
    return {"count": len(sequence), "items": constraint_items}


def _project_query_constraints(value: object) -> dict[str, object]:
    mapping = _mapping(value)
    sequence = list(mapping.values()) if mapping is not None else _sequence(value)
    items: list[dict[str, object]] = []
    for raw_item in sequence[:_MAX_COLLECTION_ITEMS]:
        item = _mapping(raw_item)
        if item is None:
            continue
        projected: dict[str, object] = {}
        kind = _copy_safe_scalar(item, projected, "kind")
        if kind == "KEYWORD":
            _copy_safe_scalar(item, projected, "match_mode")
        elif kind == "TEMPORAL_RANGE":
            _copy_safe_scalar(item, projected, "axis")
        elif kind == "PARTICIPANT":
            _copy_safe_scalar(item, projected, "match_mode")
            roles = []
            for participant in _sequence(item.get("participants")):
                participant_mapping = _mapping(participant)
                if participant_mapping is not None:
                    role = _safe_string(participant_mapping.get("role"))
                    if role is not None:
                        roles.append(role)
            projected["participant_roles"] = roles[:_MAX_COLLECTION_ITEMS]
        elif kind == "STATUS_SCOPE":
            projected["status_values"] = _safe_values(item.get("values"))
        elif kind == "CONCEPT":
            projected["manifestation_count"] = _count(item.get("manifestations"))
        items.append(projected)
    return {"count": len(sequence), "items": items}


def _source_reads(goal: Mapping[object, object] | None) -> object:
    if goal is None:
        return None
    responsibilities = _mapping(goal.get("resource_responsibilities"))
    return None if responsibilities is None else responsibilities.get("source_reads")


def _prompt_mapping(value: object) -> Mapping[object, object] | None:
    mapping = _mapping(value)
    if mapping is None:
        return None
    base = _mapping(mapping.get("base_projection"))
    return base if base is not None else mapping


def _copy_safe_scalar(
    source: Mapping[object, object], target: dict[str, object], name: str
) -> str | None:
    value = _safe_string(source.get(name))
    if value is not None:
        target[name] = value
    return value


def _safe_values(value: object) -> list[str]:
    sequence = [value] if isinstance(value, (str, Enum)) else _sequence(value)
    return [
        safe
        for item in sequence[:_MAX_COLLECTION_ITEMS]
        if (safe := _safe_string(item)) is not None
    ]


def _safe_field_values(value: object) -> dict[str, object]:
    sequence = _sequence(value)
    safe = [
        item
        for item in sequence[:_MAX_COLLECTION_ITEMS]
        if isinstance(item, str) and _SAFE_FIELD_IDENTIFIER.fullmatch(item)
    ]
    result: dict[str, object] = {"count": len(sequence)}
    if safe:
        result["values"] = safe
    return result


def _sanitize_mapping(value: Mapping[object, object], *, depth: int) -> dict[str, object]:
    if depth > _MAX_DEPTH:
        return {}
    result: dict[str, object] = {}
    for raw_key, raw_value in list(value.items())[: _MAX_COLLECTION_ITEMS * 2]:
        if not isinstance(raw_key, str) or raw_key not in _ALLOWED_PROJECTION_KEYS:
            continue
        sanitized = _sanitize_value(raw_value, depth=depth + 1)
        if sanitized is not None:
            result[raw_key] = sanitized
    return result


def _sanitize_value(value: object, *, depth: int) -> object | None:
    if depth > _MAX_DEPTH:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return max(0, value)
    if isinstance(value, float) and math.isfinite(value):
        return max(0.0, value)
    safe = _safe_string(value)
    if safe is not None:
        return safe
    mapping = _mapping(value)
    if mapping is not None:
        return _sanitize_mapping(mapping, depth=depth)
    if _is_sequence(value):
        result = []
        for item in value[:_MAX_COLLECTION_ITEMS]:
            sanitized = _sanitize_value(item, depth=depth + 1)
            if sanitized is not None:
                result.append(sanitized)
        return result
    return None


def _bounded(value: dict[str, object]) -> dict[str, object]:
    return sanitize_llm_semantic_projection(value) or _unavailable()


def _unavailable() -> dict[str, object]:
    return {
        "projection_version": LANGSMITH_LLM_SEMANTIC_PROJECTION_VERSION,
        "projection_status": "UNAVAILABLE",
    }


def _mapping(value: object) -> Mapping[object, object] | None:
    return value if isinstance(value, Mapping) else None


def _sequence(value: object) -> list[object]:
    return list(value) if _is_sequence(value) else []


def _count(value: object) -> int:
    if isinstance(value, Mapping):
        return len(value)
    if _is_sequence(value):
        return len(value)
    return 0


def _present(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (Mapping, Sequence)):
        return bool(value)
    return True


def _safe_string(value: object) -> str | None:
    if isinstance(value, Enum):
        value = value.value
    return value if isinstance(value, str) and _SAFE_VALUE.fullmatch(value) else None


def _is_sequence(value: object) -> TypeGuard[Sequence[object]]:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


__all__ = [
    "LANGSMITH_LLM_SEMANTIC_PROJECTION_VERSION",
    "project_llm_semantic_input",
    "project_llm_semantic_output",
    "sanitize_llm_semantic_projection",
]
