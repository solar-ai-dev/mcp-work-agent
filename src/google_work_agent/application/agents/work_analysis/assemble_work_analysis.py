"""Deterministically assemble the canonical ``WorkAnalysisResultV2`` artifact."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Literal, cast

from google_work_agent.application.agents.work_analysis.contracts.work_analysis_candidates import (
    DuplicateConflictAssessmentV1,
)
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import (
    RouteActionNecessityV1,
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
    route_action_necessities: Sequence[RouteActionNecessityV1],
    policy_confirmation_receipts: Sequence[PolicyConfirmationReceiptV1],
    duplicate_conflict_assessment: DuplicateConflictAssessmentV1 | None = None,
) -> WorkAnalysisResultV2:
    """Assemble validated inputs; guarded relation truth overrides LLM necessity."""

    if not artifact_id or revision < 1:
        raise ValueError("work analysis artifact identity and positive revision are required")
    facts = [cast(WorkFactV1, dict(item)) for item in work_facts]
    relations = [cast(WorkRelationV1, dict(item)) for item in validated_relations]
    base_refs = _unique_refs(based_on)
    valid_receipts = _current_receipts(policy_confirmation_receipts, based_on=base_refs)
    resolved_route_necessities, used_receipts = _apply_policy_receipts_to_routes(
        relations=relations,
        route_action_necessities=route_action_necessities,
        receipts=valid_receipts,
        duplicate_conflict_assessment=duplicate_conflict_assessment,
    )
    necessity, reason, summary_receipts = _resolve_action_necessity(
        relations=relations,
        route_action_necessities=resolved_route_necessities,
        receipts=valid_receipts,
        duplicate_conflict_assessment=duplicate_conflict_assessment,
    )
    used_receipts = _unique_receipts([*used_receipts, *summary_receipts])
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
        "route_action_necessities": [
            cast(RouteActionNecessityV1, dict(item)) for item in resolved_route_necessities
        ],
        "policy_confirmation_receipt_refs": receipt_refs,
        "evidence_refs": _unique_strings(evidence_refs),
    }


def required_override_confirmation_kind(
    *,
    validated_relations: Sequence[WorkRelationV1],
    action_execution_required: bool,
    route_action_necessities: Sequence[RouteActionNecessityV1],
    policy_confirmation_receipts: Sequence[PolicyConfirmationReceiptV1],
    based_on: Sequence[StateArtifactRefV1],
    duplicate_conflict_assessment: DuplicateConflictAssessmentV1 | None = None,
) -> Literal["DUPLICATE_OVERRIDE", "CONFLICT_OVERRIDE"] | None:
    """Return the missing override receipt kind before final assembly."""

    if not action_execution_required:
        return None
    receipts = _current_receipts(policy_confirmation_receipts, based_on=based_on)
    kinds = {relation["kind"] for relation in validated_relations}
    if "CONFLICTS_WITH" in kinds and not _has_decision(receipts, "CONFLICT_OVERRIDE"):
        return "CONFLICT_OVERRIDE"
    if (
        "DUPLICATES" in kinds
        or _duplicate_observation_requires_override(
            duplicate_conflict_assessment,
            route_action_necessities=route_action_necessities,
        )
    ) and not _has_decision(receipts, "DUPLICATE_OVERRIDE"):
        return "DUPLICATE_OVERRIDE"
    return None


def _apply_policy_receipts_to_routes(
    *,
    relations: Sequence[WorkRelationV1],
    route_action_necessities: Sequence[RouteActionNecessityV1],
    receipts: Sequence[PolicyConfirmationReceiptV1],
    duplicate_conflict_assessment: DuplicateConflictAssessmentV1 | None,
) -> tuple[list[RouteActionNecessityV1], list[PolicyConfirmationReceiptV1]]:
    routes = [cast(RouteActionNecessityV1, dict(item)) for item in route_action_necessities]
    kinds = {relation["kind"] for relation in relations}
    if _duplicate_observation_requires_override(
        duplicate_conflict_assessment,
        route_action_necessities=routes,
    ):
        kinds.add("DUPLICATES")
    used: list[PolicyConfirmationReceiptV1] = []
    for relation_kind, receipt_kind in (
        ("CONFLICTS_WITH", "CONFLICT_OVERRIDE"),
        ("DUPLICATES", "DUPLICATE_OVERRIDE"),
    ):
        if relation_kind not in kinds:
            continue
        receipt = _decision_receipt(receipts, receipt_kind)
        if receipt is None:
            continue
        used.append(receipt)
        if receipt["decision"] == "DECLINED":
            for route in routes:
                if route["status"] == "REQUIRED" and (
                    relation_kind == "CONFLICTS_WITH" or route["candidate_refs"]
                ):
                    route["status"] = "NOT_REQUIRED"
                    route["reason"] = f"{receipt_kind}_DECLINED"
    return routes, used


def _resolve_action_necessity(
    *,
    relations: Sequence[WorkRelationV1],
    route_action_necessities: Sequence[RouteActionNecessityV1],
    receipts: Sequence[PolicyConfirmationReceiptV1],
    duplicate_conflict_assessment: DuplicateConflictAssessmentV1 | None,
) -> tuple[ActionNecessityV1, str | None, list[PolicyConfirmationReceiptV1]]:
    kinds = {relation["kind"] for relation in relations}
    if _duplicate_observation_requires_override(
        duplicate_conflict_assessment,
        route_action_necessities=route_action_necessities,
    ):
        kinds.add("DUPLICATES")
    used: list[PolicyConfirmationReceiptV1] = []
    for relation_kind, receipt_kind in (
        ("CONFLICTS_WITH", "CONFLICT_OVERRIDE"),
        ("DUPLICATES", "DUPLICATE_OVERRIDE"),
    ):
        if relation_kind not in kinds:
            continue
        receipt = _decision_receipt(receipts, receipt_kind)
        if receipt is not None:
            used.append(receipt)
            if receipt["decision"] == "DECLINED":
                return "NOT_REQUIRED", f"{receipt_kind}_DECLINED", used
        elif any(item["status"] == "REQUIRED" for item in route_action_necessities):
            return "UNDETERMINED", f"{receipt_kind}_REQUIRED", used
    if not route_action_necessities:
        return "NOT_REQUIRED", "NO_ACTION_REQUESTED", used
    undetermined = next(
        (item for item in route_action_necessities if item["status"] == "UNDETERMINED"), None
    )
    if undetermined is not None:
        return "UNDETERMINED", undetermined["reason"], used
    required = next(
        (item for item in route_action_necessities if item["status"] == "REQUIRED"), None
    )
    if required is not None:
        approved_kind = next(
            (receipt["confirmation_kind"] for receipt in used if receipt["decision"] == "APPROVED"),
            None,
        )
        return (
            "REQUIRED",
            f"{approved_kind}_APPROVED" if approved_kind is not None else required["reason"],
            used,
        )
    return "NOT_REQUIRED", route_action_necessities[0]["reason"], used


def _duplicate_observation_requires_override(
    assessment: DuplicateConflictAssessmentV1 | None,
    *,
    route_action_necessities: Sequence[RouteActionNecessityV1],
) -> bool:
    if assessment is None or assessment["requested_work_status"] != "SATISFIED":
        return False
    matched = set(assessment["matched_candidate_refs"])
    return bool(
        matched
        and any(
            route["status"] == "REQUIRED" and matched.intersection(route["candidate_refs"])
            for route in route_action_necessities
        )
    )


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


def _unique_receipts(
    receipts: Sequence[PolicyConfirmationReceiptV1],
) -> list[PolicyConfirmationReceiptV1]:
    result: list[PolicyConfirmationReceiptV1] = []
    seen: set[tuple[str, int]] = set()
    for receipt in receipts:
        identity = (receipt["meta"]["artifact_id"], receipt["meta"]["revision"])
        if identity not in seen:
            seen.add(identity)
            result.append(receipt)
    return result


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
