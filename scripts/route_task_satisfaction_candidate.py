"""Inactive owner-local Task satisfaction map; no Product contract activation.

One synthetic inference chooses satisfaction for the closed frozen Task CREATE
route set. The existing scalar validator and necessity consumer remain owners.
The prototype does not perform READ/WRITE, create Runs, or grant execution rights.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import TypedDict, cast

from google_work_agent.application.agents.planning.project_request_intent_for_work_units import (
    project_request_intent_for_work_units,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV3,
)
from google_work_agent.application.agents.work_analysis.assess_action_necessity import (
    assess_action_necessity,
)
from google_work_agent.application.agents.work_analysis.assess_requested_task_satisfaction import (
    _bound_output_schema,
    _task_candidate_refs,
    _validate_and_materialize,
    not_applicable_task_satisfaction,
)
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_candidates import (
    ActionNecessityAssessmentV1,
    DuplicateConflictAssessmentV1,
)
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import (
    WorkFactV1,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort
from google_work_agent.ports.system.contracts.workflow_handoff import RequestedModeV1


class _RouteContext(TypedDict):
    request_intent: RequestIntentV3
    source_state: dict[str, object]
    work_facts: list[WorkFactV1]
    evidence_refs: set[str]


def assess_task_routes(
    *,
    request_intent: Mapping[str, object],
    output_routes: Sequence[Mapping[str, object]],
    work_facts: Sequence[WorkFactV1],
    evidence: Sequence[Mapping[str, object]],
    source_state: Mapping[str, object],
    allowed_evidence_refs: set[str],
    llm_runtime: StructuredInferencePort,
    prompt_ref: PromptReference,
    requested_mode: RequestedModeV1,
) -> dict[str, DuplicateConflictAssessmentV1]:
    routes = [route for route in output_routes if _is_task_create(route)]
    route_ids = [_route_id(route) for route in routes]
    if len(route_ids) != len(set(route_ids)):
        raise ValueError("Task assessment requires unique non-empty frozen route IDs")
    if not routes:
        return {}
    contexts = {
        _route_id(route): _route_context(
            route=route,
            request_intent=request_intent,
            source_state=source_state,
            work_facts=work_facts,
            allowed_evidence_refs=allowed_evidence_refs,
        )
        for route in routes
    }
    schemas = {
        identity: _bound_output_schema(
            {fact["fact_id"] for fact in context["work_facts"]},
            context["evidence_refs"],
            _task_candidate_refs(context["source_state"]),
        )
        for identity, context in contexts.items()
    }
    schema = OutputSchemaDefinition(
        schema_version="evaluation-route-task-satisfaction-v1",
        json_schema={
            "type": "object",
            "required": ["route_assessments"],
            "additionalProperties": False,
            "properties": {
                "route_assessments": {
                    "type": "object",
                    "required": route_ids,
                    "additionalProperties": False,
                    "properties": {
                        identity: deepcopy(bound.json_schema) for identity, bound in schemas.items()
                    },
                }
            },
        },
    )
    result = llm_runtime.infer(
        requested_mode,
        prompt_ref,
        {
            "route_requests": [
                {
                    "route_id": identity,
                    "request_intent": context["request_intent"],
                    "source_route_ids": [
                        item["route_id"]
                        for item in cast(
                            list[Mapping[str, object]], context["source_state"]["source_statuses"]
                        )
                    ],
                }
                for identity, context in contexts.items()
            ],
            # Share the observed pool once; these are accessible sources, not proof of a match.
            "source_state": deepcopy(dict(source_state)),
            "work_facts": deepcopy(list(work_facts)),
            "evidence": deepcopy(list(evidence)),
        },
        schema,
    )
    errors = validate_output_schema(result.structured_output, schema.json_schema)
    if errors:
        raise ValueError(f"invalid route Task assessment: {'; '.join(errors)}")
    raw = cast(dict[str, object], result.structured_output)["route_assessments"]
    items = cast(dict[str, object], raw)
    return {
        identity: _validate_and_materialize(
            items[identity],
            output_schema=schemas[identity],
            fact_ids={fact["fact_id"] for fact in context["work_facts"]},
            allowed_evidence_refs=context["evidence_refs"],
            candidate_refs=_task_candidate_refs(context["source_state"]),
            source_state=context["source_state"],
            work_facts=context["work_facts"],
        )
        for identity, context in contexts.items()
    }


def consume_task_route_assessments(
    *,
    request_intent: Mapping[str, object],
    output_routes: Sequence[Mapping[str, object]],
    assessments: Mapping[str, DuplicateConflictAssessmentV1],
    work_facts: Sequence[WorkFactV1],
    evidence: Sequence[Mapping[str, object]],
    source_state: Mapping[str, object],
    allowed_evidence_refs: set[str],
    llm_runtime: StructuredInferencePort,
    prompt_ref: PromptReference,
    requested_mode: RequestedModeV1,
) -> ActionNecessityAssessmentV1:
    """Reuse the Product single-route guard, including conditional non-duplicate work.

    This connected gate intentionally does not optimize N non-satisfied routes:
    each still invokes the existing necessity owner. No scalar assessment is copied.
    """
    task_ids = [_route_id(route) for route in output_routes if _is_task_create(route)]
    if len(task_ids) != len(set(task_ids)) or set(assessments) != set(task_ids):
        raise ValueError("Task assessments must cover exactly the frozen Task CREATE routes")
    result: ActionNecessityAssessmentV1 = {"route_assessments": []}
    for route in output_routes:
        context = _route_context(
            route=route,
            request_intent=request_intent,
            source_state=source_state,
            work_facts=work_facts,
            allowed_evidence_refs=allowed_evidence_refs,
        )
        local_result = assess_action_necessity(
            request_intent=context["request_intent"],
            output_routes=[route],
            work_facts=context["work_facts"],
            evidence=[item for item in evidence if _evidence_ref(item) in context["evidence_refs"]],
            source_statuses=cast(
                list[Mapping[str, object]], context["source_state"]["source_statuses"]
            ),
            task_review_candidates=cast(
                list[Mapping[str, object]], context["source_state"]["task_review_candidates"]
            ),
            duplicate_conflict_assessment=assessments.get(
                _route_id(route), not_applicable_task_satisfaction()
            ),
            llm_runtime=llm_runtime,
            prompt_ref=prompt_ref,
            allowed_evidence_refs=context["evidence_refs"],
            requested_mode=requested_mode,
        )
        result["route_assessments"].extend(local_result["route_assessments"])
    return result


def _route_context(
    *,
    route: Mapping[str, object],
    request_intent: Mapping[str, object],
    source_state: Mapping[str, object],
    work_facts: Sequence[WorkFactV1],
    allowed_evidence_refs: set[str],
) -> _RouteContext:
    work_ids = route.get("work_unit_ids")
    if not isinstance(work_ids, list):
        raise ValueError("route requires WorkUnit binding")
    local_intent = project_request_intent_for_work_units(
        request_intent, work_unit_ids=cast(list[str], work_ids)
    )
    selected = set(work_ids)
    statuses = [
        dict(item)
        for item in cast(list[Mapping[str, object]], source_state.get("source_statuses", []))
        if selected.intersection(cast(list[str], item.get("work_unit_ids", [])))
    ]
    source_routes = {str(item["route_id"]) for item in statuses}
    refs = {
        ref for status in statuses for ref in cast(list[str], status.get("evidence_refs", []))
    } & allowed_evidence_refs
    candidates = [
        dict(item)
        for item in cast(list[Mapping[str, object]], source_state.get("task_review_candidates", []))
        if item.get("route_id") in source_routes
    ]
    return {
        "request_intent": local_intent,
        "source_state": {
            **source_state,
            "source_statuses": statuses,
            "task_review_candidates": candidates,
        },
        "work_facts": [
            fact
            for fact in work_facts
            if fact["evidence_refs"] and set(fact["evidence_refs"]) <= refs
        ],
        "evidence_refs": refs,
    }


def _is_task_create(route: Mapping[str, object]) -> bool:
    return route.get("resource_type") == "TASK" and route.get("effect") == "CREATE"


def _route_id(route: Mapping[str, object]) -> str:
    identity = route.get("route_id")
    if not isinstance(identity, str) or not identity:
        raise ValueError("Task assessment requires a non-empty frozen route ID")
    return identity


def _evidence_ref(item: Mapping[str, object]) -> object:
    return item.get("evidence_ref") or item.get("evidence_id") or item.get("id")
