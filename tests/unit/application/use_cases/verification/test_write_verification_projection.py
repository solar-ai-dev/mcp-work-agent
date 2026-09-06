from dataclasses import dataclass

import pytest

from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.application.use_cases.verification.verify_effect import (
    SelectedResourceRefV1,
    VerifyEffectHandler,
    VerifyEffectQueryV1,
)
from google_work_agent.application.use_cases.verification.write_verification_projection import (
    build_expected_verification_projection,
)
from google_work_agent.ports.connector.connector_read_port import ConnectorReadResultV1, JsonValue
from google_work_agent.ports.connector.contracts.validated_connector_tool_binding import (
    ValidatedConnectorToolBindingV1,
)


@dataclass
class TaskRead:
    snapshot: dict[str, JsonValue]

    def execute_read(
        self,
        binding: ValidatedConnectorToolBindingV1,
        arguments: dict[str, JsonValue],
    ) -> ConnectorReadResultV1:
        assert binding.tool_id == "tasks_get_task"
        assert arguments == {"task_list_id": "list-1", "task_id": "task-1"}
        return ConnectorReadResultV1(
            1, binding.tool_id, "read-1", {"item": self.snapshot}, None, None
        )


@pytest.mark.parametrize(
    "changed,value",
    [
        ("title", "다른 제목"),
        ("notes", "다른 메모"),
        ("due", "2026-09-09T00:00:00Z"),
        ("parent_id", "other-list"),
        ("resource_id", "other-task"),
        ("status", "completed"),
    ],
)
def test_task_verification__approved_field_or_identity_changed__reports_mismatch(
    changed: str,
    value: str,
) -> None:
    actual: dict[str, JsonValue] = {
        "resource_id": "task-1",
        "parent_id": "list-1",
        "resource_type": "task",
        "payload": {"title": "보고서", "notes": "메모", "due": "2026-09-08T00:00:00Z"},
    }
    if changed in {"parent_id", "resource_id"}:
        actual[changed] = value
    else:
        assert isinstance(actual["payload"], dict)
        actual["payload"][changed] = value
    expected = build_expected_verification_projection(
        tool_name="tasks_create_task",
        arguments={
            "task_list_id": "list-1",
            "payload": {
                "title": "보고서",
                "notes": "메모",
                "scheduled_date": "2026-09-08",
            },
        },
    )
    result = VerifyEffectHandler(
        connector_read=TaskRead(actual),
        tool_registry=load_signed_tool_registry(),
    )(
        VerifyEffectQueryV1(
            "run",
            "action",
            "attempt",
            "CREATE",
            expected,
            SelectedResourceRefV1(1, "ref", "google_workspace", "task", "task-1", "list-1"),
        )
    )
    assert result.status == "MISMATCH"
    assert result.actual_normalized is not None
    assert result.expected_normalized[changed] != result.actual_normalized[changed]


def test_task_verification__absent_optional_fields__matches_empty_approved_values() -> None:
    expected = build_expected_verification_projection(
        tool_name="tasks_create_task",
        arguments={
            "task_list_id": "list-1",
            "payload": {"title": "보고서", "notes": ""},
        },
    )
    result = VerifyEffectHandler(
        connector_read=TaskRead(
            {
                "resource_id": "task-1",
                "parent_id": "list-1",
                "payload": {"title": "보고서", "status": "needsAction"},
            }
        ),
        tool_registry=load_signed_tool_registry(),
    )(
        VerifyEffectQueryV1(
            "run",
            "action",
            "attempt",
            "CREATE",
            expected,
            SelectedResourceRefV1(1, "ref", "google_workspace", "task", "task-1", "list-1"),
        )
    )
    assert result.status == "VERIFIED"
    assert result.expected_normalized["notes"] == ""
    assert result.expected_normalized["due"] is None


def test_task_update_expectation__title_only__does_not_require_optional_field_clearing() -> None:
    assert build_expected_verification_projection(
        tool_name="tasks_update_task",
        arguments={
            "task_list_id": "list-1",
            "task_id": "task-1",
            "payload": {"title": "변경"},
        },
    ) == {"payload": {"parent_id": "list-1", "title": "변경"}}
