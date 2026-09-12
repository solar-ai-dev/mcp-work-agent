"""Build bounded, privacy-safe LangSmith projections from LangGraph payloads."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Final, TypeGuard

LANGSMITH_WORKFLOW_IO_PROJECTION_VERSION: Final = 1
_MAX_PROJECTION_BYTES: Final = 16 * 1024
_MAX_STATE_FIELDS: Final = 64
_MAX_COLLECTION_ITEMS: Final = 12
_SAFE_VALUE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_SAFE_FIELD_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{0,63}")

_TOP_LEVEL_FIELDS = frozenset(
    {
        "schema_version",
        "workflow_phase",
        "graph_profile",
        "graph_version",
        "run_input",
        "entry_mode",
        "request_intent",
        "goal_candidate",
        "ambiguity_candidate",
        "final_intent",
        "io_resource_candidate",
        "registry_candidates",
        "bound_input_routes",
        "bound_output_routes",
        "tool_route_plan",
        "final_route",
        "workflow_signal",
        "request_reconsideration",
        "acquisition_result",
        "query_plan",
        "source_fetch_plans",
        "query_attempts",
        "source_statuses",
        "read_result_handles",
        "segment_handles",
        "rag_candidates",
        "evidence_selection",
        "sufficiency",
        "retrieval_result",
        "final_result",
        "work_analysis_result",
        "final_analysis",
        "planning_result",
        "planning_disposition",
        "plan_review",
        "review_result",
        "review_phase",
        "finalize_intent",
        "terminal_commit_intent",
        "execution_summary",
        "verification_summary",
        "user_interrupt",
        "policy_confirmation_receipts",
        "retry_budget",
        "trace_context",
        "llm_provider_result",
        "input_routes",
        "evidence_refs",
        "evidence_drafts",
        "fact_candidates",
        "entity_relation_candidates",
        "temporal_dependency_candidates",
        "duplicate_conflict_candidates",
        "ambiguity_candidates",
        "retrieval_needs",
        "operational_risk_candidates",
        "route_action_necessities",
        "action_objective_candidates",
        "argument_candidates",
        "dependency_candidates",
        "answer_outline",
        "goal_evidence_result",
        "action_scope_route_result",
        "constraints_policy_result",
        "affected_dimension_recheck",
    }
)

_STRING_FIELDS = frozenset(
    {
        "workflow_phase",
        "graph_profile",
        "graph_version",
        "entry_mode",
        "requested_mode",
        "analysis_requirement",
        "status",
        "coverage",
        "kind",
        "disposition",
        "intent",
        "result_kind",
        "output_mode",
        "effect",
        "operation",
        "operation_kind",
        "mode",
        "match_mode",
        "axis",
        "role",
        "required_for",
        "resolution_source",
        "issue_type",
        "failure_kind",
        "decision",
        "profile",
        "routing_outcome",
        "delivery_certainty",
        "interrupt_kind",
        "resume_kind",
        "origin_target",
        "planning_disposition",
        "review_phase",
        "budget_reason_code",
        "resource_type",
        "connector_id",
        "tool_id",
        "selected_tool_id",
        "tool_schema_version",
        "tool_registry_version",
        "confidence_band",
        "stop_reason",
        "field",
        "missing_information_owner",
        "continuation_status",
        "validation_stage",
        "validation_rule",
        "change_reason_code",
        "query_identity_hash",
        "previous_query_hash",
        "page_state_hash",
        "retrieval_config_version",
        "score_config_version",
        "threshold_config_version",
    }
)

_BOOLEAN_FIELDS = frozenset(
    {
        "requires_confirmation",
        "required",
        "safety_critical",
        "has_next_page",
        "exhausted",
        "is_exhausted",
        "notes_truncated",
        "read_supported",
    }
)

_NUMBER_FIELDS = frozenset(
    {
        "schema_version",
        "revision",
        "round_no",
        "attempt_no",
        "candidate_count",
        "observed_resource_count",
        "retrieval_rounds",
        "source_action_version",
        "expected_run_version",
        "top_score",
        "score_margin",
        "agent_invocation_count",
        "llm_call_count",
        "repair_count",
        "revision_count",
        "llm_calls_used",
        "llm_call_limit",
        "absolute_llm_call_limit",
        "connector_calls_used",
        "max_connector_calls",
        "source_page_calls_used",
        "max_source_page_calls",
        "detail_fetches_used",
        "max_detail_fetches",
        "context_tokens_used",
        "max_context_tokens",
        "retry_attempts_used",
        "max_retry_attempts",
        "planning_revisions_used",
        "review_rechecks_used",
        "additional_retrieval_rounds_used",
    }
)

_SAFE_VALUE_LIST_FIELDS = frozenset(
    {
        "reason_codes",
        "failure_reason_codes",
        "requested_effect_hints",
        "requested_resource_hints",
        "required_resource_types",
        "affected_dimensions",
        "input_resource_types",
        "output_resource_types",
        "output_effects",
        "allowed_read_tool_ids",
        "allowed_operations",
        "supported_constraint_kinds",
        "required_constraint_kinds",
        "write_effects",
    }
)

_STRUCTURED_SEQUENCE_FIELDS = frozenset(
    {
        "selected_resource_refs",
        "constraints",
        "source_reads",
        "outputs",
        "input_routes",
        "output_routes",
        "registry_candidates",
        "bound_input_routes",
        "bound_output_routes",
        "route_queries",
        "source_fetch_plans",
        "query_attempts",
        "source_statuses",
        "issues",
        "actions",
        "blockers",
        "route_issues",
        "evidence_gaps",
        "needs",
        "effective_constraints",
        "normalized_constraints",
    }
)

_COUNT_ONLY_SEQUENCE_FIELDS = frozenset(
    {
        "completion_conditions",
        "required_information",
        "resource_handles",
        "source_summaries",
        "missing_slots",
        "evidence_refs",
        "selected_segment_ids",
        "excluded_segment_ids",
        "source_resource_refs",
        "availability_results",
        "missing_information",
        "person_candidates",
        "selected_person_identities",
        "unresolved_event_dates",
        "task_review_candidates",
        "read_result_handles",
        "segment_handles",
        "rag_candidates",
        "evidence_drafts",
        "fact_candidates",
        "entity_relation_candidates",
        "temporal_dependency_candidates",
        "duplicate_conflict_candidates",
        "ambiguity_candidates",
        "retrieval_needs",
        "operational_risk_candidates",
        "route_action_necessities",
        "action_objective_candidates",
        "argument_candidates",
        "dependency_candidates",
        "policy_confirmation_receipts",
        "affected_action_ids",
        "affected_route_ids",
        "depends_on_action_ids",
        "added_constraints",
        "removed_constraints",
        "options",
        "affected_field_paths",
        "prompt_refs",
        "agent_node_log",
    }
)

_NESTED_MAPPING_FIELDS = frozenset(
    {
        "ambiguity",
        "resource_responsibilities",
        "input_plan",
        "output_plan",
        "search_spec",
        "constraint_delta",
        "query_spec",
        "remaining_budget",
        "meta",
        "confirmation",
        "terminal_message",
    }
)

_PRESENCE_ONLY_FIELDS = frozenset(
    {
        "llm_provider_result",
        "terminal_message",
    }
)


def project_langsmith_workflow_payload(value: object) -> dict[str, object]:
    """Project one callback payload without exporting business or provider content."""

    mapping = _mapping_view(value)
    if mapping is None:
        return {
            "projection_version": LANGSMITH_WORKFLOW_IO_PROJECTION_VERSION,
            "payload_kind": "NON_MAPPING",
        }

    present_fields = sorted(
        key for key in mapping if isinstance(key, str) and key in _TOP_LEVEL_FIELDS
    )
    field_summaries: dict[str, object] = {}
    for field_name in present_fields[:_MAX_STATE_FIELDS]:
        projected = _project_value(field_name, mapping[field_name], depth=0)
        if projected is not None:
            field_summaries[field_name] = projected
    if "run_input" in mapping:
        run_input = _mapping_view(mapping["run_input"])
        if run_input is not None:
            summary = field_summaries.setdefault("run_input", {})
            if isinstance(summary, dict):
                request = run_input.get("user_request")
                summary["has_user_request"] = isinstance(request, str) and bool(request.strip())

    result: dict[str, object] = {
        "projection_version": LANGSMITH_WORKFLOW_IO_PROJECTION_VERSION,
        "state_field_count": len(present_fields),
        "state_fields": present_fields[:_MAX_STATE_FIELDS],
        "fields": field_summaries,
    }
    if len(present_fields) > _MAX_STATE_FIELDS:
        result["state_fields_truncated"] = True
    if len(json.dumps(result, sort_keys=True, separators=(",", ":")).encode("utf-8")) <= (
        _MAX_PROJECTION_BYTES
    ):
        return result
    return {
        "projection_version": LANGSMITH_WORKFLOW_IO_PROJECTION_VERSION,
        "projection_status": "TRUNCATED",
        "state_field_count": len(present_fields),
        "state_fields": present_fields[:_MAX_STATE_FIELDS],
    }


def _project_value(field_name: str, value: object, *, depth: int) -> object | None:
    if value is None:
        return {"value_state": "NULL"}
    if field_name in _PRESENCE_ONLY_FIELDS:
        return {"value_state": "PRESENT"}
    if field_name in _STRING_FIELDS:
        return _safe_string(value)
    if field_name in _BOOLEAN_FIELDS:
        return value if isinstance(value, bool) else None
    if field_name in _NUMBER_FIELDS:
        return _safe_number(value)
    if field_name in _SAFE_VALUE_LIST_FIELDS:
        return _project_safe_value_list(value)
    if field_name == "missing_fields":
        return _project_safe_field_identifier_list(value)
    if field_name in _COUNT_ONLY_SEQUENCE_FIELDS:
        return _collection_count(value)
    if field_name in _STRUCTURED_SEQUENCE_FIELDS:
        return _project_structured_sequence(value, depth=depth)
    if field_name in _NESTED_MAPPING_FIELDS or depth == 0:
        nested = _mapping_view(value)
        if nested is not None:
            return _project_mapping(nested, depth=depth + 1)
        if _is_sequence(value):
            return _collection_count(value)
    return None


def _project_mapping(value: Mapping[object, object], *, depth: int) -> dict[str, object]:
    if depth > 4:
        return {"value_state": "PRESENT"}
    result: dict[str, object] = {}
    for raw_field_name in sorted(value, key=str):
        if not isinstance(raw_field_name, str):
            continue
        projected = _project_value(raw_field_name, value[raw_field_name], depth=depth)
        if projected is not None:
            result[raw_field_name] = projected
    return result or {"value_state": "PRESENT"}


def _project_structured_sequence(value: object, *, depth: int) -> dict[str, object] | None:
    if not _is_sequence(value):
        return None
    sequence = list(value)
    result: dict[str, object] = {"count": len(sequence)}
    items: list[dict[str, object]] = []
    for item in sequence[:_MAX_COLLECTION_ITEMS]:
        mapping = _mapping_view(item)
        if mapping is None:
            continue
        projected = _project_mapping(mapping, depth=depth + 1)
        if projected != {"value_state": "PRESENT"}:
            items.append(projected)
    if items:
        result["items"] = items
    if len(sequence) > _MAX_COLLECTION_ITEMS:
        result["items_truncated"] = True
    return result


def _project_safe_value_list(value: object) -> dict[str, object] | None:
    if not _is_sequence(value):
        return None
    sequence = list(value)
    safe_values = [
        safe_value for item in sequence if (safe_value := _safe_string(item)) is not None
    ]
    return {
        "count": len(sequence),
        "values": safe_values[:_MAX_COLLECTION_ITEMS],
        **({"values_truncated": True} if len(safe_values) > _MAX_COLLECTION_ITEMS else {}),
    }


def _project_safe_field_identifier_list(value: object) -> dict[str, object] | None:
    if not _is_sequence(value):
        return None
    sequence = list(value)
    safe_values = [
        item
        for item in sequence
        if isinstance(item, str) and _SAFE_FIELD_IDENTIFIER.fullmatch(item)
    ]
    result: dict[str, object] = {"count": len(sequence)}
    if safe_values:
        result["values"] = safe_values[:_MAX_COLLECTION_ITEMS]
    if len(safe_values) > _MAX_COLLECTION_ITEMS:
        result["values_truncated"] = True
    return result


def _collection_count(value: object) -> dict[str, int] | None:
    if isinstance(value, Mapping):
        return {"count": len(value)}
    if _is_sequence(value):
        return {"count": len(value)}
    return None


def _mapping_view(value: object) -> Mapping[object, object] | None:
    if isinstance(value, Mapping):
        return value
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: getattr(value, field.name) for field in fields(value)}
    as_dict = getattr(value, "_asdict", None)
    if callable(as_dict):
        candidate = as_dict()
        if isinstance(candidate, Mapping):
            return candidate
    return None


def _safe_string(value: object) -> str | None:
    if isinstance(value, Enum):
        value = value.value
    if not isinstance(value, str) or _SAFE_VALUE.fullmatch(value) is None:
        return None
    return value


def _safe_number(value: object) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _is_sequence(value: object) -> TypeGuard[Sequence[object]]:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


__all__ = [
    "LANGSMITH_WORKFLOW_IO_PROJECTION_VERSION",
    "project_langsmith_workflow_payload",
]
