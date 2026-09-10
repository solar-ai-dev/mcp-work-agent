from __future__ import annotations

from collections.abc import Mapping
from typing import TypedDict, cast

from google_work_agent.application.agents.work_analysis.contracts.work_analysis_candidates import (
    DuplicateConflictAssessmentV1,
)
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import (
    RouteActionNecessityV1,
    StateArtifactRefV1,
    WorkAmbiguityV1,
    WorkFactV1,
    WorkRelationV1,
    WorkRiskV1,
)
from google_work_agent.application.use_cases.run.policy_confirmation_receipt import (
    PolicyConfirmationReceiptV1,
)


class AssembleWorkAnalysisInput(TypedDict):
    based_on: list[StateArtifactRefV1]
    work_facts: list[WorkFactV1]
    validated_relations: list[WorkRelationV1]
    ambiguities: list[WorkAmbiguityV1]
    risks: list[WorkRiskV1]
    evidence_refs: list[str]
    route_action_necessities: list[RouteActionNecessityV1]
    policy_confirmation_receipts: list[PolicyConfirmationReceiptV1]
    duplicate_conflict_assessment: DuplicateConflictAssessmentV1


def project_assemble_work_analysis_input(
    state: Mapping[str, object],
) -> AssembleWorkAnalysisInput:
    required = (
        "request_intent",
        "fact_candidates",
        "validated_relations",
        "ambiguity_candidates",
        "operational_risk_candidates",
        "evidence_refs",
        "duplicate_conflict_assessment",
        "route_action_necessities",
    )
    if any(key not in state for key in required):
        raise ValueError("missing typed input projection for analysis.finalize")
    based_on: list[StateArtifactRefV1] = []
    route_plan = state.get("tool_route_plan")
    route_artifacts = (
        [route_plan.get("input_plan"), route_plan.get("output_plan")]
        if isinstance(route_plan, Mapping)
        else []
    )
    for artifact in [state.get("request_intent"), *route_artifacts, state.get("retrieval_result")]:
        if not isinstance(artifact, Mapping):
            continue
        meta = artifact.get("meta")
        if not isinstance(meta, Mapping):
            continue
        artifact_id, revision = meta.get("artifact_id"), meta.get("revision")
        if isinstance(artifact_id, str) and isinstance(revision, int):
            based_on.append({"artifact_id": artifact_id, "revision": revision})
    return {
        "based_on": based_on,
        "work_facts": cast(list[WorkFactV1], state["fact_candidates"]),
        "validated_relations": cast(list[WorkRelationV1], state["validated_relations"]),
        "ambiguities": cast(list[WorkAmbiguityV1], state["ambiguity_candidates"]),
        "risks": cast(list[WorkRiskV1], state["operational_risk_candidates"]),
        "evidence_refs": list(cast(list[str], state["evidence_refs"])),
        "route_action_necessities": cast(
            list[RouteActionNecessityV1], state["route_action_necessities"]
        ),
        "policy_confirmation_receipts": cast(
            list[PolicyConfirmationReceiptV1], state.get("policy_confirmation_receipts", [])
        ),
        "duplicate_conflict_assessment": cast(
            DuplicateConflictAssessmentV1, state["duplicate_conflict_assessment"]
        ),
    }


__all__ = ["AssembleWorkAnalysisInput", "project_assemble_work_analysis_input"]
