from __future__ import annotations

from collections.abc import Callable

from google_work_agent.adapters.langgraph.subgraphs.request_understanding.state import (
    RequestUnderstandingStateV2,
)
from google_work_agent.application.agents.request_understanding.finalize_intent import (
    finalize_intent,
)

from ..projections.finalize_intent_projection import (
    project_finalize_intent_input,
)


def finalize_intent_node(
    state: RequestUnderstandingStateV2,
    *,
    id_factory: Callable[[], str],
) -> RequestUnderstandingStateV2:
    projection = project_finalize_intent_input(state)
    intent = finalize_intent(
        projection["goal_candidate"],
        projection["ambiguity_candidate"],
        artifact_id=id_factory(),
        user_request=projection["request"].request_text,
        confirmation_response_text=(
            None
            if "confirmation_response" not in projection
            else (
                projection["confirmation_response"]["selected_option"]
                or projection["confirmation_response"]["free_text"]
            )
        ),
    )
    return {"final_intent": intent, "request_intent": intent}
