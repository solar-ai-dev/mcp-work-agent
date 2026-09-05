from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any, cast

import pytest

from google_work_agent.adapters.langgraph.main.plan_persistence import PlanPersistenceMixin
from google_work_agent.adapters.langgraph.main.workflow import LangGraphWorkflowRuntime
from google_work_agent.domain.evidence.model import EvidenceOriginType


def test_freebusy_evidence__materializes_without__durable_resource_ref() -> None:
    runtime = object.__new__(PlanPersistenceMixin)
    state = {
        "run_id": "run-1",
        "tool_route_plan": {
            "input_plan": {
                "input_routes": [
                    {
                        "resource_type": "CALENDAR_FREEBUSY",
                        "connector_id": "google_workspace",
                    }
                ]
            }
        },
    }
    acquisition_result = {
        "source_summaries": [
            {
                "source": "CALENDAR",
                "resources": [
                    {
                        "resource_handle": "calendar_freebusy:primary:query-hash",
                        "resource_type": "calendar_freebusy",
                        "resource_id": "primary",
                        "payload": {"calendars": []},
                    }
                ],
            }
        ]
    }
    retrieval_result = {
        "meta": {"artifact_id": "retrieval-1"},
    }
    evidence = {
        "segment_id": "segment-1",
        "kind": "AVAILABILITY",
        "excerpt": "The requested interval is available.",
        "resource_handle": "calendar_freebusy:primary:query-hash",
        "reason_codes": ["CONTEXT"],
        "locator": {"calendar_id": "primary"},
    }

    result = runtime._materialize_write_evidence(
        state=cast(Any, state),
        retrieval_result=cast(Any, retrieval_result),
        acquisition_result=cast(Any, acquisition_result),
        logical_evidence_id="evidence-1",
        persisted_evidence_id="persisted-evidence-1",
        draft=evidence,
    )

    assert result.origin_type is EvidenceOriginType.DERIVED
    assert result.resource_ref_id is None
    assert result.locator_json is not None


@pytest.mark.parametrize("repository", ["acme/first", "acme/second"])
def test_answer_context__github_evidence__retains_exact_identity(repository: str) -> None:
    runtime = object.__new__(LangGraphWorkflowRuntime)
    runtime._unit_of_work_factory = lambda: nullcontext(  # type: ignore[assignment,return-value]
        SimpleNamespace(resource_refs=SimpleNamespace(list_for_run_bounded=lambda *_a, **_k: ()))
    )
    runtime._now_ms = lambda: 1000
    handle = f"github_issue:{repository}#7"
    state = {
        "run_id": "run-1",
        "tool_route_plan": {"input_plan": {"input_routes": [
            {"resource_type": "GMAIL_THREAD", "connector_id": "google_workspace"},
            {"resource_type": "GITHUB_ISSUE", "connector_id": "github"},
        ]}},
        "acquisition_result": {"source_summaries": [{
            "source": "GITHUB",
            "resources": [{
                "resource_handle": handle, "resource_type": "github_issue",
                "resource_id": f"{repository}#7", "parent_id": repository,
                "version": "v1", "payload": {"title": "Issue title", "body": "private body"},
            }],
        }]},
    }
    result = runtime._answer_context_resource_refs(
        state=state, evidence_drafts=cast(Any, ({"resource_handle": handle},)),
    )
    assert len(result) == 1
    assert result[0].connector_id == "github"
    assert result[0].resource_type == "github_issue"
    assert result[0].resource_id == f"{repository}#7"
    assert result[0].parent_resource_id == repository
    assert "private body" not in result[0].metadata_json
    state["tool_route_plan"]["input_plan"]["input_routes"].pop()  # type: ignore[index]
    with pytest.raises(ValueError, match="exactly one frozen connector"):
        runtime._answer_context_resource_refs(
            state=state, evidence_drafts=cast(Any, ({"resource_handle": handle},)),
        )
