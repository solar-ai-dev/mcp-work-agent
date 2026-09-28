"""v30: one-call, current-WorkUnit ambiguity decisions; evaluation only."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, cast

from scripts.ru_ambiguity_owner_candidate import INPUT_MARKER, ambiguity_owner_instruction

from google_work_agent.application.agents.request_understanding.detect_ambiguity import (
    DETECT_AMBIGUITY_OUTPUT_SCHEMA,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import OutputSchemaDefinition

CANDIDATE_ID = "work-bound-ambiguity-v30"
_COUNTS = ("searchable_target_anchor_count", "connector_owned_source_count")


def project_work_ambiguity_input(product_input: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(product_input)
    for field in _COUNTS:
        if field not in result["resolution_responsibilities"]:
            raise ValueError("reviewed Product ambiguity count contract changed")
        del result["resolution_responsibilities"][field]
    work_unit_ids(result)
    return result


def work_unit_ids(projection: dict[str, Any]) -> list[str]:
    work = projection["goal_candidate"]["requested_work"]
    ids = [unit["unit_id"] for unit in work["work_units"]]
    if (
        not ids
        or len(set(ids)) != len(ids)
        or any(not isinstance(item, str) or not item for item in ids)
    ):
        raise ValueError("current WorkUnit IDs must be nonempty, unique and closed")
    return ids


def work_ambiguity_schema(projection: dict[str, Any]) -> OutputSchemaDefinition:
    ids = work_unit_ids(projection)
    item = cast(dict[str, Any], deepcopy(dict(DETECT_AMBIGUITY_OUTPUT_SCHEMA.json_schema)))
    item["properties"]["work_unit_id"] = {"enum": ids}
    item["required"] = ["work_unit_id", *item["required"]]
    return OutputSchemaDefinition(
        schema_version="evaluation-work-ambiguity-v30",
        json_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["work_ambiguities"],
            "properties": {
                "work_ambiguities": {
                    "type": "array",
                    "minItems": len(ids),
                    "maxItems": len(ids),
                    "items": item,
                    "allOf": [
                        {
                            "contains": {
                                "type": "object",
                                "required": ["work_unit_id"],
                                "properties": {"work_unit_id": {"const": unit}},
                            },
                            "minContains": 1,
                            "maxContains": 1,
                        }
                        for unit in ids
                    ],
                }
            },
        },
    )


def fold_work_ambiguities(raw: Any, projection: dict[str, Any]) -> dict[str, Any]:
    """Only aggregate existing owner choices; preserve every chosen field verbatim."""
    errors = validate_output_schema(raw, work_ambiguity_schema(projection).json_schema)
    if errors:
        raise ValueError(f"work ambiguity structure invalid: {errors}")
    rows = raw["work_ambiguities"]
    for row in rows:
        # Same existing owner/field invariant; do not hide an invalid lower-priority row.
        if (row["missing_information_owner"] == "NONE") != (not row["missing_fields"]):
            raise ValueError("NONE needs empty fields and USER/CONNECTOR need nonempty fields")
    chosen = next(
        (
            owner
            for owner in ("USER", "CONNECTOR")
            if any(row["missing_information_owner"] == owner for row in rows)
        ),
        "NONE",
    )
    return {
        "missing_information_owner": chosen,
        "missing_fields": [
            field
            for row in rows
            if row["missing_information_owner"] == chosen
            for field in row["missing_fields"]
        ],
    }


def _source_changes(instruction: str) -> str:
    simplified = ambiguity_owner_instruction(instruction)
    source, marker, rest = simplified.partition(INPUT_MARKER)
    count_sentence = (
        "`resolution_responsibilities.searchable_target_anchor_count`는 현재 Run의 "
        "검증된 검색 대상 "
        "constraint 수이고 `connector_owned_source_count`는 Connector가 읽을 source 책임 수다.\n\n"
    )
    before = "현재 요청을 진행하는 데 실제로 필요한 사용자 선택이 남았는지 판단한다."
    after = (
        "확정된 각 WorkUnit을 진행하는 데 실제로 필요한 사용자 선택이 남았는지 판단한다. "
        "현재 unit_id와 semantic item의 work_unit_ids를 그대로 소비하여 업무별 결과를 반환한다."
    )
    output_before = (
        "`missing_information_owner`와 `missing_fields`만 supplied schema에 맞춰 반환한다."
    )
    output_after = (
        "`work_ambiguities`에 현재 WorkUnit마다 `work_unit_id`, "
        "`missing_information_owner`, `missing_fields`를 supplied schema에 맞춰 반환한다."
    )
    for old, new in ((count_sentence, ""), (before, after), (output_before, output_after)):
        if source.count(old) != 1:
            raise ValueError("the reviewed v29 ambiguity responsibility/shape changed")
        source = source.replace(old, new, 1)
    return source + marker + rest


def work_ambiguity_instruction(
    product_instruction: str,
    *,
    product_projection: dict[str, Any],
    candidate_projection: dict[str, Any],
) -> str:
    if candidate_projection != project_work_ambiguity_input(product_projection):
        raise ValueError("v30 may remove only the two global counts from Product input")
    result = _source_changes(product_instruction)
    before = json.dumps(
        product_projection, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    after = json.dumps(
        candidate_projection, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    if result.count(INPUT_MARKER + before) != 1:
        raise ValueError("assembled Product base projection is not uniquely bound")
    return result.replace(INPUT_MARKER + before, INPUT_MARKER + after, 1)


def work_ambiguity_source_hash(source: str) -> str:
    transformed = _source_changes(source + INPUT_MARKER + "{}")
    return hashlib.sha256(transformed.partition(INPUT_MARKER)[0].encode()).hexdigest()
