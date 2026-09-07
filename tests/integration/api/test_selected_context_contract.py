"""Selected-resource runtime projection remains serializable at the HTTP boundary."""

from collections.abc import Awaitable, Callable
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient

from google_work_agent.api.dependencies.runs import get_run_route_dependencies
from google_work_agent.api.routes import runs
from google_work_agent.application.use_cases.run.get_run_snapshot import GetExecutionContextResult
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.system.contracts.workflow_execution import SelectedResourceRef


@pytest.mark.parametrize(
    "connector,resource,identity,parent",
    [
        ("google_workspace", "gmail_thread", "thread-1", None),
        ("github", "github_issue", "acme/repo#7", "acme/repo"),
    ],
)
def test_selected_context__http_response__preserves_five_field_identity(
    monkeypatch: pytest.MonkeyPatch,
    connector: str,
    resource: str,
    identity: str,
    parent: str | None,
) -> None:
    context = GetExecutionContextResult(
        run_id="run-1",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode="RESOURCE_SELECTED",
        requested_mode="LOCAL_GPU",
        status="COMPLETED",
        version=3,
        request_text="선택한 자료 요약",
        user_message_id="user-message-1",
        selected_resource_ids=(identity,),
        run_budget=build_default_run_budget(),
        selected_resources=(SelectedResourceRef("ref-1", connector, resource, identity, parent),),
    )
    app = FastAPI()
    app.include_router(runs.router)
    app.dependency_overrides[get_run_route_dependencies] = lambda: SimpleNamespace(
        api_contract_version="1",
        get_execution_context_handler=lambda _query: context,
    )

    @app.middleware("http")
    async def request_id(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request.state.request_id = "request-1"
        return await call_next(request)

    monkeypatch.setattr(runs, "enforce_access", lambda *_args, **_kwargs: None)
    with TestClient(app) as client:
        response = client.get("/api/v1/runs/run-1/context", headers={"X-API-Contract-Version": "1"})
    assert response.status_code == 200
    assert response.json()["context"]["selected_resources"] == [
        {
            "resource_ref_id": "ref-1",
            "connector_id": connector,
            "resource_type": resource,
            "resource_id": identity,
            "parent_resource_id": parent,
        }
    ]
