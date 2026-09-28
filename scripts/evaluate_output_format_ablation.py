"""Fixed RU owner FIRST format diagnostics; no Graph or repair.

Historical inputs are provenance, not new scores. Both arms retain the schema
inside the Prompt and use the same Product schema/owner validator afterwards.
The historical omitted mode uses six new calls; JSON mode reuses three constrained
records and performs only three new JSON-mode calls. Core5 rebinds inputs to the
current Prompt and uses ten new calls, with separate strict/fence validation.
Source mode reuses three exact-wire FIRSTs and generates three omitted candidates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from collections import Counter
from collections.abc import Callable
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from evaluation.dataset_v8 import (
    DEFAULT_DATASET_PATH,
    DEFAULT_PROVIDER_FIXTURE_PATH,
    load_cases,
)
from scripts.evaluate_effect_prohibition_sampler import head, inspect_model, write_json
from scripts.ru_observation import metrics, object_hash

from google_work_agent.adapters.llm.ollama import transport
from google_work_agent.application.agents.request_understanding.identify_output_responsibilities import (  # noqa: E501
    build_output_responsibility_output_schema,
    validate_output_responsibility_candidate,
)
from google_work_agent.application.agents.request_understanding.identify_source_dependencies import (  # noqa: E501
    build_source_dependency_output_schema,
    validate_source_dependency_candidate,
)
from google_work_agent.application.prompt_runtime.assemble_prompt import assemble_prompt
from google_work_agent.application.prompt_runtime.prompt_registry import EVALUATION, PromptRegistry
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.runtime_selection import OLLAMA_FIXED_LOOPBACK_ENDPOINT

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "evaluation/results"
SOURCE_ROOT = RESULTS / "064-work-span-codec-v35-connected-t1"
BASELINE_RAW = RESULTS / "064-output-format-v36-t1/raw.json"
PROMPT_ID = "request_understanding.identify_output_responsibilities"
SOURCE_PROMPT_ID = "request_understanding.identify_source_dependencies"
SOURCE_CRITERIA = "evaluation/experiments/064-source-format-v40-criteria.md"
SOURCES = (
    ("CASE-CORE-005", "production"),
    ("CASE-CORE-017", "work-span-codec-v35"),
    ("CASE-CORE-049", "work-span-codec-v35"),
)
CORE5_SOURCES = (
    ("CASE-CORE-009", "064-connected-core8-t1"),
    ("CASE-CORE-019", "064-connected-core8-t1"),
    ("CASE-CORE-023", "064-connected-core8-t1"),
    ("CASE-CORE-025", "064-connected-core8-continuation-t1"),
    ("CASE-CORE-059", "064-connected-core8-continuation-t1"),
)
CORE5_CRITERIA = "evaluation/experiments/064-output-fence-core5-criteria.md"
ARMS = ("schema_constrained", "format_omitted")
CANDIDATE_ARMS = {"omitted": "format_omitted", "json": "format_json"}
TIMEOUT_SECONDS = 180


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _work_ids(call: dict[str, Any]) -> list[str]:
    return [item["unit_id"] for item in call["input"]["requested_work"]["work_units"]]


def arms_for_mode(candidate_mode: str) -> tuple[str, str]:
    if candidate_mode not in CANDIDATE_ARMS:
        raise ValueError("unregistered candidate format mode")
    return "schema_constrained", CANDIDATE_ARMS[candidate_mode]


def reconstruct_payload(
    call: dict[str, Any], *, rebind_current_prompt: bool = False
) -> dict[str, Any]:
    """Run actual Product payload construction with an in-memory HTTP sink only."""
    prompt_id = call.get("prompt_id", PROMPT_ID)
    if prompt_id not in {PROMPT_ID, SOURCE_PROMPT_ID}:
        raise ValueError("unregistered semantic owner")
    if prompt_id == SOURCE_PROMPT_ID and rebind_current_prompt:
        raise ValueError("Source comparison requires the exact historical Prompt")
    registry = PromptRegistry()
    ref = registry.lookup_for_evaluation(prompt_id)
    current_ref = asdict(ref)
    if not rebind_current_prompt and call["prompt_ref"] != current_ref:
        raise ValueError("historical Output PromptRef differs from current artifact")
    if rebind_current_prompt and any(
        call["prompt_ref"].get(key) != value
        for key, value in current_ref.items()
        if key not in {"prompt_version", "content_hash"}
    ):
        raise ValueError("current Prompt rebind cannot change owner/schema contract")
    schema = (
        build_source_dependency_output_schema(
            call["input"]["source_candidates"], work_unit_ids=_work_ids(call)
        )
        if prompt_id == SOURCE_PROMPT_ID
        else build_output_responsibility_output_schema(
            call["input"]["output_candidates"], work_unit_ids=_work_ids(call)
        )
    )
    if schema.json_schema != call["output_schema"]:
        raise ValueError("historical Output schema differs from current owner schema")
    if (
        call["input_sha256"] != object_hash(call["input"])
        or "base_projection" in call["input"]
        or call["state"] != "RETURNED"
        or call["wire_request_count"] != 1
        or call["wire_path"] != "/api/generate"
        or call["runtime_policy"]["local_timeout_seconds"] != TIMEOUT_SECONDS
        or call["temperature"] != call["runtime_policy"]["sampling_temperature"]
        or call["seed"] != call["runtime_policy"]["sampling_seed"]
    ):
        raise ValueError("only hash-bound original single-wire Output FIRST is admissible")
    captured: list[dict[str, Any]] = []

    def capture(**kwargs: Any) -> dict[str, Any]:
        captured.append(deepcopy(kwargs))
        return {"response": "{}"}

    with patch.object(transport, "_post_json", capture):
        transport.OllamaHTTPClient().invoke_structured(
            endpoint=OLLAMA_FIXED_LOOPBACK_ENDPOINT,
            model_id=call["model"],
            prompt_ref=ref,
            prompt_input=call["input"],
            output_schema=schema,
            timeout_seconds=TIMEOUT_SECONDS,
            instruction_text=assemble_prompt(
                ref, call["input"], registry=registry, execution_scope=EVALUATION
            ),
            sampling_temperature=call["temperature"],
            sampling_seed=call["seed"],
        )
    if len(captured) != 1 or captured[0]["path"] != "/api/generate":
        raise ValueError("Product transport must produce exactly one generate payload")
    payload = cast(dict[str, Any], captured[0]["payload"])
    if (
        (not rebind_current_prompt and object_hash(payload) != call["wire_sha256"])
        or payload["options"] != call["wire_options"]
        or payload["think"] != call["wire_think"]
    ):
        raise ValueError("reconstructed Product payload differs from historical wire hash")
    return payload


def payload_for(case: dict[str, Any], arm: str) -> dict[str, Any]:
    if arm not in arms_for_mode(case.get("candidate_mode", "omitted")):
        raise ValueError("unregistered format arm")
    payload = cast(dict[str, Any], deepcopy(case["payload"]))
    if object_hash(payload) != case.get("baseline_wire_sha256", case["source_call"]["wire_sha256"]):
        raise ValueError("registered historical payload changed")
    prompt = json.loads(payload["prompt"])
    if (
        prompt["input"] != case["source_call"]["input"]
        or prompt["output_schema"] != case["source_call"]["output_schema"]
        or payload["format"] != prompt["output_schema"]
    ):
        raise ValueError("validator authority differs from actual wire input/schema")
    if "current_prompt_ref" in case and prompt["prompt_ref"] != {
        key: case["current_prompt_ref"][key]
        for key in ("prompt_id", "prompt_version", "content_hash")
    }:
        raise ValueError("registered current PromptRef differs from actual wire")
    if arm == "format_omitted":
        del payload["format"]
    elif arm == "format_json":
        payload["format"] = "json"
    if arm != "schema_constrained" and object_hash(payload) != case["candidate_wire_sha256"]:
        raise ValueError("candidate payload differs from registered format mode/hash")
    return payload


def make_plan(
    model: dict[str, Any],
    *,
    source_root: Path = SOURCE_ROOT,
    candidate_mode: str = "omitted",
    baseline_raw: Path = BASELINE_RAW,
    input_set: str = "historical3",
    core5_root: Path = RESULTS,
    owner: str = "output",
) -> dict[str, Any]:
    arms = arms_for_mode(candidate_mode)
    if owner not in {"output", "source"} or (
        owner == "source" and (input_set != "historical3" or candidate_mode != "omitted")
    ):
        raise ValueError("Source permits only three frozen FIRSTs and omitted candidate calls")
    prompt_id = SOURCE_PROMPT_ID if owner == "source" else PROMPT_ID
    if input_set not in {"historical3", "core5"} or (
        input_set == "core5" and candidate_mode != "omitted"
    ):
        raise ValueError("Core5 permits only the fixed constrained/omitted paired comparison")
    sources = (
        [(case_id, "production", core5_root / directory) for case_id, directory in CORE5_SOURCES]
        if input_set == "core5"
        else [(case_id, arm, source_root) for case_id, arm in SOURCES]
    )
    source_plans: dict[Path, dict[str, Any]] = {}
    canonical = load_cases()
    cases = []
    for case_id, arm, root in sources:
        source_plan_path = root / "plan.json"
        if source_plan_path not in source_plans:
            source_plan = json.loads(source_plan_path.read_text(encoding="utf-8"))
            if (
                source_plan["model"]["id"] != model["model_id"]
                or source_plan["model"]["digest"] != model["model_digest"]
                or not model["model_digest"]
            ):
                raise ValueError("actual installed model differs from historical model digest")
            if source_plan["dataset_sha256"] != file_hash(DEFAULT_DATASET_PATH) or source_plan[
                "snapshot_sha256"
            ] != file_hash(DEFAULT_PROVIDER_FIXTURE_PATH):
                raise ValueError("historical dataset/fixture binding changed")
            source_plans[source_plan_path] = source_plan
        source_plan = source_plans[source_plan_path]
        directory = root / case_id / arm
        calls_path, raw_path = directory / "calls.json", directory / "raw.json"
        calls = json.loads(calls_path.read_text(encoding="utf-8"))["calls"]
        matches = [
            (index, call)
            for index, call in enumerate(calls)
            if call.get("prompt_id") == prompt_id and "base_projection" not in call["input"]
        ]
        if len(matches) != 1:
            raise ValueError("exactly one original Output FIRST required per fixed source")
        call_index, call = matches[0]
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        binding = next(item for item in source_plan["cases"] if item["case_id"] == case_id)
        if (
            raw["case_binding"] != binding
            or raw["plan_sha256"] != object_hash(source_plan)
            or raw["arm"] != arm
            or binding["case_sha256"] != object_hash(canonical[case_id].raw)
            or canonical[case_id].raw["split"] != "CORE"
            or call["input"]["user_request"] != canonical[case_id].raw["canonical_user_prompt"]
            or call["model"] != model["model_id"]
        ):
            raise ValueError("frozen Case/Run/request/model provenance mismatch")
        if input_set == "core5" or owner == "source":
            _validate_core5_reference_time(call, binding, canonical[case_id].raw, source_plan)
        if owner == "source" and call["temperature"] != 0.05:
            raise ValueError("Source diagnostic must preserve its registered temperature 0.05")
        payload = reconstruct_payload(call, rebind_current_prompt=input_set == "core5")
        candidate_payload = {k: v for k, v in payload.items() if k != "format"}
        if candidate_mode == "json":
            candidate_payload["format"] = "json"
        case = {
            "case_id": case_id,
            "candidate_mode": candidate_mode,
            "case_binding": deepcopy(binding),
            "source_arm": arm,
            "source_calls_path": calls_path.resolve().as_posix(),
            "source_calls_sha256": file_hash(calls_path),
            "source_raw_path": raw_path.resolve().as_posix(),
            "source_raw_sha256": file_hash(raw_path),
            "source_call": deepcopy(call),
            "payload": payload,
            "instruction_sha256": hashlib.sha256(payload["system"].encode()).hexdigest(),
            "candidate_wire_sha256": object_hash(candidate_payload),
        }
        if input_set == "core5":
            current_ref = asdict(PromptRegistry().lookup_for_evaluation(PROMPT_ID))
            case.update(
                input_set="core5",
                source_plan_path=source_plan_path.resolve().as_posix(),
                source_plan_sha256=file_hash(source_plan_path),
                source_plan_object_sha256=object_hash(source_plan),
                source_call_array_index=call_index,
                source_call_sha256=object_hash(call),
                historical_prompt_ref=deepcopy(call["prompt_ref"]),
                historical_wire_sha256=call["wire_sha256"],
                current_prompt_ref=current_ref,
                prompt_ref_diff={
                    key: {"historical": call["prompt_ref"].get(key), "current": value}
                    for key, value in current_ref.items()
                    if call["prompt_ref"].get(key) != value
                },
                baseline_wire_sha256=object_hash(payload),
                historical_response_reused=False,
                historical_score_reused=False,
                fence_admission="EVALUATION_ONLY_SINGLE_JSON_FENCE",
            )
        if owner == "source":
            case.update(
                owner="source",
                source_plan_path=source_plan_path.resolve().as_posix(),
                source_plan_sha256=file_hash(source_plan_path),
                source_call_array_index=call_index,
                source_call_sha256=object_hash(call),
                fence_admission="EVALUATION_ONLY_SINGLE_JSON_FENCE",
            )
        cases.append(case)
    bound_files: tuple[str, ...] = (
        "scripts/evaluate_output_format_ablation.py",
        "scripts/evaluate_effect_prohibition_sampler.py",
        "scripts/ru_observation.py",
        "src/google_work_agent/adapters/llm/ollama/transport.py",
        "src/google_work_agent/application/agents/request_understanding/identify_output_responsibilities.py",
        "src/google_work_agent/application/agents/request_understanding/identify_effect_prohibitions.py",
        "src/google_work_agent/application/agents/request_understanding/contracts/work_unit_binding.py",
        "src/google_work_agent/application/agents/request_understanding/contracts/request_intent.py",
        "src/google_work_agent/application/prompt_runtime/assemble_prompt.py",
        "src/google_work_agent/application/prompt_runtime/prompt_registry.py",
        "src/google_work_agent/application/prompt_runtime/prompt_manifest.json",
        "src/google_work_agent/application/prompt_runtime/prompt_runtime_input_contract_v1.json",
        "src/google_work_agent/application/prompt_runtime/sources/request_understanding.identify_output_responsibilities.md",
        "src/google_work_agent/ports/llm/output_schema_validation.py",
    )
    if input_set == "core5":
        bound_files += (CORE5_CRITERIA,)
    if owner == "source":
        bound_files += (
            SOURCE_CRITERIA,
            "src/google_work_agent/application/agents/request_understanding/identify_source_dependencies.py",
            "src/google_work_agent/application/agents/request_understanding/contracts/source_dependency_decision.py",
            "src/google_work_agent/application/prompt_runtime/sources/request_understanding.identify_source_dependencies.md",
        )
    plan: dict[str, Any] = {
        "schema_version": 1,
        "kind": "FROZEN_OUTPUT_FIRST_FORMAT_ONLY_OWNER_DIAGNOSTIC",
        "candidate_mode": candidate_mode,
        "head_sha": head(),
        "model": deepcopy(model),
        "source_plan_path": source_plan_path.resolve().as_posix(),
        "source_plan_sha256": file_hash(source_plan_path),
        "dataset_sha256": file_hash(DEFAULT_DATASET_PATH),
        "fixture_sha256": file_hash(DEFAULT_PROVIDER_FIXTURE_PATH),
        "source_hashes": {path: file_hash(ROOT / path) for path in bound_files},
        "policy": {
            "trials_per_case_arm": 1,
            "max_http_generation_calls": len(cases) * (1 if candidate_mode == "json" else 2),
            "reused_baseline_calls": 3 if candidate_mode == "json" else 0,
            "http_calls_per_arm": 1,
            "timeout_seconds_per_arm": TIMEOUT_SECONDS,
            "schema_repairs": 0,
            "semantic_revisions": 0,
            "http_retries": 0,
            "rerun_to_pass": 0,
            "concurrent_generation_calls": 1,
            "graph_calls": 0,
            "provider_calls": 0,
            "runtime_options": "EXACT_HISTORICAL_WIRE_UNCHANGED",
            "semantic_verdict": "UNREVIEWED",
        },
        "arms": list(arms),
        "cases": cases,
        "execution_order": [
            {"case_id": case["case_id"], "arm": arm}
            for index, case in enumerate(cases)
            for arm in (arms if index % 2 == 0 else tuple(reversed(arms)))
            if candidate_mode != "json" or arm == "format_json"
        ],
    }
    if input_set == "core5":
        del plan["source_plan_path"], plan["source_plan_sha256"]
        plan["policy"]["runtime_options"] = "EXACT_HISTORICAL_OPTIONS_AND_THINK_UNCHANGED"
        plan.update(
            input_set="core5",
            kind="CURRENT_PROMPT_FROZEN_CORE5_OUTPUT_OWNER_DIAGNOSTIC",
            source_plans=[
                {
                    "path": path.resolve().as_posix(),
                    "sha256": file_hash(path),
                    "object_sha256": object_hash(value),
                    "head_sha": value["head_sha"],
                    "model": deepcopy(value["model"]),
                }
                for path, value in source_plans.items()
            ],
            historical_response_reuse=False,
            historical_score_reuse=False,
        )
    if candidate_mode == "json":
        plan["reused_baseline"] = load_reused_baseline(baseline_raw, plan)
    if owner == "source":
        plan.update(owner="source", kind="FROZEN_SOURCE_FIRST_FORMAT_ONLY_OWNER_DIAGNOSTIC")
        plan["execution_order"] = [
            {"case_id": case["case_id"], "arm": "format_omitted"} for case in cases
        ]
        plan["policy"].update(max_http_generation_calls=3, reused_baseline_calls=3)
        plan["reused_source_baseline"] = load_source_baseline(cases)
    return plan


def _validate_core5_reference_time(
    call: dict[str, Any],
    binding: dict[str, Any],
    canonical: dict[str, Any],
    source_plan: dict[str, Any],
) -> None:
    """Keep the observed Case clock and fault binding, never replace them with now."""
    reference = call["input"]["run_reference_time"]
    observed = datetime.fromisoformat(reference["reference_time"])
    case_reference = (canonical.get("evaluation_context") or {}).get("run_reference_time")
    expected_ms = source_plan["preregistered_reference_time_ms"]
    if case_reference is not None:
        case_clock = datetime.fromisoformat(case_reference)
        if case_clock.utcoffset() is None:
            raise ValueError("Canonical reference time requires an explicit offset")
        expected_ms = int(case_clock.timestamp() * 1000)
    if (
        observed.utcoffset() is None
        or int(observed.timestamp()) != binding["effective_reference_time_ms"] // 1000
        or binding["effective_reference_time_ms"] != expected_ms
        or binding["case_reference_time"] != case_reference
        or binding["reference_time_source"]
        != ("CASE" if case_reference is not None else "PREREGISTERED_PAIR_START")
        or binding["fault_profile"] != canonical["evaluation_gold"]["fault_profile"]
        or binding["request_sha256"] != object_hash(canonical["canonical_user_prompt"])
    ):
        raise ValueError("historical Case reference time/request/fault binding changed")


def load_reused_baseline(path: Path, plan: dict[str, Any]) -> dict[str, Any]:
    """Bind existing constrained FIRSTs; never create replacement baseline calls."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    binding = raw["binding"]
    if not raw["completed"] or raw["actual_http_calls"] != 6:
        raise ValueError("reused baseline must be the completed six-call comparison")
    for field in (
        "model",
        "source_plan_path",
        "source_plan_sha256",
        "dataset_sha256",
        "fixture_sha256",
    ):
        if binding[field] != plan[field]:
            raise ValueError(f"reused baseline binding changed: {field}")
    if binding.get("candidate_mode", "omitted") != "omitted" or binding["arms"] != list(ARMS):
        raise ValueError("only the original constrained/omitted comparison can supply baseline")
    for source_path, digest in plan["source_hashes"].items():
        if source_path == "scripts/evaluate_output_format_ablation.py":
            continue
        if binding["source_hashes"].get(source_path) != digest:
            raise ValueError(f"reused baseline Product/dependency code changed: {source_path}")
    origins = {case["case_id"]: case for case in binding["cases"]}
    rows = []
    for case in plan["cases"]:
        prior = origins[case["case_id"]]
        for field in (
            "case_binding",
            "source_call",
            "payload",
            "source_calls_sha256",
            "source_raw_sha256",
        ):
            if prior[field] != case[field]:
                raise ValueError(f"reused baseline input/wire provenance changed: {field}")
        matches = [
            row
            for row in raw["results"]
            if row["case_id"] == case["case_id"] and row["arm"] == "schema_constrained"
        ]
        if len(matches) != 1:
            raise ValueError("exactly one constrained result per fixed Case required")
        row = matches[0]
        if (
            row["state"] != "RETURNED"
            or row["wire_request_count"] != 1
            or row["wire_sha256"] != case["source_call"]["wire_sha256"]
            or row["input_sha256"] != case["source_call"]["input_sha256"]
            or row["wire_options"] != case["payload"]["options"]
            or row["wire_think"] != case["payload"]["think"]
            or row["format_present"] is not True
            or row["schema_repairs"] != 0
            or row["http_retries"] != 0
            or row["validation"] != validate_response(row["content"], case)
        ):
            raise ValueError(
                "reused baseline result/validator/runtime differs from frozen authority"
            )
        rows.append(
            {
                "case_id": case["case_id"],
                "row_sha256": object_hash(row),
                "new_call": False,
                "record": deepcopy(row),
            }
        )
    return {
        "path": path.resolve().as_posix(),
        "sha256": file_hash(path),
        "source_head_sha": binding["head_sha"],
        "records": rows,
    }


