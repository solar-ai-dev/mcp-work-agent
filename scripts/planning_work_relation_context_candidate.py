"""Inactive Planning relation-context projection; not work-product/specification delivery.

The existing local RequestIntent remains unchanged. An injected Planning invoker
can observe incoming requested-work relations with closed endpoint provenance.
No Action dependencies, Provider results, Approval, or Product Prompt are changed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Literal, TypedDict, cast

from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    PlanningSemanticInvoker,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestedWorkDefinitionV1,
    StateArtifactRefV1,
)
from google_work_agent.application.agents.request_understanding.contracts.work_unit_binding import (
    validate_requested_work_definition,
    validate_work_unit_refs,
)

_PROMPT_IDS = frozenset(
    {
        "planning.draft_action_objective_per_output_route",
        "planning.compose_arguments_per_output_route",
    }
)


class WorkRelationContextV1(TypedDict):
    schema_version: Literal[1]
    authority: Literal["REQUEST_DEFINITION_ONLY"]
    based_on_request_intent: StateArtifactRefV1
    applicable_work_unit_ids: list[str]
    requested_work: RequestedWorkDefinitionV1


def project_work_relation_context(
    request_intent: Mapping[str, object],
    *,
    user_request: str,
    work_unit_ids: Sequence[str],
) -> WorkRelationContextV1 | None:
    """Preserve direct incoming relations, never importing another work's semantics."""
    work = validate_requested_work_definition(
        request_intent.get("requested_work"), user_request=user_request
    )
    known_ids = [unit["unit_id"] for unit in work["work_units"]]
    selected = validate_work_unit_refs(
        list(work_unit_ids), known_unit_ids=known_ids, path="output_route.work_unit_ids"
    )
    meta = request_intent.get("meta")
    if not isinstance(meta, Mapping):
        raise ValueError("relation context requires a finalized RequestIntent ref")
    artifact_id, revision = meta.get("artifact_id"), meta.get("revision")
    if (
        not isinstance(artifact_id, str)
        or not artifact_id
        or type(revision) is not int
        or revision < 1
    ):
        raise ValueError("relation context requires a valid RequestIntent ref")
    incoming = [
        deepcopy(relation)
        for relation in work["work_relations"]
        if relation["target_work_unit_id"] in selected
    ]
    if not incoming:
        return None
    endpoint_ids = {
        endpoint
        for relation in incoming
        for endpoint in (relation["source_work_unit_id"], relation["target_work_unit_id"])
    }
    target_ids = {relation["target_work_unit_id"] for relation in incoming}
    context_work = validate_requested_work_definition(
        {
            "work_units": [
                deepcopy(unit) for unit in work["work_units"] if unit["unit_id"] in endpoint_ids
            ],
            "work_relations": incoming,
        },
        user_request=user_request,
    )
    return {
        "schema_version": 1,
        "authority": "REQUEST_DEFINITION_ONLY",
        "based_on_request_intent": {"artifact_id": artifact_id, "revision": revision},
        "applicable_work_unit_ids": [unit_id for unit_id in selected if unit_id in target_ids],
        "requested_work": context_work,
    }


def with_work_relation_context(
    *,
    request_intent: Mapping[str, object],
    user_request: str,
    invoke: PlanningSemanticInvoker,
) -> PlanningSemanticInvoker:
    """Inject metadata at the two existing semantic calls without adding calls."""
    authority = deepcopy(dict(request_intent))

    def invoke_with_context(
        prompt_id: str, prompt_input: Mapping[str, object]
    ) -> Mapping[str, object]:
        if prompt_id not in _PROMPT_IDS:
            return invoke(prompt_id, prompt_input)
        route = prompt_input.get("output_route")
        refs = route.get("work_unit_ids") if isinstance(route, Mapping) else None
        if not isinstance(refs, list) or not all(isinstance(ref, str) for ref in refs):
            raise ValueError("relation context requires frozen Output Route WorkUnit IDs")
        if "work_relation_context" in prompt_input:
            raise ValueError("relation context already has an input owner")
        context = project_work_relation_context(
            authority, user_request=user_request, work_unit_ids=cast(list[str], refs)
        )
        if context is None:
            return invoke(prompt_id, prompt_input)
        local_intent = prompt_input.get("request_intent")
        local_meta = local_intent.get("meta") if isinstance(local_intent, Mapping) else None
        if (
            not isinstance(local_meta, Mapping)
            or {
                "artifact_id": local_meta.get("artifact_id"),
                "revision": local_meta.get("revision"),
            }
            != context["based_on_request_intent"]
        ):
            raise ValueError("relation context and local Intent must use the same revision")
        return invoke(prompt_id, {**prompt_input, "work_relation_context": context})

    return invoke_with_context
