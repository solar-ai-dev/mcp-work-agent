from __future__ import annotations

from google_work_agent.adapters.langgraph.subgraphs.review.projections.proposal_transition_projection import (  # noqa: E501
    capture_reviewed_proposal,
    project_proposal_transition,
)


def _plan(action_id: str, arguments: dict[str, object]) -> dict[str, object]:
    return {
        "meta": {"artifact_id": action_id, "revision": 1, "based_on": []},
        "actions": [
            {
                "action_id": action_id,
                "route_id": "route-1",
                "tool_id": "calendar_create_event",
                "effect": "CREATE",
                "arguments": arguments,
            }
        ],
    }


def _review() -> dict[str, object]:
    return {
        "status": "REVISE",
        "issues": [
            {
                "code": "ISSUE",
                "description": "요청 날짜와 다릅니다",
                "affected_dimensions": ["review.inspect_goal_and_evidence"],
                "affected_action_ids": ["old"],
                "affected_route_ids": ["route-1"],
            }
        ],
    }


def test_proposal_transition_keeps_absent_separate_from_null_and_old_id() -> None:
    before = _plan("old", {"payload": {"attendees": ["x@example.com"], "title": None}})
    after = _plan("new", {"payload": {"title": None}})
    captured = capture_reviewed_proposal(before, _review())
    assert captured is not None
    relation = project_proposal_transition(captured, after)
    assert relation is not None
    assert relation["previous_action_id"] == "old"
    assert relation["current_action_id"] == "new"
    assert relation["changed_arguments"] == [
        {
            "path": "/payload/attendees",
            "previous": {"present": True, "value": ["x@example.com"]},
            "current": {"present": False},
        }
    ]
    assert relation["historical_review_issues"][0]["description"] == "요청 날짜와 다릅니다"


def test_proposal_transition_does_not_guess_ambiguous_or_changed_tool() -> None:
    captured = capture_reviewed_proposal(_plan("old", {}), _review())
    assert captured is not None
    many = _plan("new", {})
    many["actions"].append(dict(many["actions"][0], action_id="another"))
    assert project_proposal_transition(captured, many) is None
    changed_tool = _plan("new", {})
    changed_tool["actions"][0]["tool_id"] = "gmail_send"
    assert project_proposal_transition(captured, changed_tool) is None
    no_route = _review()
    no_route["issues"][0]["affected_route_ids"] = []
    assert capture_reviewed_proposal(_plan("old", {}), no_route) is None
