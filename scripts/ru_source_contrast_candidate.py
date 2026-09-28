"""Inactive Source contrast examples over an unchanged Product FIRST envelope.

The helper performs no inference and never transforms a model's decision. Only
the instruction gains three frozen examples; the live input, schema, context,
and transport options retain their original authority.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

from google_work_agent.application.agents.request_understanding.contracts.source_dependency_decision import (  # noqa: E501
    SourceDependencyCandidateV1,
)
from google_work_agent.application.agents.request_understanding.contracts.work_unit_binding import (
    validate_requested_work_definition,
)
from google_work_agent.application.agents.request_understanding.identify_source_dependencies import (  # noqa: E501
    build_source_dependency_output_schema,
    validate_source_dependency_candidate,
)
from google_work_agent.application.prompt_runtime.assemble_prompt import assemble_prompt
from google_work_agent.application.prompt_runtime.prompt_registry import EVALUATION, PromptRegistry

ROOT = Path(__file__).resolve().parents[1]
PROMPT_ID = "request_understanding.identify_source_dependencies"
CANDIDATE_ID = "source-contrast-v44"
EXAMPLES_PATH = ROOT / "evaluation/prompt_candidates/ru-source-contrast-v44/examples.json"


def load_examples(
    candidates: Sequence[SourceDependencyCandidateV1],
) -> list[dict[str, Any]]:
    """Validate complete authored examples, without filling omitted decisions."""
    document = json.loads(EXAMPLES_PATH.read_text(encoding="utf-8"))
    if set(document) != {"schema_version", "examples"} or document["schema_version"] != 1:
        raise ValueError("unsupported Source contrast example document")
    examples = document["examples"]
    if not isinstance(examples, list) or len(examples) != 3:
        raise ValueError("Source contrast candidate requires the three frozen examples")
    for example in examples:
        if not isinstance(example, dict) or set(example) != {"input", "output"}:
            raise ValueError("Source contrast example must contain only input and output")
        projection = example["input"]
        if not isinstance(projection, dict) or set(projection) != {
            "user_request",
            "selected_resource_refs",
            "requested_work",
        }:
            raise ValueError("Source contrast example input fields differ")
        work = validate_requested_work_definition(
            projection["requested_work"], user_request=projection["user_request"]
        )
        validate_source_dependency_candidate(
            example["output"],
            source_candidates=candidates,
            work_unit_ids=[unit["unit_id"] for unit in work["work_units"]],
        )
    return cast(list[dict[str, Any]], examples)


def build_payload(original_payload: Mapping[str, Any]) -> dict[str, Any]:
    """Append examples after the exact Product role, before its unchanged context."""
    body = json.loads(original_payload["prompt"])
    projection = body["input"]
    if any(key in projection for key in ("base_projection", "failure_record", "candidate_output")):
        raise ValueError("Source contrast diagnostic accepts only original FIRST input")
    registry = PromptRegistry()
    ref = registry.lookup_for_evaluation(PROMPT_ID)
    expected_ref = {
        "prompt_id": ref.prompt_id,
        "prompt_version": ref.prompt_version,
        "content_hash": ref.content_hash,
    }
    if body["prompt_ref"] != expected_ref:
        raise ValueError("original Source PromptRef differs from current Product")
    candidates = projection["source_candidates"]
    work_ids = [unit["unit_id"] for unit in projection["requested_work"]["work_units"]]
    schema = build_source_dependency_output_schema(candidates, work_unit_ids=work_ids).json_schema
    if body["output_schema"] != schema or original_payload["format"] != schema:
        raise ValueError("original Source schema/format differs from Product")
    instruction = assemble_prompt(ref, projection, registry=registry, execution_scope=EVALUATION)
    if original_payload["system"] != instruction:
        raise ValueError("original Source assembly differs from current Product")

    role = registry.source_text(PROMPT_ID).rstrip()
    original_json = json.dumps(
        projection, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    if not instruction.startswith(role + "\n\n") or not instruction.endswith(original_json + "\n"):
        raise ValueError("original Source assembly is not the supported FIRST envelope")
    examples = load_examples(candidates)
    examples_block = (
        "\n\n# 입력·출력 예시\n\n"
        "동일한 후보 목록을 사용하는 축약 입력과 완전한 출력의 예시:\n"
        + json.dumps(examples, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    candidate_role = role + examples_block
    result = deepcopy(dict(original_payload))
    result["system"] = candidate_role + instruction[len(role) :]
    candidate_body = deepcopy(body)
    candidate_body["prompt_ref"] = {
        **expected_ref,
        "prompt_version": "evaluation-v44-contrast",
        "content_hash": hashlib.sha256(candidate_role.encode("utf-8")).hexdigest(),
    }
    result["prompt"] = json.dumps(candidate_body, ensure_ascii=False, sort_keys=True)
    return result
