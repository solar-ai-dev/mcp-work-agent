from copy import deepcopy

import pytest

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV3,
)
from google_work_agent.application.agents.tool_routing.bind_registry_candidates import (
    bind_registry_candidates,
)
from google_work_agent.application.agents.tool_routing.contracts.semantic_route_candidate import (
    SemanticRouteCandidate,
)
from google_work_agent.application.agents.tool_routing.finalize_route import finalize_route
from google_work_agent.application.agents.tool_routing.validate_route import (
    ToolRouteValidationError,
    validate_route,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry
from google_work_agent.domain.action.model import EffectType


def _catalog() -> SignedToolRegistry:
    return load_signed_tool_registry()


def test_validate_route__mismatched_output_tool__fails_closed() -> None:
    catalog = _catalog()
    ids = iter(f"id-{index}" for index in range(30))
    binding = bind_registry_candidates(
        candidate=SemanticRouteCandidate(
            ("TASK",),
            (("TASK", EffectType.CREATE),),
            "ACTION",
            "REQUIRED",
            input_work_unit_bindings=(("TASK", ("work-1",)),),
            output_work_unit_bindings=(("TASK", EffectType.CREATE, ("work-1",)),),
        ),
        tool_catalog=catalog,
        id_factory=lambda: next(ids),
    )
    intent: RequestIntentV3 = {
        "schema_version": 3,
        "meta": {"artifact_id": "intent-1", "revision": 1, "based_on": []},
        "goal": "goal",
        "completion_conditions": ["done"],
        "constraints": [],
        "requested_effect_hints": ["CREATE"],
        "requested_resource_hints": ["TASK"],
        "analysis_requirement": "REQUIRED",
        "effect_prohibitions": [],
        "requested_work": {
            "work_units": [
                {
                    "unit_id": "work-1",
                    "request_provenance": [
                        {
                            "source": "USER_REQUEST",
                            "start_offset": 0,
                            "end_offset": 4,
                            "source_text": "goal",
                        }
                    ],
                }
            ],
            "work_relations": [],
        },
        "ambiguity": {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
    }
    selected_tools: dict[tuple[str, str], str] = {
        (item.resource_type, item.effect): item.eligible_tool_ids[0]
        for item in binding.output_candidates
    }
    result = finalize_route(
        request_intent=intent,
        binding=binding,
        selected_tools=selected_tools,
        tool_catalog=catalog,
        id_factory=lambda: next(ids),
    )
    plan = result["tool_route_plan"]
    assert plan is not None
    invalid = deepcopy(plan)
    assert invalid["output_plan"]["output_mode"] == "ACTION"
    invalid["output_plan"]["output_routes"][0]["selected_tool_id"] = "gmail_send"
    with pytest.raises(ToolRouteValidationError, match="binding is invalid"):
        validate_route(invalid, tool_catalog=catalog)
