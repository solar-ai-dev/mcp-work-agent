from __future__ import annotations

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
from google_work_agent.ports.connector.connector_read_port import ConnectorReadResultV1
from google_work_agent.ports.connector.contracts.validated_connector_tool_binding import (
    ValidatedConnectorToolBindingV1,
)


@dataclass
class _ReadPort:
    payload: dict[str, object]
    binding: ValidatedConnectorToolBindingV1 | None = None

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
            {"item": {"payload": self.payload}},
            None,
            None,
        )


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
