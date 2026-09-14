from collections.abc import Mapping

from google_work_agent.application.agents.retrieval.execute_read import execute_read

from ..projections.execute_read_projection import project_execute_read_input


def execute_read_node(state: Mapping[str, object]) -> dict[str, object]:
    result = execute_read(**project_execute_read_input(state))
    return {"read_execution": result}
