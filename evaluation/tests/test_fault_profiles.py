from __future__ import annotations

import json

from evaluation.harness.fault_profiles import (
    DEFAULT_DATASET_PATH,
    FaultHarness,
    FaultObservation,
    load_fault_profiles,
    validate_canonical_stress_profiles,
)


def test_canonical_stress_fault_profiles_resolve_20_of_20() -> None:
    profiles = load_fault_profiles()

    assert len(profiles) == 20
    assert validate_canonical_stress_profiles() == []


def test_fault_harness_is_case_scoped_and_persistence_is_deterministic() -> None:
    harness = FaultHarness.for_case("CASE-STRESS-001")
    matching = FaultObservation(
        case_id="CASE-STRESS-001",
        boundary="CONNECTOR_READ_RESULT",
        connector="gmail",
        operation="gmail_get_thread",
    )
    first = harness.observe(matching)
    second = harness.observe(matching)

    assert first is not None and first.injection_number == 1
    assert second is not None and second.injection_number == 2
    assert harness.observe(
        FaultObservation(
            case_id="CASE-STRESS-002",
            boundary=matching.boundary,
            connector=matching.connector,
            operation=matching.operation,
        )
    ) is None
    assert harness.observe(
        FaultObservation(
            case_id="CASE-STRESS-001",
            boundary="CONNECTOR_READ_RESULT",
            connector="tasks",
            operation="tasks_get_task",
        )
    ) is None


def test_post_effect_fault_invokes_delegate_once_before_losing_response() -> None:
    harness = FaultHarness.for_case("CASE-STRESS-013")
    calls: list[str] = []
    result = harness.invoke(
        FaultObservation(
            case_id="CASE-STRESS-013",
            boundary="CONNECTOR_POST_EFFECT",
            connector="calendar",
            operation="calendar_create_event",
        ),
        lambda: calls.append("created") or {"event_id": "synthetic"},
    )

    assert calls == ["created"]
    assert result.delegated is True
    assert result.effect_result == {"event_id": "synthetic"}
    assert result.directive is not None
    assert result.directive.outcome.kind == "LOSE_RESPONSE"


def test_prerequisite_fault_cannot_fire_before_verified_prefix() -> None:
    harness = FaultHarness.for_case("CASE-STRESS-020")
    base = dict(
        case_id="CASE-STRESS-020",
        boundary="BEFORE_DEPENDENT_DISPATCH",
        connector="gmail",
        operation="gmail_create_draft",
    )

    assert harness.observe(FaultObservation(**base)) is None
    directive = harness.observe(
        FaultObservation(**base, checkpoints=frozenset({"CALENDAR_EVENT_VERIFIED"}))
    )
    assert directive is not None
    assert directive.outcome.kind == "USER_CANCEL"


def test_every_dataset_fault_profile_has_one_config_authority() -> None:
    names = []
    for line in DEFAULT_DATASET_PATH.read_text(encoding="utf-8").splitlines():
        case = json.loads(line)
        if case["split"] != "STRESS":
            continue
        names.append(case["evaluation_gold"]["fault_profile"])

    assert len(names) == len(set(names)) == 20
    assert set(names) == set(load_fault_profiles())
