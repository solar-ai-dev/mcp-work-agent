"""Policy READ applicability does not expand to unrelated requested work."""

from dataclasses import replace
from typing import Any, cast

import pytest

from google_work_agent.adapters.langgraph.subgraphs.tool_routing.nodes.bind_registry_candidates_node import (  # noqa: E501
    bind_registry_candidates_node,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV3,
)
from google_work_agent.application.agents.tool_routing.contracts.semantic_route_candidate import (
    SemanticRouteCandidate,
)
from google_work_agent.application.agents.tool_routing.resolve_policy_preconditions import (
    build_policy_confirmation_receipt,
    resolve_policy_preconditions,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.domain.action.model import EffectType


def _candidate() -> SemanticRouteCandidate:
    return SemanticRouteCandidate(
        input_resource_types=(),
        output_pairs=(("TASK", EffectType.CREATE), ("CALENDAR_EVENT", EffectType.CREATE)),
        output_mode="ACTION",
        analysis_requirement="NONE",
        output_work_unit_bindings=(
            ("TASK", EffectType.CREATE, ("work-1",)),
            ("CALENDAR_EVENT", EffectType.CREATE, ("work-2",)),
        ),
    )


def _intent(*constraints: dict[str, Any]) -> RequestIntentV3:
    return cast(
        RequestIntentV3,
        {
            "schema_version": 3,
            "meta": {"artifact_id": "intent-1", "revision": 1, "based_on": []},
            "constraints": list(constraints),
        },
    )


def _scope(field: str, values: list[str], *units: str) -> dict[str, Any]:
    return {"kind": "SCOPE", "field": field, "value": values, "work_unit_ids": list(units)}


def test_policy_reads_bind_only_to_the_output_that_requires_them() -> None:
    original = _candidate()
    result = resolve_policy_preconditions(request_intent=_intent(), candidate=original)
    assert result.workflow_signal is None
    assert dict(result.candidate.input_work_unit_bindings) == {
        "TASK": ("work-1",),
        "TASK_LIST": ("work-1",),
        "CALENDAR": ("work-2",),
        "CALENDAR_EVENT": ("work-2",),
        "CALENDAR_FREEBUSY": ("work-2",),
    }
    assert result.candidate.output_work_unit_bindings == original.output_work_unit_bindings
    assert result.candidate.output_pairs == original.output_pairs


def test_unrelated_work_prohibition_does_not_block_another_work_policy_read() -> None:
    result = resolve_policy_preconditions(
        request_intent=_intent(_scope("forbidden_sources", ["CALENDAR"], "work-1")),
        candidate=_candidate(),
    )
    assert result.workflow_signal is None
    assert len(result.candidate.input_resource_types) == 5


def test_each_work_uses_its_own_allowlist_not_the_union() -> None:
    result = resolve_policy_preconditions(
        request_intent=_intent(
            _scope("required_sources", ["TASK"], "work-1"),
            _scope("required_sources", ["CALENDAR"], "work-2"),
        ),
        candidate=_candidate(),
    )
    assert result.workflow_signal is None
    # Swapping the scopes must require confirmation, not flatten into both allowed.
    blocked = resolve_policy_preconditions(
        request_intent=_intent(
            _scope("required_sources", ["CALENDAR"], "work-1"),
            _scope("required_sources", ["TASK"], "work-2"),
        ),
        candidate=_candidate(),
    )
    assert blocked.workflow_signal is not None
    assert set(blocked.workflow_signal["required_resource_types"]) == {
        "TASK",
        "TASK_LIST",
        "CALENDAR",
        "CALENDAR_EVENT",
        "CALENDAR_FREEBUSY",
    }
    assert blocked.candidate.input_resource_types == ()


def test_same_work_prohibition_requires_exact_existing_receipt() -> None:
    intent = _intent(_scope("forbidden_sources", ["CALENDAR"], "work-2"))
    original = _candidate()
    blocked = resolve_policy_preconditions(request_intent=intent, candidate=original)
    assert blocked.candidate is original
    assert blocked.workflow_signal is not None
    resources = tuple(blocked.workflow_signal["required_resource_types"])
    reasons = tuple(blocked.workflow_signal["reason_codes"])
    receipt = build_policy_confirmation_receipt(
        id_factory=lambda: "receipt-1",
        interrupt_id="interrupt-1",
        decision="APPROVED",
        request_intent=intent,
        required_resource_types=resources,
        reason_codes=reasons,
        affected_route_ids=["calendar-output"],
    )
    approved = resolve_policy_preconditions(
        request_intent=intent,
        candidate=original,
        policy_confirmation_receipts=[receipt],
        current_interrupt_id="interrupt-1",
    )
    assert approved.workflow_signal is None
    assert dict(approved.candidate.input_work_unit_bindings)["CALENDAR"] == ("work-2",)
    stale = cast(RequestIntentV3, {**intent, "meta": {**intent["meta"], "revision": 2}})
    assert (
        resolve_policy_preconditions(
            request_intent=stale,
            candidate=original,
            policy_confirmation_receipts=[receipt],
            current_interrupt_id="interrupt-1",
        ).workflow_signal
        is not None
    )


def test_shared_read_preserves_existing_binding_and_each_consumers_restriction() -> None:
    candidate = replace(
        _candidate(),
        input_resource_types=("TASK",),
        input_work_unit_bindings=(("TASK", ("work-3",)),),
        output_work_unit_bindings=(
            ("TASK", EffectType.CREATE, ("work-1",)),
            ("TASK", EffectType.CREATE, ("work-2",)),
        ),
        output_pairs=(("TASK", EffectType.CREATE), ("TASK", EffectType.CREATE)),
    )
    result = resolve_policy_preconditions(request_intent=_intent(), candidate=candidate)
    assert dict(result.candidate.input_work_unit_bindings)["TASK"] == (
        "work-3",
        "work-1",
        "work-2",
    )
    assert len(result.candidate.input_resource_types) == 2
    blocked = resolve_policy_preconditions(
        request_intent=_intent(_scope("forbidden_sources", ["TASK"], "work-2")),
        candidate=candidate,
    )
    assert blocked.workflow_signal is not None
    assert blocked.candidate is candidate


def _direct_candidate(*units: str, reason: str = "REQUESTED_INPUT") -> SemanticRouteCandidate:
    return SemanticRouteCandidate(
        input_resource_types=("GMAIL_THREAD",),
        output_pairs=(),
        output_mode="ANSWER",
        analysis_requirement="NONE",
        input_reason_codes=(("GMAIL_THREAD", reason),),
        input_work_unit_bindings=(("GMAIL_THREAD", units),),
    )


@pytest.mark.parametrize("reason", ["REQUESTED_INPUT", "RESOURCE_SELECTED"])
def test_forbidden_direct_read__stops_before_registry_materialization(reason: str) -> None:
    candidate = _direct_candidate("work-1", reason=reason)
    intent = _intent(_scope("forbidden_sources", ["EMAIL"], "work-1"))
    result = resolve_policy_preconditions(request_intent=intent, candidate=candidate)
    assert result.workflow_signal == {
        "schema_version": 1,
        "kind": "SCOPE_EXPANSION_REQUIRED",
        "reason_codes": [reason],
        "required_resource_types": ["GMAIL_THREAD"],
    }
    assert result.candidate is candidate
    patch = bind_registry_candidates_node(
        {"request_intent": intent, "io_resource_candidate": candidate},
        tool_catalog=load_signed_tool_registry(),
        id_factory=lambda: pytest.fail("unconfirmed read must not get a route identity"),
    )
    assert patch["bound_input_routes"] == []
    assert patch["bound_output_routes"] == []
    assert patch["workflow_signal"] == result.workflow_signal


def test_direct_read__unrelated_prohibition_does_not_change_binding_or_reason() -> None:
    candidate = _direct_candidate("work-1")
    result = resolve_policy_preconditions(
        request_intent=_intent(_scope("forbidden_sources", ["EMAIL"], "work-2")),
        candidate=candidate,
    )
    assert result.workflow_signal is None
    assert result.candidate == candidate


def test_direct_read__only_its_own_source_allowlist_applies() -> None:
    candidate = _direct_candidate("work-1")
    allowed = resolve_policy_preconditions(
        request_intent=_intent(
            _scope("required_sources", ["EMAIL"], "work-1"),
            _scope("required_sources", ["TASK"], "work-2"),
        ),
        candidate=candidate,
    )
    assert allowed.workflow_signal is None
    blocked = resolve_policy_preconditions(
        request_intent=_intent(
            _scope("required_sources", ["TASK"], "work-1"),
            _scope("required_sources", ["EMAIL"], "work-2"),
        ),
        candidate=candidate,
    )
    assert blocked.workflow_signal is not None
    assert blocked.workflow_signal["required_resource_types"] == ["GMAIL_THREAD"]


def test_shared_direct_read__one_consumers_prohibition_cannot_be_overridden() -> None:
    candidate = _direct_candidate("work-1", "work-2")
    result = resolve_policy_preconditions(
        request_intent=_intent(
            _scope("required_sources", ["EMAIL"], "work-1"),
            _scope("forbidden_sources", ["EMAIL"], "work-2"),
        ),
        candidate=candidate,
    )
    assert result.workflow_signal is not None
    assert result.workflow_signal["required_resource_types"] == ["GMAIL_THREAD"]
    assert result.candidate is candidate


@pytest.mark.parametrize("invalid_receipt", [None, "interrupt", "revision", "declined", "hash"])
def test_direct_read__requires_exact_current_receipt(invalid_receipt: str | None) -> None:
    candidate = _direct_candidate("work-1")
    intent = _intent(_scope("forbidden_sources", ["EMAIL"], "work-1"))
    receipt = build_policy_confirmation_receipt(
        id_factory=lambda: "direct-receipt",
        interrupt_id="direct-interrupt",
        decision="APPROVED",
        request_intent=intent,
        required_resource_types=("GMAIL_THREAD",),
        reason_codes=("REQUESTED_INPUT",),
        affected_route_ids=["GMAIL_THREAD:READ"],
    )
    interrupt_id = "direct-interrupt"
    if invalid_receipt == "interrupt":
        interrupt_id = "different-interrupt"
    elif invalid_receipt == "revision":
        intent = cast(RequestIntentV3, {**intent, "meta": {**intent["meta"], "revision": 2}})
    elif invalid_receipt == "declined":
        receipt["decision"] = "DECLINED"
    elif invalid_receipt == "hash":
        receipt["decision_context_hash"] = "a" * 64
    result = resolve_policy_preconditions(
        request_intent=intent,
        candidate=candidate,
        policy_confirmation_receipts=[receipt],
        current_interrupt_id=interrupt_id,
    )
    assert (result.workflow_signal is None) == (invalid_receipt is None)
    assert result.candidate == candidate
    if invalid_receipt is None:
        ids = iter(f"direct-route-{index}" for index in range(5))
        patch = bind_registry_candidates_node(
            {
                "request_intent": intent,
                "io_resource_candidate": candidate,
                "policy_confirmation_receipts": [receipt],
                "prompt_context": {
                    "confirmation_interrupt": {"interrupt_id": interrupt_id},
                },
            },
            tool_catalog=load_signed_tool_registry(),
            id_factory=lambda: next(ids),
        )
        assert patch["workflow_signal"] is None
        assert len(patch["bound_input_routes"]) == 1
        assert patch["bound_input_routes"][0]["work_unit_ids"] == ["work-1"]
        assert patch["bound_output_routes"] == []


def test_shared_direct_and_policy_read__receipt_stays_bound_after_materialization() -> None:
    candidate = replace(
        _candidate(),
        input_resource_types=("TASK",),
        input_reason_codes=(("TASK", "REQUESTED_INPUT"),),
        input_work_unit_bindings=(("TASK", ("work-3",)),),
    )
    intent = _intent(_scope("forbidden_sources", ["TASK"], "work-3"))
    blocked = resolve_policy_preconditions(request_intent=intent, candidate=candidate)
    assert blocked.workflow_signal is not None
    assert blocked.workflow_signal["required_resource_types"] == ["TASK"]
    assert blocked.workflow_signal["reason_codes"] == ["POLICY_TASK_DUPLICATE_CHECK"]
    receipt = build_policy_confirmation_receipt(
        id_factory=lambda: "shared-receipt",
        interrupt_id="shared-interrupt",
        decision="APPROVED",
        request_intent=intent,
        required_resource_types=tuple(blocked.workflow_signal["required_resource_types"]),
        reason_codes=tuple(blocked.workflow_signal["reason_codes"]),
        affected_route_ids=["TASK:READ"],
    )
    approved = resolve_policy_preconditions(
        request_intent=intent,
        candidate=candidate,
        policy_confirmation_receipts=[receipt],
        current_interrupt_id="shared-interrupt",
    )
    assert approved.workflow_signal is None
    assert dict(approved.candidate.input_work_unit_bindings)["TASK"] == ("work-3", "work-1")
    assert dict(approved.candidate.input_work_unit_bindings)["CALENDAR_EVENT"] == ("work-2",)
    repeated = resolve_policy_preconditions(
        request_intent=intent,
        candidate=approved.candidate,
        policy_confirmation_receipts=[receipt],
        current_interrupt_id="shared-interrupt",
    )
    assert repeated.workflow_signal is None
    assert repeated.candidate == approved.candidate
