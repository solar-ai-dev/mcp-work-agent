"""Artifact dependency freshness and downstream invalidation for Supervisor routing."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from google_work_agent.adapters.langgraph.main.state import (
    GraphState,
    InputPlanReuseV1,
    WorkflowPhase,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.state_artifact import StateArtifactRefV1
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    ToolRoutePlanV2,
)
from google_work_agent.application.agents.tool_routing.resolve_policy_preconditions import (
    effective_analysis_required,
)


def is_work_analysis_required(*, state: GraphState, plan: ToolRoutePlanV2) -> bool:
    intent = state.get("request_intent")
    if not isinstance(intent, Mapping):
        raise ValueError("request_intent must be an object")
    return effective_analysis_required(
        request_intent=cast(RequestIntentV2, intent),
        tool_route_plan=plan,
    )


def artifact_freshness_violation(phase: WorkflowPhase, state: GraphState) -> str | None:
    if phase in {
        WorkflowPhase.REQUEST_ANALYSIS,
        WorkflowPhase.RECOVERY,
        WorkflowPhase.FINALIZE,
        WorkflowPhase.PREFLIGHT,
    }:
        return None
    intent = state.get("request_intent")
    if not isinstance(intent, Mapping):
        return "REQUEST_INTENT_MISSING"
    plan = state.get("tool_route_plan")
    if phase is WorkflowPhase.TOOL_ROUTING:
        return None
    if not isinstance(plan, Mapping) or not _route_plan_is_fresh(
        plan,
        intent=intent,
        input_plan_reuse=state.get("input_plan_reuse"),
    ):
        return "TOOL_ROUTE_STALE"
    if phase is WorkflowPhase.CONTEXT_RETRIEVAL:
        return None
    input_plan = cast(Mapping[str, object], plan.get("input_plan"))
    retrieval = state.get("retrieval_result")
    has_input_routes = bool(input_plan.get("input_routes"))
    if has_input_routes and (
        not isinstance(retrieval, Mapping)
        or not _depends_on_current_or_reused_intent(
            retrieval,
            intent=intent,
            input_plan_reuse=state.get("input_plan_reuse"),
        )
        or not _depends_on(retrieval, input_plan)
    ):
        return "RETRIEVAL_RESULT_STALE"
    if phase is WorkflowPhase.WORK_ANALYSIS:
        return None
    analysis_required = is_work_analysis_required(
        state=state,
        plan=cast(ToolRoutePlanV2, plan),
    )
    analysis = state.get("work_analysis_result")
    if analysis_required and (
        not isinstance(analysis, Mapping)
        or not _depends_on(analysis, intent)
        or not _depends_on(analysis, cast(Mapping[str, object], plan.get("output_plan")))
        or (has_input_routes and not _depends_on(analysis, cast(Mapping[str, object], retrieval)))
    ):
        return "WORK_ANALYSIS_RESULT_STALE"
    if phase is WorkflowPhase.SOLUTION_PLANNING:
        return None
    planning = state.get("planning_result")
    output_plan = cast(Mapping[str, object], plan.get("output_plan"))
    if not isinstance(planning, Mapping) or not _depends_on(planning, output_plan):
        return "PLANNING_RESULT_STALE"
    if has_input_routes and not _depends_on(planning, cast(Mapping[str, object], retrieval)):
        return "PLANNING_RESULT_STALE"
    if analysis_required and not _depends_on(planning, cast(Mapping[str, object], analysis)):
        return "PLANNING_RESULT_STALE"
    if phase is WorkflowPhase.PLAN_REVIEW:
        return None
    review = state.get("plan_review")
    if not isinstance(review, Mapping) or not _depends_on(review, planning):
        return "PLAN_REVIEW_STALE"
    return None


def invalidate_stale_downstream(*, previous: GraphState, current: GraphState) -> list[str]:
    """Clear unchanged downstream artifacts when an upstream revision changes."""

    request_changed = _artifact_signature(previous.get("request_intent")) != (
        _artifact_signature(current.get("request_intent"))
    )
    reuse_input = request_changed and _can_reuse_input_plan(previous=previous, current=current)
    if reuse_input:
        current["input_plan_reuse"] = _input_plan_reuse_projection(
            previous=previous,
            current=current,
        )
    elif request_changed:
        current["input_plan_reuse"] = None

    dependencies: tuple[tuple[str, tuple[str, ...]], ...] = (
        (
            "request_intent",
            (
                "tool_route_plan",
                "acquisition_result",
                "retrieval_result",
                "work_analysis_result",
                "planning_result",
                "plan_review",
            ),
        ),
        (
            "tool_route_plan",
            (
                "acquisition_result",
                "retrieval_result",
                "work_analysis_result",
                "planning_result",
                "plan_review",
            ),
        ),
        (
            "retrieval_result",
            ("work_analysis_result", "planning_result", "plan_review"),
        ),
        ("work_analysis_result", ("planning_result", "plan_review")),
        ("planning_result", ("plan_review", "approved_plan_id")),
    )
    invalidated: list[str] = []
    for upstream, downstream_fields in dependencies:
        if _artifact_signature(previous.get(upstream)) == _artifact_signature(
            current.get(upstream)
        ):
            continue
        preserved_fields: frozenset[str] = frozenset()
        if upstream == "request_intent" and reuse_input:
            preserved_fields = frozenset(
                {"tool_route_plan", "acquisition_result", "retrieval_result"}
            )
        elif upstream == "tool_route_plan" and _same_input_plan(previous, current):
            preserved_fields = frozenset({"acquisition_result", "retrieval_result"})
        for field in downstream_fields:
            if field in preserved_fields:
                continue
            if field in invalidated:
                continue
            if _artifact_signature(previous.get(field)) != _artifact_signature(current.get(field)):
                continue
            if current.get(field) is not None:
                current[field] = None  # type: ignore[literal-required]
                invalidated.append(field)
    if _artifact_signature(previous.get("tool_route_plan")) != _artifact_signature(
        current.get("tool_route_plan")
    ) and not _same_input_plan(previous, current):
        current["input_plan_reuse"] = None
    return invalidated


def artifact_revision_projection(state: GraphState) -> dict[str, str]:
    projection: dict[str, str] = {}
    for field in (
        "request_intent",
        "tool_route_plan",
        "retrieval_result",
        "work_analysis_result",
        "planning_result",
        "plan_review",
    ):
        signature = _artifact_signature(state.get(field))
        projection[field] = (
            "-"
            if signature is None
            else "+".join(f"{artifact_id}:{revision}" for artifact_id, revision in signature)
        )
    return projection


def _route_plan_is_fresh(
    plan: Mapping[str, object],
    *,
    intent: Mapping[str, object],
    input_plan_reuse: object,
) -> bool:
    input_plan = plan.get("input_plan")
    output_plan = plan.get("output_plan")
    return (
        isinstance(input_plan, Mapping)
        and isinstance(output_plan, Mapping)
        and (
            _depends_on(input_plan, intent)
            or _input_plan_reuse_matches(
                input_plan_reuse,
                input_plan=input_plan,
                current_intent=intent,
            )
        )
        and _depends_on(output_plan, intent)
    )


def input_plan_reuse_is_current(state: Mapping[str, object]) -> bool:
    plan = state.get("tool_route_plan")
    intent = state.get("request_intent")
    return (
        isinstance(plan, Mapping)
        and isinstance(intent, Mapping)
        and isinstance(plan.get("input_plan"), Mapping)
        and _input_plan_reuse_matches(
            state.get("input_plan_reuse"),
            input_plan=cast(Mapping[str, object], plan["input_plan"]),
            current_intent=intent,
        )
    )


def _can_reuse_input_plan(*, previous: GraphState, current: GraphState) -> bool:
    previous_intent = previous.get("request_intent")
    current_intent = current.get("request_intent")
    plan = previous.get("tool_route_plan")
    return (
        isinstance(previous_intent, Mapping)
        and isinstance(current_intent, Mapping)
        and isinstance(plan, Mapping)
        and isinstance(plan.get("input_plan"), Mapping)
        and _request_input_semantics(previous_intent) == _request_input_semantics(current_intent)
        and _request_input_semantics(current_intent) is not None
    )


def _request_input_semantics(intent: Mapping[str, object]) -> object | None:
    responsibilities = intent.get("resource_responsibilities")
    if not isinstance(responsibilities, Mapping):
        return None
    source_reads = responsibilities.get("source_reads")
    constraints = intent.get("constraints")
    if not isinstance(source_reads, list) or not isinstance(constraints, list):
        return None
    return {
        "source_reads": source_reads,
        "constraints": constraints,
    }


def _input_plan_reuse_projection(*, previous: GraphState, current: GraphState) -> InputPlanReuseV1:
    previous_intent = cast(Mapping[str, object], previous["request_intent"])
    current_intent = cast(Mapping[str, object], current["request_intent"])
    plan = cast(Mapping[str, object], previous["tool_route_plan"])
    input_plan = cast(Mapping[str, object], plan["input_plan"])
    return {
        "schema_version": 1,
        "input_plan_ref": _required_artifact_ref(input_plan),
        "prior_request_intent_ref": _required_artifact_ref(previous_intent),
        "current_request_intent_ref": _required_artifact_ref(current_intent),
    }


def _input_plan_reuse_matches(
    value: object,
    *,
    input_plan: Mapping[str, object],
    current_intent: Mapping[str, object],
) -> bool:
    if not isinstance(value, Mapping) or value.get("schema_version") != 1:
        return False
    return value.get("input_plan_ref") == _artifact_ref(input_plan) and value.get(
        "current_request_intent_ref"
    ) == _artifact_ref(current_intent)


def _depends_on_current_or_reused_intent(
    artifact: Mapping[str, object],
    *,
    intent: Mapping[str, object],
    input_plan_reuse: object,
) -> bool:
    if _depends_on(artifact, intent):
        return True
    if not isinstance(input_plan_reuse, Mapping):
        return False
    current_ref = _artifact_ref(intent)
    prior_ref = input_plan_reuse.get("prior_request_intent_ref")
    meta = artifact.get("meta")
    based_on = meta.get("based_on") if isinstance(meta, Mapping) else None
    return (
        input_plan_reuse.get("schema_version") == 1
        and input_plan_reuse.get("current_request_intent_ref") == current_ref
        and isinstance(prior_ref, Mapping)
        and isinstance(based_on, list)
        and prior_ref in based_on
    )


def _same_input_plan(previous: GraphState, current: GraphState) -> bool:
    previous_plan = previous.get("tool_route_plan")
    current_plan = current.get("tool_route_plan")
    if not isinstance(previous_plan, Mapping) or not isinstance(current_plan, Mapping):
        return False
    previous_signature = _artifact_signature(previous_plan.get("input_plan"))
    return previous_signature is not None and previous_signature == _artifact_signature(
        current_plan.get("input_plan")
    )


def _depends_on(artifact: Mapping[str, object], upstream: Mapping[str, object]) -> bool:
    upstream_ref = _artifact_ref(upstream)
    meta = artifact.get("meta")
    based_on = meta.get("based_on") if isinstance(meta, Mapping) else None
    return upstream_ref is not None and isinstance(based_on, list) and upstream_ref in based_on


def _artifact_ref(value: Mapping[str, object]) -> StateArtifactRefV1 | None:
    meta = value.get("meta")
    if not isinstance(meta, Mapping):
        return None
    artifact_id = meta.get("artifact_id")
    revision = meta.get("revision")
    if not isinstance(artifact_id, str) or not isinstance(revision, int):
        return None
    return {"artifact_id": artifact_id, "revision": revision}


def _required_artifact_ref(value: Mapping[str, object]) -> StateArtifactRefV1:
    reference = _artifact_ref(value)
    if reference is None:
        raise ValueError("artifact reuse requires a valid artifact reference")
    return reference


def _artifact_signature(value: object) -> tuple[tuple[str, int], ...] | None:
    if not isinstance(value, Mapping):
        return None
    direct = _artifact_ref(value)
    if direct is not None:
        return ((cast(str, direct["artifact_id"]), cast(int, direct["revision"])),)
    refs = [
        ref
        for key in ("input_plan", "output_plan")
        if isinstance((child := value.get(key)), Mapping)
        and (ref := _artifact_ref(child)) is not None
    ]
    if not refs:
        return None
    return tuple((cast(str, ref["artifact_id"]), cast(int, ref["revision"])) for ref in refs)


__all__ = [
    "artifact_freshness_violation",
    "artifact_revision_projection",
    "input_plan_reuse_is_current",
    "invalidate_stale_downstream",
    "is_work_analysis_required",
]
