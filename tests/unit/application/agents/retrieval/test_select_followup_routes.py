from google_work_agent.application.agents.retrieval.select_followup_routes import (
    select_followup_routes,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)


def _route(route_id: str, connector_id: str) -> InputToolRouteV1:
    return {
        "route_id": route_id,
        "resource_type": "GMAIL_THREAD",
        "connector_id": connector_id,
        "allowed_read_tool_ids": ["read"],
        "required": True,
        "reason_codes": [],
    }


def test_required_issue__selects_only__matching_frozen_route() -> None:
    routes = [_route("mail", "google_workspace"), _route("issue", "github")]

    selected = select_followup_routes(
        {
            "unresolved_sufficiency_issues": [
                {"required": True, "resolution_source": "GOOGLE", "route_id": "mail"}
            ]
        },
        routes,
    )

    assert selected == [routes[0]]


def test_unqualified_issue__selects_route__only_when_unambiguous() -> None:
    one_google_route = [_route("mail", "google_workspace"), _route("issue", "github")]
    two_google_routes = [*one_google_route, _route("calendar", "google_workspace")]
    prompt_input = {
        "unresolved_sufficiency_issues": [{"required": True, "resolution_source": "GOOGLE"}]
    }

    assert select_followup_routes(prompt_input, one_google_route) == [one_google_route[0]]
    assert select_followup_routes(prompt_input, two_google_routes) == []


def test_required_issues__across_connectors__preserve_route_bindings() -> None:
    routes = [_route("mail", "google_workspace"), _route("issue", "github")]

    selected = select_followup_routes(
        {
            "unresolved_sufficiency_issues": [
                {"required": True, "resolution_source": "GOOGLE", "route_id": "mail"},
                {
                    "required": True,
                    "resolution_source": "CONNECTOR",
                    "route_id": "issue",
                },
            ]
        },
        routes,
    )

    assert selected == routes
