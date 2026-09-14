from __future__ import annotations

import pytest

from google_work_agent.adapters.system.memory.resource_continuation import (
    InMemoryResourceContinuationAdapter,
)
from google_work_agent.ports.system.resource_continuation_invalid_error import (
    ResourceContinuationInvalidError,
)


def test_continuation__is_reusable_within_scope__and_expires() -> None:
    now_ms = 100
    store = InMemoryResourceContinuationAdapter(
        token_factory=lambda: "local-bound",
        now_ms=lambda: now_ms,
        ttl_ms=10,
    )
    scope = ("a" * 64, "account-1", "gmail", "", "20", "metadata")
    handle = store.issue(scope=scope, provider_page_token="provider-secret")

    assert store.resolve(scope=scope, local_handle=handle) == "provider-secret"
    assert store.resolve(scope=scope, local_handle=handle) == "provider-secret"

    with pytest.raises(ResourceContinuationInvalidError):
        store.resolve(
            scope=("b" * 64, "account-1", "gmail", "", "20", "metadata"),
            local_handle=handle,
        )
    with pytest.raises(ResourceContinuationInvalidError):
        store.resolve(
            scope=("a" * 64, "account-2", "gmail", "", "20", "metadata"),
            local_handle=handle,
        )

    now_ms = 110
    with pytest.raises(ResourceContinuationInvalidError):
        store.resolve(scope=scope, local_handle=handle)
