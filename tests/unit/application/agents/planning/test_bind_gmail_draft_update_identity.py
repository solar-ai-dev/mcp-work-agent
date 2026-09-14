from collections.abc import Mapping
from typing import cast

import pytest

from google_work_agent.application.agents.planning.bind_gmail_draft_update_identity import (
    GmailDraftUpdateAlreadySatisfiedError,
)
from google_work_agent.application.agents.planning.compose_arguments_per_output_route import (
    compose_arguments_per_output_route,
    tool_argument_candidate_output_schema,
)
from google_work_agent.application.agents.planning.contracts.planning_tool_schema import (
    planning_tool_argument_schema,
)
from google_work_agent.application.agents.planning.resolve_default_container import (
    BoundSelectedToolSchemaV1,
    PlanningArgumentBindingError,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.system.contracts.workflow_execution import SelectedResourceRef

ROUTE = {
    "route_id": "r1",
    "resource_type": "GMAIL_DRAFT",
    "connector_id": "google_workspace",
    "effect": "UPDATE",
    "selected_tool_id": "gmail_update_draft",
    "reason_codes": [],
}
PAYLOAD: dict[str, object] = {
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


def test_gmail_draft_update__patch_preserves__unrequested_observed_values() -> None:
    result = _compose(
        model_draft_id=None,
        payload={"body": "기존 본문\n추가 문장"},
    )[0]

    assert result["arguments"] == {"draft_id": "draft-actual", "payload": PAYLOAD}


def test_quartz_baseline_snapshot__with_known_fixture__builds_exact_update_preview() -> None:
    exact_sentence = "8월 21일 입고 준비를 확인 중입니다."

    result = _compose(
        model_draft_id=None,
        payload={"body": f"기존 본문\n{exact_sentence}"},
        request_intent={
            "constraints": [
                {
                    "kind": "USER_REQUIREMENT",
                    "field": "original_search_request",
                    "value": [f"초안 끝에 “{exact_sentence}”만 추가해줘. 보내지는 마."],
                }
            ],
        },
    )[0]

    assert result["arguments"] == {
        "draft_id": "draft-actual",
        "payload": {**PAYLOAD, "body": f"기존 본문\n{exact_sentence}"},
    }


def test_gmail_draft_update__no_op_body__materializes_typed_exact_append() -> None:
    exact_sentence = "8월 21일 입고 준비를 확인 중입니다."

    result = _compose(
        model_draft_id=None,
        payload={"body": "기존 본문"},
        request_intent={
            "completion_conditions": [f"초안 본문에 '{exact_sentence}' 문장이 추가됨"],
            "constraints": [
                {
                    "kind": "RESOURCE",
                    "field": "notes",
                    "value": f"초안 본문에 '{exact_sentence}' 추가",
                },
                {
                    "kind": "USER_REQUIREMENT",
                    "field": "original_search_request",
                    "value": [
                        "임시보관함의 ‘현재 초안’ 끝에 "
                        f"‘{exact_sentence}’만 추가해줘."
                    ],
                },
            ],
        },
    )[0]

    assert result["arguments"] == {
        "draft_id": "draft-actual",
        "payload": {**PAYLOAD, "body": f"기존 본문\n{exact_sentence}"},
    }


def test_gmail_draft_update__without_typed_body_semantics__keeps_no_op_guard() -> None:
    with pytest.raises(GmailDraftUpdateAlreadySatisfiedError):
        _compose(
            model_draft_id=None,
            payload={"body": "기존 본문"},
            request_intent={
                "completion_conditions": ["제목이 '새 제목'으로 변경됨"],
                "constraints": [
                    {
                        "kind": "RESOURCE",
                        "field": "subject",
                        "value": "새 제목",
                    },
                    {
                        "kind": "USER_REQUIREMENT",
                        "field": "original_search_request",
                        "value": ["제목을 ‘새 제목’으로 바꿔줘."],
                    },
                ],
            },
        )


def test_gmail_draft_update__unchanged_patch__is_not_an_action_preview() -> None:
    with pytest.raises(GmailDraftUpdateAlreadySatisfiedError) as captured:
        _compose(model_draft_id=None, payload={"body": "기존 본문"})

    assert captured.value.evidence_refs == ("draft-evidence",)


def test_gmail_draft_update__argument_prompt__receives_bounded_editable_source() -> None:
    prompt_inputs: list[dict[str, object]] = []

    def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        del prompt_id
        prompt_inputs.append(dict(prompt_input))
        return {
            "schema_version": 1,
            "route_id": "r1",
            "arguments": {"payload": {"body": "기존 본문\n추가 문장"}},
            "evidence_refs": ["draft-evidence"],
        }

    bound = cast(
        BoundSelectedToolSchemaV1,
        {
            **ROUTE,
            "schema_version": 1,
            "argument_schema": planning_tool_argument_schema("gmail_update_draft"),
            "immutable_arguments": {},
        },
    )

    compose_arguments_per_output_route(
        [ROUTE],
        objectives=[
            {
                "schema_version": 1,
                "route_id": "r1",
                "objective": "Append the requested sentence to the current body",
                "target_semantics": "GMAIL_DRAFT",
                "scope_constraints": [],
                "evidence_refs": ["draft-evidence"],
            }
        ],
        bound_tool_schemas=[bound],
        request_intent={},
        evidence=[
            {
                "evidence_id": "draft-evidence",
                "resource_handle": "gmail_draft:draft-actual",
            }
        ],
        source_snapshots={"draft-evidence": {**PAYLOAD, "body": "기존 본문"}},
        invoke=invoke,
    )

    assert prompt_inputs[0]["editable_source"] == {
        "to": ["recipient@example.com"],
        "cc": [],
        "bcc": [],
        "subject": "Quartz 납품 회신 검토",
        "body": "기존 본문",
        "attachments": [],
    }
    assert "thread_id" not in cast(dict[str, object], prompt_inputs[0]["editable_source"])


def test_gmail_draft_update__model_schema_accepts_patch__and_rejects_source_identity() -> None:
    schema = tool_argument_candidate_output_schema(
        {
            "output_route": ROUTE,
            "tool_schema": planning_tool_argument_schema("gmail_update_draft"),
            "evidence": [{"evidence_id": "draft-evidence"}],
        }
    )
    candidate = {
        "schema_version": 1,
        "route_id": "r1",
        "arguments": {"payload": {"body": "변경 본문"}},
        "evidence_refs": ["draft-evidence"],
    }

    assert validate_output_schema(candidate, schema.json_schema) == []
    candidate["arguments"] = {
        "draft_id": "invented",
        "payload": {"body": "변경 본문"},
    }
    assert validate_output_schema(candidate, schema.json_schema)


def test_gmail_draft_update__with_model_authored_identity__rejects_target() -> None:
    with pytest.raises(PlanningArgumentBindingError, match="cannot override"):
        _compose(model_draft_id="intent-artifact-id")


def test_gmail_draft_update__without_exact_evidence__requires_one_identity() -> None:
    with pytest.raises(PlanningArgumentBindingError, match="exactly one retrieved"):
        _compose(model_draft_id=None, evidence=[])


def test_gmail_draft_update__model_evidence_choice__cannot_select_between_identities() -> None:
    evidence: list[dict[str, object]] = [
        {"evidence_id": "draft-a", "resource_handle": "gmail_draft:draft-a"},
        {"evidence_id": "draft-b", "resource_handle": "gmail_draft:draft-b"},
    ]
    snapshots = {
        "draft-a": {**PAYLOAD, "body": "A"},
        "draft-b": {**PAYLOAD, "body": "B"},
    }

    with pytest.raises(PlanningArgumentBindingError, match="exactly one retrieved"):
        _compose(
            model_draft_id=None,
            evidence=evidence,
            source_snapshots=snapshots,
            model_evidence_refs=["draft-a"],
        )


def test_gmail_draft_update__selected_identity__authorizes_one_retrieved_target() -> None:
    evidence: list[dict[str, object]] = [
        {"evidence_id": "draft-a", "resource_handle": "gmail_draft:draft-a"},
        {"evidence_id": "draft-b", "resource_handle": "gmail_draft:draft-b"},
    ]
    snapshots = {
        "draft-a": {**PAYLOAD, "body": "A"},
        "draft-b": {**PAYLOAD, "body": "B"},
    }

    result = _compose(
        model_draft_id=None,
        evidence=evidence,
        source_snapshots=snapshots,
        selected_resources=(
            SelectedResourceRef(
                resource_ref_id="ref-b",
                connector_id="google_workspace",
                resource_type="gmail_draft",
                resource_id="draft-b",
            ),
        ),
        model_evidence_refs=["draft-b"],
        payload={"body": "B\n추가 문장"},
    )[0]

    arguments = cast(dict[str, object], result["arguments"])
    assert arguments["draft_id"] == "draft-b"
    assert result["evidence_refs"] == ["draft-b"]


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
            "constraints": [
                {
                    "kind": "USER_REQUIREMENT",
                    "field": "original_search_request",
                    "value": [f"초안 끝에 “{exact_sentence}”만 추가해줘."],
                }
            ],
        },
    )[0]

    assert _result_payload(result)["body"] == f"기존 본문 {exact_sentence}"


