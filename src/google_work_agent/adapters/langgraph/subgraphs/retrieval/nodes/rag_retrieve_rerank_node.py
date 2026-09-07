from collections.abc import Mapping

from google_work_agent.application.agents.retrieval.rag_retrieve_rerank import rag_retrieve_rerank

from ..projections.rag_retrieve_rerank_projection import project_rag_retrieve_rerank_input


def rag_retrieve_rerank_node(state: Mapping[str, object]) -> dict[str, object]:
    return {"rag_candidates": rag_retrieve_rerank(**project_rag_retrieve_rerank_input(state))}
