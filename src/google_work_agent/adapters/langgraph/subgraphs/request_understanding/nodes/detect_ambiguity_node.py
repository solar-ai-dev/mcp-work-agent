from __future__ import annotations

from google_work_agent.adapters.langgraph.subgraphs.request_understanding.state import (
    RequestUnderstandingStateV2,
)
from google_work_agent.application.agents.request_understanding.detect_ambiguity import (
    detect_ambiguity,
)
from google_work_agent.application.use_cases.connection.check_connector_prerequisites import (
    CheckConnectorPrerequisitesHandler,
    CheckConnectorPrerequisitesQuery,
)
from google_work_agent.ports.llm.structured_inference_contracts import PromptReference
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort

from ..projections.detect_ambiguity_projection import (
    project_detect_ambiguity_input,
)


def detect_ambiguity_node(
    state: RequestUnderstandingStateV2,
    *,
    llm_runtime: StructuredInferencePort,
    prompt_ref: PromptReference | None,
    connector_prerequisites: CheckConnectorPrerequisitesHandler | None = None,
) -> RequestUnderstandingStateV2:
    projection = project_detect_ambiguity_input(state)
    patch: RequestUnderstandingStateV2 = {"prerequisite_message": None}
    if connector_prerequisites is not None and "admitted_connector_ids" in state:
        prerequisites = connector_prerequisites(
            CheckConnectorPrerequisitesQuery(
                connector_ids=(),
                admitted_connector_ids=tuple(state["admitted_connector_ids"]),
                run_id=state.get("run_id"),
                resource_types=tuple(projection["goal_candidate"]["requested_resource_hints"]),
            )
        )
        patch["admitted_connector_ids"] = list(prerequisites.admitted_connector_ids)
        patch["prerequisite_message"] = prerequisites.user_message
        if prerequisites.user_message is not None:
            return patch
    ambiguity_candidate, retry_budget = detect_ambiguity(
        llm_runtime=llm_runtime,
        request=projection["request"],
        goal_candidate=projection["goal_candidate"],
        prompt_ref=prompt_ref,
        confirmation_response=projection.get("confirmation_response"),
        retry_budget=projection["retry_budget"],
    )
    return {
        **patch,
        "ambiguity_candidate": ambiguity_candidate,
        "retry_budget": retry_budget,
    }
