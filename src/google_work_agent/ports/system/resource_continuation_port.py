"""Boundary for issuing and resolving server-local resource continuations."""

from typing import Protocol

type ResourceContinuationScope = tuple[str, ...]


class ResourceContinuationPort(Protocol):
    def issue(
        self,
        *,
        scope: ResourceContinuationScope,
        provider_page_token: str,
    ) -> str: ...

    def resolve(
        self,
        *,
        scope: ResourceContinuationScope,
        local_handle: str,
    ) -> str: ...


__all__ = ["ResourceContinuationPort", "ResourceContinuationScope"]
