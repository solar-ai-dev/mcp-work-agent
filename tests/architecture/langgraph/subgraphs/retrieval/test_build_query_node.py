from pathlib import Path

from google_work_agent.adapters.langgraph.subgraphs.retrieval.routing import (
    route_after_build_query as build_query_routing,
)


def test_build_query__exact_node__projection_and_router() -> None:
    owner = (
        Path(__file__).resolve().parents[5]
        / "src/google_work_agent/adapters/langgraph/subgraphs/retrieval"
    )
    assert "project_build_query_input" in (owner / "nodes/build_query_node.py").read_text()
    assert (owner / "projections/build_query_projection.py").exists()
    assert 'return "execute_read"' in (owner / "routing/route_after_build_query.py").read_text()


def test_build_query__mixed_supported_operations__remain_on_execute_read_edge() -> None:
    marker = build_query_routing.followup_operation_marker({"SEARCH", "DETAIL_FETCH"})

    assert marker == "READ"
    assert (
        build_query_routing.route_after_build_query({"__context_followup_operation__": marker})
        == "execute_read"
    )


def test_build_query__single_freebusy_operation__uses_search_round_semantics() -> None:
    assert build_query_routing.followup_operation_marker({"FREEBUSY"}) == "SEARCH"