def load_source_baseline(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reuse the actual Source FIRST, with explicit current structural revalidation."""
    rows = []
    for case in cases:
        for kind in ("calls", "raw", "plan"):
            if file_hash(Path(case[f"source_{kind}_path"])) != case[f"source_{kind}_sha256"]:
                raise ValueError("frozen Source baseline file changed")
        calls = json.loads(Path(case["source_calls_path"]).read_text(encoding="utf-8"))["calls"]
        call = calls[case["source_call_array_index"]]
        if (
            call != case["source_call"]
            or object_hash(call) != case["source_call_sha256"]
            or call["prompt_id"] != SOURCE_PROMPT_ID
            or reconstruct_payload(call) != case["payload"]
        ):
            raise ValueError("frozen Source FIRST input/wire/Prompt changed")
        validation = validate_response(call["content"], case)
        rows.append(
            {
                "case_id": case["case_id"],
                "arm": "schema_constrained",
                "new_call": False,
                "owner": "source",
                "origin_path": case["source_calls_path"],
                "origin_raw_sha256": case["source_calls_sha256"],
                "origin_row_sha256": case["source_call_sha256"],
                "origin_array_index": case["source_call_array_index"],
                **{
                    key: deepcopy(call[key])
                    for key in (
                        "state",
                        "content",
                        "input_sha256",
                        "wire_sha256",
                        "wire_options",
                        "wire_think",
                        "wire_request_count",
                        "prompt_ref",
                        "model",
                    )
                },
                **{
                    key: call.get(key)
                    for key in (
                        "input_tokens",
                        "output_tokens",
                        "latency_ms",
                        "wall_latency_ms",
                    )
                },
                "format_present": True,
                "schema_repairs": 0,
                "http_retries": 0,
                "validation": validation,
                "validation_origin": "CURRENT_OWNER_REVALIDATION_OF_ORIGINAL_FIRST",
                "source_observations": source_observations(validation, case),
                "semantic_verdict": "UNREVIEWED",
                "business_success": "NOT_EVALUATED",
            }
        )
    return rows


def source_observations(validation: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    """Copy decisions and inventory equality only; never infer business necessity."""
    decisions = validation.get("validated_output", {}).get("source_dependencies", [])
    inventory = {
        item["resource_type"]: item["owned_fact_kinds"]
        for item in case["source_call"]["input"]["source_candidates"]
    }
    return {
        "decisions": [
            {
                **deepcopy(item),
                "candidate_owned_fact_kinds": deepcopy(inventory[item["resource_type"]]),
                "full_capability_inventory_selected": (
                    item["dependency"] == "SOURCE_REQUIRED"
                    and set(item["required_information"]) == set(inventory[item["resource_type"]])
                ),
                "business_necessity": "UNREVIEWED_REQUIRED_OPTIONAL_OR_UNNECESSARY",
            }
            for item in decisions
        ],
        "business_review": {
            "required_source_omission": "UNREVIEWED",
            "optional_source_use": "UNREVIEWED",
            "unnecessary_source_use": "UNREVIEWED",
            "new_output_as_existing_source": "UNREVIEWED",
        },
        "structural_validation_only": True,
    }


def validate_response(content: object, case: dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(content) if isinstance(content, str) else None
    except json.JSONDecodeError as error:
        return {"structural_result": "INVALID_JSON", "error": str(error)}
    errors = list(validate_output_schema(value, case["source_call"]["output_schema"]))
    if errors:
        return {"structural_result": "INVALID_SCHEMA", "schema_errors": errors}
    projection = case["source_call"]["input"]
    try:
        validated = (
            validate_source_dependency_candidate(
                value,
                source_candidates=projection["source_candidates"],
                work_unit_ids=_work_ids(case["source_call"]),
            )
            if case.get("owner") == "source"
            else validate_output_responsibility_candidate(
                value,
                output_candidates=projection["output_candidates"],
                effect_prohibitions={"effect_prohibitions": projection["effect_prohibitions"]},
                work_unit_ids=_work_ids(case["source_call"]),
            )
        )
    except ValueError as error:
        return {
            "structural_result": "OWNER_REJECTED",
            "error_type": type(error).__name__,
            "error": str(error),
            "parsed_output": value,
        }
    return {"structural_result": "VALIDATED", "validated_output": validated}


def unwrap_single_json_fence(content: str) -> str:
    """Admit exactly one lowercase json fence, not arbitrary JSON extraction."""
    match = re.fullmatch(r"```json\r?\n(?P<body>[\s\S]*?)\r?\n```", content.strip(" \t\r\n"))
    if match is None or "```" in match["body"]:
        raise ValueError("response is not a single complete json-tagged fence")
    return match["body"]


def validate_fenced_response(content: object, case: dict[str, Any]) -> dict[str, Any]:
    """Separate the original strict result from the evaluation-only admission."""
    strict = validate_response(content, case)
    result: dict[str, Any] = {
        "strict_validation": strict,
        "candidate_validation": deepcopy(strict),
        "admission": "STRICT_JSON_UNCHANGED",
        "raw_content": content,
        "semantic_verdict": "UNREVIEWED",
        "business_success": "NOT_EVALUATED",
        "model_calls": 0,
    }
    if strict["structural_result"] != "INVALID_JSON" or not isinstance(content, str):
        return result
    try:
        body = unwrap_single_json_fence(content)
    except ValueError as error:
        result.update(admission="FENCE_REJECTED", admission_error=str(error))
        return result
    result.update(
        admission="SINGLE_JSON_FENCE_UNWRAPPED",
        candidate_content_sha256=hashlib.sha256(body.encode()).hexdigest(),
        candidate_validation=validate_response(body, case),
    )
    return result


def regrade_fenced_raw(paths: list[Path]) -> dict[str, Any]:
    """Revalidate actual candidate FIRSTs without catalog/Graph/model/Provider calls."""
    if not paths:
        raise ValueError("at least one registered source raw is required")
    rows, sources = [], []
    seen: set[Path] = set()
    for path in paths:
        path = path.resolve()
        if path in seen:
            raise ValueError("same source raw cannot be counted twice")
        seen.add(path)
        original_bytes = path.read_bytes()
        digest = hashlib.sha256(original_bytes).hexdigest()
        raw = json.loads(original_bytes)
        binding = raw["binding"]
        if (
            not raw["completed"]
            or binding["kind"] != "FROZEN_OUTPUT_FIRST_FORMAT_ONLY_OWNER_DIAGNOSTIC"
        ):
            raise ValueError("completed registered format-owner diagnostic required")
        for source_path, expected_hash in binding["source_hashes"].items():
            if source_path.startswith("src/") and file_hash(ROOT / source_path) != expected_hash:
                raise ValueError("historical Product schema/Prompt/validator dependency changed")
        cases = {case["case_id"]: case for case in binding["cases"]}
        if set(cases) != {case_id for case_id, _ in SOURCES}:
            raise ValueError("revalidation is limited to the fixed three Output inputs")
        source_rows = []
        for index, row in enumerate(raw["results"]):
            if row["arm"] not in {"format_omitted", "format_json"}:
                continue
            case = cases[row["case_id"]]
            if (
                reconstruct_payload(case["source_call"]) != case["payload"]
                or row["wire_sha256"] != object_hash(payload_for(case, row["arm"]))
                or row["input_sha256"] != case["source_call"]["input_sha256"]
                or row["state"] != "RETURNED"
                or row["wire_request_count"] != 1
                or row["schema_repairs"] != 0
                or row["http_retries"] != 0
            ):
                raise ValueError("record is not the registered returned single FIRST")
            result = validate_fenced_response(row["content"], case)
            if result["strict_validation"] != row["validation"]:
                raise ValueError("original strict validation changed; do not overwrite history")
            source_rows.append(
                {
                    "source_path": path.as_posix(),
                    "source_sha256": digest,
                    "source_head_sha": binding["head_sha"],
                    "source_record_index": index,
                    "source_row_sha256": object_hash(row),
                    "case_id": row["case_id"],
                    "arm": row["arm"],
                    "new_call": False,
                    "historical_validation": deepcopy(row["validation"]),
                    **result,
                }
            )
        if len(source_rows) != 3 or len({row["case_id"] for row in source_rows}) != 3:
            raise ValueError("exactly three candidate FIRSTs required from each source raw")
        if path.read_bytes() != original_bytes:
            raise ValueError("source raw changed during revalidation")
        rows.extend(source_rows)
        sources.append({"path": path.as_posix(), "sha256": digest})
    return {
        "schema_version": 1,
        "kind": "OFFLINE_SINGLE_JSON_FENCE_ADMISSION_REVALIDATION",
        "head_sha": head(),
        "runner_sha256": file_hash(Path(__file__)),
        "sources": sources,
        "rows": rows,
        "model_calls": 0,
        "provider_calls": 0,
        "raw_files_changed": 0,
        "semantic_verdict": "UNREVIEWED",
        "summary": {
            "reused_observations": len(rows),
            "new_calls": 0,
            "strict": dict(Counter(row["strict_validation"]["structural_result"] for row in rows)),
            "candidate": dict(
                Counter(row["candidate_validation"]["structural_result"] for row in rows)
            ),
            "admission": dict(Counter(row["admission"] for row in rows)),
        },
    }


def run_arm(
    case: dict[str, Any],
    arm: str,
    *,
    persist: Callable[[dict[str, Any]], None],
) -> dict[str, Any]:
    payload = payload_for(case, arm)
    record: dict[str, Any] = {
        "case_id": case["case_id"],
        "arm": arm,
        "state": "DISPATCH_STARTED",
        "wire_sha256": object_hash(payload),
        "wire_options": deepcopy(payload["options"]),
        "wire_think": payload["think"],
        "format_present": "format" in payload,
        "candidate_mode": case.get("candidate_mode", "omitted"),
        "new_call": True,
        "input_sha256": case["source_call"]["input_sha256"],
        "semantic_verdict": "UNREVIEWED",
        "business_success": "NOT_EVALUATED",
        "wire_request_count": 1,
        "schema_repairs": 0,
        "http_retries": 0,
    }
    if case.get("input_set") == "core5":
        record.update(
            prompt_ref=deepcopy(case["current_prompt_ref"]),
            historical_prompt_ref=deepcopy(case["historical_prompt_ref"]),
            historical_wire_sha256=case["historical_wire_sha256"],
            historical_response_reused=False,
        )
    if case.get("owner") == "source":
        record.update(owner="source", prompt_ref=deepcopy(case["source_call"]["prompt_ref"]))
    persist(record)
    started = time.monotonic()
    try:
        response = transport._post_json(
            endpoint=OLLAMA_FIXED_LOOPBACK_ENDPOINT,
            path="/api/generate",
            payload=payload,
            timeout_seconds=TIMEOUT_SECONDS,
        )
        # Never persist a provider's hidden reasoning, including on malformed output.
        thinking = response.get("thinking")
        total_duration = response.get("total_duration")
        record.update(
            state="RETURNED",
            content=response.get("response"),
            model=response.get("model"),
            done=response.get("done"),
            done_reason=response.get("done_reason"),
            thinking_present=bool(thinking),
            thinking_characters=len(thinking) if isinstance(thinking, str) else 0,
            input_tokens=response.get("prompt_eval_count"),
            output_tokens=response.get("eval_count"),
            latency_ms=total_duration // 1_000_000 if type(total_duration) is int else None,
        )
        if case.get("input_set") == "core5" or case.get("owner") == "source":
            for field in ("load_duration", "prompt_eval_duration", "eval_duration"):
                duration = response.get(field)
                record[f"{field}_ms"] = duration // 1_000_000 if type(duration) is int else None
        persist(record)
        record["validation"] = validate_response(record["content"], case)
        if (
            case.get("input_set") == "core5" or case.get("owner") == "source"
        ) and arm == "format_omitted":
            record["fence_validation"] = validate_fenced_response(record["content"], case)
        if case.get("owner") == "source":
            record["strict_source_observations"] = source_observations(record["validation"], case)
            record["source_observations"] = source_observations(
                record.get("fence_validation", {}).get(
                    "candidate_validation", record["validation"]
                ),
                case,
            )
    except Exception as error:
        record.update(
            state="ERROR",
            error_type=type(error).__name__,
            error=str(error)[:500],
        )
    finally:
        record["wall_latency_ms"] = int((time.monotonic() - started) * 1000)
        persist(record)
    return record


def execute_plan(plan: dict[str, Any], output: Path, *, plan_sha256: str) -> dict[str, Any]:
    if object_hash(plan) != plan_sha256:
        raise ValueError("registered plan object hash mismatch")
    output = output.resolve()
    if not output.is_relative_to(RESULTS.resolve()) or output == RESULTS.resolve():
        raise ValueError("dedicated evaluation/results directory required")
    candidate_mode = plan.get("candidate_mode", "omitted")
    input_set = plan.get("input_set", "historical3")
    owner = plan.get("owner", "output")
    if owner not in {"output", "source"} or (
        owner == "source" and (input_set != "historical3" or candidate_mode != "omitted")
    ):
        raise ValueError("unregistered Source comparison")
    if input_set not in {"historical3", "core5"} or (
        input_set == "core5" and candidate_mode != "omitted"
    ):
        raise ValueError("only the registered input set and format mode are allowed")
    sources = CORE5_SOURCES if input_set == "core5" else SOURCES
    arms = arms_for_mode(candidate_mode)
    expected_order = [
        {"case_id": case_id, "arm": arm}
        for index, (case_id, _) in enumerate(sources)
        for arm in (arms if index % 2 == 0 else tuple(reversed(arms)))
        if (owner == "source" and arm == "format_omitted")
        or (owner == "output" and (candidate_mode != "json" or arm == "format_json"))
    ]
    if (
        plan["execution_order"] != expected_order
        or plan["arms"] != list(arms)
        or any(case.get("candidate_mode", "omitted") != candidate_mode for case in plan["cases"])
        or any(case.get("input_set", "historical3") != input_set for case in plan["cases"])
        or any(case.get("owner", "output") != owner for case in plan["cases"])
        or tuple(item["case_id"] for item in plan["cases"]) != tuple(row[0] for row in sources)
        or plan["policy"]["max_http_generation_calls"]
        != len(sources) * (1 if candidate_mode == "json" or owner == "source" else 2)
        or plan["policy"]["reused_baseline_calls"]
        != (3 if candidate_mode == "json" or owner == "source" else 0)
    ):
        raise ValueError("only the registered inputs and mode-bound one-shot arms are allowed")
    reused = []
    if owner == "source":
        reused = load_source_baseline(plan["cases"])
        if reused != plan["reused_source_baseline"]:
            raise ValueError("Source baseline revalidation changed after registration")
    elif candidate_mode == "json":
        authority = plan["reused_baseline"]
        if load_reused_baseline(Path(authority["path"]), plan) != authority:
            raise ValueError("reused baseline file/row hashes changed after registration")
        reused = [
            {
                **deepcopy(row["record"]),
                "new_call": False,
                "origin_path": authority["path"],
                "origin_raw_sha256": authority["sha256"],
                "origin_row_sha256": row["row_sha256"],
            }
            for row in authority["records"]
        ]
    for case in plan["cases"]:
        for arm in arms:
            payload_for(case, arm)
    if output.exists() and any(path.name != "preregistered-plan.json" for path in output.iterdir()):
        raise ValueError("execution output must be new; prior partial/failed trial is preserved")
    claim = RESULTS / ".output-format-trials" / f"{plan_sha256}.json"
    write_json(claim, {"output": output.as_posix()}, exclusive=True)
    raw: dict[str, Any] = {
        "binding": plan,
        "results": [],
        "reused_results": reused,
        "completed": False,
    }
    path = output / "raw.json"
    write_json(path, raw, exclusive=True)
    by_id = {case["case_id"]: case for case in plan["cases"]}
    for entry in plan["execution_order"]:

        def persist(record: dict[str, Any]) -> None:
            if not raw["results"] or raw["results"][-1] is not record:
                raw["results"].append(record)
            write_json(path, raw)

        run_arm(by_id[entry["case_id"]], entry["arm"], persist=persist)
    raw.update(
        completed=True,
        actual_http_calls=sum(row["wire_request_count"] for row in raw["results"]),
        reused_http_calls=len(reused),
        metrics_by_arm={
            arm: metrics([r for r in [*raw["results"], *reused] if r["arm"] == arm]) for arm in arms
        },
        new_call_metrics=metrics(raw["results"]),
        reused_call_metrics=metrics(reused),
        semantic_verdict="UNREVIEWED",
        provider_calls=0,
    )
    write_json(path, raw)
    return raw


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result-dir", type=Path, required=True)
    parser.add_argument("--execute-plan", type=Path)
    parser.add_argument("--expected-plan-sha256")
    parser.add_argument("--candidate-mode", choices=tuple(CANDIDATE_ARMS), default="omitted")
    parser.add_argument("--input-set", choices=("historical3", "core5"), default="historical3")
    parser.add_argument("--owner", choices=("output", "source"), default="output")
    parser.add_argument("--reuse-baseline-raw", type=Path, default=BASELINE_RAW)
    parser.add_argument("--regrade-fenced-raw", type=Path, action="append")
    args = parser.parse_args()
    output = args.result_dir.resolve()
    if not output.is_relative_to(RESULTS.resolve()) or output == RESULTS.resolve():
        raise ValueError("dedicated evaluation/results directory required")
    if args.regrade_fenced_raw:
        if (
            args.execute_plan is not None
            or args.expected_plan_sha256 is not None
            or args.input_set != "historical3"
            or args.owner != "output"
        ):
            raise ValueError("offline revalidation cannot be combined with model execution")
        report = regrade_fenced_raw(args.regrade_fenced_raw)
        path = output / "fence-revalidation.json"
        write_json(path, report, exclusive=True)
        print(json.dumps({"path": str(path), **report["summary"]}))
        return
    current = make_plan(
        inspect_model(transport.OllamaHTTPClient()),
        candidate_mode=args.candidate_mode,
        baseline_raw=args.reuse_baseline_raw,
        input_set=args.input_set,
        owner=args.owner,
    )
    if args.execute_plan is None:
        path = output / "preregistered-plan.json"
        write_json(path, current, exclusive=True)
        print(json.dumps({"plan": str(path), "sha256": object_hash(current), "model_calls": 0}))
        return
    plan = json.loads(args.execute_plan.read_text(encoding="utf-8"))
    if plan != current or object_hash(plan) != args.expected_plan_sha256:
        raise ValueError(
            "registered HEAD/input/raw/code/Prompt/schema/model/runtime binding changed"
        )
    raw = execute_plan(plan, output, plan_sha256=args.expected_plan_sha256)
    print(
        json.dumps(
            {
                "actual_http_calls": raw["actual_http_calls"],
                "reused_http_calls": raw["reused_http_calls"],
                "semantic_verdict": "UNREVIEWED",
                "metrics_by_arm": raw["metrics_by_arm"],
            }
        )
    )


if __name__ == "__main__":
    main()
