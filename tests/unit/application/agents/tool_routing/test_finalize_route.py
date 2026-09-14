from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.tool_routing.bind_registry_candidates import (
    bind_registry_candidates,
)
from google_work_agent.application.agents.tool_routing.contracts.semantic_route_candidate import (
    SemanticRouteCandidate,
)
from google_work_agent.application.agents.tool_routing.finalize_route import finalize_route
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry
from google_work_agent.domain.action.model import EffectType


def _catalog() -> SignedToolRegistry:
    return load_signed_tool_registry()


def test_finalize_route_freezes__prebound_v2_plan__without_reowning_preconditions() -> None:
    catalog = _catalog()
    ids = iter(f"id-{index}" for index in range(30))
    binding = bind_registry_candidates(
        candidate=SemanticRouteCandidate(
            ("TASK", "TASK_LIST"),
            (("TASK", EffectType.CREATE),),
            "ACTION",
            "REQUIRED",
            (
                ("TASK", "POLICY_TASK_DUPLICATE_CHECK"),
                ("TASK_LIST", "POLICY_TASK_DUPLICATE_CHECK"),
            ),
        ),
        tool_catalog=catalog,
        id_factory=lambda: next(ids),
    )
    intent: RequestIntentV2 = {
        "schema_version": 2,
        "meta": {"artifact_id": "intent-1", "revision": 1, "based_on": []},
        "goal": "task create",
        "completion_conditions": ["created"],
        "constraints": [],
        "requested_effect_hints": ["CREATE"],
        "requested_resource_hints": ["TASK"],
        "analysis_requirement": "REQUIRED",
        "ambiguity": {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
    }
    result = finalize_route(
        request_intent=intent,
        binding=binding,
        selected_tools={("TASK", "CREATE"): "tasks_create_task"},
        tool_catalog=catalog,
        id_factory=lambda: next(ids),
    )
    assert result["disposition"] == "ROUTE_READY"
    plan = result["tool_route_plan"]
    assert plan is not None and plan["schema_version"] == 2
    assert {route["resource_type"] for route in plan["input_plan"]["input_routes"]} == {
        "TASK",
        "TASK_LIST",
    }


def test_finalize_route__selection_outside_bound_set__blocks() -> None:
    catalog = _catalog()
    ids = iter(f"id-{index}" for index in range(30))
    binding = bind_registry_candidates(
        candidate=SemanticRouteCandidate((), (("TASK", EffectType.CREATE),), "ACTION", "NONE"),
        tool_catalog=catalog,
        id_factory=lambda: next(ids),
    )
    intent: RequestIntentV2 = {
        "schema_version": 2,
        "meta": {"artifact_id": "intent-1", "revision": 1, "based_on": []},
        "goal": "task create",
        "completion_conditions": ["created"],
        "constraints": [],
        "requested_effect_hints": ["CREATE"],
        "requested_resource_hints": ["TASK"],
        "analysis_requirement": "NONE",
        "ambiguity": {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
    }
    result = finalize_route(
        request_intent=intent,
        binding=binding,
        selected_tools={("TASK", "CREATE"): "not_registry_eligible"},
        tool_catalog=catalog,
        id_factory=lambda: next(ids),
    )
    assert result["disposition"] == "BLOCKED"
    assert result["tool_route_plan"] is None
    assert any("outside the bound eligible set" in reason for reason in result["reason_codes"])


def test_finalize_route__output_only_revision__reuses_exact_input_plan() -> None:
    catalog = _catalog()
    ids = iter(f"id-{index}" for index in range(30))
    binding = bind_registry_candidates(
        candidate=SemanticRouteCandidate(
            ("TASK", "TASK_LIST"),
            (("TASK", EffectType.CREATE),),
            "ACTION",
            "REQUIRED",
            (
                ("TASK", "POLICY_TASK_DUPLICATE_CHECK"),
                ("TASK_LIST", "POLICY_TASK_DUPLICATE_CHECK"),
            ),
        ),
        tool_catalog=catalog,
        id_factory=lambda: next(ids),
    )
    first_intent: RequestIntentV2 = {
        "schema_version": 2,
        "meta": {"artifact_id": "intent-1", "revision": 1, "based_on": []},
        "goal": "create task when needed",
        "completion_conditions": ["safe preview"],
        "constraints": [],
        "requested_effect_hints": ["CREATE"],
        "requested_resource_hints": ["TASK"],
        "analysis_requirement": "REQUIRED",
        "ambiguity": {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
    }
    first = finalize_route(
        request_intent=first_intent,
        binding=binding,
        selected_tools={("TASK", "CREATE"): "tasks_create_task"},
        tool_catalog=catalog,
        id_factory=lambda: next(ids),
    )
    first_plan = first["tool_route_plan"]
    assert first_plan is not None
    revised_intent: RequestIntentV2 = {
        **first_intent,
        "meta": {
            "artifact_id": "intent-1",
            "revision": 2,
            "based_on": [{"artifact_id": "intent-1", "revision": 1}],
        },
        "completion_conditions": ["no action when already satisfied"],
    }

    revised = finalize_route(
        request_intent=revised_intent,
        binding=binding,
        selected_tools={("TASK", "CREATE"): "tasks_create_task"},
        tool_catalog=catalog,
        id_factory=lambda: next(ids),
        previous_plan=first_plan,
        reuse_input_plan=True,
    )

    revised_plan = revised["tool_route_plan"]
    assert revised_plan is not None
    assert revised_plan["input_plan"] == first_plan["input_plan"]
    assert revised_plan["output_plan"]["meta"]["revision"] == 2
    assert revised_plan["output_plan"]["meta"]["based_on"] == [
        {"artifact_id": "intent-1", "revision": 2}
    ]


def test_finalize_route__same_request_and_routes__preserves_input_plan_identity() -> None:
    catalog = _catalog()
    ids = iter(f"id-{index}" for index in range(30))
    candidate = SemanticRouteCandidate(
        ("GMAIL_THREAD",),
        (),
        "ANSWER",
        "REQUIRED",
    )
    binding = bind_registry_candidates(
        candidate=candidate,
        tool_catalog=catalog,
        id_factory=lambda: next(ids),
    )
    intent: RequestIntentV2 = {
        "schema_version": 2,
        "meta": {"artifact_id": "intent-read", "revision": 1, "based_on": []},
        "goal": "list matching mail",
        "completion_conditions": ["all matching titles returned"],
        "constraints": [],
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["GMAIL_THREAD"],
        "analysis_requirement": "REQUIRED",
        "ambiguity": {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
    }
    first = finalize_route(
        request_intent=intent,
        binding=binding,
        selected_tools={},
        tool_catalog=catalog,
        id_factory=lambda: next(ids),
    )
    first_plan = first["tool_route_plan"]
    assert first_plan is not None
    repeated_binding = bind_registry_candidates(
        candidate=candidate,
        tool_catalog=catalog,
        id_factory=lambda: next(ids),
    )
    assert repeated_binding.input_routes[0]["route_id"] != (
        first_plan["input_plan"]["input_routes"][0]["route_id"]
    )

    repeated = finalize_route(
        request_intent=intent,
        binding=repeated_binding,
        selected_tools={},
        tool_catalog=catalog,
        id_factory=lambda: next(ids),
        previous_plan=first_plan,
    )

    repeated_plan = repeated["tool_route_plan"]
    assert repeated_plan is not None
    assert repeated_plan["input_plan"] is first_plan["input_plan"]
    assert repeated_plan["output_plan"]["meta"]["revision"] == 2
