from typing import cast

import pytest

from google_work_agent.application.agents.planning.compose_arguments_per_output_route import (
    compose_arguments_per_output_route,
)
from google_work_agent.application.agents.planning.contracts.planning_tool_schema import (
    planning_tool_argument_schema,
)
from google_work_agent.application.agents.planning.resolve_default_container import (
    BoundSelectedToolSchemaV1,
    PlanningArgumentBindingError,
)

ROUTE = {
    "route_id": "r1",
    "resource_type": "GMAIL_DRAFT",
    "connector_id": "google_workspace",
    "effect": "UPDATE",
    "selected_tool_id": "gmail_update_draft",
    "reason_codes": [],
}
PAYLOAD = {
    "to": ["recipient@example.com"],
    "cc": [],
    "bcc": [],
    "subject": "Quartz 납품 회신 검토",
    "body": "기존 본문\n추가 문장",
    "thread_id": None,
    "in_reply_to": None,
    "references": None,
    "attachments": [],
}


def test_gmail_draft_update__with_retrieved_evidence__binds_exact_identity() -> None:
    result = _compose(model_draft_id=None)[0]

    assert result["arguments"] == {"draft_id": "draft-actual", "payload": PAYLOAD}
    assert result["evidence_refs"] == ["draft-evidence"]


def test_gmail_draft_update__with_model_authored_identity__rejects_target() -> None:
    with pytest.raises(PlanningArgumentBindingError, match="cannot override"):
        _compose(model_draft_id="intent-artifact-id")


def test_gmail_draft_update__without_exact_evidence__requires_one_identity() -> None:
    with pytest.raises(PlanningArgumentBindingError, match="exactly one retrieved"):
        _compose(model_draft_id=None, evidence=[])


def test_gmail_draft_update__with_spaced_literal__restores_exact_value() -> None:
    exact_sentence = "8월 21일 입고 준비를 확인 중입니다."
    payload = {
        **PAYLOAD,
        "body": "기존 본문 8 월 21 일 입고 준비를 확인 중입니다.",
    }

    result = _compose(
        model_draft_id=None,
        payload=payload,
        request_intent={
            "constraints": [{
                "kind": "USER_REQUIREMENT",
                "field": "original_search_request",
                "value": [f'초안 끝에 “{exact_sentence}”만 추가해줘.'],
            }],
        },
    )[0]

    assert result["arguments"]["payload"]["body"] == f"기존 본문 {exact_sentence}"


def _compose(
    *,
    model_draft_id: str | None,
    evidence: list[dict[str, object]] | None = None,
    payload: dict[str, object] = PAYLOAD,
    request_intent: dict[str, object] | None = None,
) -> tuple[dict[str, object], ...]:
    bound = cast(
        BoundSelectedToolSchemaV1,
        {
            **ROUTE,
            "schema_version": 1,
            "argument_schema": planning_tool_argument_schema("gmail_update_draft"),
            "immutable_arguments": {},
        },
    )
    arguments: dict[str, object] = {"payload": payload}
    if model_draft_id is not None:
        arguments["draft_id"] = model_draft_id
    return cast(
        tuple[dict[str, object], ...],
        compose_arguments_per_output_route(
            [ROUTE],
            objectives=[
                {
                    "schema_version": 1,
                    "route_id": "r1",
                    "objective": "Update the existing Draft",
                    "target_semantics": "GMAIL_DRAFT",
                    "scope_constraints": [],
                    "evidence_refs": [],
                }
            ],
            bound_tool_schemas=[bound],
            request_intent=request_intent or {},
            evidence=(
                [{"evidence_id": "draft-evidence", "resource_handle": "gmail_draft:draft-actual"}]
                if evidence is None
                else evidence
            ),
            invoke=lambda *_: {
                "schema_version": 1,
                "route_id": "r1",
                "arguments": arguments,
                "evidence_refs": [],
            },
        ),
    )
