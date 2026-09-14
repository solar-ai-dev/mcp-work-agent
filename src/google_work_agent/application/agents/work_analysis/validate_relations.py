"""Deterministic final authority for Work Analysis relations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TypedDict, cast

from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import (
    WorkAmbiguityV1,
    WorkFactV1,
    WorkRelationV1,
)

_RELATION_KINDS = frozenset(
    {"DEPENDS_ON", "ASSIGNED_TO", "DUE_AT", "DUPLICATES", "CONFLICTS_WITH", "RELATED_TO"}
)
_GUARDED_KINDS = frozenset({"DUPLICATES", "CONFLICTS_WITH"})


class RelationValidationBundleV1(TypedDict):
    validated_relations: list[WorkRelationV1]
    relation_validation_ambiguities: list[WorkAmbiguityV1]


def validate_relations(
    *,
    work_facts: Sequence[WorkFactV1],
    entity_relation_candidates: Sequence[Mapping[str, object]],
    temporal_dependency_candidates: Sequence[Mapping[str, object]],
    duplicate_conflict_candidates: Sequence[Mapping[str, object]],
    allowed_evidence_refs: set[str],
) -> RelationValidationBundleV1:
    """Validate identities and citations after the owning Agent decides semantics."""

    facts = {fact["fact_id"]: fact for fact in work_facts}
    if len(facts) != len(work_facts):
        raise ValueError("duplicate WorkFactV1.fact_id")
    relations: list[WorkRelationV1] = []
    ambiguities: list[WorkAmbiguityV1] = []
    seen_ids: set[str] = set()
    groups = (
        (entity_relation_candidates, frozenset({"ASSIGNED_TO", "RELATED_TO"})),
        (temporal_dependency_candidates, frozenset({"DEPENDS_ON", "DUE_AT", "RELATED_TO"})),
        (duplicate_conflict_candidates, _GUARDED_KINDS),
    )
    for candidates, allowed_kinds in groups:
        for raw in candidates:
            relation = _relation(raw, facts=facts, allowed_evidence_refs=allowed_evidence_refs)
            if relation["kind"] not in allowed_kinds:
                raise ValueError("relation kind is outside its atomic candidate owner")
            relation_id = relation["relation_id"]
            if relation_id in seen_ids:
                raise ValueError("duplicate WorkRelationV1.relation_id")
            seen_ids.add(relation_id)
            if relation["kind"] not in _GUARDED_KINDS:
                relations.append(relation)
                continue
            relations.append(relation)
    return {
        "validated_relations": relations,
        "relation_validation_ambiguities": ambiguities,
    }


def _relation(
    raw: Mapping[str, object],
    *,
    facts: Mapping[str, WorkFactV1],
    allowed_evidence_refs: set[str],
) -> WorkRelationV1:
    expected = {"relation_id", "kind", "source_fact_id", "target_fact_id", "evidence_refs"}
    if set(raw) != expected:
        raise ValueError("invalid WorkRelationV1 candidate schema")
    relation_id = _text(raw["relation_id"], "relation_id")
    kind = _text(raw["kind"], "kind")
    source = _text(raw["source_fact_id"], "source_fact_id")
    target = _text(raw["target_fact_id"], "target_fact_id")
    if kind not in _RELATION_KINDS:
        raise ValueError("unknown WorkRelationV1 kind")
    if source == target or source not in facts or target not in facts:
        raise ValueError("relation operands must be distinct same-invocation facts")
    refs = _strings(raw["evidence_refs"], "evidence_refs")
    if not refs or not set(refs).issubset(allowed_evidence_refs):
        raise ValueError("relation evidence is outside current RetrievalResultV1")
    return cast(
        WorkRelationV1,
        {
            "relation_id": relation_id,
            "kind": kind,
            "source_fact_id": source,
            "target_fact_id": target,
            "evidence_refs": refs,
        },
    )


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _strings(value: object, field: str) -> list[str]:
    if not isinstance(value, (list, tuple)) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise ValueError(f"{field} must contain non-empty strings")
    result = list(value)
    if len(result) != len(set(result)):
        raise ValueError(f"{field} contains duplicates")
    return result


__all__ = ["RelationValidationBundleV1", "validate_relations"]
