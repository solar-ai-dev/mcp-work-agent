from __future__ import annotations

from dataclasses import dataclass, field, replace

import pytest

from google_work_agent.adapters.connectors.github.github.composition import (
    github_internal_read_binding,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.application.use_cases.recovery.lookup_unknown_result import (
    LookupUnknownResultHandler,
    LookupUnknownResultQueryV1,
)
from google_work_agent.application.use_cases.verification.verify_effect import (
    SelectedResourceRefV1,
)
from google_work_agent.ports.connector.connector_failure import (
    ConnectorFailureCode,
    ConnectorOperationFailure,
)
from google_work_agent.ports.connector.connector_read_port import ConnectorReadResultV1
from google_work_agent.ports.connector.contracts.validated_connector_tool_binding import (
    ValidatedConnectorToolBindingV1,
)


@dataclass
class _ReadPort:
    responses: list[dict[str, object]]
    calls: list[tuple[str, str, dict[str, object]]] = field(default_factory=list)

    def execute_read(
        self,
        binding: ValidatedConnectorToolBindingV1,
        arguments: dict[str, object],
    ) -> ConnectorReadResultV1:
        self.calls.append((binding.connector_id, binding.tool_id, arguments))
        return ConnectorReadResultV1(
            1,
            binding.tool_id,
            f"request-{len(self.calls)}",
            self.responses.pop(0),  # type: ignore[arg-type]
            None,
            None,
        )


@dataclass
class _SecondReadFailurePort(_ReadPort):
    def execute_read(
        self,
        binding: ValidatedConnectorToolBindingV1,
        arguments: dict[str, object],
    ) -> ConnectorReadResultV1:
        if self.calls:
            raise ConnectorOperationFailure(
                ConnectorFailureCode.UPSTREAM_UNAVAILABLE,
                "CONNECTOR_UPSTREAM_UNAVAILABLE",
                retryable=True,
            )
        return super().execute_read(binding, arguments)


def _handler(read: _ReadPort) -> LookupUnknownResultHandler:
    return LookupUnknownResultHandler(
        connector_read=read,  # type: ignore[arg-type]
        tool_registry=load_signed_tool_registry(),
        recovery_search_binding=github_internal_read_binding("search_by_recovery_fingerprint"),
    )


def _target() -> SelectedResourceRefV1:
    return SelectedResourceRefV1(
        1,
        "ref-1",
        "github",
        "github_issue",
        "acme/repo#7",
        "acme/repo",
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"connector_id": "google_workspace"},
        {"parent_resource_id": "other/repo"},
        {"resource_id": "acme/repo#07"},
        {"resource_id": "acme/r?x=1#7", "parent_resource_id": "acme/r?x=1"},
    ],
)
def test_github_recovery__invalid_binding__prevents_read(changes: dict[str, str]) -> None:
    read = _ReadPort([])
    with pytest.raises(ValueError, match="identity"):
        _handler(read)(
            LookupUnknownResultQueryV1(
                "run",
                "action",
                "attempt",
                "UPDATE",
                "fingerprint",
                replace(
                    _target(),
                    connector_id=changes.get("connector_id", "github"),
                    parent_resource_id=changes.get("parent_resource_id", "acme/repo"),
                    resource_id=changes.get("resource_id", "acme/repo#7"),
                ),
            )
        )
    assert read.calls == []


def test_github_recovery__same_content_wrong_issue__is_not_proof() -> None:
    read = _ReadPort([{"item": {"resource_id": "acme/repo#8", "payload": {"state": "CLOSED"}}}])
    result = _handler(read)(
        LookupUnknownResultQueryV1(
            "run",
            "action",
            "attempt",
            "UPDATE",
            "fingerprint",
            _target(),
            "github_close_issue",
            {"repository": "acme/repo", "issue_number": 7},
        )
    )
    assert result.disposition == "UNRESOLVED"


def test_github_create_recovery__wrong_connector__prevents_search() -> None:
    read = _ReadPort([])
    with pytest.raises(ValueError, match="identity"):
        _handler(read)(
            LookupUnknownResultQueryV1(
                "run",
                "action",
                "attempt",
                "CREATE",
                "fingerprint",
                replace(_target(), connector_id="google_workspace"),
            )
        )
    assert read.calls == []


def test_lookup_unknown_result__has_exact__application_owner() -> None:
    assert (
        LookupUnknownResultHandler.__module__
        == "google_work_agent.application.use_cases.recovery.lookup_unknown_result"
    )
    assert LookupUnknownResultHandler.__name__ == "LookupUnknownResultHandler"


