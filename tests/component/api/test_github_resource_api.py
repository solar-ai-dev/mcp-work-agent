from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import cast

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient

from google_work_agent.api.dependencies.resources import (
    ResourceRouteDependencies,
    get_resource_route_dependencies,
)
from google_work_agent.api.routes import resources
from google_work_agent.api.security.cookies import local_session_cookie_name
from google_work_agent.api.security.sessions import calculate_session_digest
from google_work_agent.application.use_cases.resource.issue_selection_handle import (
    IssueSelectionHandle,
)
from google_work_agent.application.use_cases.resource.list_resources import (
    ListResourceAccess,
    ListResourcesHandler,
)
from google_work_agent.application.use_cases.resource.resolve_selection_handle import (
    ResolveSelectionHandle,
    ResolveSelectionHandleQuery,
)
from google_work_agent.ports.connector.contracts.google_workspace import (
    ResourcePage,
    ResourceSnapshot,
    ResourceType,
)


class _GitHubResourceAccess:
    def list_github_issues_page(self, *, repository: str, state: str) -> ResourcePage:
        assert repository == "solar-ai-dev/google-work-agent"
        assert state == "ALL"
        return ResourcePage(
            items=(
                ResourceSnapshot(
                    fixture_snapshot_id=f"{repository}#181",
                    resource_type=ResourceType.GITHUB_ISSUE,
                    resource_id=f"{repository}#181",
                    parent_id=repository,
                    related_resource_ids=(repository,),
                    version="2026-09-06T00:00:00Z",
                    recovery_fingerprint=None,
                    payload={
                        "repository": repository,
                        "issue_number": 181,
                        "title": "Runtime closure",
                        "description": "Connector Sidebar",
                        "state": "OPEN",
                        "url": f"https://github.com/{repository}/issues/181",
                        "labels": ["product"],
                        "assignees": ["octocat"],
                    },
                ),
            ),
            next_page_token=None,
        )


def _app(dependencies: ResourceRouteDependencies) -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def request_id(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request.state.request_id = "request-1"
        return await call_next(request)

    app.include_router(resources.router)
    app.dependency_overrides[get_resource_route_dependencies] = lambda: dependencies
    return app


def test_github_issue_resource_api__uses_github_account__and_signed_selection_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(resources, "enforce_access", lambda *_args, **_kwargs: None)

    def now_ms() -> int:
        return 1_000

    secret = b"g" * 32
    issuer = IssueSelectionHandle(
        signing_secret=secret,
        service_instance_id="service-1",
        now_ms=now_ms,
        ttl_ms=60_000,
    )
    resolver = ResolveSelectionHandle(
        signing_secret=secret,
        service_instance_id="service-1",
        now_ms=now_ms,
    )
    dependencies = ResourceRouteDependencies(
        api_contract_version="1",
        now_ms=now_ms,
        issue_selection_handle=issuer,
        resolve_selection_handle=resolver,
        service_instance_id="service-1",
        resource_connector_id="google_workspace",
        current_account_id=lambda: None,
        current_account_ids={"google_workspace": lambda: None, "github": lambda: "github:42"},
        list_task_lists_handler=None,
        list_calendars_handler=None,
        list_resources_handler=ListResourcesHandler(
            cast(ListResourceAccess, _GitHubResourceAccess())
        ),
        get_resource_count_handler=None,
        get_resource_detail_handler=None,
        get_task_resource_detail_handler=None,
        get_calendar_resource_detail_handler=None,
    )

    with TestClient(_app(dependencies)) as client:
        client.cookies.set(local_session_cookie_name("service-1"), "local-session")
        response = client.get(
            "/api/v1/resources/github?repository=solar-ai-dev%2Fgoogle-work-agent&state=ALL",
            headers={"X-Api-Contract-Version": "1"},
        )

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["resource_id"] == "solar-ai-dev/google-work-agent#181"
    assert item["issue_state"] == "OPEN"
    selected = resolver(
        ResolveSelectionHandleQuery(
            item["selection_handle"],
            session_digest=calculate_session_digest("local-session"),
            account_id="github:42",
            expected_connector_id="github",
            expected_resource_type="github_issue",
        )
    )
    assert selected.parent_resource_id == "solar-ai-dev/google-work-agent"
