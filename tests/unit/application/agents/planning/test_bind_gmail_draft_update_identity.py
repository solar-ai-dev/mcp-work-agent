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


def test_gmail_draft_update__binds_retrieved_identity_and_evidence() -> None:
    result = _compose(model_draft_id=None)[0]

    assert result["arguments"] == {"draft_id": "draft-actual", "payload": PAYLOAD}
    assert result["evidence_refs"] == ["draft-evidence"]


def test_gmail_draft_update__rejects_model_authored_target_identity() -> None:
    with pytest.raises(PlanningArgumentBindingError, match="cannot override"):
        _compose(model_draft_id="intent-artifact-id")


def test_gmail_draft_update__requires_one_retrieved_identity() -> None:
    with pytest.raises(PlanningArgumentBindingError, match="exactly one retrieved"):
        _compose(model_draft_id=None, evidence=[])


def _compose(
    *, model_draft_id: str | None, evidence: list[dict[str, object]] | None = None
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
    arguments: dict[str, object] = {"payload": PAYLOAD}
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
            request_intent={},
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
