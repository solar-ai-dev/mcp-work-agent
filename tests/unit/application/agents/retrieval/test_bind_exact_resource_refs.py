from typing import cast

import pytest

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.retrieval.bind_exact_resource_refs import (
    bind_exact_resource_refs,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    RetrievalV2ValidationError,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)
from google_work_agent.ports.system.contracts.workflow_execution import SelectedResourceRef


def _intent(draft_id: str) -> RequestIntentV2:
    return cast(
        RequestIntentV2,
        {
            "schema_version": 2,
            "meta": {"artifact_id": "intent", "revision": 1, "based_on": []},
            "goal": "update draft",
            "completion_conditions": ["updated"],
            "constraints": [
                {
                    "kind": "RESOURCE",
                    "field": "draft_id",
                    "value": draft_id,
                    "provenance": {
                        "source": "USER_REQUEST",
                        "start_offset": 16,
                        "end_offset": 36,
                    },
                }
            ],
            "requested_effect_hints": ["UPDATE"],
            "requested_resource_hints": ["GMAIL_DRAFT"],
            "analysis_requirement": "NONE",
            "ambiguity": {
                "requires_confirmation": False,
                "reason_codes": [],
                "missing_fields": [],
            },
        },
    )


def _route() -> InputToolRouteV1:
    return {
        "route_id": "route-draft",
        "resource_type": "GMAIL_DRAFT",
        "connector_id": "google_workspace",
        "allowed_read_tool_ids": ["gmail_get_draft"],
        "required": True,
        "reason_codes": ["EXPLICIT_RESOURCE_ID"],
    }


def test_explicit_draft_anchor__one_direct_read_identity__is_bound() -> None:
    result = bind_exact_resource_refs(
        request_intent=_intent("r976635311795334843"),
        frozen_routes=[_route()],
        selected_resources=(),
    )

    assert result == {
        "refs_by_route": {"route-draft": ["gmail_draft:r976635311795334843"]},
        "identities_by_ref": {
            "gmail_draft:r976635311795334843": {
                "resource_type": "gmail_draft",
                "resource_id": "r976635311795334843",
                "parent_id": None,
            }
        },
    }


def test_explicit_and_selected_draft__with_different_ids__fails_closed() -> None:
    with pytest.raises(RetrievalV2ValidationError, match="anchors conflict"):
        bind_exact_resource_refs(
            request_intent=_intent("r976635311795334843"),
            frozen_routes=[_route()],
            selected_resources=(
                SelectedResourceRef(
                    "ref-selected",
                    "google_workspace",
                    "gmail_draft",
                    "r-different",
                ),
            ),
        )
