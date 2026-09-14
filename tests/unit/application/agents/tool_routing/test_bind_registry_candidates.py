from google_work_agent.application.agents.tool_routing.bind_registry_candidates import (
    bind_registry_candidates,
    is_retrieval_dependency_route,
)
from google_work_agent.application.agents.tool_routing.contracts.semantic_route_candidate import (
    SemanticRouteCandidate,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry
from google_work_agent.domain.action.model import EffectType


def _catalog() -> SignedToolRegistry:
    return load_signed_tool_registry()


def test_task_create_binds__bounded_registry_candidates__and_read_dependency() -> None:
    ids = iter(f"route-{index}" for index in range(10))
    binding = bind_registry_candidates(
        candidate=SemanticRouteCandidate(
            input_resource_types=("TASK",),
            output_pairs=(("TASK", EffectType.CREATE),),
            output_mode="ACTION",
            analysis_requirement="REQUIRED",
        ),
        tool_catalog=_catalog(),
        id_factory=lambda: next(ids),
    )
    bound = binding.output_candidates[0]
    assert bound.resource_type == "TASK"
    assert bound.effect == "CREATE"
    assert bound.connector_id == "google_workspace"
    assert bound.eligible_tool_ids == ("tasks_create_task",)
    assert {route["resource_type"] for route in binding.input_routes} == {"TASK", "TASK_LIST"}
    routes = {route["resource_type"]: route for route in binding.input_routes}
    assert not is_retrieval_dependency_route(routes["TASK"])
    assert is_retrieval_dependency_route(routes["TASK_LIST"])
    assert routes["TASK_LIST"]["required"] is True


def test_selected_gmail_thread__binds_exact_read__without_discovery_dependency() -> None:
    ids = iter(f"route-{index}" for index in range(10))
    binding = bind_registry_candidates(
        candidate=SemanticRouteCandidate(
            input_resource_types=("GMAIL_THREAD",),
            output_pairs=(),
            output_mode="ANSWER",
            analysis_requirement="REQUIRED",
            input_reason_codes=(("GMAIL_THREAD", "RESOURCE_SELECTED"),),
        ),
        tool_catalog=_catalog(),
        id_factory=lambda: next(ids),
    )

    assert len(binding.input_routes) == 1
    route = binding.input_routes[0]
    assert route["resource_type"] == "GMAIL_THREAD"
    assert route["reason_codes"] == ["RESOURCE_SELECTED"]
    assert "gmail_get_thread" in route["allowed_read_tool_ids"]


def test_general_gmail_thread__avoids_redundant__message_detail_route() -> None:
    ids = iter(f"route-{index}" for index in range(10))
    binding = bind_registry_candidates(
        candidate=SemanticRouteCandidate(
            input_resource_types=("GMAIL_THREAD",),
            output_pairs=(),
            output_mode="ANSWER",
            analysis_requirement="NONE",
        ),
        tool_catalog=_catalog(),
        id_factory=lambda: next(ids),
    )

    assert [route["resource_type"] for route in binding.input_routes] == ["GMAIL_THREAD"]


def test_calendar_event_read__without_create_effect__adds_discovery_not_freebusy() -> None:
    ids = iter(f"route-{index}" for index in range(10))
    binding = bind_registry_candidates(
        candidate=SemanticRouteCandidate(
            input_resource_types=("CALENDAR_EVENT",),
            output_pairs=(),
            output_mode="ANSWER",
            analysis_requirement="REQUIRED",
        ),
        tool_catalog=_catalog(),
        id_factory=lambda: next(ids),
    )

    assert {route["resource_type"] for route in binding.input_routes} == {
        "CALENDAR",
        "CALENDAR_EVENT",
    }
    routes = {route["resource_type"]: route for route in binding.input_routes}
    assert is_retrieval_dependency_route(routes["CALENDAR"])
    assert not is_retrieval_dependency_route(routes["CALENDAR_EVENT"])


def test_explicit_freebusy_read__when_requested__retains_route() -> None:
    ids = iter(f"route-{index}" for index in range(10))
    binding = bind_registry_candidates(
        candidate=SemanticRouteCandidate(
            input_resource_types=("CALENDAR_FREEBUSY",),
            output_pairs=(),
            output_mode="ANSWER",
            analysis_requirement="REQUIRED",
        ),
        tool_catalog=_catalog(),
        id_factory=lambda: next(ids),
    )

    assert {route["resource_type"] for route in binding.input_routes} == {
        "CALENDAR",
        "CALENDAR_EVENT",
        "CALENDAR_FREEBUSY",
    }
    routes = {route["resource_type"]: route for route in binding.input_routes}
    assert not is_retrieval_dependency_route(routes["CALENDAR_FREEBUSY"])
    assert is_retrieval_dependency_route(routes["CALENDAR"])
    assert is_retrieval_dependency_route(routes["CALENDAR_EVENT"])


def test_gmail_message_read__for_thread_discovery__distinguishes_dependency() -> None:
    ids = iter(f"route-{index}" for index in range(10))
    binding = bind_registry_candidates(
        candidate=SemanticRouteCandidate(
            input_resource_types=("GMAIL_MESSAGE",),
            output_pairs=(),
            output_mode="ANSWER",
            analysis_requirement="REQUIRED",
        ),
        tool_catalog=_catalog(),
        id_factory=lambda: next(ids),
    )

    routes = {route["resource_type"]: route for route in binding.input_routes}
    assert not is_retrieval_dependency_route(routes["GMAIL_MESSAGE"])
    assert is_retrieval_dependency_route(routes["GMAIL_THREAD"])
    assert routes["GMAIL_THREAD"]["required"] is True


def test_cross_source_draft__with_calendar_read__does_not_infer_freebusy() -> None:
    ids = iter(f"route-{index}" for index in range(10))
    binding = bind_registry_candidates(
        candidate=SemanticRouteCandidate(
            input_resource_types=("TASK", "CALENDAR_EVENT"),
            output_pairs=(("GMAIL_DRAFT", EffectType.CREATE),),
            output_mode="ACTION",
            analysis_requirement="REQUIRED",
        ),
        tool_catalog=_catalog(),
        id_factory=lambda: next(ids),
    )

    assert {route["resource_type"] for route in binding.input_routes} == {
        "TASK",
        "TASK_LIST",
        "CALENDAR",
        "CALENDAR_EVENT",
    }
    assert binding.output_candidates[0].resource_type == "GMAIL_DRAFT"
    assert binding.output_candidates[0].effect == "CREATE"


def test_github_issue__binds_to_github__without_task_collision() -> None:
    ids = iter(f"route-{index}" for index in range(10))
    binding = bind_registry_candidates(
        candidate=SemanticRouteCandidate(
            input_resource_types=("GITHUB_ISSUE",),
            output_pairs=(("GITHUB_ISSUE", EffectType.CREATE),),
            output_mode="ACTION",
            analysis_requirement="REQUIRED",
        ),
        tool_catalog=_catalog(),
        id_factory=lambda: next(ids),
    )

    output = binding.output_candidates[0]
    assert output.connector_id == "github"
    assert output.resource_type == "GITHUB_ISSUE"
    assert output.eligible_tool_ids == ("github_create_issue",)
    assert binding.input_routes[0]["connector_id"] == "github"
    assert set(binding.input_routes[0]["allowed_read_tool_ids"]) == {
        "github_get_issue",
        "github_list_issues",
    }
