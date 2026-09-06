from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import pytest

from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.application.use_cases.verification.verify_effect import (
    SelectedResourceRefV1,
    VerifyEffectHandler,
    VerifyEffectQueryV1,
)
from google_work_agent.ports.connector.connector_read_port import ConnectorReadResultV1, JsonValue
from google_work_agent.ports.connector.contracts.validated_connector_tool_binding import (
    ValidatedConnectorToolBindingV1,
)


@dataclass
class _ReadPort:
    payload: dict[str, object]
    binding: ValidatedConnectorToolBindingV1 | None = None
    resource_id: str | None = None

    def execute_read(
        self,
        binding: ValidatedConnectorToolBindingV1,
        _arguments: dict[str, object],
    ) -> ConnectorReadResultV1:
        self.binding = binding
        return ConnectorReadResultV1(
            1,
            binding.tool_id,
            "request-1",
            {"item": {
                "payload": cast(dict[str, JsonValue], self.payload),
                **({"resource_id": self.resource_id} if self.resource_id is not None else {}),
            }},
            None,
            None,
        )


@pytest.mark.parametrize("body_present", [True, False])
def test_gmail_verification__absent_reply_headers_are_optional__body_is_required(
    body_present: bool,
) -> None:
    expected: dict[str, object] = {
        "to": ["to@example.com"], "cc": [], "bcc": [], "subject": "회신",
        "body": "", "attachments": [], "in_reply_to": None, "references": None, "sent": True,
    }
    actual = {k: v for k, v in expected.items() if k not in {"in_reply_to", "references"}}
    if not body_present:
        actual.pop("body")
    read = _ReadPort(actual, resource_id="message-1")
    result = VerifyEffectHandler(
        connector_read=read,  # type: ignore[arg-type]
        tool_registry=load_signed_tool_registry(),
    )(VerifyEffectQueryV1(
        "run-1", "action-1", "attempt-1", "SEND", {"payload": expected},
        SelectedResourceRefV1(1, "ref-1", "google_workspace", "gmail_message", "message-1", None),
    ))
    assert result.status == ("VERIFIED" if body_present else "MISMATCH")
    assert read.binding is not None and read.binding.tool_id == "gmail_get_message"


def test_verify_effect__has_exact__application_owner() -> None:
    assert (
        VerifyEffectHandler.__module__
        == "google_work_agent.application.use_cases.verification.verify_effect"
    )
    assert VerifyEffectHandler.__name__ == "VerifyEffectHandler"


@pytest.mark.parametrize(
    ("expected", "actual"),
    [
        (
            {"title": "created", "body": "approved"},
            {
                "title": "created",
                "description": (
                    "approved\n\n<!-- gwa-recovery-fingerprint:fingerprint-1 -->"
                ),
                "state": "OPEN",
            },
        ),
        ({"title": "changed"}, {"title": "changed", "description": "unchanged"}),
        ({"state": "CLOSED"}, {"title": "x", "description": "", "state": "CLOSED"}),
        ({"state": "OPEN"}, {"title": "x", "description": "", "state": "OPEN"}),
    ],
)
def test_github_verification__uses_connector_read__and_approved_subset(
    expected: dict[str, object], actual: dict[str, object]
) -> None:
    read = _ReadPort(actual)
    handler = VerifyEffectHandler(
        connector_read=read,  # type: ignore[arg-type]
        tool_registry=load_signed_tool_registry(),
    )

    result = handler(
        VerifyEffectQueryV1(
            run_id="run-1",
            action_id="action-1",
            execution_attempt_id="attempt-1",
            effect="UPDATE",
            expected_effect=expected,
            target_resource_ref=SelectedResourceRefV1(
                1,
                "ref-1",
                "github",
                "github_issue",
                "acme/repo#7",
                "acme/repo",
            ),
        )
    )

    assert result.status == "VERIFIED"
    assert read.binding is not None
    assert (read.binding.connector_id, read.binding.tool_id) == (
        "github",
        "github_get_issue",
    )


def test_github_verification__provider_differs_from_approval__cannot_succeed() -> None:
    read = _ReadPort({"title": "unapproved title", "description": "body", "state": "OPEN"})
    handler = VerifyEffectHandler(
        connector_read=read,  # type: ignore[arg-type]
        tool_registry=load_signed_tool_registry(),
    )
    result = handler(VerifyEffectQueryV1(
        run_id="run-1", action_id="action-1", execution_attempt_id="attempt-1",
        effect="UPDATE", expected_effect={"title": "approved title"},
        target_resource_ref=SelectedResourceRefV1(
            1, "ref-1", "github", "github_issue", "acme/repo#7", "acme/repo",
        ),
    ))
    assert result.status != "VERIFIED"
