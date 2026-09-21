from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from .request_intent import RequestedWorkDefinitionV1, RequestUnderstandingValidationError


def work_unit_id_schema(unit_ids: Sequence[str]) -> dict[str, object]:
    normalized = _known_ids(unit_ids)
    return {
        "type": "array",
        "minItems": 1,
        "uniqueItems": True,
        "items": {"enum": normalized},
    }


def validate_work_unit_refs(
    value: object,
    *,
    known_unit_ids: Sequence[str],
    path: str,
) -> list[str]:
    known = set(_known_ids(known_unit_ids))
    if not isinstance(value, list) or not value:
        raise RequestUnderstandingValidationError(f"{path} must be a non-empty list")
    if not all(isinstance(item, str) and item for item in value):
        raise RequestUnderstandingValidationError(f"{path} must contain non-empty strings")
    refs = cast(list[str], value)
    if len(refs) != len(set(refs)):
        raise RequestUnderstandingValidationError(f"{path} contains duplicate WorkUnit IDs")
    unknown = sorted(set(refs) - known)
    if unknown:
        raise RequestUnderstandingValidationError(
            f"{path} contains unknown WorkUnit IDs: {unknown}"
        )
    return refs


def validate_requested_work_definition(
    value: object,
    *,
    user_request: str,
) -> RequestedWorkDefinitionV1:
    if not isinstance(value, Mapping) or set(value) != {"work_units", "work_relations"}:
        raise RequestUnderstandingValidationError("$.requested_work fields are invalid")
    raw_units = value.get("work_units")
    raw_relations = value.get("work_relations")
    if not isinstance(raw_units, list) or not raw_units or not isinstance(raw_relations, list):
        raise RequestUnderstandingValidationError("$.requested_work is invalid")
    unit_ids: list[str] = []
    normalized_units: list[dict[str, object]] = []
    for index, raw in enumerate(raw_units):
        path = f"$.requested_work.work_units[{index}]"
        if not isinstance(raw, Mapping) or set(raw) != {"unit_id", "request_provenance"}:
            raise RequestUnderstandingValidationError(f"{path} fields are invalid")
        unit_id = raw.get("unit_id")
        provenance = raw.get("request_provenance")
        if (
            not isinstance(unit_id, str)
            or not unit_id
            or not isinstance(provenance, list)
            or not provenance
        ):
            raise RequestUnderstandingValidationError(f"{path} is invalid")
        bound: list[dict[str, object]] = []
        for span_index, item in enumerate(provenance):
            span_path = f"{path}.request_provenance[{span_index}]"
            if not isinstance(item, Mapping) or set(item) != {
                "source", "start_offset", "end_offset", "source_text"
            }:
                raise RequestUnderstandingValidationError(f"{span_path} fields are invalid")
            start = item.get("start_offset")
            end = item.get("end_offset")
            source_text = item.get("source_text")
            if (
                item.get("source") != "USER_REQUEST"
                or type(start) is not int
                or type(end) is not int
                or not isinstance(source_text, str)
                or start < 0
                or end <= start
                or end > len(user_request)
                or user_request[start:end] != source_text
            ):
                raise RequestUnderstandingValidationError(f"{span_path} is not source-bound")
            bound.append(dict(item))
        unit_ids.append(unit_id)
        normalized_units.append({"unit_id": unit_id, "request_provenance": bound})
    _known_ids(unit_ids)
    normalized_relations: list[dict[str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()
    known = set(unit_ids)
    for index, raw in enumerate(raw_relations):
        path = f"$.requested_work.work_relations[{index}]"
        if not isinstance(raw, Mapping) or set(raw) != {
            "source_work_unit_id", "target_work_unit_id", "kind"
        }:
            raise RequestUnderstandingValidationError(f"{path} fields are invalid")
        source = raw.get("source_work_unit_id")
        target = raw.get("target_work_unit_id")
        kind = raw.get("kind")
        pair = (source, target)
        if (
            source not in known
            or target not in known
            or source == target
            or pair in seen_pairs
            or kind not in {"CONSUMES_WORK_PRODUCT", "CONSUMES_PLANNED_SPECIFICATION"}
        ):
            raise RequestUnderstandingValidationError(f"{path} is invalid")
        seen_pairs.add(cast(tuple[str, str], pair))
        normalized_relations.append(
            {
                "source_work_unit_id": cast(str, source),
                "target_work_unit_id": cast(str, target),
                "kind": cast(str, kind),
            }
        )
    return cast(
        RequestedWorkDefinitionV1,
        {"work_units": normalized_units, "work_relations": normalized_relations},
    )


def _known_ids(values: Sequence[str]) -> list[str]:
    normalized = list(values)
    if not normalized or any(not isinstance(item, str) or not item for item in normalized):
        raise ValueError("WorkUnit IDs must be non-empty strings")
    if len(normalized) != len(set(normalized)):
        raise ValueError("WorkUnit IDs must be unique")
    return normalized


__all__ = [
    "validate_requested_work_definition",
    "validate_work_unit_refs",
    "work_unit_id_schema",
]
