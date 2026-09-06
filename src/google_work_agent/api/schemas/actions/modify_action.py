"""Modify-action wire request."""

from pydantic import Field, model_validator

from google_work_agent.api.schemas.model import ContractVersionedRequest


class ModifyActionRequestV2(ContractVersionedRequest):
    command_id: str
    expected_version: int
    # Only business fields are accepted; authority metadata remains server-owned.
    arguments_patch: dict[str, object] = Field(default_factory=dict)
    modification_request: str | None = Field(default=None, min_length=1, max_length=2000)

    @model_validator(mode="after")
    def validate_modification_input(self) -> "ModifyActionRequestV2":
        if self.modification_request is not None and (
            not self.modification_request.strip() or self.arguments_patch
        ):
            raise ValueError("Use either a modification request or an arguments patch")
        return self
