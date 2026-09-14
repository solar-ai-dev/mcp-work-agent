"""Project source-owned collection metadata for Planning answer Prompts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence


def retrieval_collections_are_answer_target(
    *,
    request_intent: Mapping[str, object],
    evidence: Sequence[Mapping[str, object]],
    retrieval_result: Mapping[str, object],
) -> bool:
    """Keep collection metadata only when typed intent or selected evidence targets it."""
    constraints = request_intent.get("constraints", [])
    if isinstance(constraints, list) and any(
        isinstance(item, Mapping)
        and item.get("kind") == "SCOPE"
        and item.get("field") == "coverage_requirement"
        and item.get("value") == "EXHAUSTIVE"
        for item in constraints
    ):
        return True

    selected_handles = {
        handle
        for item in evidence
        if isinstance((handle := item.get("resource_handle")), str) and handle
    }
    if not selected_handles:
        return False
    collection_handles = {
        handle
        for result in _mappings(retrieval_result.get("collection_results"))
        for item in _mappings(result.get("items"))
        if isinstance(
            (handle := item.get("resource_handle") or item.get("resource_ref")), str
        )
        and handle
    }
    return bool(selected_handles & collection_handles)


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


def _mappings(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


__all__ = ["project_retrieval_collections", "retrieval_collections_are_answer_target"]
