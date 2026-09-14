from collections.abc import Mapping

from google_work_agent.application.agents.retrieval.plan_query import plan_query

from ..projections.plan_query_projection import project_plan_query_input


def plan_query_node(state: Mapping[str, object]) -> dict[str, object]:
    query_plan, retry_budget, _ = plan_query(**project_plan_query_input(state))
    return {"query_plan": query_plan, "retry_budget": retry_budget}