def test_recovery__revoked_resource__remains_unresolved(tmp_path) -> None:
    from google_work_agent.adapters.system.json_settings import (
        FileSettingsStore,
        JsonSettingsAdapter,
    )
    from google_work_agent.application.use_cases.resource.require_resource_selection import (
        RequireResourceSelectionHandler,
        SelectedResourceReadPort,
    )

    settings = replace(
        JsonSettingsAdapter(store=FileSettingsStore(tmp_path / "settings.json")).get_settings(),
        selected_github_repositories=(),
    )
    read = _ReadPort([])
    scoped = SelectedResourceReadPort(
        read, RequireResourceSelectionHandler(lambda: settings, lambda _: "account")
    )
    query = LookupUnknownResultQueryV1(
        "run", "action", "attempt", "CREATE", "fingerprint", _target()
    )
    result = _handler(scoped)(query)
    assert result.disposition == "UNRESOLVED" and result.reason_codes == ["RESOURCE_NOT_SELECTED"]
    assert read.calls == [] and query.target_resource_ref == _target()


def test_github_create_unknown__requires_unique_complete_search__then_get_compare() -> None:
    marker = "<!-- gwa-recovery-fingerprint:fingerprint-1 -->"
    candidate = {
        "resource_id": "acme/repo#7",
        "payload": {"title": "created", "description": f"approved\n\n{marker}"},
    }
    read = _ReadPort(
        [
            {"items": [candidate], "coverage_complete": True, "examined_count": 1},
            {"item": candidate},
        ]
    )

    result = _handler(read)(
        LookupUnknownResultQueryV1(
            "run-1",
            "action-1",
            "attempt-1",
            "CREATE",
            "fingerprint-1",
            SelectedResourceRefV1(
                1,
                "recovery-search-scope",
                "github",
                "github_issue",
                "recovery-search-scope",
                "acme/repo",
            ),
            "github_create_issue",
            {"repository": "acme/repo", "title": "created", "body": "approved"},
        )
    )

    assert result.disposition == "MUTATION_FOUND"
    assert [call[1] for call in read.calls] == [
        "search_by_recovery_fingerprint",
        "github_get_issue",
    ]


@pytest.mark.parametrize(
    "search_output",
    [
        {"items": [], "coverage_complete": True, "examined_count": 0},
        {
            "items": [{"resource_id": "acme/repo#7"}],
            "coverage_complete": False,
            "examined_count": 100,
        },
        {
            "items": [
                {"resource_id": "acme/repo#7"},
                {"resource_id": "acme/repo#8"},
            ],
            "coverage_complete": True,
            "examined_count": 2,
        },
    ],
)
def test_github_create_zero_ambiguous_or_incomplete_search__stays__unresolved(
    search_output: dict[str, object],
) -> None:
    read = _ReadPort([search_output])
    query = LookupUnknownResultQueryV1(
        "run-1",
        "action-1",
        "attempt-1",
        "CREATE",
        "fingerprint-1",
        SelectedResourceRefV1(
            1,
            "scope",
            "github",
            "github_issue",
            "scope",
            "acme/repo",
        ),
        "github_create_issue",
        {"repository": "acme/repo", "title": "created"},
    )

    assert _handler(read)(query).disposition == "UNRESOLVED"
    assert len(read.calls) == 1


def test_github_create_get_compare_error__stays__unresolved() -> None:
    read = _SecondReadFailurePort(
        [
            {
                "items": [
                    {
                        "resource_id": "acme/repo#7",
                        "payload": {
                            "description": ("<!-- gwa-recovery-fingerprint:fingerprint-1 -->")
                        },
                    }
                ],
                "coverage_complete": True,
                "examined_count": 1,
            }
        ]
    )

    result = _handler(read)(
        LookupUnknownResultQueryV1(
            "run-1",
            "action-1",
            "attempt-1",
            "CREATE",
            "fingerprint-1",
            SelectedResourceRefV1(
                1,
                "scope",
                "github",
                "github_issue",
                "scope",
                "acme/repo",
            ),
            "github_create_issue",
            {"repository": "acme/repo", "title": "created"},
        )
    )

    assert result.disposition == "UNRESOLVED"
    assert result.reason_codes == ["RECOVERY_GET_UPSTREAM_UNAVAILABLE"]


@pytest.mark.parametrize(
    ("tool_name", "arguments", "payload"),
    [
        (
            "github_update_issue",
            {"repository": "acme/repo", "issue_number": 7, "title": "changed"},
            {"title": "changed", "description": "concurrent body", "state": "OPEN"},
        ),
        (
            "github_close_issue",
            {"repository": "acme/repo", "issue_number": 7},
            {"title": "x", "description": "", "state": "CLOSED"},
        ),
        (
            "github_reopen_issue",
            {"repository": "acme/repo", "issue_number": 7},
            {"title": "x", "description": "", "state": "OPEN"},
        ),
    ],
)
def test_github_targeted_unknown__uses_get__compare(
    tool_name: str,
    arguments: dict[str, object],
    payload: dict[str, object],
) -> None:
    read = _ReadPort([{"item": {"resource_id": "acme/repo#7", "payload": payload}}])

    result = _handler(read)(
        LookupUnknownResultQueryV1(
            "run-1",
            "action-1",
            "attempt-1",
            "UPDATE",
            "fingerprint-1",
            _target(),
            tool_name,
            arguments,
        )
    )

    assert result.disposition == "MUTATION_FOUND"
    assert read.calls[0][1] == "github_get_issue"
