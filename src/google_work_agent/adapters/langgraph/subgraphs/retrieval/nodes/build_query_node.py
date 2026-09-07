from collections.abc import Mapping

from google_work_agent.application.agents.retrieval.build_query import build_query

from ..projections.build_query_projection import project_build_query_input


def build_query_node(state: Mapping[str, object]) -> dict[str, object]:
    return {"source_fetch_plans": build_query(**project_build_query_input(state))}
