"""GitHub write ClaimContextV2 validation authority."""

from __future__ import annotations

import hashlib
import hmac
import json

from google_work_agent.domain.canonical import calculate_canonical_json_hash
from google_work_agent.ports.connector.claim_context_contract import CLAIM_CONTEXT_MAX_TTL_MS

from .composition import GitHubMcpServerState

CLAIM_CONTEXT_VERSION = 2
CLAIM_CONTEXT_REQUIRED_FIELDS = (
    "claim_version",
    "connector_id",
    "service_instance_id",
    "mcp_process_instance_id",
    "action_id",
    "approval_id",
    "execution_attempt_id",
    "tool_name",
    "approval_arguments_hash",
    "execution_arguments_hash",
    "issued_at_ms",
    "expires_at_ms",
    "nonce",
    "signature",
)


class GitHubClaimError(PermissionError):
    def __init__(self, safe_code: str) -> None:
        super().__init__(safe_code)
        self.safe_code = safe_code


def validate_github_claim_context(
    state: GitHubMcpServerState,
    *,
    tool_name: str,
    claim_context: object,
    execution_arguments: dict[str, object],
) -> None:
    if state.session_key is None or state.service_instance_id is None:
        raise GitHubClaimError("CLAIM_SERVICE_UNAVAILABLE")
    if not isinstance(claim_context, dict):
        raise GitHubClaimError("CLAIM_MISSING")
    claim = claim_context
    if any(field not in claim for field in CLAIM_CONTEXT_REQUIRED_FIELDS):
        raise GitHubClaimError("CLAIM_MISSING")
    if claim.get("claim_version") != CLAIM_CONTEXT_VERSION:
        raise GitHubClaimError("CLAIM_VERSION_MISMATCH")
    signature = claim.get("signature")
    if not isinstance(signature, str) or not signature:
        raise GitHubClaimError("CLAIM_INVALID_SIGNATURE")
    unsigned = {key: value for key, value in claim.items() if key != "signature"}
    normalized = json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")
    expected_signature = hmac.new(
        bytes.fromhex(state.session_key), normalized, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        raise GitHubClaimError("CLAIM_INVALID_SIGNATURE")
    for field in ("action_id", "approval_id", "execution_attempt_id"):
        if not isinstance(claim.get(field), str) or not claim[field]:
            raise GitHubClaimError("CLAIM_MALFORMED")
    if claim.get("connector_id") != "github":
        raise GitHubClaimError("CLAIM_CONNECTOR_MISMATCH")
    if claim.get("tool_name") != tool_name:
        raise GitHubClaimError("CLAIM_TOOL_MISMATCH")
    if claim.get("service_instance_id") != state.service_instance_id:
        raise GitHubClaimError("CLAIM_SERVICE_INSTANCE_MISMATCH")
    if claim.get("mcp_process_instance_id") != state.process_instance_id:
        raise GitHubClaimError("CLAIM_PROCESS_INSTANCE_MISMATCH")
    issued_at_ms = claim.get("issued_at_ms")
    expires_at_ms = claim.get("expires_at_ms")
    if not isinstance(issued_at_ms, int) or not isinstance(expires_at_ms, int):
        raise GitHubClaimError("CLAIM_MALFORMED")
    if expires_at_ms <= issued_at_ms or expires_at_ms - issued_at_ms > CLAIM_CONTEXT_MAX_TTL_MS:
        raise GitHubClaimError("CLAIM_TTL_EXCEEDED")
    if state.now_ms() >= expires_at_ms:
        raise GitHubClaimError("CLAIM_EXPIRED")
    nonce = claim.get("nonce")
    if not isinstance(nonce, str) or not nonce:
        raise GitHubClaimError("CLAIM_MALFORMED")
    if nonce in state.used_nonces:
        raise GitHubClaimError("CLAIM_TOKEN_REUSED")
    for field in ("approval_arguments_hash", "execution_arguments_hash"):
        if not isinstance(claim.get(field), str) or not claim[field]:
            raise GitHubClaimError("CLAIM_MALFORMED")
    actual_hash = calculate_canonical_json_hash(execution_arguments)
    if not hmac.compare_digest(actual_hash, str(claim["execution_arguments_hash"])):
        raise GitHubClaimError("CLAIM_ARGUMENTS_MISMATCH")
    state.used_nonces.add(nonce)


__all__ = ["GitHubClaimError", "validate_github_claim_context"]
