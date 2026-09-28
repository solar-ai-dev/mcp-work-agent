"""Evaluation-only envelope codec: keep Source input in USER, not duplicated SYSTEM."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

INPUT_MARKER = "Allowed current-Run input projection (JSON):\n"
FIRST_INPUT_FIELDS = frozenset(
    {
        "user_request",
        "selected_resource_refs",
        "run_reference_time",
        "requested_work",
        "goal_candidate",
        "source_candidates",
    }
)


def build_payload(original: dict[str, Any]) -> dict[str, Any]:
    """Remove only an exact terminal input block after caller validates wire authority.

    This changes transport placement, not Prompt source, Source meaning, or schema.
    The caller owns Product/074 artifact validation and complete wire hash binding.
    """
    prompt, system = original.get("prompt"), original.get("system")
    if not isinstance(prompt, str) or not isinstance(system, str):
        raise ValueError("Source FIRST system and prompt strings required")
    body = json.loads(prompt)
    if not isinstance(body, dict) or set(body) != {"prompt_ref", "input", "output_schema"}:
        raise ValueError("exact Source FIRST body required")
    projection = body["input"]
    if not isinstance(projection, dict) or set(projection) not in (
        FIRST_INPUT_FIELDS,
        FIRST_INPUT_FIELDS | {"interpretation_candidate"},
    ):
        raise ValueError("Source FIRST input requires original six or interpretation seven fields")
    if not isinstance(body["prompt_ref"], dict) or set(body["prompt_ref"]) != {
        "prompt_id",
        "prompt_version",
        "content_hash",
    }:
        raise ValueError("Source FIRST PromptRef required")
    schema = body["output_schema"]
    if not isinstance(schema, dict) or original.get("format") != schema:
        raise ValueError("Source FIRST body schema and transport format must match")
    suffix = (
        INPUT_MARKER
        + json.dumps(projection, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    )
    if not system.endswith(suffix):
        raise ValueError("exact terminal SYSTEM input projection required")
    prefix = system[: -len(suffix)]
    if not prefix.strip() or INPUT_MARKER in prefix:
        raise ValueError("one terminal input block after nonempty instruction required")
    candidate = deepcopy(original)
    candidate["system"] = prefix
    return candidate
