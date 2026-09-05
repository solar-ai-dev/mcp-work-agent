"""stdio entrypoint and protocol envelope for the GitHub MCP process."""

from __future__ import annotations

import json
import sys
from typing import cast

from google_work_agent.adapters.connectors.github.issues.issues.issue_contract import (
    GitHubIssueQueryError,
)
from google_work_agent.adapters.connectors.runtime.stdio_mcp_client import PROTOCOL_VERSION

from .composition import GitHubMcpServerState
from .dispatch_tool import (
    ControlCallError,
    ToolNotAvailableError,
    dispatch_control,
    dispatch_github_tool,
)
from .github_api import GitHubProviderError
from .oauth_device_flow import GitHubOAuthConfigurationError
from .project_registry import (
    GitHubToolContractViolation,
    get_projected_github_tool,
    github_registry_manifest_hash,
    project_github_registry,
    validate_github_tool_input,
    validate_github_tool_output,
)
from .validate_claim_context import GitHubClaimError


def github_mcp_main() -> None:
    state = GitHubMcpServerState()
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        request = cast(dict[str, object], json.loads(line))
        request_id = str(request.get("id", ""))
        if str(request.get("type")) == "shutdown":
            break
        try:
            _write({"id": request_id, "payload": dispatch_request(state, request)})
        except ToolNotAvailableError:
            _write_error(request_id, "TOOL_REJECTED", "TOOL_NOT_AVAILABLE", "NOT_SENT")
        except GitHubOAuthConfigurationError as error:
            _write_error(request_id, "CONFIGURATION_ERROR", error.safe_code, "NOT_SENT")
        except ControlCallError as error:
            _write_error(request_id, error.code, error.message, "NOT_SENT")
        except (GitHubIssueQueryError, GitHubToolContractViolation) as error:
            message = getattr(error, "safe_code", "INVALID_ARGUMENT")
            _write_error(request_id, "TOOL_REJECTED", str(message), "NOT_SENT")
        except GitHubClaimError as error:
            _write_error(request_id, "TOOL_REJECTED", error.safe_code, "NOT_SENT")
        except GitHubProviderError as error:
            _write_error(
                request_id,
                _provider_error_code(error.safe_code),
                error.safe_code,
                error.delivery_certainty.value,
            )
        except Exception:
            _write_error(
                request_id,
                "MALFORMED_RESPONSE",
                "MCP request failed.",
                "MAY_HAVE_BEEN_SENT",
            )


def dispatch_request(
    state: GitHubMcpServerState, request: dict[str, object]
) -> dict[str, object]:
    message_type = str(request["type"])
    if message_type == "handshake":
        session_key = str(request["session_key"])
        if len(bytes.fromhex(session_key)) < 32:
            raise ValueError("session key must be at least 256 bits")
        state.service_instance_id = str(request["service_instance_id"])
        state.session_key = session_key
        return {"process_instance_id": state.process_instance_id}
    if message_type == "initialize":
        expected_hash = github_registry_manifest_hash()
        if str(request["registry_manifest_hash"]) != expected_hash:
            raise GitHubToolContractViolation("REGISTRY_PROJECTION_MISMATCH")
        return {
            "protocol_version": PROTOCOL_VERSION,
            "manifest_version": str(request["manifest_version"]),
            "registry_manifest_hash": expected_hash,
        }
    if message_type == "list_tools":
        projected = project_github_registry()
        if {descriptor.tool_id for descriptor in projected} != set(state.operations()):
            raise GitHubToolContractViolation("DECLARED_TOOL_SURFACE_MISMATCH")
        return {"tool_names": [descriptor.tool_id for descriptor in projected]}
    if message_type == "control_call":
        return dispatch_control(
            state,
            method=str(request["method"]),
            arguments=cast(dict[str, object], request.get("arguments", {})),
        )
    if message_type == "tool_call":
        tool_name = str(request["tool_name"])
        arguments = cast(dict[str, object], request.get("arguments", {}))
        if (
            get_projected_github_tool(tool_name) is None
            and tool_name != "search_by_recovery_fingerprint"
        ):
            raise ToolNotAvailableError(tool_name)
        validate_github_tool_input(tool_name, arguments)
        output = dispatch_github_tool(
            state,
            tool_name=tool_name,
            arguments=arguments,
        )
        validate_github_tool_output(tool_name, output)
        return output
    raise ValueError("unsupported message type")


def _write_error(
    request_id: str,
    code: str,
    message: str,
    delivery_certainty: str,
) -> None:
    _write(
        {
            "id": request_id,
            "error": {
                "code": code,
                "message": message,
                "delivery_certainty": delivery_certainty,
            },
        }
    )


def _provider_error_code(safe_code: str) -> str:
    return {
        "REAUTH_REQUIRED": "AUTH_REQUIRED",
        "PERMISSION_DENIED": "PERMISSION_DENIED",
        "NOT_FOUND": "NOT_FOUND",
        "MALFORMED_RESPONSE": "MALFORMED_RESPONSE",
    }.get(safe_code, "TOOL_REJECTED")


def _write(payload: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, sort_keys=True) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    github_mcp_main()
