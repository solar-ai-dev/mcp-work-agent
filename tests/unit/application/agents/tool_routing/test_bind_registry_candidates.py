from google_work_agent.application.agents.tool_routing.bind_registry_candidates import (
    bind_registry_candidates,
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
