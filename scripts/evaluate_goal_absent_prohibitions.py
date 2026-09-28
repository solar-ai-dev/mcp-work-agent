"""V33 removes only generated Goal from v32's frozen owner input.

The Product input loader remains strict. A declared evaluation projection removes
one exact root field after validating the original context; normalization alone
continues to use the original Goal outside the model input.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any
from unittest.mock import patch

from scripts import evaluate_sparse_effect_prohibitions as sparse
from scripts.ru_observation import object_hash

from google_work_agent.application.prompt_runtime.assemble_prompt import assemble_prompt
from google_work_agent.application.prompt_runtime.prompt_registry import EVALUATION, PromptRegistry
from google_work_agent.ports.llm.structured_inference_contracts import PromptReference

CANDIDATE_ID = "goal-absent-prohibitions-v33"
BASELINE_RAW = sparse.baseline.ROOT / "evaluation/results/064-prohibition-sparse-v32-t1/raw.json"
BASELINE_SHA256 = "358ad42822b4b4c020b75d7df26db4872d9a155f2727df12e4dc8975b058f77d"
INPUT_CONTRACT: dict[str, Any] = {
    "version": "evaluation-goal-absent-v33",
    "required_root_fields": [
        "user_request",
        "selected_resource_refs",
        "requested_work",
        "run_reference_time",
        "effect_candidates",
    ],
    "forbidden_root_fields": ["goal_candidate"],
    "additional_root_fields": False,
    "authority": "FROZEN_V32_INPUT_MINUS_GOAL_ONLY",
    "normalization_goal": "PRESERVED_OUTSIDE_MODEL_INPUT",
    "prompt_body": "UNCHANGED_V32_INCLUDING_GOAL_REFERENCE_NO_NEW_RULE",
}
_SPARSE_REF = sparse.candidate_ref
_SPARSE_PLAN = sparse.make_plan
_SPARSE_RUN = sparse.run_candidate
_SPARSE_NORMALIZE = sparse.normalize_with_product


def candidate_ref() -> PromptReference:
    # Body version/hash stays identical; the evaluation input contract differs.
    return replace(_SPARSE_REF(), input_schema_version=str(INPUT_CONTRACT["version"]))


def project_case(original: dict[str, Any]) -> dict[str, Any]:
    if object_hash(original["input"]) != original["input_sha256"]:
        raise ValueError("original frozen input hash mismatch")
    case = deepcopy(original)
    case["normalization_goal_candidate"] = case["input"].pop("goal_candidate")
    if set(case["input"]) != set(INPUT_CONTRACT["required_root_fields"]):
        raise ValueError("Goal-only input projection has unexpected fields")
    case["original_input_sha256"] = original["input_sha256"]
    case["input_sha256"] = object_hash(case["input"])
    return case


def restore_normalization_case(case: dict[str, Any]) -> dict[str, Any]:
    if object_hash(case["input"]) != case["input_sha256"]:
        raise ValueError("reduced frozen input hash mismatch")
    if set(case["input"]) != set(INPUT_CONTRACT["required_root_fields"]):
        raise ValueError("evaluation Goal-absent input contract violated")
    original = deepcopy(case)
    original["input"]["goal_candidate"] = deepcopy(case["normalization_goal_candidate"])
    original["input_sha256"] = case["original_input_sha256"]
    if object_hash(original["input"]) != original["input_sha256"]:
        raise ValueError("normalization context differs from original frozen Goal")
    return original


def instruction(
    case: dict[str, Any], ref: PromptReference, projection: Mapping[str, object]
) -> str:
    if ref != candidate_ref():
        raise ValueError("evaluation input contract PromptRef mismatch")
    original = restore_normalization_case(case)
    is_repair = set(projection) == {"base_projection", "candidate_output", "failure_record"}
    reduced = projection["base_projection"] if is_repair else projection
    if reduced != case["input"]:
        raise ValueError("actual inference input differs from frozen Goal-only projection")
    full_projection = deepcopy(dict(projection))
    if is_repair:
        full_projection["base_projection"] = original["input"]
    else:
        full_projection = original["input"]
    registry = PromptRegistry()
    base_ref = registry.lookup_for_evaluation(sparse.baseline.PROMPT_ID)
    # No loader patch: validate the real original Product context and keep its
    # wide instruction plus bounded repair assembly. Change only the JSON input.
    assembled = assemble_prompt(
        base_ref,
        full_projection,
        registry=registry,
        execution_scope=EVALUATION,
    )
    source = registry.source_text(sparse.baseline.PROMPT_ID).rstrip()
    if not assembled.startswith(source + "\n"):
        raise ValueError("Product instruction source boundary changed")
    assembled = sparse.SOURCE.rstrip() + assembled[len(source) :]
    marker = "Allowed current-Run input projection (JSON):\n"
    full_text = json.dumps(
        original["input"], ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    reduced_text = json.dumps(
        case["input"], ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    if assembled.count(marker + full_text) != 1:
        raise ValueError("original projection must occur once in the assembled system")
    return assembled.replace(marker + full_text, marker + reduced_text, 1)


def run_candidate(case: dict[str, Any], client: sparse.baseline.OllamaHTTPClient) -> dict[str, Any]:
    original = restore_normalization_case(case)
    with patch.multiple(
        sparse,
        candidate_ref=candidate_ref,
        instruction=lambda ref, projection: instruction(case, ref, projection),
        normalize_with_product=lambda value, ignored: _SPARSE_NORMALIZE(value, original),
    ):
        row = _SPARSE_RUN(case, client)
    row["candidate_id"] = CANDIDATE_ID
    row["original_input_sha256"] = case["original_input_sha256"]
    row["input_contract_version"] = INPUT_CONTRACT["version"]
    return row


def verified_v32_baseline(current: dict[str, Any]) -> dict[str, Any]:
    if hashlib.sha256(BASELINE_RAW.read_bytes()).hexdigest() != BASELINE_SHA256:
        raise ValueError("frozen v32 baseline raw changed")
    raw = json.loads(BASELINE_RAW.read_text(encoding="utf-8"))
    old = raw["binding"]
    for field in (
        "model",
        "candidate_prompt_ref",
        "candidate_source_sha256",
        "candidate_module_sha256",
        "consumer_source_hashes",
        "dataset_sha256",
        "fixture_sha256",
        "frozen_inputs_sha256",
        "policy",
    ):
        if current[field] != old[field]:
            raise ValueError(f"v32 baseline {field} changed")
    if len(raw["results"]) != 6 or not raw["completed"]:
        raise ValueError("six completed frozen baseline trials required")
    current_cases = {case["case_id"]: case for case in current["cases"]}
    if {row["case_id"] for row in raw["results"]} != set(current_cases):
        raise ValueError("v32 baseline case identities changed")
    for row in raw["results"]:
        case = current_cases[row["case_id"]]
        wire = row["wire_calls"][0]
        if (
            row["input_sha256"] != case["input_sha256"]
            or wire["input_sha256"] != case["input_sha256"]
            or wire["format_sha256"] != case["sparse_schema_sha256"]
            or wire["system_sha256"] != case["instruction_sha256"]
            or wire["options"] != {"num_ctx": 16384, "seed": sparse.baseline.SEED}
            or wire["think"] is not False
        ):
            raise ValueError("v32 baseline actual input/Schema/Prompt/runtime mismatch")
    return {
        "raw_path": str(BASELINE_RAW.relative_to(sparse.baseline.ROOT)),
        "raw_sha256": BASELINE_SHA256,
        "origin_head": old["head_sha"],
        "rows": raw["results"],
        "owner_input_contract_sha256": current["baseline_reuse"]["owner_input_contract_sha256"],
        "earlier_reuse_checks": current["baseline_reuse"]["global_slot_files"],
    }


def make_plan(model: dict[str, Any]) -> dict[str, Any]:
    base = _SPARSE_PLAN(model)
    reuse = verified_v32_baseline(base)
    cases = [project_case(case) for case in base["cases"]]
    for case in cases:
        case["instruction_sha256"] = hashlib.sha256(
            instruction(case, candidate_ref(), case["input"]).encode()
        ).hexdigest()
    return {
        **base,
        "candidate_id": CANDIDATE_ID,
        "candidate_prompt_ref": asdict(candidate_ref()),
        "input_contract": INPUT_CONTRACT,
        "input_contract_sha256": object_hash(INPUT_CONTRACT),
        "v32_module_sha256": base["candidate_module_sha256"],
        "candidate_module_sha256": sparse.normalized_sha256(Path(__file__)),
        "baseline_reuse": reuse,
        "baseline_reuse_scope": "ONLY_VERIFIED_V32_SPARSE_OWNER_ROWS",
        "cases": cases,
    }


def main() -> None:
    # Shared CLI keeps hash checks, six-call budget, exclusive claims and metrics.
    with patch.multiple(sparse, make_plan=make_plan, run_candidate=run_candidate, __doc__=__doc__):
        sparse.main()


if __name__ == "__main__":
    main()
