"""Compare a provenance-bound Preview requirement projection at the Review Goal node."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

from scripts.evaluate_review_current_user_edit import _goal_input
from scripts.evaluate_review_decomposition_node import MODEL_ID, _runtime

from google_work_agent.adapters.llm.ollama.transport import OllamaHTTPClient
from google_work_agent.application.agents.review.contracts.review_findings import (
    review_inspector_output_schema,
    validate_review_inspector_result,
)
from google_work_agent.application.prompt_runtime.prompt_registry import (
    DEVELOPMENT_SMOKE,
    default_prompt_manifest_path,
    load_prompt_reference,
)
from google_work_agent.application.use_cases.run.account_provider_dispatch import (
    provider_dispatch_budget_scope,
    provider_dispatch_execution_scope,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget

PROMPT_ID = "review.inspect_goal_and_evidence"


def project_current_edit(
    prompt_input: dict[str, Any], *, prior_plan: dict[str, Any]
) -> dict[str, Any]:
    """Ignore only an old constraint proven equal to this Action's prior argument."""
    projected = deepcopy(prompt_input)
    modifications = projected.get("user_action_modifications")
    current = projected["planning_result"]["actions"]
    prior = prior_plan["actions"]
    if not isinstance(modifications, list) or len(current) != 1 or len(prior) != 1:
        return projected
    action, before = current[0], prior[0]
    if (action.get("route_id"), action.get("tool_id")) != (
        before.get("route_id"), before.get("tool_id")
    ):
        return projected
    constraints = projected["request_intent"]["constraints"]
    for modification in modifications:
        if modification.get("action_id") != action.get("action_id"):
            continue
        for path, after_value in modification.get("argument_overrides", {}).items():
            if not isinstance(path, str) or not path or not isinstance(after_value, str):
                continue
            old_present, old_value = _at_path(before["arguments"], path)
            new_present, new_value = _at_path(action["arguments"], path)
            if not old_present or not new_present or new_value != after_value:
                continue
            field = path.rsplit(".", 1)[-1]
            matches = [
                item
                for item in constraints
                if item.get("field") == field and item.get("value") == old_value
            ]
            if len(matches) != 1 or "provenance" in matches[0]:
                continue
            constraints.remove(matches[0])
    return projected


def _at_path(arguments: dict[str, Any], path: str) -> tuple[bool, Any]:
    current: Any = arguments
    for part in path.split("."):
        if not part or not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current


def _inputs(cycle: dict[str, Any]) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    cases = {item["label"]: item for item in cycle["cases"]}
    normal_023 = _goal_input(cases["NORMAL_023"])
    normal_028 = _goal_input(cases["NORMAL_028"])
    edited_023 = _goal_input(cases["USER_EDIT_023"])
    edited_028 = deepcopy(normal_028)
    action_028 = edited_028["planning_result"]["actions"][0]
    action_028["arguments"]["payload"]["title"] = "Kestrel 일정 후속 점검"
    edited_028["user_action_modifications"] = [
        {
            "action_id": action_028["action_id"],
            "argument_overrides": {"payload.title": "Kestrel 일정 후속 점검"},
        }
    ]
    mismatch_023 = deepcopy(edited_023)
    mismatch_023["planning_result"]["actions"][0]["arguments"]["payload"][
        "title"
    ] = normal_023["planning_result"]["actions"][0]["arguments"]["payload"]["title"]
    description_028 = deepcopy(normal_028)
    desc_action = description_028["planning_result"]["actions"][0]
    desc_action["arguments"]["payload"]["description"] = "Kestrel 공급 일정과 조치 확인"
    description_028["user_action_modifications"] = [
        {
            "action_id": desc_action["action_id"],
            "argument_overrides": {"payload.description": "Kestrel 공급 일정과 조치 확인"},
        }
    ]
    mismatch_description = deepcopy(description_028)
    mismatch_description["planning_result"]["actions"][0]["arguments"]["payload"][
        "description"
    ] = normal_028["planning_result"]["actions"][0]["arguments"]["payload"][
        "description"
    ]
    return [
        ("USER_EDIT_023", edited_023, normal_023["planning_result"]),
        ("USER_EDIT_028_SYNTHETIC", edited_028, normal_028["planning_result"]),
        ("EDIT_MISMATCH_023_SYNTHETIC", mismatch_023, normal_023["planning_result"]),
        ("EDIT_DESCRIPTION_028_SYNTHETIC", description_028, normal_028["planning_result"]),
        (
            "DESCRIPTION_MISMATCH_028_SYNTHETIC",
            mismatch_description,
            normal_028["planning_result"],
        ),
        ("NORMAL_023", normal_023, normal_023["planning_result"]),
        ("NORMAL_028", normal_028, normal_028["planning_result"]),
        (
            "MISSING_MAIL_023_SYNTHETIC",
            _goal_input(cases["MISSING_MAIL_023"]),
            normal_023["planning_result"],
        ),
    ]


