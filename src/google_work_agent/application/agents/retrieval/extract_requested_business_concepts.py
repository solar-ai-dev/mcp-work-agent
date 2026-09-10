"""Extract business concepts explicitly carried by the current request."""

from __future__ import annotations

from collections.abc import Mapping


def extract_requested_business_concepts(value: object) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {
        entry
        for item in value
        if isinstance(item, Mapping)
        and item.get("kind") == "USER_REQUIREMENT"
        and item.get("field") == "business_concepts"
        for entry in (item["value"] if isinstance(item.get("value"), list) else [item.get("value")])
        if isinstance(entry, str) and entry
    }
