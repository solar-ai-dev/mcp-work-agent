from typing import cast

import pytest

from google_work_agent.application.agents.planning.compose_arguments_per_output_route import (
    compose_arguments_per_output_route,
)
from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    ActionTargetSemanticsV1,
)
from google_work_agent.application.agents.planning.contracts.planning_tool_schema import (
    planning_tool_argument_schema,
)
from google_work_agent.application.agents.planning.resolve_default_container import (
    BoundSelectedToolSchemaV1,
    PlanningArgumentBindingError,
)


def test_gmail_thread_reply__validated_message_identity__binds_reply_headers() -> None:
    route, bound, intent = _gmail_reply_inputs()
    result = _compose(route=route, bound=bound, intent=intent)[0]

    assert _result_payload(result) == {
        "to": ["recipient@example.com"],
        "subject": "Status",
        "body": "Confirmed.",
        "thread_id": "thread-1",
        "in_reply_to": "<latest@example.com>",
        "references": "<root@example.com> <latest@example.com>",
    }
    assert result["evidence_refs"] == ["thread-evidence"]


def test_gmail_thread_reply__multiple_messages__binds_latest_identity() -> None:
    route, bound, intent = _gmail_reply_inputs()
    earlier = _gmail_reply_evidence()
    cast(dict[str, object], earlier["locator"])["received_at"] = "2026-09-07T06:00:00Z"
    latest = _gmail_reply_evidence()
    latest["evidence_id"] = "latest-evidence"
    cast(dict[str, object], latest["locator"]).update(
        rfc822_message_id="<newest@example.com>",
        references="<root@example.com> <latest@example.com>",
        received_at="2026-09-07T16:00:00+09:00",
    )
    result = _compose(route=route, bound=bound, intent=intent, evidence=[earlier, latest])[0]
    payload = _result_payload(result)

    assert payload["in_reply_to"] == "<newest@example.com>"
    assert payload["references"] == ("<root@example.com> <latest@example.com> <newest@example.com>")
    assert result["evidence_refs"] == ["latest-evidence"]


@pytest.mark.parametrize("field", ["thread_id", "in_reply_to", "references"])
def test_gmail_thread_reply__conflicting_model_identity__fails_closed(field: str) -> None:
    route, bound, intent = _gmail_reply_inputs()
    with pytest.raises(PlanningArgumentBindingError, match="Gmail reply"):
        _compose(route=route, bound=bound, intent=intent, payload_extra={field: "wrong"})


def test_gmail_thread_reply__missing_rfc_identity__fails_closed() -> None:
    route, bound, intent = _gmail_reply_inputs()
    evidence = _gmail_reply_evidence()
    cast(dict[str, object], evidence["locator"]).pop("rfc822_message_id")
    with pytest.raises(PlanningArgumentBindingError, match="exactly one validated"):
        _compose(route=route, bound=bound, intent=intent, evidence=[evidence])


def test_new_gmail_send__thread_evidence__does_not_turn_into_reply() -> None:
    route, bound, intent = _gmail_reply_inputs()
    result = _compose(
        route=route,
        bound=bound,
        intent=intent,
        payload_extra={"subject": "New message", "body": "Hello."},
        target_semantics="GMAIL_MESSAGE",
    )[0]

    assert _result_payload(result) == {
        "to": ["recipient@example.com"],
        "subject": "New message",
        "body": "Hello.",
    }


@pytest.mark.parametrize("field", ["thread_id", "in_reply_to", "references"])
def test_new_gmail_send__model_reply_identity__fails_closed(field: str) -> None:
    route, bound, intent = _gmail_reply_inputs()

    with pytest.raises(PlanningArgumentBindingError, match="standalone Gmail SEND"):
        _compose(
            route=route,
            bound=bound,
            intent=intent,
            payload_extra={field: "model-authored-reply-identity"},
            target_semantics="GMAIL_MESSAGE",
        )


def _compose(
    *,
    route: dict[str, object],
    bound: BoundSelectedToolSchemaV1,
    intent: dict[str, object],
    evidence: list[dict[str, object]] | None = None,
    payload_extra: dict[str, object] | None = None,
    target_semantics: ActionTargetSemanticsV1 = "GMAIL_THREAD_REPLY",
) -> tuple[dict[str, object], ...]:
    payload = {
        "to": ["recipient@example.com"],
        "subject": "Status",
        "body": "Confirmed.",
        **(payload_extra or {}),
    }
    return cast(
        tuple[dict[str, object], ...],
        compose_arguments_per_output_route(
            [route],
            objectives=[
                {
                    "schema_version": 1,
                    "route_id": "r1",
                    "objective": "Reply to the thread",
                    "target_semantics": target_semantics,
                    "scope_constraints": [],
                    "evidence_refs": [],
                }
            ],
            bound_tool_schemas=[bound],
            request_intent=intent,
            evidence=evidence or [_gmail_reply_evidence()],
            invoke=lambda *_: {
                "schema_version": 1,
                "route_id": "r1",
                "arguments": {"payload": payload},
                "evidence_refs": [],
            },
        ),
    )


def _gmail_reply_inputs() -> tuple[dict[str, object], BoundSelectedToolSchemaV1, dict[str, object]]:
    route: dict[str, object] = {
        "route_id": "r1",
        "resource_type": "GMAIL_MESSAGE",
        "connector_id": "google_workspace",
        "effect": "SEND",
        "selected_tool_id": "gmail_send",
        "reason_codes": [],
    }
    bound = cast(
        BoundSelectedToolSchemaV1,
        {
            **route,
            "schema_version": 1,
            "argument_schema": planning_tool_argument_schema("gmail_send"),
            "immutable_arguments": {},
        },
    )
    intent: dict[str, object] = {
        "requested_effect_hints": ["READ", "SEND"],
        "requested_resource_hints": ["GMAIL_THREAD", "GMAIL_MESSAGE"],
    }
    return route, bound, intent


def _result_payload(result: dict[str, object]) -> dict[str, object]:
    arguments = cast(dict[str, object], result["arguments"])
    return cast(dict[str, object], arguments["payload"])


def _gmail_reply_evidence() -> dict[str, object]:
    return {
        "evidence_id": "thread-evidence",
        "resource_handle": "gmail_thread:thread-1",
        "locator": {
            "thread_id": "thread-1",
            "message_id": "gmail-internal-id",
            "rfc822_message_id": "<latest@example.com>",
            "references": "<root@example.com>",
            "received_at": "2026-09-07T15:00:00+09:00",
        },
    }
