from typing import cast

import pytest

from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import (
    WorkRelationV1,
)
from google_work_agent.application.agents.work_analysis.validate_relations import validate_relations
from tests.support.work_analysis import fact


def _candidate(kind: str = "DUPLICATES") -> WorkRelationV1:
    return cast(
        WorkRelationV1,
        {
            "relation_id": "r1",
            "kind": kind,
            "source_fact_id": "f1",
            "target_fact_id": "f2",
            "evidence_refs": ["ev-1"],
        },
    )


def test_guarded_candidate__from_semantic_owner__keeps_bounded_evidence() -> None:
    result = validate_relations(
        work_facts=[fact("f1"), fact("f2")],
        entity_relation_candidates=[],
        temporal_dependency_candidates=[],
        duplicate_conflict_candidates=[_candidate()],
        allowed_evidence_refs={"ev-1"},
    )
    assert result["validated_relations"] == [_candidate()]
    assert result["relation_validation_ambiguities"] == []


def test_guarded_candidate__outside_current_evidence__fails_closed() -> None:
    with pytest.raises(ValueError, match="outside current RetrievalResultV1"):
        validate_relations(
            work_facts=[fact("f1"), fact("f2")],
            entity_relation_candidates=[],
            temporal_dependency_candidates=[],
            duplicate_conflict_candidates=[_candidate()],
            allowed_evidence_refs=set(),
        )


def test_unknown_or__free_text_relation__kind_fails_closed() -> None:
    with pytest.raises(ValueError, match="unknown WorkRelationV1"):
        validate_relations(
            work_facts=[fact("f1"), fact("f2")],
            entity_relation_candidates=[_candidate("OWNS")],
            temporal_dependency_candidates=[],
            duplicate_conflict_candidates=[],
            allowed_evidence_refs={"ev-1"},
        )
