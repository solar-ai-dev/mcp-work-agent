"""Normalize a local resource-continuation error for API-facing use cases."""

from google_work_agent.ports.connector.connector_failure import (
    ConnectorFailureCode,
    ConnectorOperationFailure,
)
from google_work_agent.ports.system.resource_continuation_invalid_error import (
    ResourceContinuationInvalidError,
)


def normalize_resource_continuation_error(
    error: ResourceContinuationInvalidError,
) -> ConnectorOperationFailure:
    return ConnectorOperationFailure(
        code=ConnectorFailureCode.INVALID_ARGUMENT,
        detail_code="RESOURCE_CONTINUATION_INVALID",
        safe_description=str(error),
    )


__all__ = ["normalize_resource_continuation_error"]
