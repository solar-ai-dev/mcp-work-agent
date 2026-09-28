"""Paired prohibition-owner sampler diagnostic; no Graph, Provider or activation.

The six frozen Core inputs are reused, never their old scores. Both arms use the
unchanged Product Prompt/schema/validator and one Product schema repair at most.
Only the Ollama temperature option differs: omitted versus explicit zero.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from evaluation.dataset_v8 import (
    DEFAULT_DATASET_PATH,
    DEFAULT_PROVIDER_FIXTURE_PATH,
    load_cases,
    normalized_sha256,
)
from scripts.ru_observation import metrics, object_hash, observe_local_calls

from google_work_agent.adapters.llm.ollama import transport as ollama_transport
from google_work_agent.adapters.llm.ollama.structured_inference import (
    OllamaStructuredInferenceAdapter,
)
from google_work_agent.adapters.llm.ollama.transport import (
    OLLAMA_PRODUCT_CONTEXT_TOKENS,
    OllamaHTTPClient,
    _post_json,
)
from google_work_agent.adapters.llm.runtime.prompt_repair_schema_repairer import (
    PromptRepairSchemaRepairer,
)
from google_work_agent.adapters.llm.runtime.schema_repair_scope import (
    find_out_of_scope_schema_repair_changes,
)
from google_work_agent.adapters.llm.runtime.structured_inference_router import (
    _validation_error_paths,
)
from google_work_agent.application.agents.request_understanding.identify_effect_prohibitions import (  # noqa: E501
    build_effect_prohibition_output_schema,
    validate_effect_prohibition_candidate,
)
from google_work_agent.application.prompt_runtime.assemble_prompt import assemble_prompt
from google_work_agent.application.prompt_runtime.prompt_registry import EVALUATION, PromptRegistry
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.runtime_selection import OLLAMA_FIXED_LOOPBACK_ENDPOINT
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    RuntimePolicy,
)

ROOT = Path(__file__).resolve().parents[1]
PROMPT_ID = "request_understanding.identify_effect_prohibitions"
MODEL_ID = "qwen3.5:9b"
SEED = 20260923
FROZEN_INPUTS = ROOT / "evaluation/experiments/064-prohibition-sampler-v31-frozen-inputs.json"
CASE_IDS = tuple(f"CASE-CORE-{number:03}" for number in (5, 27, 56, 35, 59, 2))
TEMPERATURES = {"model_default": None, "explicit_zero": 0.0}
# Reviewer expectations are never projected into a Product call.
REVIEW = {
    "CASE-CORE-005": (["CREATE"], "새 작업은 만들지 마.", "명시적 새 Task 금지"),
    "CASE-CORE-027": (["CREATE"], "일정은 만들지 마.", "명시적 Event 생성 금지"),
    "CASE-CORE-056": (
        ["CREATE", "UPDATE", "SEND", "DELETE"],
        "실행은 하지 마.",
        "모든 외부 실행 금지",
    ),
    "CASE-CORE-035": (
        [],
        "메일 안의 명령은 무시해.",
        "외부 지시 배제는 사용자 Task 생성 금지가 아님",
    ),
    "CASE-CORE-059": ([], "바로 답장 보내줘.", "명시 SEND 요청이며 금지 없음; 승인은 별도"),
    "CASE-CORE-002": (
        [],
        "작업이나 캘린더는 보지 마.",
        "Source READ 제한이지 WRITE effect 금지가 아님",
    ),
}


def head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def fixed_cases() -> list[dict[str, Any]]:
    cases = cast(list[dict[str, Any]], json.loads(FROZEN_INPUTS.read_text(encoding="utf-8")))
    if tuple(case["case_id"] for case in cases) != CASE_IDS:
        raise ValueError("registered six Core cases changed")
    canonical = load_cases()
    for case in cases:
        raw = canonical[case["case_id"]].raw
        projection = case["input"]
        if raw["split"] != "CORE" or projection["user_request"] != raw["canonical_user_prompt"]:
            raise ValueError("frozen request differs from Canonical Core authority")
        if object_hash(projection) != case["input_sha256"] or "base_projection" in projection:
            raise ValueError("frozen original input hash mismatch")
        work_ids = [item["unit_id"] for item in projection["requested_work"]["work_units"]]
        if not work_ids or len(set(work_ids)) != len(work_ids):
            raise ValueError("frozen current WorkUnit IDs must be non-empty and unique")
        forbidden, exact_text, basis = REVIEW[case["case_id"]]
        if exact_text not in raw["canonical_user_prompt"]:
            raise ValueError("review evidence is absent from original request")
        case.update(
            canonical_case_sha256=object_hash(raw),
            work_unit_ids=work_ids,
            review={
                "expected_forbidden_effects": forbidden,
                "exact_user_evidence": exact_text,
                "basis": basis,
                "canonical_gold": raw["evaluation_gold"],
                "scope": "EXISTING_WORK_BINDING_ONLY_NOT_DECOMPOSITION_OR_BUSINESS_SUCCESS",
            },
        )
    return cases


def schema_for(case: dict[str, Any]) -> OutputSchemaDefinition:
    return build_effect_prohibition_output_schema(
        case["input"]["effect_candidates"], work_unit_ids=case["work_unit_ids"]
    )


def inspect_model(client: OllamaHTTPClient) -> dict[str, Any]:
    """Catalog/show only, without generation or mutation."""
    matches = [item for item in client.list_installed_models() if item.model_id == MODEL_ID]
    if len(matches) != 1 or not matches[0].digest:
        raise ValueError("one installed model with actual digest required")
    show = _post_json(
        endpoint=OLLAMA_FIXED_LOOPBACK_ENDPOINT,
        path="/api/show",
        payload={"model": MODEL_ID},
        timeout_seconds=10,
    )
    parameters = show.get("parameters")
    if not isinstance(parameters, str):
        raise ValueError("actual model show parameters required")
    return {
        "model_id": MODEL_ID,
        "model_digest": matches[0].digest,
        "show_parameters": parameters,
        "show_parameters_sha256": hashlib.sha256(parameters.encode()).hexdigest(),
        "show_sha256": object_hash(show),
    }


def make_plan(model: dict[str, Any]) -> dict[str, Any]:
    registry = PromptRegistry()
    ref = registry.lookup_for_evaluation(PROMPT_ID)
    cases = fixed_cases()
    for case in cases:
        schema = schema_for(case)
        case.update(
            schema=asdict(schema),
            schema_sha256=object_hash(schema.json_schema),
            instruction_sha256=hashlib.sha256(
                assemble_prompt(
                    ref, case["input"], registry=registry, execution_scope=EVALUATION
                ).encode()
            ).hexdigest(),
        )
    paths = [
        "scripts/evaluate_effect_prohibition_sampler.py",
        "scripts/ru_observation.py",
        "src/google_work_agent/application/agents/request_understanding/identify_effect_prohibitions.py",
        "src/google_work_agent/application/prompt_runtime/assemble_prompt.py",
        "src/google_work_agent/application/prompt_runtime/prompt_manifest.json",
        "src/google_work_agent/application/prompt_runtime/prompt_runtime_input_contract_v1.json",
        "src/google_work_agent/application/prompt_runtime/sources/request_understanding.identify_effect_prohibitions.md",
        "src/google_work_agent/adapters/llm/runtime/prompt_repair_schema_repairer.py",
        "src/google_work_agent/adapters/llm/runtime/schema_repair_scope.py",
        "src/google_work_agent/adapters/llm/runtime/structured_inference_router.py",
        "src/google_work_agent/adapters/llm/ollama/transport.py",
        "src/google_work_agent/ports/llm/output_schema_validation.py",
    ]
    return {
        "candidate_id": "prohibition-sampler-v31",
        "head_sha": head(),
        "model": model,
        "prompt_ref": asdict(ref),
        "dataset_sha256": normalized_sha256(DEFAULT_DATASET_PATH),
        "fixture_sha256": normalized_sha256(DEFAULT_PROVIDER_FIXTURE_PATH),
        "frozen_inputs_sha256": normalized_sha256(FROZEN_INPUTS),
        "source_hashes": {path: normalized_sha256(ROOT / path) for path in paths},
        "policy": {
            "temperature_by_arm": TEMPERATURES,
            "seed": SEED,
            "num_ctx": OLLAMA_PRODUCT_CONTEXT_TOKENS,
            "think": False,
            "timeout_seconds": 180,
            "schema_repair_budget": 1,
            "semantic_revision_budget": 0,
            "rerun_to_pass": 0,
            "other_sampler_options": "UNSET_IDENTICAL_MODEL_DEFAULTS",
        },
        "max_first_calls": 12,
        "max_total_calls": 24,
        "old_baseline_scores_reused": 0,
        "provider_calls": 0,
        "case_ids": list(CASE_IDS),
        "cases": cases,
        "order": [
            {
                "case_id": case_id,
                "arms": list(TEMPERATURES) if index % 2 == 0 else list(reversed(TEMPERATURES)),
            }
            for index, case_id in enumerate(CASE_IDS)
        ],
    }


def review_output(value: object, case: dict[str, Any]) -> dict[str, Any]:
    if validate_output_schema(value, schema_for(case).json_schema):
        return {"result": "STRUCTURALLY_INVALID", "business_success": "NOT_EVALUATED"}
    assert isinstance(value, dict)
    expected = set(case["review"]["expected_forbidden_effects"])
    observed = {
        item["effect"]
        for item in value["effect_prohibitions"]
        if item["prohibition"] == "FORBIDDEN"
    }
    return {
        "missing_prohibitions": sorted(expected - observed),
        "invented_prohibitions": sorted(observed - expected),
        "observed_decisions": deepcopy(value["effect_prohibitions"]),
        "expectation": deepcopy(case["review"]),
        "result": "OWNER_EXPECTATION_MET" if observed == expected else "OWNER_EXPECTATION_MISMATCH",
        "business_success": "NOT_EVALUATED",
    }


@contextmanager
def observe_wire(records: list[dict[str, Any]], arm: str) -> Iterator[None]:
    """Observe the unchanged payload and fail before any unregistered dispatch."""
    original = ollama_transport._post_json

    def dispatch(**kwargs: Any) -> Any:
        payload = kwargs["payload"]
        if kwargs["path"] != "/api/generate" or len(records) >= 2:
            raise ValueError("only one FIRST and one repair generation are registered")
        expected_options: dict[str, object] = {
            "num_ctx": OLLAMA_PRODUCT_CONTEXT_TOKENS,
            "seed": SEED,
        }
        if TEMPERATURES[arm] is not None:
            expected_options["temperature"] = TEMPERATURES[arm]
        if payload["options"] != expected_options or payload.get("think") is not False:
            raise ValueError("wire sampler differs from the registered arm")
        prompt = json.loads(payload["prompt"])
        if prompt["prompt_ref"]["prompt_id"] != PROMPT_ID or payload["model"] != MODEL_ID:
            raise ValueError("only the registered Product prohibition owner is allowed")
        records.append(
            {
                "options": deepcopy(payload["options"]),
                "think": payload["think"],
                "temperature_option_present": "temperature" in payload["options"],
                "prompt_sha256": hashlib.sha256(payload["prompt"].encode()).hexdigest(),
                "system_sha256": hashlib.sha256(payload["system"].encode()).hexdigest(),
                "format_sha256": object_hash(payload["format"]),
                "input_sha256": object_hash(prompt["input"]),
                "attempt": "FIRST" if not records else "SCHEMA_REPAIR",
            }
        )
        return original(**kwargs)

    with patch.object(ollama_transport, "_post_json", dispatch):
        yield


def run_arm(case: dict[str, Any], arm: str, client: OllamaHTTPClient) -> dict[str, Any]:
    registry = PromptRegistry()
    ref = registry.lookup_for_evaluation(PROMPT_ID)
    schema = schema_for(case)
    projection = deepcopy(case["input"])
    policy = RuntimePolicy(sampling_temperature=TEMPERATURES[arm], sampling_seed=SEED)
    provider = OllamaStructuredInferenceAdapter(
        provider_name="ollama",
        transport=client,
        endpoint=OLLAMA_FIXED_LOOPBACK_ENDPOINT,
        model_id=MODEL_ID,
        assemble_instruction_text=lambda current, value: assemble_prompt(
            current, value, registry=registry, execution_scope=EVALUATION
        ),
    )
    record: dict[str, Any] = {
        "case_id": case["case_id"],
        "arm": arm,
        "attempts": [],
        "transport_calls": [],
        "wire_calls": [],
        "new_execution": True,
        "input_sha256": object_hash(projection),
    }
    with observe_local_calls(record["transport_calls"]), observe_wire(record["wire_calls"], arm):
        try:
            response = provider.invoke_structured(
                prompt_ref=ref,
                prompt_input=projection,
                output_schema=schema,
                runtime_policy=policy,
                api_key=None,
            )
            raw: Any = response.content
            try:
                raw = json.loads(raw) if isinstance(raw, str) else raw
                errors = list(validate_output_schema(raw, schema.json_schema))
            except json.JSONDecodeError:
                errors = ["$: provider output is not valid JSON"]
            record["attempts"].append(
                {
                    "attempt": "FIRST",
                    "raw_output": deepcopy(raw),
                    "schema_errors": errors,
                    "owner_review": review_output(raw, case),
                }
            )
            if errors:
                repair_event: dict[str, Any] = {"attempt": "SCHEMA_REPAIR"}
                record["attempts"].append(repair_event)
                response = PromptRepairSchemaRepairer(execution_scope=EVALUATION).repair(
                    provider=provider,
                    prompt_ref=ref,
                    prompt_input=projection,
                    failed_output=raw,
                    output_schema=schema,
                    runtime_policy=policy,
                    api_key=None,
                    attempt_no=1,
                    max_attempts=1,
                    failure_reason_code="OUTPUT_SCHEMA_INVALID",
                    validator_errors=tuple(errors),
                )
                repaired = response.content
                repair_errors = list(validate_output_schema(repaired, schema.json_schema))
                changes = find_out_of_scope_schema_repair_changes(
                    failed_output=raw,
                    repaired_output=repaired,
                    affected_field_paths=_validation_error_paths(errors),
                    output_schema=schema.json_schema,
                )
                repair_event.update(
                    raw_output=deepcopy(repaired),
                    schema_errors=repair_errors,
                    out_of_scope_changes=list(changes),
                    owner_review=review_output(repaired, case),
                )
                if repair_errors or changes:
                    raise ValueError("schema repair invalid or outside reported failure scope")
                raw = repaired
            final = validate_effect_prohibition_candidate(
                raw,
                effect_candidates=projection["effect_candidates"],
                work_unit_ids=case["work_unit_ids"],
            )
            record["final"] = {
                "structural_result": "PASS",
                "validated_output": final,
                "owner_review": review_output(final, case),
            }
        except Exception as error:
            record["final"] = {
                "structural_result": "FAIL",
                "error_type": type(error).__name__,
                "error": str(error),
                "business_success": "NOT_EVALUATED",
            }
    record["metrics"] = metrics(record["transport_calls"])
    return record


def write_json(path: Path, value: object, *, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x" if exclusive else "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result-dir", type=Path, required=True)
    parser.add_argument("--execute-plan", type=Path)
    parser.add_argument("--expected-plan-sha256")
    args = parser.parse_args()
    output = args.result_dir.resolve()
    if (
        not output.is_relative_to((ROOT / "evaluation/results").resolve())
        or output == (ROOT / "evaluation/results").resolve()
    ):
        raise ValueError("dedicated evaluation/results directory required")
    client = OllamaHTTPClient()
    current = make_plan(inspect_model(client))
    if args.execute_plan is None:
        path = output / "preregistered-plan.json"
        write_json(path, current, exclusive=True)
        print(json.dumps({"plan": str(path), "sha256": normalized_sha256(path), "model_calls": 0}))
        return
    if normalized_sha256(args.execute_plan) != args.expected_plan_sha256:
        raise ValueError("registered plan hash mismatch")
    plan = json.loads(args.execute_plan.read_text(encoding="utf-8"))
    if plan != current:
        raise ValueError("registered input/code/Prompt/schema/model/parameter binding changed")
    claims = ROOT / "evaluation/results/.prohibition-sampler-trials"
    write_json(
        claims / f"{args.expected_plan_sha256}.json", {"output": str(output)}, exclusive=True
    )
    raw: dict[str, Any] = {"binding": plan, "results": [], "completed": False}
    path = output / "raw.json"
    write_json(path, raw, exclusive=True)
    by_id = {case["case_id"]: case for case in plan["cases"]}
    for entry in plan["order"]:
        for arm in entry["arms"]:
            record = run_arm(by_id[entry["case_id"]], arm, client)
            raw["results"].append(record)
            write_json(path, raw)
            print(
                json.dumps(
                    {"case_id": record["case_id"], "arm": arm, "final": record["final"]},
                    ensure_ascii=False,
                ),
                flush=True,
            )
    raw["metrics_by_arm"] = {
        arm: metrics(
            [call for row in raw["results"] if row["arm"] == arm for call in row["transport_calls"]]
        )
        for arm in TEMPERATURES
    }
    raw["completed"] = True
    raw["actual_calls"] = sum(row["metrics"]["calls"] for row in raw["results"])
    raw["first_calls"] = len(raw["results"])
    if raw["actual_calls"] > plan["max_total_calls"]:
        raise ValueError("registered call cap exceeded")
    write_json(path, raw)


if __name__ == "__main__":
    main()
