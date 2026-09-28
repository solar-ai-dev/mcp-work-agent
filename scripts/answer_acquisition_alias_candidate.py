"""091 inactive projection: omit only exact, mechanically derived Source aliases.

The reduced request_intent is an evaluation input view, not a replacement
RequestIntentV3 artifact. The original Product intent remains authoritative.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from typing import Any, cast

from scripts import evaluate_registered_answer_choice as registered
from scripts.ru_observation import object_hash

from google_work_agent.application.agents.request_understanding.contracts import (
    request_goal_candidate_schema,
)
from google_work_agent.application.agents.request_understanding.validate_intent import (
    validate_intent,
)
from google_work_agent.application.prompt_runtime.prompt_registry import PromptRegistry

INPUT_VERSION = "evaluation-answer-acquisition-alias-input-v1"


def project_acquisition_aliases(
    original_input: Mapping[str, object],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Do not infer whether a condition is redundant; require exact owner equality."""
    original = cast(dict[str, Any], deepcopy(dict(original_input)))
    PromptRegistry().input_contract.validate_projection("planning.compose_answer", original)
    request = original.get("user_request")
    if not isinstance(request, str):
        raise ValueError("original user request required")
    intent = validate_intent(
        original.get("request_intent"),
        require_meta=True,
        provenance_sources={"USER_REQUEST": request},
    )
    derived = request_goal_candidate_schema.derive_source_information_constraints(
        intent["resource_responsibilities"]
    )
    result = deepcopy(original)
    constraints = result["request_intent"]["constraints"]
    kept, omitted = [], []
    for index, item in enumerate(constraints):
        if any(item == alias for alias in derived):
            omitted.append({"index": index, "constraint": deepcopy(item)})
        else:
            kept.append(item)
    result["request_intent"]["constraints"] = kept
    return result, omitted


def validate_projection(
    value: Mapping[str, object], *, original_input: Mapping[str, object]
) -> None:
    """Validate the distinct view against the full, already-valid original input."""
    expected, _ = project_acquisition_aliases(original_input)
    if dict(value) != expected:
        raise ValueError("091 view changed more than exact acquisition aliases")


def build_payload(
    original: dict[str, Any], *, source_snapshots: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Change both input copies only; original PromptRef is provenance, not resolve."""
    body = json.loads(original["prompt"])
    original_input = body["input"]
    rebuilt = registered.expected_first(original_input, source_snapshots)
    if registered.transport_hash(original) != registered.transport_hash(rebuilt["payload"]):
        raise ValueError("current registered original FIRST drift")
    if json.dumps(body, ensure_ascii=False, sort_keys=True) != original["prompt"]:
        raise ValueError("original canonical body serialization required")
    projection, omitted = project_acquisition_aliases(original_input)
    validate_projection(projection, original_input=original_input)
    old_json = json.dumps(original_input, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    new_json = json.dumps(projection, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    suffix = "Allowed current-Run input projection (JSON):\n" + old_json + "\n"
    if not original["system"].endswith(suffix):
        raise ValueError("original assembled projection suffix changed")
    payload = deepcopy(original)
    payload["system"] = original["system"][: -len(old_json + "\n")] + new_json + "\n"
    body["input"] = projection
    payload["prompt"] = json.dumps(body, ensure_ascii=False, sort_keys=True)
    contract = {
        "input_schema_version": INPUT_VERSION,
        "activation_status": "INACTIVE_EVALUATION_ONLY",
        "wire_prompt_ref_status": "HISTORICAL_PROVENANCE_NOT_RESOLVED_FOR_REDUCED_VIEW",
        "original_input_sha256": object_hash(original_input),
        "candidate_input_sha256": object_hash(projection),
        "source_responsibilities_sha256": object_hash(
            cast(dict[str, Any], original_input["request_intent"])["resource_responsibilities"]
        ),
        "omitted_aliases": omitted,
        "validator": "validate_projection_exact_derivation_from_valid_original",
        "reduced_intent_authority": "EVALUATION_VIEW_NOT_PRODUCT_REQUEST_INTENT_V3",
    }
    return payload, projection, contract
