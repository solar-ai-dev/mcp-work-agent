from google_work_agent.adapters.langgraph.subgraphs.retrieval.projections import (
    select_evidence_projection,
)


def test_select_evidence_projection__with_foreign_state__returns_owned_fields() -> None:
    state = {
        "request_intent": {"goal": "find evidence"},
        "rag_candidates": [],
        "exclusion_obligation_segment_ids": ["segment-1"],
        "foreign": {"secret": True},
    }

    assert dict(select_evidence_projection.project_select_evidence_input(state)) == {
        "request_intent": {"goal": "find evidence"},
        "rag_candidates": [],
        "exclusion_obligation_segment_ids": ["segment-1"],
        "query_attempts": [],
        "prior_selection": None,
        "evidence_reassessment_issues": [],
    }
