from __future__ import annotations

from collections.abc import Mapping


def project_retrieval_source_statuses(
    state: Mapping[str, object],
) -> list[dict[str, object]]:
    retrieval = state.get("retrieval_result")
    if not isinstance(retrieval, Mapping):
        return []
    statuses = retrieval.get("source_statuses", [])
    if not isinstance(statuses, list) or not all(
        isinstance(item, Mapping) for item in statuses
    ):
        raise ValueError("retrieval source_statuses must be objects")
    return [dict(item) for item in statuses]


__all__ = ["project_retrieval_source_statuses"]
