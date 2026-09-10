"""Closed router after the deterministic ``analysis.finalize`` node."""

from collections.abc import Mapping
from typing import Literal


def route_after_assemble_work_analysis(
    state: Mapping[str, object],
) -> Literal["assess_information_gaps", "assess_operational_risks", "finalize", "end"]:
    disposition = state.get("__analysis_noncomplete_disposition__")
    if state.get("__work_analysis_retry_confirmation__") and disposition == (
        "RESUME_INFORMATION_GAPS"
    ):
        return "assess_information_gaps"
    if state.get("__work_analysis_retry_confirmation__") and disposition == "RESUME_FINALIZE":
        return "finalize"
    if state.get("__work_analysis_retry_confirmation__"):
        return "assess_operational_risks"
    return "end"


__all__ = ["route_after_assemble_work_analysis"]
