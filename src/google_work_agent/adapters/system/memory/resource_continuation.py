"""Process-local implementation of the resource continuation boundary."""

from collections.abc import Callable
from dataclasses import dataclass
from secrets import token_urlsafe
from threading import RLock
from time import time

from google_work_agent.ports.system.resource_continuation_invalid_error import (
    ResourceContinuationInvalidError,
)
from google_work_agent.ports.system.resource_continuation_port import (
    ResourceContinuationScope,
)


@dataclass(frozen=True, slots=True)
class _StoredContinuation:
    scope: ResourceContinuationScope
    provider_page_token: str
    expires_at_ms: int


class InMemoryResourceContinuationAdapter:
    """Keep provider cursors behind expiring local opaque handles."""

    def __init__(
        self,
        *,
        token_factory: Callable[[], str] | None = None,
        now_ms: Callable[[], int] | None = None,
        ttl_ms: int = 300_000,
    ) -> None:
        if ttl_ms < 1:
            raise ValueError("resource continuation TTL must be positive")
        self._token_factory = token_factory or (lambda: token_urlsafe(24))
        self._now_ms = now_ms or (lambda: int(time() * 1000))
        self._ttl_ms = ttl_ms
        self._values: dict[str, _StoredContinuation] = {}
        self._lock = RLock()

    def issue(
        self,
        *,
        scope: ResourceContinuationScope,
        provider_page_token: str,
    ) -> str:
        if not provider_page_token:
            raise ValueError("provider page token must be non-empty")
        local_handle = self._token_factory()
        if not local_handle:
            raise RuntimeError("local continuation factory returned an empty handle")
        with self._lock:
            if local_handle in self._values:
                raise RuntimeError("local continuation handle collision")
            self._values[local_handle] = _StoredContinuation(
                scope=scope,
                provider_page_token=provider_page_token,
                expires_at_ms=self._now_ms() + self._ttl_ms,
            )
        return local_handle

    def resolve(
        self,
        *,
        scope: ResourceContinuationScope,
        local_handle: str,
    ) -> str:
        with self._lock:
            stored = self._values.get(local_handle)
            if stored is not None and stored.expires_at_ms <= self._now_ms():
                self._values.pop(local_handle, None)
                stored = None
        if stored is None or stored.scope != scope:
            raise ResourceContinuationInvalidError(
                "local resource continuation is invalid for this query"
            )
        return stored.provider_page_token


__all__ = ["InMemoryResourceContinuationAdapter"]
