"""Inactive single-Resource Source assessment; no inferred decisions for other Resources."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

from google_work_agent.application.agents.request_understanding.identify_source_dependencies import (  # noqa: E501
    build_source_dependency_candidates,
    build_source_dependency_output_schema,
    validate_source_dependency_candidate,
)
from google_work_agent.application.prompt_runtime.assemble_prompt import assemble_prompt
from google_work_agent.application.prompt_runtime.prompt_registry import EVALUATION, PromptRegistry
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_development_tool_registry,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema

PROMPT_ID = "request_understanding.identify_source_dependencies"
CANDIDATE_ID = "evaluation.source_focal_assessment"
INPUT_FIELDS = frozenset(
    {
        "user_request",
        "selected_resource_refs",
        "run_reference_time",
        "requested_work",
        "goal_candidate",
        "source_candidates",
    }
)
ROLE_REPLACEMENTS = (
    ("각 Resource 후보", "`assessment_resource_type`으로 지정된 Resource 후보 하나"),
    (
        "후보를 추가·삭제·중복하지 않고 각 후보를 정확히 한 번 판정한다.",
        "source_candidates는 전체 READ 후보 참조이며, 이번 호출에서는 "
        "assessment_resource_type으로 지정된 후보 하나만 판정한다.",
    ),
    (
        "외부 사실 의존성이 하나도 빠지지 않았는지",
        "판정 대상 Resource의 외부 사실 의존성이 빠지지 않았는지",
    ),
)


def build_payload(original: dict[str, Any], focus_resource_type: str) -> dict[str, Any]:
    """Validate current Product FIRST authority, then narrow only assessment/return scope."""
    body = json.loads(original["prompt"])
    if not isinstance(body, dict) or set(body) != {"prompt_ref", "input", "output_schema"}:
        raise ValueError("Product FIRST envelope required")
    projection = body["input"]
    if not isinstance(projection, dict) or set(projection) != INPUT_FIELDS:
        raise ValueError("exact original Source FIRST fields required")
    registry = PromptRegistry()
    ref = registry.lookup_for_evaluation(PROMPT_ID)
    if body["prompt_ref"] != {
        "prompt_id": ref.prompt_id,
        "prompt_version": ref.prompt_version,
        "content_hash": ref.content_hash,
    }:
        raise ValueError("original Source PromptRef differs from Product")
    catalog = list(build_source_dependency_candidates(load_development_tool_registry()))
    if projection["source_candidates"] != catalog:
        raise ValueError("original Source catalog differs from current Registry")
    selected = [item for item in catalog if item["resource_type"] == focus_resource_type]
    if len(selected) != 1:
        raise ValueError("focus must select exactly one existing Resource")
    work_ids = [unit["unit_id"] for unit in projection["requested_work"]["work_units"]]
    original_schema = build_source_dependency_output_schema(
        catalog, work_unit_ids=work_ids
    ).json_schema
    if body["output_schema"] != original_schema or original.get("format") != original_schema:
        raise ValueError("original Source schema differs from Product")
    instruction = assemble_prompt(ref, projection, registry=registry, execution_scope=EVALUATION)
    if original["system"] != instruction:
        raise ValueError("original Source assembly differs from Product")
    role = registry.source_text(PROMPT_ID).rstrip()
    suffix = (
        json.dumps(projection, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    )
    if not instruction.startswith(role + "\n\n") or not instruction.endswith(suffix):
        raise ValueError("unsupported Product FIRST assembly")
    candidate_role = role
    for old, new in ROLE_REPLACEMENTS:
        if candidate_role.count(old) != 1:
            raise ValueError("Product role replacement must have exactly one match")
        candidate_role = candidate_role.replace(old, new, 1)
    result, candidate_body = deepcopy(original), deepcopy(body)
    candidate_body["input"]["assessment_resource_type"] = focus_resource_type
    candidate_body["prompt_ref"] = {
        "prompt_id": CANDIDATE_ID,
        "prompt_version": "v1",
        "content_hash": hashlib.sha256(candidate_role.encode("utf-8")).hexdigest(),
    }
    schema = build_source_dependency_output_schema(selected, work_unit_ids=work_ids).json_schema
    candidate_body["output_schema"] = deepcopy(schema)
    result["format"] = deepcopy(schema)
    result["system"] = (
        candidate_role
        + instruction[len(role) : -len(suffix)]
        + json.dumps(
            candidate_body["input"], ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )
        + "\n"
    )
    result["prompt"] = json.dumps(candidate_body, ensure_ascii=False, sort_keys=True)
    return result


def admit_focus(content: object, payload: dict[str, Any]) -> dict[str, Any]:
    """Strictly validate one frozen focus; never fill negatives or merge full Source decisions."""
    body = json.loads(payload["prompt"])
    projection = body["input"]
    if set(projection) != INPUT_FIELDS | {"assessment_resource_type"}:
        raise ValueError("focal FIRST input required")
    selected = [
        item
        for item in projection["source_candidates"]
        if item["resource_type"] == projection["assessment_resource_type"]
    ]
    if len(selected) != 1:
        raise ValueError("one frozen focus required")
    work_ids = [unit["unit_id"] for unit in projection["requested_work"]["work_units"]]
    schema = build_source_dependency_output_schema(selected, work_unit_ids=work_ids).json_schema
    if body["output_schema"] != schema or payload.get("format") != schema:
        raise ValueError("focal Source schema differs from frozen focus")
    try:
        value = json.loads(content) if isinstance(content, str) else None
    except json.JSONDecodeError as error:
        return {
            "validation": {"structural_result": "INVALID_JSON", "error": str(error)},
            "validated_focus": None,
        }
    errors = list(validate_output_schema(value, schema))
    if errors:
        return {
            "validation": {"structural_result": "INVALID_SCHEMA", "schema_errors": errors},
            "validated_focus": None,
        }
    try:
        validated = validate_source_dependency_candidate(
            value,
            source_candidates=selected,
            work_unit_ids=work_ids,
        )
    except ValueError as error:
        return {
            "validation": {"structural_result": "OWNER_REJECTED", "error": str(error)},
            "validated_focus": None,
        }
    return {
        "validation": {"structural_result": "VALIDATED", "validated_output": validated},
        "validated_focus": deepcopy(validated["source_dependencies"][0]),
    }
