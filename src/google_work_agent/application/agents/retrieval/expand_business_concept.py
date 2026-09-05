"""Bounded workplace search manifestations, separate from evidence facts."""

from google_work_agent.application.agents.retrieval.contracts.query_plan import ConceptConstraintV1


def expand_business_concept(concept: str) -> ConceptConstraintV1 | None:
    """Expand the supported schedule concept without inventing an event or identity."""
    if concept != "일정":
        return None
    return {
        "kind": "CONCEPT",
        "concept": concept,
        "manifestations": [
            "일정", "회의", "행사", "박람회", "체육대회", "교육",
            "출장", "방문", "참석", "개최", "시간변경",
        ],
    }
