"""Deterministically assemble the canonical ``WorkAnalysisResultV2`` artifact."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Literal, cast

from google_work_agent.application.agents.work_analysis.contracts.work_analysis_candidates import (
    DuplicateConflictAssessmentV1,
)
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import (
    StateArtifactMetaV1,
    StateArtifactRefV1,
    WorkAmbiguityV1,
    WorkAnalysisResultV2,
    WorkFactV1,
    WorkRelationV1,
    WorkRiskV1,
)
from google_work_agent.application.use_cases.run.policy_confirmation_receipt import (
    PolicyConfirmationReceiptV1,
)
from google_work_agent.domain.canonical import calculate_canonical_json_hash

ActionNecessityV1 = Literal["REQUIRED", "NOT_REQUIRED", "UNDETERMINED"]
_OVERRIDE_KINDS = frozenset({"DUPLICATE_OVERRIDE", "CONFLICT_OVERRIDE"})


def work_analysis_confirmation_context_hash(
    *,
    confirmation_kind: str,
    interrupt_id: str,
    based_on: Sequence[StateArtifactRefV1],
) -> str:
    if confirmation_kind not in _OVERRIDE_KINDS or not interrupt_id:
        raise ValueError("invalid Work Analysis policy confirmation context")
    refs = _unique_refs(based_on)
    return cast(
        str,
        calculate_canonical_json_hash(
            {
                "confirmation_kind": confirmation_kind,
                "interrupt_id": interrupt_id,
                "based_on": _sorted_refs(refs),
            }
        ),
    )


def assemble_work_analysis(
    *,
    artifact_id: str,
    revision: int,
    based_on: Iterable[StateArtifactRefV1],
    work_facts: Iterable[WorkFactV1],
    validated_relations: Iterable[WorkRelationV1],
    ambiguities: Iterable[WorkAmbiguityV1],
    risks: Iterable[WorkRiskV1],
    evidence_refs: Iterable[str],
    action_route_required: bool,
    duplicate_conflict_assessment: DuplicateConflictAssessmentV1,
    policy_confirmation_receipts: Sequence[PolicyConfirmationReceiptV1],
) -> WorkAnalysisResultV2:
    """Assemble validated inputs; guarded relation truth overrides LLM necessity."""

    if not artifact_id or revision < 1:
        raise ValueError("work analysis artifact identity and positive revision are required")
    facts = [cast(WorkFactV1, dict(item)) for item in work_facts]
    relations = [cast(WorkRelationV1, dict(item)) for item in validated_relations]
    base_refs = _unique_refs(based_on)
    valid_receipts = _current_receipts(policy_confirmation_receipts, based_on=base_refs)
    necessity, reason, used_receipts = _resolve_action_necessity(
        relations=relations,
        action_route_required=action_route_required,
        duplicate_conflict_assessment=duplicate_conflict_assessment,
        receipts=valid_receipts,
    )
    receipt_refs: list[StateArtifactRefV1] = [
        {
            "artifact_id": receipt["meta"]["artifact_id"],
            "revision": receipt["meta"]["revision"],
        }
        for receipt in used_receipts
    ]
    meta: StateArtifactMetaV1 = {
        "artifact_id": artifact_id,
        "revision": revision,
        "based_on": _unique_refs([*base_refs, *receipt_refs]),
    }
    return {
        "schema_version": 2,
        "meta": meta,
        "work_facts": facts,
        "relations": relations,
        "ambiguities": [cast(WorkAmbiguityV1, dict(item)) for item in ambiguities],
        "risks": [cast(WorkRiskV1, dict(item)) for item in risks],
        "action_necessity": necessity,
        "action_necessity_reason": reason,
        "policy_confirmation_receipt_refs": receipt_refs,
        "evidence_refs": _unique_strings(evidence_refs),
    }


def required_override_confirmation_kind(
    *,
    validated_relations: Sequence[WorkRelationV1],
    action_route_required: bool,
    policy_confirmation_receipts: Sequence[PolicyConfirmationReceiptV1],
    based_on: Sequence[StateArtifactRefV1],
) -> Literal["DUPLICATE_OVERRIDE", "CONFLICT_OVERRIDE"] | None:
    """Return the missing override receipt kind before final assembly."""

    if not action_route_required:
        return None
    receipts = _current_receipts(policy_confirmation_receipts, based_on=based_on)
    kinds = {relation["kind"] for relation in validated_relations}
    if "CONFLICTS_WITH" in kinds and not _has_decision(receipts, "CONFLICT_OVERRIDE"):
        return "CONFLICT_OVERRIDE"
    return None


def _resolve_action_necessity(
    *,
    relations: Sequence[WorkRelationV1],
    action_route_required: bool,
    duplicate_conflict_assessment: DuplicateConflictAssessmentV1,
    receipts: Sequence[PolicyConfirmationReceiptV1],
) -> tuple[ActionNecessityV1, str | None, list[PolicyConfirmationReceiptV1]]:
    kinds = {relation["kind"] for relation in relations}
    used: list[PolicyConfirmationReceiptV1] = []
    if "CONFLICTS_WITH" in kinds:
        receipt = _decision_receipt(receipts, "CONFLICT_OVERRIDE")
        if receipt is not None:
            used.append(receipt)
            if receipt["decision"] == "APPROVED":
                return "REQUIRED", "CONFLICT_OVERRIDE_APPROVED", used
            return "NOT_REQUIRED", "CONFLICT_OVERRIDE_DECLINED", used
        return "UNDETERMINED", "CONFLICT_OVERRIDE_REQUIRED", used
    status = duplicate_conflict_assessment["requested_work_status"]
    if status == "SATISFIED":
        return "NOT_REQUIRED", "EXACT_DUPLICATE_ALREADY_SATISFIES_REQUEST", used
    if action_route_required and status == "UNDETERMINED":
        return "UNDETERMINED", "DUPLICATE_REVIEW_UNDETERMINED", used
    if action_route_required:
        return "REQUIRED", "FROZEN_ACTION_ROUTE_REQUIRES_EXECUTION", used
    return "UNDETERMINED", None, used


def _current_receipts(
    receipts: Sequence[PolicyConfirmationReceiptV1],
    *,
    based_on: Sequence[StateArtifactRefV1],
) -> list[PolicyConfirmationReceiptV1]:
    required = {(item["artifact_id"], item["revision"]) for item in based_on}
    result: list[PolicyConfirmationReceiptV1] = []
    for receipt in receipts:
        if (
            receipt.get("schema_version") != 1
            or receipt.get("semantic_owner_id") != "WORK_ANALYSIS"
            or receipt.get("confirmation_kind") not in _OVERRIDE_KINDS
            or receipt.get("decision") not in {"APPROVED", "DECLINED"}
        ):
            continue
        receipt_based_on = {
            (item["artifact_id"], item["revision"])
            for item in receipt["meta"]["based_on"]
            if isinstance(item, Mapping)
            and isinstance(item.get("artifact_id"), str)
            and isinstance(item.get("revision"), int)
        }
        expected_hash = work_analysis_confirmation_context_hash(
            confirmation_kind=receipt["confirmation_kind"],
            interrupt_id=receipt["interrupt_id"],
            based_on=cast(Sequence[StateArtifactRefV1], receipt["meta"]["based_on"]),
        )
        if (
            required.issubset(receipt_based_on)
            and receipt.get("decision_context_hash") == expected_hash
        ):
            result.append(receipt)
    return result


def _has_decision(receipts: Sequence[PolicyConfirmationReceiptV1], kind: str) -> bool:
    return _decision_receipt(receipts, kind) is not None


def _decision_receipt(
    receipts: Sequence[PolicyConfirmationReceiptV1], kind: str
) -> PolicyConfirmationReceiptV1 | None:
    return next((item for item in reversed(receipts) if item["confirmation_kind"] == kind), None)


def _unique_strings(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value:
            raise ValueError("reference must not be empty")
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _unique_refs(values: Iterable[StateArtifactRefV1]) -> list[StateArtifactRefV1]:
    result: list[StateArtifactRefV1] = []
    seen: set[tuple[str, int]] = set()
    for value in values:
        artifact_id = value.get("artifact_id")
        revision = value.get("revision")
        if not isinstance(artifact_id, str) or not artifact_id:
            raise ValueError("based_on artifact_id is required")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
            raise ValueError("based_on revision must be positive")
        identity = (artifact_id, revision)
        if identity not in seen:
            seen.add(identity)
            result.append({"artifact_id": artifact_id, "revision": revision})
    return result


def _sorted_refs(values: Sequence[StateArtifactRefV1]) -> list[StateArtifactRefV1]:
    identities = sorted((value["artifact_id"], value["revision"]) for value in values)
    return [
        {"artifact_id": artifact_id, "revision": revision} for artifact_id, revision in identities
    ]


__all__ = [
    "ActionNecessityV1",
    "assemble_work_analysis",
    "required_override_confirmation_kind",
    "work_analysis_confirmation_context_hash",
]
