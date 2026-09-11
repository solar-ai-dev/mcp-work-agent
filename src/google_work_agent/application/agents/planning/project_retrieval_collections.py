"""Project source-owned collection metadata for Planning answer Prompts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence


def project_retrieval_collections(
    retrieval_result: Mapping[str, object],
) -> list[dict[str, object]]:
    raw_results = retrieval_result.get("collection_results", [])
    if not isinstance(raw_results, Sequence) or isinstance(raw_results, (str, bytes)):
        raise ValueError("retrieval collection_results must be a sequence")
    projected: list[dict[str, object]] = []
    for raw_result in raw_results:
        if not isinstance(raw_result, Mapping):
            raise ValueError("retrieval collection result must be an object")
        raw_items = raw_result.get("items", [])
        if not isinstance(raw_items, Sequence) or isinstance(raw_items, (str, bytes)):
            raise ValueError("retrieval collection items must be a sequence")
        items: list[dict[str, object]] = []
        for index, raw_item in enumerate(raw_items):
            if not isinstance(raw_item, Mapping):
                raise ValueError("retrieval collection item must be an object")
            title = raw_item.get("title")
            if title is not None and not isinstance(title, str):
                raise ValueError("retrieval collection title must be a string or null")
            items.append({"item_number": index + 1, "title": title})
        resource_type = raw_result.get("resource_type")
        continuation = raw_result.get("continuation_status")
        if not isinstance(resource_type, str) or continuation not in {
            "EXHAUSTED",
            "HAS_MORE",
            "UNKNOWN",
        }:
            raise ValueError("retrieval collection result metadata is invalid")
        projected.append(
            {
                "resource_type": resource_type,
                "continuation_status": continuation,
                "items": items,
            }
        )
    return projected


__all__ = ["project_retrieval_collections"]
