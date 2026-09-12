import pytest

from google_work_agent.application.agents.planning.build_dependencies import build_dependencies


def _seed(
    action_id: str,
    tool_id: str,
    arguments: dict[str, object],
) -> dict[str, object]:
    return {
        "action_id": action_id,
        "route_id": f"route-{action_id}",
        "tool_id": tool_id,
        "effect": "UPDATE",
        "arguments": arguments,
        "evidence_refs": ["e1"],
    }


def test_only_same__stable_resource__is_ordered() -> None:
    seeds = [
        {
            "action_id": "a1",
            "route_id": "r1",
            "tool_id": "tasks_update_task",
            "effect": "UPDATE",
            "arguments": {"task_list_id": "l", "task_id": "t"},
            "evidence_refs": ["e1"],
        },
        {
            "action_id": "a2",
            "route_id": "r2",
            "tool_id": "tasks_update_task",
            "effect": "UPDATE",
            "arguments": {"task_list_id": "l", "task_id": "t"},
            "evidence_refs": ["e1"],
        },
    ]
    assert build_dependencies(seeds) == (  # type: ignore[arg-type]
        {"action_id": "a2", "depends_on_action_id": "a1", "reason": "SAME_RESOURCE_ORDER"},
    )


def test_github_issue_actions__link_same__repository_and_issue() -> None:
    seeds = [
        _seed(
            "a1",
            "github_update_issue",
            {"repository": "owner/repo", "issue_number": 17, "body": "updated"},
        ),
        _seed(
            "a2",
            "github_close_issue",
            {"repository": "owner/repo", "issue_number": 17},
        ),
        _seed(
            "a3",
            "github_reopen_issue",
            {"repository": "owner/repo", "issue_number": 17},
        ),
    ]

    assert build_dependencies(seeds) == (  # type: ignore[arg-type]
        {"action_id": "a2", "depends_on_action_id": "a1", "reason": "SAME_RESOURCE_ORDER"},
        {"action_id": "a3", "depends_on_action_id": "a2", "reason": "SAME_RESOURCE_ORDER"},
    )


@pytest.mark.parametrize(
    ("first_tool", "second_tool"),
    [
        ("github_update_issue", "github_close_issue"),
        ("github_update_issue", "github_reopen_issue"),
        ("github_close_issue", "github_update_issue"),
        ("github_reopen_issue", "github_update_issue"),
    ],
)
def test_github_issue_actions__preserve_order_across_supported_mutations(
    first_tool: str,
    second_tool: str,
) -> None:
    arguments = {"repository": "owner/repo", "issue_number": 17, "body": "updated"}
    seeds = [
        _seed("a1", first_tool, arguments),
        _seed("a2", second_tool, arguments),
    ]

    assert build_dependencies(seeds) == (  # type: ignore[arg-type]
        {"action_id": "a2", "depends_on_action_id": "a1", "reason": "SAME_RESOURCE_ORDER"},
    )


def test_github_issue_actions__do_not_link_different_stable_targets() -> None:
    seeds = [
        _seed(
            "a1",
            "github_update_issue",
            {"repository": "owner/repo", "issue_number": 17, "body": "updated"},
        ),
        _seed(
            "a2",
            "github_close_issue",
            {"repository": "owner/repo", "issue_number": 18},
        ),
        _seed(
            "a3",
            "github_reopen_issue",
            {"repository": "other/repo", "issue_number": 17},
        ),
    ]

    assert build_dependencies(seeds) == ()  # type: ignore[arg-type]


def test_github_create_issue__does_not_infer_existing_resource_identity() -> None:
    seeds = [
        _seed(
            "a1",
            "github_create_issue",
            {"repository": "owner/repo", "title": "New issue"},
        ),
        _seed(
            "a2",
            "github_close_issue",
            {"repository": "owner/repo", "issue_number": 17},
        ),
    ]

    assert build_dependencies(seeds) == ()  # type: ignore[arg-type]
