"""Evaluation-only projections for RequestedWorkDefinition binding candidates.

This module compares representation shape only.  It does not infer user meaning,
replace a Request Understanding semantic owner, or define a production contract.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from copy import deepcopy

SEMANTIC_COLLECTIONS: tuple[str, ...] = (
    "source_scopes",
    "targets",
    "temporal_constraints",
    "quantity_constraints",
    "prohibitions",
)

RELATION_KINDS = frozenset({"CONSUMES_WORK_PRODUCT", "CONSUMES_PLANNED_SPECIFICATION"})


def project_inline_work_unit_ids(
    decomposition: Mapping[str, object],
) -> dict[str, object]:
    """Move applicability onto each existing semantic item.

    Equal owner values are represented once and carry every applicable WorkUnit
    ID.  WorkUnit keeps only its boundary/provenance fields.
    """

    units = _work_units(decomposition)
    semantic_items: dict[str, list[dict[str, object]]] = {
        field: [] for field in SEMANTIC_COLLECTIONS
    }
    membership: dict[tuple[str, str], list[str]] = defaultdict(list)
    for unit in units:
        unit_id = _nonempty_string(unit.get("unit_id"), "work unit id")
        for field in SEMANTIC_COLLECTIONS:
            for value in _string_list(unit.get(field, []), f"{unit_id}.{field}"):
                ids = membership[(field, value)]
                if unit_id not in ids:
                    ids.append(unit_id)

    for field in SEMANTIC_COLLECTIONS:
        semantic_items[field] = [
            {"value": value, "work_unit_ids": membership[(field, value)]}
            for collection, value in membership
            if collection == field
        ]

    return {
        "requested_work": _requested_work(decomposition, units),
        "semantic_items": semantic_items,
    }


def project_local_id_bindings(
    decomposition: Mapping[str, object],
) -> dict[str, object]:
    """Represent the same applicability through local IDs and a binding table."""

    inline = project_inline_work_unit_ids(decomposition)
    raw_items = _mapping(inline["semantic_items"], "semantic_items")
    semantic_items: dict[str, list[dict[str, str]]] = {field: [] for field in SEMANTIC_COLLECTIONS}
    bindings: list[dict[str, object]] = []
    for field in SEMANTIC_COLLECTIONS:
        for raw_item in _mapping_list(raw_items.get(field), field):
            value = _nonempty_string(raw_item.get("value"), f"{field}.value")
            local_id = _local_id(field, value)
            semantic_items[field].append({"local_id": local_id, "value": value})
            bindings.append(
                {
                    "semantic_collection": field,
                    "semantic_local_id": local_id,
                    "work_unit_ids": list(
                        _string_list(raw_item.get("work_unit_ids"), "work_unit_ids")
                    ),
                }
            )
    return {
        "requested_work": deepcopy(inline["requested_work"]),
        "semantic_items": semantic_items,
        "semantic_bindings": bindings,
    }


def validate_inline_work_unit_ids(
    candidate: Mapping[str, object], *, user_request: str
) -> list[str]:
    errors, unit_ids = _validate_requested_work(candidate, user_request=user_request)
    raw_items = candidate.get("semantic_items")
    if not isinstance(raw_items, Mapping):
        return [*errors, "semantic_items must be an object"]
    for field in SEMANTIC_COLLECTIONS:
        seen: set[str] = set()
        for index, item in enumerate(_mapping_list(raw_items.get(field), field)):
            value = item.get("value")
            if not isinstance(value, str) or not value:
                errors.append(f"{field}[{index}].value must be non-empty")
                continue
            if value in seen:
                errors.append(f"{field} contains duplicate value {value!r}")
            seen.add(value)
            errors.extend(
                _validate_unit_refs(
                    item.get("work_unit_ids"),
                    unit_ids=unit_ids,
                    path=f"{field}[{index}].work_unit_ids",
                )
            )
    return errors


def validate_local_id_bindings(candidate: Mapping[str, object], *, user_request: str) -> list[str]:
    errors, unit_ids = _validate_requested_work(candidate, user_request=user_request)
    raw_items = candidate.get("semantic_items")
    if not isinstance(raw_items, Mapping):
        return [*errors, "semantic_items must be an object"]
    known_ids: dict[str, str] = {}
    for field in SEMANTIC_COLLECTIONS:
        for index, item in enumerate(_mapping_list(raw_items.get(field), field)):
            local_id = item.get("local_id")
            value = item.get("value")
            if not isinstance(local_id, str) or not local_id:
                errors.append(f"{field}[{index}].local_id must be non-empty")
                continue
            if local_id in known_ids:
                errors.append(f"duplicate semantic local id {local_id!r}")
            known_ids[local_id] = field
            if not isinstance(value, str) or not value:
                errors.append(f"{field}[{index}].value must be non-empty")

    bound_ids: set[str] = set()
    for index, binding in enumerate(
        _mapping_list(candidate.get("semantic_bindings"), "semantic_bindings")
    ):
        field = binding.get("semantic_collection")
        local_id = binding.get("semantic_local_id")
        if field not in SEMANTIC_COLLECTIONS:
            errors.append(f"semantic_bindings[{index}] has unknown collection")
        if not isinstance(local_id, str) or known_ids.get(local_id) != field:
            errors.append(f"semantic_bindings[{index}] has unresolved local id")
        else:
            bound_ids.add(local_id)
        errors.extend(
            _validate_unit_refs(
                binding.get("work_unit_ids"),
                unit_ids=unit_ids,
                path=f"semantic_bindings[{index}].work_unit_ids",
            )
        )
    for local_id in sorted(set(known_ids) - bound_ids):
        errors.append(f"semantic item {local_id!r} is unbound")
    return errors


def inline_round_trip_semantics(candidate: Mapping[str, object]) -> dict[str, object]:
    """Reconstruct the original per-WorkUnit semantic projection for comparison."""

    requested_work = _mapping(candidate.get("requested_work"), "requested_work")
    units = [
        deepcopy(item) for item in _mapping_list(requested_work.get("work_units"), "work_units")
    ]
    by_id = {_nonempty_string(item.get("unit_id"), "work unit id"): item for item in units}
    semantic_items = _mapping(candidate.get("semantic_items"), "semantic_items")
    for field in SEMANTIC_COLLECTIONS:
        for item in _mapping_list(semantic_items.get(field), field):
            value = _nonempty_string(item.get("value"), f"{field}.value")
            for unit_id in _string_list(item.get("work_unit_ids"), "work_unit_ids"):
                by_id[unit_id].setdefault(field, []).append(value)
    return {
        "work_units": units,
        "work_relations": deepcopy(requested_work.get("work_relations", [])),
    }


def local_id_round_trip_semantics(candidate: Mapping[str, object]) -> dict[str, object]:
    requested_work = _mapping(candidate.get("requested_work"), "requested_work")
    semantic_items = _mapping(candidate.get("semantic_items"), "semantic_items")
    value_by_id = {
        _nonempty_string(item.get("local_id"), "local_id"): _nonempty_string(
            item.get("value"), "value"
        )
        for field in SEMANTIC_COLLECTIONS
        for item in _mapping_list(semantic_items.get(field), field)
    }
    units = [
        deepcopy(item) for item in _mapping_list(requested_work.get("work_units"), "work_units")
    ]
    by_id = {_nonempty_string(item.get("unit_id"), "work unit id"): item for item in units}
    for binding in _mapping_list(candidate.get("semantic_bindings"), "semantic_bindings"):
        field = _nonempty_string(binding.get("semantic_collection"), "semantic_collection")
        local_id = _nonempty_string(binding.get("semantic_local_id"), "semantic_local_id")
        value = value_by_id[local_id]
        for unit_id in _string_list(binding.get("work_unit_ids"), "work_unit_ids"):
            by_id[unit_id].setdefault(field, []).append(value)
    return {
        "work_units": units,
        "work_relations": deepcopy(requested_work.get("work_relations", [])),
    }


def normalized_decomposition(decomposition: Mapping[str, object]) -> dict[str, object]:
    units = []
    for raw_unit in _work_units(decomposition):
        unit = {
            key: deepcopy(value)
            for key, value in raw_unit.items()
            if key in {"unit_id", "objective", "request_spans", *SEMANTIC_COLLECTIONS}
        }
        for field in SEMANTIC_COLLECTIONS:
            if field in unit:
                unit[field] = list(_string_list(unit[field], field))
        units.append(unit)
    return {
        "work_units": units,
        "work_relations": deepcopy(decomposition.get("work_relations", [])),
    }


def representation_metrics(candidate: Mapping[str, object]) -> dict[str, int]:
    semantic_items = _mapping(candidate.get("semantic_items"), "semantic_items")
    item_count = sum(
        len(_mapping_list(semantic_items.get(field), field)) for field in SEMANTIC_COLLECTIONS
    )
    binding_count = len(_mapping_list(candidate.get("semantic_bindings", []), "semantic_bindings"))
    ref_count = 0
    if binding_count:
        for binding in _mapping_list(candidate.get("semantic_bindings"), "semantic_bindings"):
            ref_count += len(_string_list(binding.get("work_unit_ids"), "work_unit_ids"))
    else:
        for field in SEMANTIC_COLLECTIONS:
            for item in _mapping_list(semantic_items.get(field), field):
                ref_count += len(_string_list(item.get("work_unit_ids"), "work_unit_ids"))
    return {
        "semantic_item_count": item_count,
        "binding_record_count": binding_count,
        "work_unit_reference_count": ref_count,
        "semantic_local_id_count": item_count if binding_count else 0,
    }


def _requested_work(
    decomposition: Mapping[str, object], units: Sequence[Mapping[str, object]]
) -> dict[str, object]:
    return {
        "work_units": [
            {
                key: deepcopy(value)
                for key, value in unit.items()
                if key in {"unit_id", "objective", "request_spans"}
            }
            for unit in units
        ],
        "work_relations": deepcopy(decomposition.get("work_relations", [])),
    }


def _validate_requested_work(
    candidate: Mapping[str, object], *, user_request: str
) -> tuple[list[str], set[str]]:
    errors: list[str] = []
    requested_work = candidate.get("requested_work")
    if not isinstance(requested_work, Mapping):
        return ["requested_work must be an object"], set()
    unit_ids: set[str] = set()
    for index, unit in enumerate(_mapping_list(requested_work.get("work_units"), "work_units")):
        unit_id = unit.get("unit_id")
        if not isinstance(unit_id, str) or not unit_id:
            errors.append(f"work_units[{index}].unit_id must be non-empty")
            continue
        if unit_id in unit_ids:
            errors.append(f"duplicate work unit id {unit_id!r}")
        unit_ids.add(unit_id)
        for span in _string_list(unit.get("request_spans", []), "request_spans"):
            if span not in user_request:
                errors.append(f"work_units[{index}] has non-verbatim request span")
    for index, relation in enumerate(
        _mapping_list(requested_work.get("work_relations", []), "work_relations")
    ):
        source = relation.get("source_unit_id")
        target = relation.get("target_unit_id")
        if source not in unit_ids or target not in unit_ids or source == target:
            errors.append(f"work_relations[{index}] has invalid endpoint")
        if relation.get("kind") not in RELATION_KINDS:
            errors.append(f"work_relations[{index}] has invalid kind")
    return errors, unit_ids


def _validate_unit_refs(value: object, *, unit_ids: set[str], path: str) -> list[str]:
    try:
        refs = _string_list(value, path)
    except (TypeError, ValueError) as exc:
        return [str(exc)]
    errors: list[str] = []
    if not refs:
        errors.append(f"{path} must be non-empty")
    if len(refs) != len(set(refs)):
        errors.append(f"{path} must be unique")
    unknown = sorted(set(refs) - unit_ids)
    if unknown:
        errors.append(f"{path} contains unknown ids: {unknown}")
    return errors


def _work_units(decomposition: Mapping[str, object]) -> list[Mapping[str, object]]:
    return _mapping_list(decomposition.get("work_units"), "work_units")


def _mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{path} must be an object")
    return value


def _mapping_list(value: object, path: str) -> list[Mapping[str, object]]:
    if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
        raise TypeError(f"{path} must be an object list")
    return list(value)


def _string_list(value: object, path: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise TypeError(f"{path} must be a non-empty string list")
    return list(value)


def _nonempty_string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{path} must be non-empty")
    return value


def _local_id(collection: str, value: str) -> str:
    payload = json.dumps(
        {"collection": collection, "value": value},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"{collection}:{hashlib.sha256(payload).hexdigest()[:16]}"


__all__ = [
    "SEMANTIC_COLLECTIONS",
    "inline_round_trip_semantics",
    "local_id_round_trip_semantics",
    "normalized_decomposition",
    "project_inline_work_unit_ids",
    "project_local_id_bindings",
    "representation_metrics",
    "validate_inline_work_unit_ids",
    "validate_local_id_bindings",
]
