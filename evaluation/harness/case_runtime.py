"""Canonical Case runtime bindings for business time and fault application."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .fault_adapters import EvaluationMode, FaultApplyingAdapter
from .fault_profiles import DEFAULT_DATASET_PATH, FaultHarness, load_cases
from .temporal_bindings import resolve_reference_time

DEFAULT_SIMULATED_FIXTURES_PATH = (
    Path(__file__).resolve().parent / "canonical_v8_simulated_fixtures.json"
)


@dataclass(frozen=True, slots=True)
class BusinessTimeBinding:
    reference_time: datetime
    time_zone: str

    @property
    def epoch_ms(self) -> int:
        return int(self.reference_time.timestamp() * 1_000)

    def previous_calendar_week(self) -> tuple[datetime, datetime]:
        local_midnight = self.reference_time.replace(hour=0, minute=0, second=0, microsecond=0)
        current_week = local_midnight - timedelta(days=local_midnight.weekday())
        start = current_week - timedelta(days=7)
        return start, start + timedelta(days=7)


class CanonicalCaseRuntime:
    """One isolated evaluation Case; business and elapsed clocks never mix."""

    def __init__(
        self,
        *,
        case: dict[str, Any],
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.case = case
        self.case_id = str(case["case_id"])
        self._monotonic = monotonic
        self._elapsed_origin = monotonic()
        self.business_clock_reads = 0
        reference = resolve_reference_time(case)
        context = case.get("evaluation_context", {})
        timezone = context.get("time_zone") if isinstance(context, dict) else None
        self.business_time = (
            None
            if reference is None
            else BusinessTimeBinding(reference, str(timezone or reference.tzinfo))
        )
        self.fault_harness: FaultHarness | None
        self.evaluation_mode: EvaluationMode
        profile_name = case.get("evaluation_gold", {}).get("fault_profile")
        if isinstance(profile_name, str) and profile_name:
            self.fault_harness = FaultHarness.for_case(self.case_id)
            self.evaluation_mode = self.fault_harness.profile.evaluation_mode
        else:
            self.fault_harness = None
            self.evaluation_mode = "COMPONENT_ONLY"

    @classmethod
    def for_case(
        cls,
        case_id: str,
        *,
        dataset_path: Path = DEFAULT_DATASET_PATH,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> CanonicalCaseRuntime:
        cases = load_cases(dataset_path)
        try:
            case = cases[case_id]
        except KeyError as error:
            raise ValueError(f"Unknown canonical case: {case_id}") from error
        return cls(case=case, monotonic=monotonic)

    def business_now_ms(self) -> int:
        if self.business_time is None:
            raise RuntimeError(f"{self.case_id} has no run_reference_time")
        self.business_clock_reads += 1
        return self.business_time.epoch_ms

    def product_now_ms(self) -> int:
        """Advance Product duration guards from the fixed business-time anchor."""

        return self.business_now_ms() + self.elapsed_ms()

    def elapsed_ms(self) -> int:
        return max(0, int((self._monotonic() - self._elapsed_origin) * 1_000))

    def fault_adapter(self, **kwargs: Any) -> FaultApplyingAdapter:
        if self.fault_harness is None:
            raise RuntimeError(f"{self.case_id} has no fault profile")
        return FaultApplyingAdapter(self.fault_harness, **kwargs)

    def simulated_fixture(self) -> dict[str, Any]:
        context = self.case.get("evaluation_context")
        reference = context.get("simulated_fixture_ref") if isinstance(context, dict) else None
        if not isinstance(reference, str) or not reference:
            raise RuntimeError(f"{self.case_id} has no simulated fixture binding")
        path_text, separator, fixture_id = reference.partition("#")
        if not separator or not fixture_id:
            raise ValueError("simulated_fixture_ref must contain a fixture fragment")
        path = (DEFAULT_SIMULATED_FIXTURES_PATH.parent.parent / path_text).resolve()
        root = DEFAULT_SIMULATED_FIXTURES_PATH.parent.parent.resolve()
        if not path.is_relative_to(root):
            raise ValueError("simulated fixture path leaves evaluation harness")
        document = json.loads(path.read_text(encoding="utf-8"))
        fixture = document.get("fixtures", {}).get(fixture_id)
        if not isinstance(fixture, dict):
            raise ValueError(f"unknown simulated fixture: {fixture_id}")
        return fixture


__all__ = [
    "BusinessTimeBinding",
    "CanonicalCaseRuntime",
    "DEFAULT_SIMULATED_FIXTURES_PATH",
]