def evaluate(cycle_path: Path, output_path: Path) -> None:
    cycle_bytes = cycle_path.read_bytes()
    cycle = json.loads(cycle_bytes)
    digest = next(
        (
            item.digest
            for item in OllamaHTTPClient().list_installed_models()
            if item.model_id == MODEL_ID
        ),
        None,
    )
    if digest != cycle["binding"]["model_digest"]:
        raise ValueError("installed model differs from frozen cycle")
    inputs = _inputs(cycle)
    if len(inputs) != 8:
        raise ValueError("predeclared input count changed")
    root = Path(tempfile.mkdtemp(prefix="gwa-review-edit-provenance-"))
    runtime = _runtime(root / "runtime", default_prompt_manifest_path())
    reference = load_prompt_reference(
        PROMPT_ID, default_prompt_manifest_path(), execution_scope=DEVELOPMENT_SMOKE
    )
    schema = review_inspector_output_schema(PROMPT_ID)
    result: dict[str, Any] = {
        "binding": {
            "baseline_sha": "4405f17d",
            "cycle_sha256": hashlib.sha256(cycle_bytes).hexdigest(),
            "model_id": MODEL_ID,
            "model_digest": digest,
            "temperature": 0.0,
            "seed": 1729,
            "prompt_hash": reference.content_hash,
            "output_schema_version": schema.schema_version,
            "call_limit": 16,
            "provider_read_enabled": False,
            "provider_write_enabled": False,
        },
        "trials": [],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    for label, original, prior_plan in inputs:
        arms = ("B", "A") if label in {"USER_EDIT_028_SYNTHETIC", "NORMAL_028"} else ("A", "B")
        for arm in arms:
            prompt_input = (
                deepcopy(original)
                if arm == "A"
                else project_current_edit(original, prior_plan=prior_plan)
            )
            trial: dict[str, Any] = {
                "label": label,
                "arm": arm,
                "input_sha256": hashlib.sha256(
                    json.dumps(prompt_input, sort_keys=True, ensure_ascii=False).encode("utf-8")
                ).hexdigest(),
                "prompt_input": prompt_input,
            }
            started = time.perf_counter()
            started_at_ms = 1786060800000
            try:
                with (
                    provider_dispatch_execution_scope(
                        run_id=f"review-edit-provenance-{label}-{arm}",
                        now_ms=lambda start=started, base=started_at_ms: base
                        + int((time.perf_counter() - start) * 1000),
                    ),
                    provider_dispatch_budget_scope(
                        build_default_run_budget(started_at_ms=started_at_ms)
                    ),
                ):
                    inference = runtime.infer("LOCAL_GPU", reference, prompt_input, schema)
                trial.update(
                    outcome="COMPLETED",
                    structured_output=validate_review_inspector_result(
                        inference.structured_output, expected_dimension=PROMPT_ID
                    ),
                    fallback_reason=inference.fallback_reason,
                    input_tokens=inference.input_tokens,
                    output_tokens=inference.output_tokens,
                    provider_latency_ms=inference.latency_ms,
                )
            except Exception as error:
                code = getattr(error, "code", None)
                trial.update(
                    outcome="FAILED",
                    error_type=type(error).__name__,
                    error_code=getattr(code, "value", None),
                    message=str(error),
                )
            trial["duration_ms"] = int((time.perf_counter() - started) * 1000)
            cast(list[dict[str, Any]], result["trials"]).append(trial)
            output_path.write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            print(label, arm, trial["outcome"], flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evaluate(args.cycle, args.output)


if __name__ == "__main__":
    main()
