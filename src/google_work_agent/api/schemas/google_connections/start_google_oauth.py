"""Canonical Google OAuth start wire contracts."""

from typing import Literal

from google_work_agent.api.schemas.model import ApiModel


class StartAuthorizationRequestV1(ApiModel):
    schema_version: Literal[1]
    command_id: str


class AuthorizationStartV1(ApiModel):
    schema_version: Literal[1]
    authorization_url: str
    callback_id: str
    flow_kind: Literal["AUTHORIZATION_CODE", "DEVICE_CODE"] = "AUTHORIZATION_CODE"
    verification_uri: str | None = None
    user_code: str | None = None
    expires_at_ms: int | None = None
    poll_interval_seconds: int | None = None


__all__ = ["AuthorizationStartV1", "StartAuthorizationRequestV1"]
