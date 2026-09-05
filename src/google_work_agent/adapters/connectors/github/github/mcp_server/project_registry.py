"""GitHub MCP projection and connector-local request/response contracts."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from string import hexdigits
from typing import cast

from google_work_agent.ports.connector.mcp_client_port import MCPToolDescriptorV1

GITHUB_CONNECTOR_ID = "github"
GITHUB_RESOURCE_TYPE = "github_issue"
WRITE_TOOL_IDS = frozenset(
    {
        "github_create_issue",
        "github_update_issue",
        "github_close_issue",
        "github_reopen_issue",
    }
)


class GitHubToolContractViolation(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class GitHubIssueToolContract:
    tool_id: str
    effect: str
    required_fields: frozenset[str]
    optional_fields: frozenset[str]
    input_schema_ref: str = "v1"
    output_schema_ref: str = "v1"
    resource_type: str = GITHUB_RESOURCE_TYPE


_CONTRACTS = {
    "github_list_issues": GitHubIssueToolContract(
        "github_list_issues",
        "READ",
        frozenset({"repository"}),
        frozenset({"state", "assignee", "label"}),
    ),
    "github_get_issue": GitHubIssueToolContract(
        "github_get_issue",
        "READ",
        frozenset({"repository", "issue_number"}),
        frozenset(),
    ),
    "github_create_issue": GitHubIssueToolContract(
        "github_create_issue",
        "CREATE",
        frozenset({"repository", "title"}),
        frozenset({"body", "recovery_fingerprint", "claim_context"}),
    ),
    "github_update_issue": GitHubIssueToolContract(
        "github_update_issue",
        "UPDATE",
        frozenset({"repository", "issue_number"}),
        frozenset({"title", "body", "claim_context"}),
    ),
    "github_close_issue": GitHubIssueToolContract(
        "github_close_issue",
        "UPDATE",
        frozenset({"repository", "issue_number"}),
        frozenset({"claim_context"}),
    ),
    "github_reopen_issue": GitHubIssueToolContract(
        "github_reopen_issue",
        "UPDATE",
        frozenset({"repository", "issue_number"}),
        frozenset({"claim_context"}),
    ),
}

_DEFAULT_PROJECTION = Path(__file__).with_name("tool_descriptor_projection.json")
_PROJECTION_PATH_ENV = "GWA_MCP_TOOL_PROJECTION_PATH"
_PROJECTION_FIELDS = frozenset(
    {"schema_version", "connector_id", "registry_manifest_hash", "tools"}
)
_TOOL_FIELDS = frozenset(
    {
        "schema_version",
        "connector_id",
        "tool_id",
        "input_schema_ref",
        "output_schema_ref",
        "registry_entry_hash",
    }
)


def github_issue_tool_contract(tool_id: str) -> GitHubIssueToolContract:
    try:
        return _CONTRACTS[tool_id]
    except KeyError as error:
        raise GitHubToolContractViolation("TOOL_NOT_AVAILABLE") from error


def validate_github_tool_input(tool_id: str, arguments: dict[str, object]) -> None:
    if tool_id == "search_by_recovery_fingerprint":
        if frozenset(arguments) != {"repository", "recovery_fingerprint"}:
            raise GitHubToolContractViolation("recovery search input is invalid")
        repository = arguments.get("repository")
        fingerprint = arguments.get("recovery_fingerprint")
        if (
            not isinstance(repository, str)
            or len(repository.split("/")) != 2
            or any(not part.strip() for part in repository.split("/"))
            or not isinstance(fingerprint, str)
            or not fingerprint.strip()
        ):
            raise GitHubToolContractViolation("recovery search input is invalid")
        return
    contract = github_issue_tool_contract(tool_id)
    actual = frozenset(arguments)
    if not contract.required_fields.issubset(actual):
        raise GitHubToolContractViolation("required input field is missing")
    if not actual.issubset(contract.required_fields | contract.optional_fields):
        raise GitHubToolContractViolation("input field is not allowed")
    repository = arguments.get("repository")
    if (
        not isinstance(repository, str)
        or len(repository.split("/")) != 2
        or any(not part.strip() for part in repository.split("/"))
    ):
        raise GitHubToolContractViolation("repository is invalid")
    issue_number = arguments.get("issue_number")
    if "issue_number" in actual and (
        not isinstance(issue_number, int)
        or isinstance(issue_number, bool)
        or issue_number < 1
    ):
        raise GitHubToolContractViolation("issue_number is invalid")
    for field in ("title", "body", "assignee", "label", "recovery_fingerprint"):
        value = arguments.get(field)
        if field in actual and (not isinstance(value, str) or not value.strip()):
            raise GitHubToolContractViolation(f"{field} is invalid")
    state = arguments.get("state")
    if state is not None and (
        not isinstance(state, str)
        or state.upper() not in {"OPEN", "CLOSED", "ALL"}
    ):
        raise GitHubToolContractViolation("state is invalid")
    if tool_id == "github_update_issue" and not ({"title", "body"} & actual):
        raise GitHubToolContractViolation("update requires title or body")


def validate_github_tool_output(tool_id: str, output: dict[str, object]) -> None:
    if tool_id == "search_by_recovery_fingerprint":
        if (
            frozenset(output) != {"items", "coverage_complete", "examined_count"}
            or not isinstance(output.get("items"), list)
            or not isinstance(output.get("coverage_complete"), bool)
            or not isinstance(output.get("examined_count"), int)
        ):
            raise GitHubToolContractViolation("recovery search output is invalid")
        return
    contract = github_issue_tool_contract(tool_id)
    key = "items" if tool_id == "github_list_issues" else "item"
    if frozenset(output) != {key}:
        raise GitHubToolContractViolation("output envelope is invalid")
    values = output[key] if key == "items" else [output[key]]
    if not isinstance(values, list):
        raise GitHubToolContractViolation("output items are invalid")
    for value in values:
        if not isinstance(value, dict):
            raise GitHubToolContractViolation("output snapshot is invalid")
        snapshot = cast(dict[str, object], value)
        if snapshot.get("resource_type") != contract.resource_type:
            raise GitHubToolContractViolation("output resource_type is invalid")
        if not all(
            isinstance(snapshot.get(field), str) and bool(str(snapshot[field]).strip())
            for field in ("resource_id", "parent_id")
        ):
            raise GitHubToolContractViolation("output resource identity is invalid")
        if not isinstance(snapshot.get("payload"), dict):
            raise GitHubToolContractViolation("output payload is invalid")


def project_github_registry(path: Path | None = None) -> tuple[MCPToolDescriptorV1, ...]:
    projection_path = path or Path(os.environ.get(_PROJECTION_PATH_ENV, _DEFAULT_PROJECTION))
    decoded = json.loads(projection_path.read_text(encoding="utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("tool descriptor projection must be an object")
    payload = cast(dict[str, object], decoded)
    _require_exact_fields(payload, _PROJECTION_FIELDS, "tool descriptor projection")
    if payload.get("schema_version") != 1 or payload.get("connector_id") != GITHUB_CONNECTOR_ID:
        raise ValueError("invalid GitHub MCP projection identity")
    raw_tools = payload.get("tools")
    if not isinstance(raw_tools, list) or not raw_tools:
        raise ValueError("tool descriptor projection tools must be a non-empty list")
    tools = tuple(_descriptor(_require_object(item)) for item in raw_tools)
    if len({tool.tool_id for tool in tools}) != len(tools):
        raise ValueError("duplicate tool_id in GitHub MCP projection")
    if {tool.tool_id for tool in tools} != set(_CONTRACTS):
        raise ValueError("GitHub MCP projection does not match operation contracts")
    return tuple(sorted(tools, key=lambda tool: tool.tool_id))


def github_registry_manifest_hash(path: Path | None = None) -> str:
    projection_path = path or Path(os.environ.get(_PROJECTION_PATH_ENV, _DEFAULT_PROJECTION))
    payload = cast(dict[str, object], json.loads(projection_path.read_text(encoding="utf-8")))
    value = str(payload.get("registry_manifest_hash", ""))
    _validate_hash(value, "registry_manifest_hash")
    return value


def get_projected_github_tool(tool_id: str) -> MCPToolDescriptorV1 | None:
    return next(
        (tool for tool in project_github_registry() if tool.tool_id == tool_id),
        None,
    )


def _descriptor(payload: dict[str, object]) -> MCPToolDescriptorV1:
    _require_exact_fields(payload, _TOOL_FIELDS, "MCPToolDescriptorV1")
    if payload.get("schema_version") != 1 or payload.get("connector_id") != GITHUB_CONNECTOR_ID:
        raise ValueError("invalid projected tool identity")
    _validate_hash(str(payload.get("registry_entry_hash", "")), "registry_entry_hash")
    return MCPToolDescriptorV1(
        schema_version=1,
        connector_id=GITHUB_CONNECTOR_ID,
        tool_id=str(payload["tool_id"]),
        input_schema_ref=str(payload["input_schema_ref"]),
        output_schema_ref=str(payload["output_schema_ref"]),
        registry_entry_hash=str(payload["registry_entry_hash"]),
    )


def _require_object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("MCPToolDescriptorV1 must be an object")
    return cast(dict[str, object], value)


def _require_exact_fields(
    payload: dict[str, object], expected: frozenset[str], contract_name: str
) -> None:
    actual = frozenset(payload)
    if actual != expected:
        raise ValueError(
            f"{contract_name} fields mismatch: missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )


def _validate_hash(value: str, field_name: str) -> None:
    if (
        len(value) != 64
        or value != value.lower()
        or any(character not in hexdigits for character in value)
    ):
        raise ValueError(f"{field_name} must be lowercase SHA-256")


__all__ = [
    "GITHUB_CONNECTOR_ID",
    "GITHUB_RESOURCE_TYPE",
    "GitHubIssueToolContract",
    "GitHubToolContractViolation",
    "WRITE_TOOL_IDS",
    "get_projected_github_tool",
    "github_issue_tool_contract",
    "project_github_registry",
    "github_registry_manifest_hash",
    "validate_github_tool_input",
    "validate_github_tool_output",
]