def test_gmail_draft_update__same_resource_versions__binds_selected_evidence_snapshot() -> None:
    bound = cast(
        BoundSelectedToolSchemaV1,
        {
            **ROUTE,
            "schema_version": 1,
            "argument_schema": planning_tool_argument_schema("gmail_update_draft"),
            "immutable_arguments": {},
        },
    )
    evidence = [
        {
            "evidence_id": "draft-v1",
            "resource_handle": "gmail_draft:draft-actual",
            "locator": {"kind": "resource_payload", "source_version_ref": "v1"},
        },
        {
            "evidence_id": "draft-v2",
            "resource_handle": "gmail_draft:draft-actual",
            "locator": {"kind": "resource_payload", "source_version_ref": "v2"},
        },
    ]

    result = compose_arguments_per_output_route(
        [ROUTE],
        objectives=[
            {
                "schema_version": 1,
                "route_id": "r1",
                "objective": "Update the observed Draft",
                "target_semantics": "GMAIL_DRAFT",
                "scope_constraints": [],
                "evidence_refs": ["draft-v2"],
            }
        ],
        bound_tool_schemas=[bound],
        request_intent={},
        evidence=evidence,
        source_snapshots={
            "draft-v1": {**PAYLOAD, "body": "이전 본문"},
            "draft-v2": {**PAYLOAD, "body": "현재 본문"},
        },
        invoke=lambda *_: {
            "schema_version": 1,
            "route_id": "r1",
            "arguments": {"payload": {"body": "현재 본문\n추가 문장"}},
            "evidence_refs": ["draft-v2"],
        },
    )[0]

    assert _result_payload(result)["body"] == "현재 본문\n추가 문장"
    assert result["evidence_refs"] == ["draft-v2"]


def _compose(
    *,
    model_draft_id: str | None,
    evidence: list[dict[str, object]] | None = None,
    payload: dict[str, object] = PAYLOAD,
    request_intent: dict[str, object] | None = None,
    source_snapshots: dict[str, dict[str, object]] | None = None,
    selected_resources: tuple[SelectedResourceRef, ...] = (),
    model_evidence_refs: list[str] | None = None,
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
                [
                    {
                        "evidence_id": "draft-evidence",
                        "resource_handle": "gmail_draft:draft-actual",
                        "locator": {"kind": "resource_payload"},
                    }
                ]
                if evidence is None
                else evidence
            ),
            source_snapshots=(
                {"draft-evidence": {**PAYLOAD, "body": "기존 본문"}}
                if source_snapshots is None
                else source_snapshots
            ),
            selected_resources=selected_resources,
            invoke=lambda *_: {
                "schema_version": 1,
                "route_id": "r1",
                "arguments": arguments,
                "evidence_refs": model_evidence_refs or [],
            },
        ),
    )


def _result_payload(result: object) -> dict[str, object]:
    result_dict = cast(dict[str, object], result)
    arguments = cast(dict[str, object], result_dict["arguments"])
    return cast(dict[str, object], arguments["payload"])
