"""Project current-Run evidence available to approval-gated write actions."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from json import loads
from typing import Any, Literal, TypedDict, cast

from google_work_agent.adapters.langgraph.main.state import request_from_state
from google_work_agent.adapters.system.memory.retrieval_evidence_store import (
    resolve_evidence_projection,
)
from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    RetrievalResultV1,
)
from google_work_agent.domain.action.model import ActionEvidence
from google_work_agent.domain.evidence.model import Evidence as EvidenceRecord
from google_work_agent.domain.evidence.model import EvidenceOriginType
from google_work_agent.domain.resource_ref.model import ResourceRef as ResourceRefRecord


class UserMessageEvidenceDraftV1(TypedDict):
    schema_version: Literal[1]
    evidence_id: str
    origin_type: Literal["USER_MESSAGE"]
    message_id: str
    kind: Literal["USER_REQUEST"]
    excerpt: str


type ActionEvidenceDraftV1 = dict[str, object]


def project_current_action_evidence(
    *, state: Mapping[str, object], evidence_store: Any
) -> list[ActionEvidenceDraftV1]:
    """Join Retrieval evidence with the current Run's persisted USER Message.

    The user message is an existing Domain evidence origin, not a synthetic
    Connector resource. Its durable message identity lets CREATE actions remain
    grounded without inventing a ResourceRef or weakening the one-evidence rule.
    """

    run_id = state.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("action evidence projection requires run_id")

    result: list[ActionEvidenceDraftV1] = []
    retrieval_result = state.get("retrieval_result")
    if retrieval_result is not None:
        if not isinstance(retrieval_result, Mapping):
            raise TypeError("retrieval_result must be an object")
        result.extend(
            dict(item)
            for item in resolve_evidence_projection(
                store=evidence_store,
                run_id=run_id,
                retrieval_result=cast(RetrievalResultV1, retrieval_result),
            )
        )

    request = request_from_state(state)
    if request.run_id != run_id:
        raise ValueError("workflow request does not belong to current Run")
    if request.user_message_id is not None:
        if not request.user_message_id:
            raise ValueError("current Run user_message_id must not be empty")
        user_evidence: UserMessageEvidenceDraftV1 = {
            "schema_version": 1,
            "evidence_id": request.user_message_id,
            "origin_type": "USER_MESSAGE",
            "message_id": request.user_message_id,
            "kind": "USER_REQUEST",
            "excerpt": request.request_text,
        }
        if any(item.get("evidence_id") == request.user_message_id for item in result):
            raise ValueError("user message evidence identity collides with Retrieval evidence")
        result.append(dict(user_evidence))
    return result


def project_persisted_plan_evidence_for_review(
    *,
    run_id: str,
    evidence_by_id: Mapping[str, EvidenceRecord],
    action_evidence: Sequence[ActionEvidence],
    logical_evidence_refs_by_action: Mapping[str, Sequence[str]],
    resource_refs_by_id: Mapping[str, ResourceRefRecord],
) -> list[ActionEvidenceDraftV1]:
    """Rebuild the published Plan's Review evidence from its Domain aggregate.

    Persisted Evidence owns repository-wide ids while the Planning artifact keeps
    run-local ids. The Action-Evidence incidence relation is the durable mapping
    authority; ids that have the same incidence are interchangeable opaque labels
    and are paired deterministically. USER_MESSAGE keeps its message identity as
    required by Domain validation.
    """

    logical_membership: dict[str, set[str]] = defaultdict(set)
    logical_order: list[str] = []
    for action_id, evidence_refs in logical_evidence_refs_by_action.items():
        for evidence_ref in evidence_refs:
            if not evidence_ref:
                raise ValueError("persisted Review evidence reference must not be empty")
            if evidence_ref not in logical_membership:
                logical_order.append(evidence_ref)
            logical_membership[evidence_ref].add(action_id)

    persisted_membership: dict[str, set[str]] = defaultdict(set)
    for link in action_evidence:
        if link.action_id not in logical_evidence_refs_by_action:
            raise ValueError("persisted Review evidence links an unknown Action")
        if link.evidence_id not in evidence_by_id:
            raise ValueError("persisted Review evidence link is missing its Evidence")
        persisted_membership[link.evidence_id].add(link.action_id)

    logical_by_incidence: dict[frozenset[str], list[str]] = defaultdict(list)
    for evidence_id, action_ids in logical_membership.items():
        logical_by_incidence[frozenset(action_ids)].append(evidence_id)
    persisted_by_incidence: dict[frozenset[str], list[str]] = defaultdict(list)
    for evidence_id, action_ids in persisted_membership.items():
        persisted_by_incidence[frozenset(action_ids)].append(evidence_id)
    if set(logical_by_incidence) != set(persisted_by_incidence):
        raise ValueError("persisted Review evidence incidence drifted")

    record_by_logical_id: dict[str, EvidenceRecord] = {}
    for incidence, logical_ids in logical_by_incidence.items():
        persisted_ids = persisted_by_incidence[incidence]
        if len(logical_ids) != len(persisted_ids):
            raise ValueError("persisted Review evidence cardinality drifted")

        remaining_logical = set(logical_ids)
        remaining_persisted = set(persisted_ids)
        for persisted_id in sorted(persisted_ids):
            record = evidence_by_id[persisted_id]
            message_id = record.message_id
            if (
                record.origin_type is EvidenceOriginType.USER_MESSAGE
                and message_id in remaining_logical
            ):
                record_by_logical_id[cast(str, message_id)] = record
                remaining_logical.remove(cast(str, message_id))
                remaining_persisted.remove(persisted_id)

        for logical_id, persisted_id in zip(
            sorted(remaining_logical), sorted(remaining_persisted), strict=True
        ):
            record_by_logical_id[logical_id] = evidence_by_id[persisted_id]

    return [
        _project_persisted_evidence_record(
            run_id=run_id,
            logical_evidence_id=logical_id,
            record=record_by_logical_id[logical_id],
            resource_refs_by_id=resource_refs_by_id,
        )
        for logical_id in logical_order
    ]


def _project_persisted_evidence_record(
    *,
    run_id: str,
    logical_evidence_id: str,
    record: EvidenceRecord,
    resource_refs_by_id: Mapping[str, ResourceRefRecord],
) -> ActionEvidenceDraftV1:
    if record.run_id != run_id:
        raise ValueError("persisted Review Evidence belongs to another Run")
    if record.origin_type is EvidenceOriginType.USER_MESSAGE:
        if (
            record.message_id != logical_evidence_id
            or record.resource_ref_id is not None
            or record.locator_json is not None
            or record.kind != "USER_REQUEST"
        ):
            raise ValueError("persisted USER_MESSAGE Review evidence drifted")
        return {
            "schema_version": 1,
            "evidence_id": logical_evidence_id,
            "origin_type": "USER_MESSAGE",
            "message_id": logical_evidence_id,
            "kind": record.kind,
            "excerpt": record.excerpt,
        }

    if record.message_id is not None or record.locator_json is None:
        raise ValueError("persisted Connector Review evidence is incomplete")
    locator = loads(record.locator_json)
    if not isinstance(locator, Mapping):
        raise ValueError("persisted Connector Review locator must be an object")
    resource_handle = locator.get("resource_handle")
    segment_id = locator.get("segment_id")
    role = locator.get("role")
    source_locator = locator.get("source_locator")
    if (
        not isinstance(resource_handle, str)
        or not resource_handle
        or not isinstance(segment_id, str)
        or not segment_id
        or role not in {"SUPPORTS", "CONTRADICTS", "CONTEXT"}
        or (source_locator is not None and not isinstance(source_locator, Mapping))
    ):
        raise ValueError("persisted Connector Review locator drifted")
    if record.resource_ref_id is not None:
        resource_ref = resource_refs_by_id.get(record.resource_ref_id)
        if resource_ref is None or resource_ref.run_id != run_id:
            raise ValueError("persisted Review ResourceRef is unavailable for this Run")
        expected_handle = f"{resource_ref.resource_type}:{resource_ref.resource_id}"
        if resource_handle != expected_handle:
            raise ValueError("persisted Review ResourceRef identity drifted")
    return {
        "schema_version": 1,
        "evidence_id": logical_evidence_id,
        "resource_handle": resource_handle,
        "segment_id": segment_id,
        "kind": record.kind,
        "excerpt": record.excerpt,
        "locator": None if source_locator is None else dict(source_locator),
        "reason_codes": [cast(str, role)],
    }


__all__ = [
    "ActionEvidenceDraftV1",
    "UserMessageEvidenceDraftV1",
    "project_current_action_evidence",
    "project_persisted_plan_evidence_for_review",
]
