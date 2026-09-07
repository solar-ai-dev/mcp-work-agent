"""Failure raised when a local resource continuation is invalid or stale."""


class ResourceContinuationInvalidError(ValueError):
    pass


__all__ = ["ResourceContinuationInvalidError"]
