"""Canonical Retrieval semantic operation: plan_query."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.retrieval.build_query import (
    RouteConstraintPolicy,
    bind_required_container_constraints,
    build_query,
    followup_planner_projection,
)
from google_work_agent.application.agents.retrieval.contracts.query_attempt import (
    QueryAttemptV1,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    PLANNER_CONCEPT_MANIFESTATION_LIMIT,
    RetrievalConstraintKindV1,
    RetrievalOperationV2,
    RetrievalQueryPlanV2,
    RetrievalV2ValidationError,
    SourceFetchPlanV1,
    route_operation_tool_id,
    status_scope_values,
    validate_retrieval_query_plan_v2,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan_schema import (
    bind_retrieval_query_plan_output_schema,
)
from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    PersonCandidateV1,
)
from google_work_agent.application.agents.retrieval.plan_candidate_detail import (
    plan_candidate_detail,
)
from google_work_agent.application.agents.retrieval.plan_query_expansion import plan_query_expansion
from google_work_agent.application.agents.retrieval.resolve_gmail_planner_constraint_kinds import (
    resolve_gmail_planner_constraint_kinds,
)
from google_work_agent.application.agents.retrieval.resolve_gmail_query_periods import (
    resolve_gmail_query_periods,
)
from google_work_agent.application.agents.retrieval.resolve_request_participants import (
    resolve_request_participants,
)
from google_work_agent.application.agents.retrieval.resolve_requested_gmail_concepts import (
    resolve_requested_gmail_concepts,
)
from google_work_agent.application.agents.retrieval.select_followup_routes import (
    select_followup_routes,
)
from google_work_agent.application.agents.tool_routing.bind_registry_candidates import (
    coarse_resource_category,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
    ToolRoutePlanV2,
)
from google_work_agent.application.prompt_runtime.contracts.failure_record import (
    build_failure_record_v1,
)
from google_work_agent.application.use_cases.run.guard_run_budget import (
    BudgetDecision,
    RunBudgetV2,
    approve_semantic_revision,
    build_semantic_failure_signature_v1,
)
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort
from google_work_agent.ports.system.contracts.workflow_handoff import RequestedModeV1


def exact_resource_detail_plan(
    *,
    frozen_routes: Sequence[InputToolRouteV1],
    validated_resource_refs: Mapping[str, Collection[str]] | None,
    is_followup: bool,
) -> RetrievalQueryPlanV2 | None:
    """Materialize the one initial exact-resource read with no semantic choice left."""
    if is_followup or len(frozen_routes) != 1:
        return None
    route = frozen_routes[0]
    exact_reason = next(
        (
            reason
            for reason in route["reason_codes"]
            if reason in {"RESOURCE_SELECTED", "EXPLICIT_RESOURCE_ID"}
        ),
        None,
    )
    if exact_reason is None:
        return None
    if route_operation_tool_id(route, "DETAIL_FETCH") is None:
        return None
    resource_refs = tuple((validated_resource_refs or {}).get(route["route_id"], ()))
    if len(resource_refs) != 1:
        return None
    resource_ref = resource_refs[0]
    if not resource_ref.startswith(f"{route['resource_type'].lower()}:"):
        raise RetrievalV2ValidationError(
            "exact-resource ref does not match its frozen route",
            reason_code="RETRIEVAL_ROUTE_SCOPE_VIOLATION",
            affected_field_paths=("$.validated_resource_refs",),
        )
    return {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": route["route_id"],
                "operation": "DETAIL_FETCH",
                "reason_codes": [exact_reason],
                "search_spec": None,
                "detail_candidate_ref": resource_ref,
            }
        ],
    }


def deterministic_initial_query_plan(
    *,
    prompt_input: Mapping[str, object],
    frozen_routes: Sequence[InputToolRouteV1],
    route_policies: Mapping[str, RouteConstraintPolicy],
    validated_resource_refs: Mapping[str, Collection[str]] | None,
    validated_container_refs: Mapping[str, Collection[str]] | None,
    timezone: str | None = None,
) -> RetrievalQueryPlanV2 | None:
    """Materialize initial reads whose meaning is fully fixed by validated state."""
    exact_detail = exact_resource_detail_plan(
        frozen_routes=frozen_routes,
        validated_resource_refs=validated_resource_refs,
        is_followup="current_round_no" in prompt_input,
    )
    if exact_detail is not None:
        return exact_detail
    draft_source_plan = _exact_gmail_draft_source_plan(
        prompt_input=prompt_input,
        frozen_routes=frozen_routes,
        route_policies=route_policies,
        is_followup="current_round_no" in prompt_input,
    )
    if draft_source_plan is not None:
        return draft_source_plan
    calendar_plan = _exact_calendar_conflict_check_plan(
        prompt_input=prompt_input,
        frozen_routes=frozen_routes,
        route_policies=route_policies,
        validated_container_refs=validated_container_refs,
        is_followup="current_round_no" in prompt_input,
        timezone=timezone,
    )
    if calendar_plan is not None:
        return calendar_plan
    return _exact_task_duplicate_check_plan(
        prompt_input=prompt_input,
        frozen_routes=frozen_routes,
        route_policies=route_policies,
        validated_container_refs=validated_container_refs,
        is_followup="current_round_no" in prompt_input,
    )


def _exact_gmail_draft_source_plan(
    *,
    prompt_input: Mapping[str, object],
    frozen_routes: Sequence[InputToolRouteV1],
    route_policies: Mapping[str, RouteConstraintPolicy],
    is_followup: bool,
) -> RetrievalQueryPlanV2 | None:
    """Search an existing Draft by the one user-bound lookup literal before editing it."""
    if is_followup or len(frozen_routes) != 1:
        return None
    route = frozen_routes[0]
    if route["resource_type"] != "GMAIL_DRAFT" or not route["required"]:
        return None
    request_intent = prompt_input.get("request_intent")
    if not isinstance(request_intent, Mapping):
        return None
    effects = _string_collection(request_intent.get("requested_effect_hints"))
    if "UPDATE" not in effects or not effects.issubset({"READ", "UPDATE"}):
        return None
    lookup_literal = _one_user_bound_search_literal(request_intent.get("constraints"))
    policy = route_policies.get(route["route_id"])
    if (
        lookup_literal is None
        or policy is None
        or not {"KEYWORD", "STATUS_SCOPE"}.issubset(policy.supported_kinds)
        or route_operation_tool_id(route, "SEARCH") is None
    ):
        return None
    return {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": route["route_id"],
                "operation": "SEARCH",
                "reason_codes": ["EXACT_DRAFT_SOURCE_LOOKUP"],
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": [
                        {"kind": "KEYWORD", "terms": [lookup_literal], "match_mode": "PHRASE"},
                        {"kind": "STATUS_SCOPE", "values": ["DRAFT"]},
                    ],
                },
                "detail_candidate_ref": None,
            }
        ],
    }


def _one_user_bound_search_literal(value: object) -> str | None:
    if not isinstance(value, list):
        return None
    literals: list[str] = []
    for constraint in value:
        if (
            not isinstance(constraint, Mapping)
            or constraint.get("kind") != "USER_REQUIREMENT"
            or constraint.get("field") != "search_terms"
        ):
            continue
        provenance = constraint.get("provenance")
        if not isinstance(provenance, Mapping) or provenance.get("source") != "USER_REQUEST":
            continue
        raw = constraint.get("value")
        terms = raw if isinstance(raw, list) else [raw]
        if not all(isinstance(term, str) and term.strip() for term in terms):
            return None
        literals.extend(term.strip() for term in cast(list[str], terms))
    unique = tuple(dict.fromkeys(literals))
    return unique[0] if len(unique) == 1 else None


def deterministic_query_plan(
    *,
    prompt_input: Mapping[str, object],
    frozen_routes: Sequence[InputToolRouteV1],
    route_policies: Mapping[str, RouteConstraintPolicy],
    validated_resource_refs: Mapping[str, Collection[str]] | None,
    validated_container_refs: Mapping[str, Collection[str]] | None,
    timezone: str | None = None,
    detail_candidate_refs: Collection[str] = (),
    attempted_detail_candidate_refs: Collection[str] = (),
    person_candidates: Sequence[PersonCandidateV1] = (),
    selected_person_identities: Mapping[str, str] | None = None,
) -> RetrievalQueryPlanV2 | None:
    """Project deterministic initial and candidate-detail continuations."""

    candidate_detail = plan_candidate_detail(
        prompt_input=prompt_input,
        frozen_routes=frozen_routes,
        detail_candidate_refs=detail_candidate_refs,
        attempted_detail_candidate_refs=attempted_detail_candidate_refs,
    )
    if candidate_detail is not None:
        return candidate_detail
    followup = plan_query_expansion(
        prompt_input=prompt_input,
        frozen_routes=frozen_routes,
        person_candidates=person_candidates,
        selected_person_identities=selected_person_identities,
    )
    if followup is not None:
        return followup
    return deterministic_initial_query_plan(
        prompt_input=prompt_input,
        frozen_routes=frozen_routes,
        route_policies=route_policies,
        validated_resource_refs=validated_resource_refs,
        validated_container_refs=validated_container_refs,
        timezone=timezone,
    )


def _exact_calendar_conflict_check_plan(
    *,
    prompt_input: Mapping[str, object],
    frozen_routes: Sequence[InputToolRouteV1],
    route_policies: Mapping[str, RouteConstraintPolicy],
    validated_container_refs: Mapping[str, Collection[str]] | None,
    is_followup: bool,
    timezone: str | None,
) -> RetrievalQueryPlanV2 | None:
    """Build the policy-required Calendar pre-read when no query choice remains."""
    if is_followup or not frozen_routes:
        return None
    if {route["resource_type"] for route in frozen_routes} != {
        "CALENDAR",
        "CALENDAR_EVENT",
        "CALENDAR_FREEBUSY",
    }:
        return None
    if any(
        not route["required"] or "POLICY_CALENDAR_CONFLICT_CHECK" not in route["reason_codes"]
        for route in frozen_routes
    ):
        return None

    request_intent = prompt_input.get("request_intent")
    if not isinstance(request_intent, Mapping):
        return None
    if "CREATE" not in _string_collection(request_intent.get("requested_effect_hints")):
        return None
    if "CALENDAR_EVENT" not in _string_collection(request_intent.get("requested_resource_hints")):
        return None
    temporal = _exact_calendar_temporal_range(
        request_intent.get("constraints"),
        default_timezone=timezone,
    )
    if temporal is None:
        return None

    route_queries: list[dict[str, object]] = []
    for route in frozen_routes:
        route_id = route["route_id"]
        policy = route_policies.get(route_id)
        container_refs = tuple((validated_container_refs or {}).get(route_id, ()))
        if (
            policy is None
            or "CONTAINER_REF" not in policy.supported_kinds
            or "TEMPORAL_RANGE" not in policy.supported_kinds
            or len(container_refs) != 1
        ):
            return None
        operation = "FREEBUSY" if route["resource_type"] == "CALENDAR_FREEBUSY" else "SEARCH"
        axis = "AVAILABILITY_WINDOW" if operation == "FREEBUSY" else "EVENT_TIME"
        route_queries.append(
            {
                "route_id": route_id,
                "operation": operation,
                "reason_codes": ["POLICY_CALENDAR_CONFLICT_CHECK"],
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": [
                        {"kind": "CONTAINER_REF", "container_refs": [container_refs[0]]},
                        {"kind": "TEMPORAL_RANGE", "axis": axis, **temporal},
                    ],
                },
                "detail_candidate_ref": None,
            }
        )
    return cast(
        RetrievalQueryPlanV2,
        {
            "schema_version": 2,
            "route_queries": route_queries,
        },
    )


def _exact_task_duplicate_check_plan(
    *,
    prompt_input: Mapping[str, object],
    frozen_routes: Sequence[InputToolRouteV1],
    route_policies: Mapping[str, RouteConstraintPolicy],
    validated_container_refs: Mapping[str, Collection[str]] | None,
    is_followup: bool,
) -> RetrievalQueryPlanV2 | None:
    """Build the policy-required Task duplicate pre-read from the bound list."""
    if is_followup or not frozen_routes:
        return None
    if {route["resource_type"] for route in frozen_routes} != {"TASK", "TASK_LIST"}:
        return None
    if any(
        not route["required"] or "POLICY_TASK_DUPLICATE_CHECK" not in route["reason_codes"]
        for route in frozen_routes
    ):
        return None
    request_intent = prompt_input.get("request_intent")
    if not isinstance(request_intent, Mapping):
        return None
    requested_effects = _string_collection(request_intent.get("requested_effect_hints"))
    requested_resources = _string_collection(request_intent.get("requested_resource_hints"))
    if (
        requested_effects not in {frozenset({"CREATE"}), frozenset({"READ", "CREATE"})}
        or "TASK" not in requested_resources
        or not requested_resources.issubset({"TASK", "TASK_LIST"})
        or _exact_task_title(request_intent.get("constraints")) is None
    ):
        return None

    route_queries: list[dict[str, object]] = []
    for route in frozen_routes:
        route_id = route["route_id"]
        policy = route_policies.get(route_id)
        container_refs = tuple((validated_container_refs or {}).get(route_id, ()))
        if (
            policy is None
            or "CONTAINER_REF" not in policy.supported_kinds
            or len(container_refs) != 1
        ):
            return None
        route_queries.append(
            {
                "route_id": route_id,
                "operation": "SEARCH",
                "reason_codes": ["POLICY_TASK_DUPLICATE_CHECK"],
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": [
                        {"kind": "CONTAINER_REF", "container_refs": [container_refs[0]]}
                    ],
                },
                "detail_candidate_ref": None,
            }
        )
    return cast(
        RetrievalQueryPlanV2,
        {
            "schema_version": 2,
            "route_queries": route_queries,
        },
    )


def _exact_task_title(value: object) -> str | None:
    if not isinstance(value, list):
        return None
    title_constraints = [
        constraint
        for constraint in value
        if isinstance(constraint, Mapping)
        and constraint.get("kind") == "RESOURCE"
        and constraint.get("field") == "title"
    ]
    if len(title_constraints) != 1:
        return None
    constraint = title_constraints[0]
    title = constraint.get("value")
    if not isinstance(title, str) or not title:
        return None
    return title


def _string_collection(value: object) -> frozenset[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return frozenset()
    return frozenset(value)


def _exact_calendar_temporal_range(
    value: object,
    *,
    default_timezone: str | None,
) -> dict[str, str] | None:
    if not isinstance(value, list):
        return None
    values: dict[str, str] = {}
    for item in value:
        if not isinstance(item, Mapping) or item.get("kind") not in {"DATE", "TIME"}:
            continue
        field = item.get("field")
        item_value = item.get("value")
        if field in {"date", "start_time", "end_time", "timezone"} and isinstance(item_value, str):
            if field in values:
                return None
            values[field] = item_value
    if not {"start_time", "end_time"}.issubset(values):
        return None
    timezone_name = values.get("timezone", default_timezone)
    if timezone_name is None:
        return None
    try:
        timezone = ZoneInfo(timezone_name)
        start = _calendar_local_datetime(values["start_time"], values.get("date"))
        end = _calendar_local_datetime(values["end_time"], values.get("date"))
        start_local = (
            start.replace(tzinfo=timezone) if start.tzinfo is None else start.astimezone(timezone)
        )
        end_local = end.replace(tzinfo=timezone) if end.tzinfo is None else end.astimezone(timezone)
    except (ValueError, ZoneInfoNotFoundError):
        return None
    if end_local <= start_local:
        return None
    return {
        "start_local": start_local.replace(tzinfo=None).isoformat(),
        "end_local": end_local.replace(tzinfo=None).isoformat(),
        "timezone": timezone_name,
    }


def _calendar_local_datetime(value: str, date_value: str | None) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        if date_value is None:
            raise
        return datetime.combine(date.fromisoformat(date_value), time.fromisoformat(value))


def plan_query(
    *,
    llm_runtime: StructuredInferencePort,
    prompt_ref: PromptReference,
    revision_prompt_ref: PromptReference,
    output_schema: OutputSchemaDefinition,
    prompt_input: dict[str, object],
    requested_mode: RequestedModeV1,
    frozen_routes: Sequence[InputToolRouteV1],
    route_policies: Mapping[str, RouteConstraintPolicy],
    retry_budget: RunBudgetV2,
    validated_resource_refs: Mapping[str, Collection[str]] | None = None,
    validated_container_refs: Mapping[str, Collection[str]] | None = None,
    detail_candidate_refs: Collection[str] = (),
    attempted_detail_candidate_refs: Collection[str] = (),
    now_ms: int | None = None,
    timezone: str | None = None,
    person_candidates: Sequence[PersonCandidateV1] = (),
    selected_person_identities: Mapping[str, str] | None = None,
    prior_plans: Mapping[str, SourceFetchPlanV1] | None = None,
    prior_read_result_handles: Mapping[str, str] | None = None,
    read_result_summaries: Sequence[Mapping[str, object]] | None = None,
) -> tuple[RetrievalQueryPlanV2, RunBudgetV2, bool]:
    """Plan provider-neutral retrieval intent against already-frozen input routes."""
    for route_id, policy in route_policies.items():
        if (
            "CONTAINER_REF" in policy.required_kinds
            and len(set((validated_container_refs or {}).get(route_id, ()))) != 1
        ):
            raise RetrievalV2ValidationError(f"route {route_id} requires one validated container")
    supported_kinds = _applicable_constraint_kinds(
        route_policies,
        validated_resource_refs=validated_resource_refs,
        validated_container_refs=validated_container_refs,
    )
    is_followup = "current_round_no" in prompt_input
    meaningful_kinds = resolve_gmail_planner_constraint_kinds(prompt_input)
    if meaningful_kinds is not None:
        supported_kinds = {
            route["route_id"]: (
                frozenset(supported_kinds[route["route_id"]]).intersection(
                    meaningful_kinds
                    | (
                        {"CONCEPT"}
                        if is_followup
                        and "CONCEPT" in route_policies[route["route_id"]].supported_kinds
                        else set()
                    )
                )
                | route_policies[route["route_id"]].required_kinds
                if route["resource_type"] in {"GMAIL_THREAD", "GMAIL_MESSAGE"}
                else supported_kinds[route["route_id"]]
            )
            for route in frozen_routes
        }
    concepts_by_route = resolve_requested_gmail_concepts(prompt_input, frozen_routes)
    planner_kinds: dict[str, Collection[RetrievalConstraintKindV1]] = dict(supported_kinds)
    next_page_route_ids = _next_page_route_ids(prompt_input)
    route_operations = _route_operations(
        frozen_routes,
        validated_resource_refs=validated_resource_refs,
        detail_candidate_refs=detail_candidate_refs,
        next_page_route_ids=next_page_route_ids,
    )
    route_operations = {
        route_id: tuple(
            operation
            for operation in operations
            if operation not in {"SEARCH", "FREEBUSY"} or supported_kinds.get(route_id)
        )
        for route_id, operations in route_operations.items()
    }
    if not any(route_operations.values()):
        raise RetrievalV2ValidationError(
            "no executable retrieval operation is available for the frozen routes",
            reason_code="QUERY_OPERATION_UNAVAILABLE",
            affected_field_paths=("$.input_routes[].allowed_read_tool_ids",),
        )
    planner_input = _project_route_constraint_policies(
        prompt_input,
        route_policies,
        supported_kinds=planner_kinds,
        route_operations=route_operations,
    )
    bounded_output_schema = bind_retrieval_query_plan_output_schema(
        base_schema=output_schema,
        route_ids=supported_kinds,
        route_operations=route_operations,
        route_status_values={
            route["route_id"]: status_scope_values(route) for route in frozen_routes
        },
        supported_constraint_kinds=planner_kinds,
        validated_resource_refs=validated_resource_refs,
        validated_container_refs=validated_container_refs,
        detail_candidate_refs_by_route=_detail_candidate_refs_by_route(
            frozen_routes,
            detail_candidate_refs,
        ),
        is_followup=is_followup,
        requested_concepts=concepts_by_route,
        next_page_route_ids=next_page_route_ids,
        removable_constraint_kinds=_removable_constraint_kinds_by_route(
            prior_plans=prior_plans,
            route_policies=route_policies,
        ),
        gmail_route_ids={
            route["route_id"]
            for route in frozen_routes
            if route["resource_type"] in {"EMAIL", "GMAIL_THREAD", "GMAIL_MESSAGE", "GMAIL_DRAFT"}
        },
        allowed_participant_identities=resolve_request_participants(prompt_input),
        resolved_temporal_constraints=resolve_gmail_query_periods(
            prompt_input=prompt_input,
            frozen_routes=frozen_routes,
            now_ms=now_ms,
            timezone=timezone,
        ),
    )
    deterministic_plan = deterministic_query_plan(
        prompt_input=prompt_input,
        frozen_routes=frozen_routes,
        route_policies=route_policies,
        validated_resource_refs=validated_resource_refs,
        validated_container_refs=validated_container_refs,
        timezone=timezone,
        detail_candidate_refs=detail_candidate_refs,
        attempted_detail_candidate_refs=attempted_detail_candidate_refs,
        person_candidates=person_candidates,
        selected_person_identities=selected_person_identities,
    )
    if deterministic_plan is not None:
        validated_deterministic = validate_retrieval_query_plan_v2(
            deterministic_plan,
            frozen_routes=frozen_routes,
            supported_constraint_kinds=supported_kinds,
            validated_resource_refs=validated_resource_refs,
            validated_container_refs=validated_container_refs,
            detail_candidate_refs=detail_candidate_refs,
        )
        build_query(
            validated_deterministic,
            frozen_routes=frozen_routes,
            route_policies=route_policies,
            prior_plans=prior_plans,
            prior_read_result_handles=prior_read_result_handles,
            validated_resource_refs=validated_resource_refs,
            validated_container_refs=validated_container_refs,
            detail_candidate_refs=detail_candidate_refs,
            person_candidates=person_candidates,
            selected_person_identities=selected_person_identities,
            read_result_summaries=read_result_summaries,
        )
        return (
            validated_deterministic,
            retry_budget,
            False,
        )
    result = llm_runtime.infer(
        requested_mode,
        prompt_ref,
        planner_input,
        bounded_output_schema,
    )
    try:
        candidate = bind_required_container_constraints(
            result.structured_output,
            route_policies=route_policies,
            validated_container_refs=validated_container_refs,
        )
        validated = validate_retrieval_query_plan_v2(
            candidate,
            frozen_routes=frozen_routes,
            supported_constraint_kinds=supported_kinds,
            validated_resource_refs=validated_resource_refs,
            validated_container_refs=validated_container_refs,
            detail_candidate_refs=detail_candidate_refs,
        )
        validated_round = _validate_query_plan_round(validated, is_followup=is_followup)
        build_query(
            validated_round,
            frozen_routes=frozen_routes,
            route_policies=route_policies,
            prior_plans=prior_plans,
            prior_read_result_handles=prior_read_result_handles,
            validated_resource_refs=validated_resource_refs,
            validated_container_refs=validated_container_refs,
            detail_candidate_refs=detail_candidate_refs,
            person_candidates=person_candidates,
            selected_person_identities=selected_person_identities,
            read_result_summaries=read_result_summaries,
        )
        return (
            validated_round,
            retry_budget,
            True,
        )
    except RetrievalV2ValidationError as error:
        revised_plan, revised_budget = _revise_plan_once(
            llm_runtime=llm_runtime,
            revision_prompt_ref=revision_prompt_ref,
            output_schema=bounded_output_schema,
            prompt_input=planner_input,
            requested_mode=requested_mode,
            frozen_routes=frozen_routes,
            route_policies=route_policies,
            supported_kinds=supported_kinds,
            validated_resource_refs=validated_resource_refs,
            validated_container_refs=validated_container_refs,
            detail_candidate_refs=detail_candidate_refs,
            previous_output=result.structured_output,
            failure_reason_code=error.reason_code,
            affected_field_paths=error.affected_field_paths,
            failure_detail=str(error),
            retry_budget=retry_budget,
            is_followup=is_followup,
            now_ms=now_ms,
            timezone=timezone,
            prior_plans=prior_plans,
            prior_read_result_handles=prior_read_result_handles,
            read_result_summaries=read_result_summaries,
            person_candidates=person_candidates,
            selected_person_identities=selected_person_identities,
        )
    return revised_plan, revised_budget, True


def _validate_query_plan_round(
    plan: RetrievalQueryPlanV2,
    *,
    is_followup: bool,
) -> RetrievalQueryPlanV2:
    """Reject continuation operations before a validated prior read can exist."""
    if not is_followup and any(
        query["operation"] == "NEXT_PAGE" for query in plan["route_queries"]
    ):
        raise RetrievalV2ValidationError(
            "initial retrieval cannot request NEXT_PAGE without a validated prior read result",
            reason_code="QUERY_OPERATION_FIELD_MISMATCH",
            affected_field_paths=("$.route_queries[].operation",),
        )
    expected_mode = "CHANGED" if is_followup else "INITIAL"
    for query in plan["route_queries"]:
        if query["operation"] not in {"SEARCH", "FREEBUSY"}:
            continue
        search_spec = query["search_spec"]
        if search_spec is None or search_spec["mode"] != expected_mode:
            raise RetrievalV2ValidationError(
                f"{'follow-up' if is_followup else 'initial'} search must use {expected_mode}",
                reason_code="QUERY_OPERATION_FIELD_MISMATCH",
                affected_field_paths=("$.route_queries[].search_spec.mode",),
            )
        constraints = (
            search_spec["constraints"]
            if search_spec["mode"] == "INITIAL"
            else search_spec["constraint_delta"]["upsert_constraints"]
        )
        if any(
            item["kind"] == "CONCEPT"
            and len(item["manifestations"]) > PLANNER_CONCEPT_MANIFESTATION_LIMIT
            for item in constraints
        ):
            raise RetrievalV2ValidationError(
                "one search hypothesis allows at most 3 manifestations"
            )
    return plan


def _project_route_constraint_policies(
    prompt_input: Mapping[str, object],
    route_policies: Mapping[str, RouteConstraintPolicy],
    *,
    supported_kinds: Mapping[str, Collection[RetrievalConstraintKindV1]],
    route_operations: Mapping[str, Collection[RetrievalOperationV2]],
) -> dict[str, object]:
    """Expose the existing deterministic route policy to the semantic planner."""

    result = deepcopy(dict(prompt_input))
    if isinstance(result.get("prior_query_attempts"), list):
        result["prior_query_attempts"] = followup_planner_projection(
            current_round_no=0,
            prior_query_attempts=cast(list[QueryAttemptV1], result["prior_query_attempts"]),
            unresolved_sufficiency_issues=[],
            read_result_summaries=[],
        )["prior_query_attempts"]
    routes = result.get("input_routes")
    if not isinstance(routes, list):
        return result
    for route in routes:
        if not isinstance(route, dict):
            continue
        route_id = route.get("route_id")
        if not isinstance(route_id, str):
            continue
        policy = route_policies.get(route_id)
        if policy is None:
            continue
        route["allowed_operations"] = sorted(route_operations.get(route_id, ()))
        route["supported_constraint_kinds"] = sorted(supported_kinds.get(route_id, ()))
        route["required_constraint_kinds"] = sorted(policy.required_kinds)
    return result


def _next_page_route_ids(prompt_input: Mapping[str, object]) -> set[str]:
    return {
        str(summary["route_id"])
        for summary in cast(
            list[Mapping[str, object]], prompt_input.get("read_result_summaries", [])
        )
        if summary.get("has_next_page") is True and summary.get("exhausted") is not True
    }


def _route_operations(
    frozen_routes: Sequence[InputToolRouteV1],
    *,
    validated_resource_refs: Mapping[str, Collection[str]] | None,
    detail_candidate_refs: Collection[str],
    next_page_route_ids: Collection[str],
) -> dict[str, tuple[RetrievalOperationV2, ...]]:
    operations: dict[str, tuple[RetrievalOperationV2, ...]] = {}
    for route in frozen_routes:
        route_id = route["route_id"]
        allowed: list[RetrievalOperationV2] = []
        if route_operation_tool_id(route, "SEARCH") is not None:
            allowed.append("SEARCH")
        if route_operation_tool_id(route, "FREEBUSY") is not None:
            allowed.append("FREEBUSY")
        if route_id in next_page_route_ids and route_operation_tool_id(route, "NEXT_PAGE"):
            allowed.append("NEXT_PAGE")
        has_detail_ref = bool((validated_resource_refs or {}).get(route_id)) or any(
            ref.startswith(f"{route['resource_type'].lower()}:") for ref in detail_candidate_refs
        )
        if has_detail_ref and route_operation_tool_id(route, "DETAIL_FETCH") is not None:
            allowed.append("DETAIL_FETCH")
        operations[route_id] = tuple(allowed)
    return operations


def _detail_candidate_refs_by_route(
    frozen_routes: Sequence[InputToolRouteV1],
    detail_candidate_refs: Collection[str],
) -> dict[str, tuple[str, ...]]:
    return {
        route["route_id"]: tuple(
            ref
            for ref in detail_candidate_refs
            if ref.startswith(f"{route['resource_type'].lower()}:")
        )
        for route in frozen_routes
    }


def _removable_constraint_kinds_by_route(
    *,
    prior_plans: Mapping[str, SourceFetchPlanV1] | None,
    route_policies: Mapping[str, RouteConstraintPolicy],
) -> dict[str, frozenset[RetrievalConstraintKindV1]]:
    return {
        route_id: frozenset(
            {item["kind"] for item in plan["effective_constraints"]}
            - route_policies[route_id].required_kinds
        )
        for route_id, plan in (prior_plans or {}).items()
        if route_id in route_policies
    }


def _applicable_constraint_kinds(
    route_policies: Mapping[str, RouteConstraintPolicy],
    *,
    validated_resource_refs: Mapping[str, Collection[str]] | None,
    validated_container_refs: Mapping[str, Collection[str]] | None,
) -> dict[str, frozenset[RetrievalConstraintKindV1]]:
    """Narrow supported kinds to constraints materializable from current state."""

    result: dict[str, frozenset[RetrievalConstraintKindV1]] = {}
    for route_id, policy in route_policies.items():
        applicable = set(policy.supported_kinds)
        if not (validated_resource_refs or {}).get(route_id):
            applicable.discard("RESOURCE_REF")
        if not (validated_container_refs or {}).get(route_id):
            applicable.discard("CONTAINER_REF")
        result[route_id] = frozenset(applicable)
    return result


def _revise_plan_once(
    *,
    llm_runtime: StructuredInferencePort,
    revision_prompt_ref: PromptReference,
    output_schema: OutputSchemaDefinition,
    prompt_input: dict[str, object],
    requested_mode: RequestedModeV1,
    frozen_routes: Sequence[InputToolRouteV1],
    route_policies: Mapping[str, RouteConstraintPolicy],
    supported_kinds: Mapping[str, frozenset[RetrievalConstraintKindV1]],
    validated_resource_refs: Mapping[str, Collection[str]] | None,
    validated_container_refs: Mapping[str, Collection[str]] | None,
    detail_candidate_refs: Collection[str],
    previous_output: object,
    failure_reason_code: str,
    affected_field_paths: tuple[str, ...],
    failure_detail: str,
    retry_budget: RunBudgetV2,
    is_followup: bool,
    now_ms: int | None,
    timezone: str | None,
    prior_plans: Mapping[str, SourceFetchPlanV1] | None,
    prior_read_result_handles: Mapping[str, str] | None,
    read_result_summaries: Sequence[Mapping[str, object]] | None,
    person_candidates: Sequence[PersonCandidateV1],
    selected_person_identities: Mapping[str, str] | None,
) -> tuple[RetrievalQueryPlanV2, RunBudgetV2]:
    signature = build_semantic_failure_signature_v1(
        node_id="retrieval.plan_query",
        failure_reason_codes=[failure_reason_code],
    )
    decision = approve_semantic_revision(retry_budget, signature=signature)
    if decision["decision"] == BudgetDecision.DENY.value:
        raise RetrievalV2ValidationError(
            "retrieval query plan revision denied: same failure signature already used"
        )
    revision = llm_runtime.infer(
        requested_mode,
        revision_prompt_ref,
        {
            "base_projection": dict(prompt_input),
            "candidate_output": previous_output,
            "failure_record": build_failure_record_v1(
                failure_reason_code=failure_reason_code,
                failure_origin="QUERY_PLANNING",
                detected_by="RUNTIME_DOMAIN_VALIDATOR",
                runtime_disposition="RETRYABLE",
                experiment_disposition="RUN_REVISION",
                affected_field_paths=list(affected_field_paths)
                or [
                    "$.route_queries",
                ],
                failure_context_ids=[failure_detail],
            ),
        },
        output_schema,
    )
    candidate = bind_required_container_constraints(
        revision.structured_output,
        route_policies=route_policies,
        validated_container_refs=validated_container_refs,
    )
    validated = validate_retrieval_query_plan_v2(
        candidate,
        frozen_routes=frozen_routes,
        supported_constraint_kinds=supported_kinds,
        validated_resource_refs=validated_resource_refs,
        validated_container_refs=validated_container_refs,
        detail_candidate_refs=detail_candidate_refs,
    )
    validated_round = _validate_query_plan_round(validated, is_followup=is_followup)
    build_query(
        validated_round,
        frozen_routes=frozen_routes,
        route_policies=route_policies,
        prior_plans=prior_plans,
        prior_read_result_handles=prior_read_result_handles,
        validated_resource_refs=validated_resource_refs,
        validated_container_refs=validated_container_refs,
        detail_candidate_refs=detail_candidate_refs,
        person_candidates=person_candidates,
        selected_person_identities=selected_person_identities,
        read_result_summaries=read_result_summaries,
    )
    return (
        validated_round,
        decision["run_budget"],
    )


# Preserved planner-input construction is owned by this query-planning operation.


@dataclass(frozen=True, slots=True)
class RetrievalBudget:
    max_sources: int = 3
    max_pages_per_source: int = 1
    max_page_size: int = 20
    max_candidates_per_source: int = 20
    max_details_per_source: int = 10

    def as_remaining(self) -> dict[str, int]:
        return {
            "sources": self.max_sources,
            "pages": self.max_sources * self.max_pages_per_source,
            "candidates": self.max_sources * self.max_candidates_per_source,
            "details": self.max_sources * self.max_details_per_source,
        }


DEFAULT_RETRIEVAL_BUDGET = RetrievalBudget()


def has_retrieval_followup_path(
    *,
    request_intent: RequestIntentV2,
    tool_route_plan: ToolRoutePlanV2,
    route_policies: Mapping[str, RouteConstraintPolicy],
    unresolved_sufficiency_issues: Sequence[Mapping[str, object]],
    read_result_summaries: Sequence[Mapping[str, object]],
    query_attempts: Sequence[QueryAttemptV1],
    detail_candidate_refs: Collection[str] = (),
    attempted_detail_candidate_refs: Collection[str] = (),
) -> bool:
    """Return whether the frozen route can produce information not read yet."""

    routes = tool_route_plan["input_plan"]["input_routes"]
    eligible_route_ids = {
        route["route_id"]
        for route in select_followup_routes(
            {
                "unresolved_sufficiency_issues": list(unresolved_sufficiency_issues),
            },
            routes,
        )
    }
    return deterministic_query_plan(
        prompt_input={
            "request_intent": request_intent,
            "current_round_no": max(
                (attempt.get("round_no", 0) for attempt in query_attempts), default=0
            ),
            "prior_query_attempts": list(query_attempts),
            "unresolved_sufficiency_issues": list(unresolved_sufficiency_issues),
            "read_result_summaries": list(read_result_summaries),
        },
        frozen_routes=routes,
        route_policies=route_policies,
        validated_resource_refs=None,
        validated_container_refs=None,
        detail_candidate_refs=detail_candidate_refs,
        attempted_detail_candidate_refs=attempted_detail_candidate_refs,
    ) is not None or any(
        attempt["operation_kind"] == "SEARCH"
        and attempt["route_id"] in eligible_route_ids
        and attempt.get("stop_reason") == "COMPLETE"
        and not any(
            other["route_id"] == attempt["route_id"]
            and other.get("stop_reason") not in {"COMPLETE", None}
            for other in query_attempts
        )
        and sum(
            other["operation_kind"] == "SEARCH" and other["route_id"] == attempt["route_id"]
            for other in query_attempts
        )
        < 3
        for attempt in query_attempts
    )


def initial_retrieval_planner_input(
    *,
    request_intent: RequestIntentV2,
    input_routes: Sequence[InputToolRouteV1],
    retrieval_budget: RetrievalBudget,
    validated_resource_refs: Mapping[str, Sequence[str]] | None = None,
    validated_container_refs: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, object]:
    """Project exactly the initial-round V2 input contract."""
    return {
        "request_intent": request_intent,
        "input_routes": [
            _prompt_route(
                route,
                validated_resource_refs=validated_resource_refs,
                validated_container_refs=validated_container_refs,
            )
            for route in input_routes
        ],
        "retrieval_budget": retrieval_budget.as_remaining(),
    }


def followup_retrieval_planner_input(
    *,
    request_intent: RequestIntentV2,
    input_routes: Sequence[InputToolRouteV1],
    retrieval_budget: RetrievalBudget,
    followup: Mapping[str, object],
    validated_resource_refs: Mapping[str, Sequence[str]] | None = None,
    validated_container_refs: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, object]:
    """Add only the bounded follow-up metadata permitted by the V2 contract."""
    result = initial_retrieval_planner_input(
        request_intent=request_intent,
        input_routes=input_routes,
        retrieval_budget=retrieval_budget,
        validated_resource_refs=validated_resource_refs,
        validated_container_refs=validated_container_refs,
    )
    for field in (
        "current_round_no",
        "prior_query_attempts",
        "unresolved_sufficiency_issues",
        "read_result_summaries",
    ):
        if field not in followup:
            raise ValueError(f"follow-up retrieval planner input is missing {field}")
        result[field] = followup[field]
    return result


def _prompt_route(
    route: InputToolRouteV1,
    *,
    validated_resource_refs: Mapping[str, Sequence[str]] | None = None,
    validated_container_refs: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, object]:
    prompt_route: dict[str, object] = {
        "route_id": route["route_id"],
        "connector_id": route["connector_id"],
        "resource_type": coarse_resource_category(route["resource_type"]),
        "allowed_read_tool_ids": list(route["allowed_read_tool_ids"]),
        "required": route["required"],
        "reason_codes": list(route["reason_codes"]),
    }
    resource_refs = (validated_resource_refs or {}).get(route["route_id"])
    if resource_refs:
        prompt_route["resource_refs"] = list(resource_refs)
    container_refs = (validated_container_refs or {}).get(route["route_id"])
    if container_refs:
        # Pre-Prompt Runtime Closure: the only container refs the LLM is
        # ever shown are already-validated internal refs resolved by
        # deterministic code (see _validated_task_container_refs,
        # context_retrieval.py) -- never a raw provider/task_list_id the
        # model could invent on its own.
        prompt_route["container_refs"] = list(container_refs)
    return prompt_route
