from typing import cast

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    EvidenceDraftV1,
    SufficiencyResultV2,
)
from google_work_agent.application.agents.retrieval.require_read_evidence_support import (
    require_read_evidence_support,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    ToolRoutePlanV2,
)


def _intent(*, effect: str = "READ") -> RequestIntentV2:
    return cast(RequestIntentV2, {"requested_effect_hints": [effect]})


def _plan(*, connector_id: str = "google_workspace") -> ToolRoutePlanV2:
    return cast(
        ToolRoutePlanV2,
        {
            "input_plan": {
                "input_routes": [
                    {
                        "route_id": "route-source",
                        "connector_id": connector_id,
                        "required": True,
                    }
                ]
            }
        },
    )


def _evidence(role: str) -> EvidenceDraftV1:
    return cast(EvidenceDraftV1, {"reason_codes": [role]})


def test_context_only_read__when_marked_sufficient__requires_support() -> None:
    result = cast(
        SufficiencyResultV2,
        {"schema_version": 2, "status": "SUFFICIENT", "issues": []},
    )

    guarded = require_read_evidence_support(
        result,
        request_intent=_intent(),
        tool_route_plan=_plan(),
        evidence_drafts=[_evidence("CONTEXT")],
    )

    assert guarded["issues"] == [
        {
            "slot": "requested_fact_support",
            "issue_type": "MISSING",
            "required": True,
            "resolution_source": "GOOGLE",
            "safety_critical": False,
            "reason_codes": ["NO_SELECTED_EVIDENCE_SUPPORTS_REQUESTED_FACT"],
        }
    ]


def test_direct_read_support__when_sufficient__preserves_result() -> None:
    result = cast(
        SufficiencyResultV2,
        {"schema_version": 2, "status": "SUFFICIENT", "issues": []},
    )

    assert require_read_evidence_support(
        result,
        request_intent=_intent(),
        tool_route_plan=_plan(),
        evidence_drafts=[_evidence("SUPPORTS"), _evidence("CONTEXT")],
    ) is result


def test_write_sufficiency__through_read_evidence_guard__is_unchanged() -> None:
    result = cast(
        SufficiencyResultV2,
        {"schema_version": 2, "status": "SUFFICIENT", "issues": []},
    )

    assert require_read_evidence_support(
        result,
        request_intent=_intent(effect="CREATE"),
        tool_route_plan=_plan(connector_id="github"),
        evidence_drafts=[_evidence("CONTEXT")],
    ) is result
