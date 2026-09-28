"""Three fixed Source FIRSTs with only the installed model artifact changed.

Evaluation-only, no training/Graph/Provider or Product configuration changes.
The historical 9B wire is reconstructed, then only its model key changes to 4B.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from scripts import evaluate_source_catalog_projection as shared
from scripts.evaluate_effect_prohibition_sampler import write_json
from scripts.ru_observation import object_hash

existing = shared.existing
ROOT = shared.ROOT
RESULTS = shared.RESULTS
MODEL_ID = "qwen3.5:4b"
MODEL_DIGEST = "2a654d98e6fba55d452b7043684e9b57a947e393bbffa62485a7aac05ee4eefd"
BASELINE_MODEL_ID = "qwen3.5:9b"
BASELINE_MODEL_DIGEST = "6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7"
CRITERIA = "evaluation/experiments/066-source-fixed-model-v46-criteria.md"
RENDER_OBSERVATION = RESULTS / "066-source-fixed-model-v46-preflight/render-observation.json"
RENDER_TEMPLATE = (
    "<|im_start|>system\nEVAL_ROLE_SYSTEM_066<|im_end|>\n"
    "<|im_start|>user\nEVAL_ROLE_USER_066<|im_end|>\n"
    "<|im_start|>assistant\n<think>\n\n</think>\n\n"
)


def inspect_candidate_model() -> dict[str, Any]:
    """Read installed tags/show/version only; never invoke generation or download."""
    endpoint = existing.OLLAMA_FIXED_LOOPBACK_ENDPOINT
    tags = existing.transport._get_json(endpoint=endpoint, path="/api/tags", timeout_seconds=10)
    models = tags.get("models")
    if not isinstance(models, list):
        raise ValueError("actual installed model catalog required")
    matches = [m for m in models if isinstance(m, dict) and m.get("name") == MODEL_ID]
    if len(matches) != 1 or matches[0].get("digest") != MODEL_DIGEST:
        raise ValueError("registered installed 4B digest required; no download/fallback")
    show = existing.transport._post_json(
        endpoint=endpoint, path="/api/show", payload={"model": MODEL_ID}, timeout_seconds=10
    )
    parameters = show.get("parameters")
    if not isinstance(parameters, str) or not isinstance(show.get("template"), str):
        raise ValueError("actual model parameters and template required")
    version = existing.transport._get_json(
        endpoint=endpoint, path="/api/version", timeout_seconds=10
    )
    result = {
        "model_id": MODEL_ID,
        "model_digest": MODEL_DIGEST,
        "tags_selected_model": deepcopy(matches[0]),
        "tags_response_sha256": object_hash(tags),
        "show_response": deepcopy(show),
        "show_parameters": parameters,
        "show_parameters_sha256": hashlib.sha256(parameters.encode()).hexdigest(),
        "show_sha256": object_hash(show),
        "ollama_version_response": version,
        "ollama_version_sha256": object_hash(version),
    }
    existing._validate_presence_version(result)
    return result


def render_binding(model: dict[str, Any]) -> dict[str, Any]:
    """Bind the prior synthetic zero-token observation, not a new model call."""
    observation = shared.read_json(RENDER_OBSERVATION)
    request = observation.get("request", {})
    response = observation.get("response", {})
    expected_request = {
        "model": MODEL_ID,
        "system": "EVAL_ROLE_SYSTEM_066",
        "prompt": "EVAL_ROLE_USER_066",
        "think": False,
        "stream": False,
        "options": {"num_ctx": 16384},
        "_debug_render_only": True,
    }
    if (
        observation.get("model_digest") != model["model_digest"]
        or observation.get("ollama_version") != model["ollama_version_response"]["version"]
        or observation.get("new_generation_calls") != 0
        or request != expected_request
        or response.get("model") != MODEL_ID
        or response.get("response") != ""
        or response.get("done") is not False
        or "eval_count" in response
        or "prompt_eval_count" in response
        or response.get("_debug_info", {}).get("rendered_template") != RENDER_TEMPLATE
    ):
        raise ValueError("unverified or generating render observation")
    return {
        "path": RENDER_OBSERVATION.as_posix(),
        "sha256": existing.file_hash(RENDER_OBSERVATION),
        "basis": "HISTORICAL_SYNTHETIC_RENDER_ONLY_NOT_NEW_GENERATION",
        "rendered_template_sha256": hashlib.sha256(RENDER_TEMPLATE.encode()).hexdigest(),
    }


def make_plan(baseline_model: dict[str, Any], model: dict[str, Any]) -> dict[str, Any]:
    existing._validate_presence_version(model)
    if (
        baseline_model.get("model_id") != BASELINE_MODEL_ID
        or baseline_model.get("model_digest") != BASELINE_MODEL_DIGEST
        or model.get("model_id") != MODEL_ID
        or model.get("model_digest") != MODEL_DIGEST
        or model.get("show_parameters") != baseline_model.get("show_parameters")
    ):
        raise ValueError("registered 9B/4B artifacts and identical actual defaults required")
    # Reuse only the historical-wire/Canonical/admission checks. The v45
    # read_tool_ids ablation is discarded; each new wire starts from payload.
    plan = deepcopy(shared.make_plan(baseline_model))
    if tuple(c["case_id"] for c in plan["cases"]) != shared.CASE_IDS:
        raise ValueError("registered three Core inputs required")
    for case in plan["cases"]:
        original = case["payload"]
        if original.get("model") != BASELINE_MODEL_ID:
            raise ValueError("historical payload is not the registered baseline model")
        transformed = deepcopy(original)
        transformed["model"] = MODEL_ID
        case.update(
            candidate_payload=transformed,
            candidate_wire_sha256=object_hash(transformed),
            model_only_change=True,
        )
    paths = (
        "scripts/evaluate_source_fixed_model.py",
        "tests/evaluation/test_source_fixed_model.py",
        CRITERIA,
    )
    plan["source_hashes"].update({p: existing.file_hash(ROOT / p) for p in paths})
    plan.update(
        kind="SOURCE_FIXED_MODEL_V46",
        candidate_input_contract="ORIGINAL_SOURCE_INPUT_AND_SCHEMA_MODEL_ARTIFACT_ONLY",
        baseline_model=deepcopy(baseline_model),
        model=deepcopy(model),
        render_observation=render_binding(model),
        comparison_scope="FIXED_SOURCE_OWNER_ARTIFACT_COMPARISON_NOT_PARAMETER_COUNT_EFFECT",
        runtime_arm="INSTALLED_4B_ORIGINAL_SOURCE_WIRE",
    )
    return plan


def execute_plan(plan: dict[str, Any], output: Path, *, plan_sha256: str) -> dict[str, Any]:
    if object_hash(plan) != plan_sha256:
        raise ValueError("plan hash mismatch")
    current = make_plan(
        existing.inspect_diagnostic_model("presence_zero"), inspect_candidate_model()
    )
    if current != plan:
        raise ValueError("HEAD/code/input/artifact/runtime/render drift")
    return shared.execute_registered_firsts(
        plan,
        output,
        plan_sha256=plan_sha256,
        claim_directory=".source-fixed-model-trials",
        response_model=MODEL_ID,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result-dir", type=Path, required=True)
    parser.add_argument("--execute-plan", type=Path)
    parser.add_argument("--expected-plan-sha256")
    args = parser.parse_args()
    if args.execute_plan:
        raw = execute_plan(
            shared.read_json(args.execute_plan),
            args.result_dir,
            plan_sha256=args.expected_plan_sha256,
        )
        print(json.dumps({"calls": raw["actual_http_calls"], "semantic_verdict": "UNREVIEWED"}))
        return
    output = args.result_dir.resolve()
    if output == RESULTS.resolve() or not output.is_relative_to(RESULTS.resolve()):
        raise ValueError("dedicated evaluation/results directory required")
    plan = make_plan(existing.inspect_diagnostic_model("presence_zero"), inspect_candidate_model())
    path = output / "preregistered-plan.json"
    write_json(path, plan, exclusive=True)
    print(json.dumps({"plan": str(path), "sha256": object_hash(plan), "model_calls": 0}))


if __name__ == "__main__":
    main()
