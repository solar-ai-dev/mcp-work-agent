"""Reject READ sufficiency that is backed only by contextual material."""

from __future__ import annotations

from collections.abc import Sequence

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    EvidenceDraftV1,
    SufficiencyIssueV2,
    SufficiencyResolutionSourceValue,
    SufficiencyResultV2,
)
from google_work_agent.application.agents.tool_routing.bind_registry_candidates import (
    business_required_source_routes,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    ToolRoutePlanV2,
)


def require_read_evidence_support(
    result: SufficiencyResultV2,
    *,
    request_intent: RequestIntentV2,
    tool_route_plan: ToolRoutePlanV2 | None,
    evidence_drafts: Sequence[EvidenceDraftV1],
) -> SufficiencyResultV2:
    """Require at least one direct support or contradiction for a READ answer."""

    if (
        result["status"] != "SUFFICIENT"
        or set(request_intent["requested_effect_hints"]) != {"READ"}
        or tool_route_plan is None
        or any(
            {"SUPPORTS", "CONTRADICTS"}.intersection(draft["reason_codes"])
            for draft in evidence_drafts
        )
    ):
        return result

    required_routes = business_required_source_routes(
        tool_route_plan["input_plan"]["input_routes"]
    )
    if not required_routes:
        return result
    resolution_source: SufficiencyResolutionSourceValue = (
        "GOOGLE"
        if all(route["connector_id"] == "google_workspace" for route in required_routes)
        else "CONNECTOR"
    )
    issue: SufficiencyIssueV2 = {
        "slot": "requested_fact_support",
        "issue_type": "MISSING",
        "required": True,
        "resolution_source": resolution_source,
        "safety_critical": False,
        "reason_codes": ["NO_SELECTED_EVIDENCE_SUPPORTS_REQUESTED_FACT"],
    }
    return {
        "schema_version": 2,
        "status": result["status"],
        "issues": [*result["issues"], issue],
    }


__all__ = ["require_read_evidence_support"]
