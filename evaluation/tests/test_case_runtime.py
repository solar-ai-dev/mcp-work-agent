from __future__ import annotations

from datetime import datetime

from evaluation.harness.case_runtime import CanonicalCaseRuntime


def test_case_runtime_exposes_fixed_business_clock_and_independent_elapsed_clock() -> None:
    monotonic_values = iter((100.0, 100.125, 100.250))
    runtime = CanonicalCaseRuntime.for_case(
        "CASE-CORE-033", monotonic=monotonic_values.__next__
    )

    assert runtime.business_now_ms() == int(
        datetime.fromisoformat("2026-08-07T09:00:00+09:00").timestamp() * 1_000
    )
    assert runtime.elapsed_ms() == 125
    assert runtime.product_now_ms() == int(
        datetime.fromisoformat("2026-08-07T09:00:00+09:00").timestamp() * 1_000
    ) + 250
    assert runtime.business_clock_reads == 2


def test_core_033_and_035_share_the_same_product_business_time_binding() -> None:
    first = CanonicalCaseRuntime.for_case("CASE-CORE-033")
    second = CanonicalCaseRuntime.for_case("CASE-CORE-035")

    assert first.business_now_ms() == second.business_now_ms()
    assert first.business_time.reference_time.isoformat() == "2026-08-07T09:00:00+09:00"  # type: ignore[union-attr]


def test_delta_stress_fixture_is_explicitly_simulated_and_inside_last_week() -> None:
    runtime = CanonicalCaseRuntime.for_case("CASE-STRESS-010")
    fixture = runtime.simulated_fixture()
    start, end = runtime.business_time.previous_calendar_week()  # type: ignore[union-attr]

    assert runtime.evaluation_mode == "SIMULATED_PROVIDER"
    assert fixture["evaluation_mode"] == "SIMULATED_PROVIDER"
    assert fixture["fixture_snapshot_id"] == "SIMULATED-V8-DELTA-CLOSE-CANDIDATES"
    assert {
        item["payload"]["project"] for item in fixture["resources"]
    } == {"Delta", "Delta Plus"}
    assert all(
        start <= datetime.fromisoformat(item["received_at"]) < end
        for item in fixture["resources"]
    )
