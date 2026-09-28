"""Inactive Source-input ablation: hide READ tool IDs, not eligible Resources.

Admission checks the complete original Product FIRST envelope and current
Registry-derived catalog. The evaluation-only projection removes one metadata
field from both input copies; it does not change the role, output contract,
runtime, Resource eligibility, or any model decision.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from google_work_agent.application.agents.request_understanding.identify_source_dependencies import (  # noqa: E501
    build_source_dependency_candidates,
    build_source_dependency_output_schema,
)
from google_work_agent.application.prompt_runtime.assemble_prompt import assemble_prompt
from google_work_agent.application.prompt_runtime.prompt_registry import EVALUATION, PromptRegistry
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_development_tool_registry,
)

PROMPT_ID = "request_understanding.identify_source_dependencies"
CANDIDATE_ID = "source-catalog-projection-v45"
INPUT_CONTRACT = "evaluation-source-catalog-without-read-tool-ids-v45"


def build_payload(original_payload: Mapping[str, Any]) -> dict[str, Any]:
    """Project an exact current FIRST wire without inventing a Product contract."""
    body = json.loads(original_payload["prompt"])
    if not isinstance(body, dict) or set(body) != {"prompt_ref", "input", "output_schema"}:
        raise ValueError("Source catalog diagnostic requires the Product FIRST envelope")
    projection = body["input"]
    if not isinstance(projection, dict) or any(
        key in projection for key in ("base_projection", "failure_record", "candidate_output")
    ):
        raise ValueError("Source catalog diagnostic accepts only original FIRST input")

    registry = PromptRegistry()
    ref = registry.lookup_for_evaluation(PROMPT_ID)
    expected_ref = {
        "prompt_id": ref.prompt_id,
        "prompt_version": ref.prompt_version,
        "content_hash": ref.content_hash,
    }
    if body["prompt_ref"] != expected_ref:
        raise ValueError("original Source PromptRef differs from current Product")
    candidates = projection.get("source_candidates")
    current_candidates = list(build_source_dependency_candidates(load_development_tool_registry()))
    if candidates != current_candidates:
        raise ValueError("original Source catalog differs from current Registry READ eligibility")
    work_ids = [unit["unit_id"] for unit in projection["requested_work"]["work_units"]]
    schema = build_source_dependency_output_schema(
        current_candidates, work_unit_ids=work_ids
    ).json_schema
    if body["output_schema"] != schema or original_payload["format"] != schema:
        raise ValueError("original Source schema/format differs from Product")
    instruction = assemble_prompt(ref, projection, registry=registry, execution_scope=EVALUATION)
    if original_payload["system"] != instruction:
        raise ValueError("original Source assembly differs from current Product")

    role = registry.source_text(PROMPT_ID).rstrip()
    original_json = json.dumps(
        projection, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    suffix = original_json + "\n"
    if not instruction.startswith(role + "\n\n") or not instruction.endswith(suffix):
        raise ValueError("original Source assembly is not the supported FIRST envelope")

    candidate_body = deepcopy(body)
    candidate_projection = candidate_body["input"]
    for item in candidate_projection["source_candidates"]:
        del item["read_tool_ids"]
    candidate_json = json.dumps(
        candidate_projection, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    result = deepcopy(dict(original_payload))
    result["system"] = instruction[: -len(suffix)] + candidate_json + "\n"
    result["prompt"] = json.dumps(candidate_body, ensure_ascii=False, sort_keys=True)
    return result
