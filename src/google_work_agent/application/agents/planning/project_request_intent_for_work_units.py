"""Project RequestIntentV3 and Evidence without re-interpreting WorkUnit ownership."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import cast

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV3,
)


def project_request_intent_for_work_units(
    request_intent: Mapping[str, object],
    *,
    work_unit_ids: Sequence[str],
) -> RequestIntentV3:
    selected = set(_work_unit_ids(work_unit_ids))
    requested_work = _mapping(request_intent.get("requested_work"), "requested_work")
    raw_units = _mappings(requested_work.get("work_units"), "requested_work.work_units")
    known = {str(unit.get("unit_id")) for unit in raw_units}
    if not selected.issubset(known):
        raise ValueError("planning route references unknown WorkUnit IDs")
    projected_units = [
        deepcopy(dict(unit)) for unit in raw_units if unit.get("unit_id") in selected
    ]
    raw_relations = _mappings(
        requested_work.get("work_relations"), "requested_work.work_relations"
    )
    projected_relations = [
        deepcopy(dict(relation))
        for relation in raw_relations
        if relation.get("source_work_unit_id") in selected
        and relation.get("target_work_unit_id") in selected
    ]

    constraints = _project_items(request_intent.get("constraints"), selected)
    prohibitions = _project_items(request_intent.get("effect_prohibitions"), selected)
    responsibilities = _mapping(
        request_intent.get("resource_responsibilities"), "resource_responsibilities"
    )
    source_reads = _project_items(responsibilities.get("source_reads"), selected)
    outputs = _project_items(responsibilities.get("outputs"), selected)
    effects = list(dict.fromkeys(
        (["READ"] if source_reads else [])
        + [str(item["effect"]) for item in outputs]
    ))
    resources = list(dict.fromkeys(
        [str(item["resource_type"]) for item in source_reads]
        + [str(item["resource_type"]) for item in outputs]
    ))
    projected = deepcopy(dict(request_intent))
    projected.update(
        {
            "constraints": constraints,
            "effect_prohibitions": prohibitions,
            "requested_effect_hints": effects,
            "requested_resource_hints": resources,
            "resource_responsibilities": {
                "source_reads": source_reads,
                "outputs": outputs,
            },
            "requested_work": {
                "work_units": projected_units,
                "work_relations": projected_relations,
            },
        }
    )
    return cast(RequestIntentV3, projected)


def evidence_refs_for_work_units(
    retrieval_result: Mapping[str, object] | None,
    *,
    work_unit_ids: Sequence[str],
) -> set[str]:
    if retrieval_result is None:
        return set()
    selected = set(_work_unit_ids(work_unit_ids))
    bindings = _mappings(
        retrieval_result.get("evidence_by_work_unit", []),
        "retrieval_result.evidence_by_work_unit",
    )
    return {
        ref
        for binding in bindings
        if binding.get("work_unit_id") in selected
        for ref in cast(list[object], binding.get("evidence_refs", []))
        if isinstance(ref, str) and ref
    }


def _project_items(value: object, selected: set[str]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for item in _mappings(value, "semantic_items"):
        refs = item.get("work_unit_ids")
        if not isinstance(refs, list) or not all(isinstance(ref, str) for ref in refs):
            raise ValueError("semantic item requires work_unit_ids")
        applicable = [ref for ref in refs if ref in selected]
        if not applicable:
            continue
        result.append({**deepcopy(dict(item)), "work_unit_ids": applicable})
    return result


def _work_unit_ids(value: Sequence[str]) -> tuple[str, ...]:
    refs = tuple(value)
    if not refs or len(refs) != len(set(refs)) or any(not ref for ref in refs):
        raise ValueError("work_unit_ids must be non-empty and unique")
    return refs


def _mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{path} must be an object")
    return value


def _mappings(value: object, path: str) -> list[Mapping[str, object]]:
    if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
        raise ValueError(f"{path} must be a list of objects")
    return cast(list[Mapping[str, object]], value)


__all__ = [
    "evidence_refs_for_work_units",
    "project_request_intent_for_work_units",
]
