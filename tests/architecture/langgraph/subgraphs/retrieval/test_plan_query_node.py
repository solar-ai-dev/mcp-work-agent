from pathlib import Path

from google_work_agent.adapters.langgraph.subgraphs.retrieval.routing import route_after_plan_query


def test_plan_query__exact_node__projection_and_router() -> None:
    owner = (
        Path(__file__).resolve().parents[5]
        / "src/google_work_agent/adapters/langgraph/subgraphs/retrieval"
    )
    assert "project_plan_query_input" in (owner / "nodes/plan_query_node.py").read_text()
    assert (owner / "projections/plan_query_projection.py").exists()
    route = route_after_plan_query.route_after_plan_query
    assert route({"__context_followup_operation__": "FINALIZE"}) == "finalize"
    assert route({}) == "build_query"
