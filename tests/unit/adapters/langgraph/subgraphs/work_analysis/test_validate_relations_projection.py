from typing import cast

from google_work_agent.adapters.langgraph.subgraphs.work_analysis.projections import (
    validate_relations_projection,
)
from google_work_agent.adapters.langgraph.subgraphs.work_analysis.state import (
    WorkAnalysisLocalState,
)


def test_validate_relations_projection__with_foreign_state__returns_owned_fields() -> None:
    state = cast(
        WorkAnalysisLocalState,
        {
            "fact_candidates": [],
            "entity_relation_candidates": [],
            "temporal_dependency_candidates": [],
            "duplicate_conflict_candidates": [],
            "evidence_refs": [],
            "planning": {"x": 1},
        },
    )

    assert validate_relations_projection.project_validate_relations_input(state) == {
        "work_facts": [],
        "entity_relation_candidates": [],
        "temporal_dependency_candidates": [],
        "duplicate_conflict_candidates": [],
        "allowed_evidence_refs": set(),
    }
