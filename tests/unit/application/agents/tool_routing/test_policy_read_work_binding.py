"""Policy READ applicability does not expand to unrelated requested work."""

from dataclasses import replace
from typing import Any, cast

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
