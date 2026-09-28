"""Six preregistered SourceStatus owner comparisons, not upstream/Core92 scores.

Both arms use the unchanged Product Prompt source, Ollama transport, schema
validator, bounded repair projection and repair-scope guard. Upstream work and
responsibilities are explicit fixtures, not model-derived decomposition results.
No Graph, Connector, credential store or Product activation is constructed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from evaluation.dataset_v8 import (
    DEFAULT_DATASET_PATH,
    DEFAULT_PROVIDER_FIXTURE_PATH,
    load_cases,
    normalized_sha256,
)
from scripts.ru_observation import metrics, object_hash, observe_local_calls
from scripts.ru_work_bound_source_status_candidate import (
    identify_work_bound_source_status,
    normalize_work_bound_source_statuses,
)

from google_work_agent.adapters.llm.ollama.transport import (
    OLLAMA_PRODUCT_CONTEXT_TOKENS,
    OllamaHTTPClient,
)
from google_work_agent.adapters.llm.runtime.prompt_repair_schema_repairer import _build_repair_input
from google_work_agent.adapters.llm.runtime.schema_repair_scope import (
    find_out_of_scope_schema_repair_changes,
)
from google_work_agent.application.agents.request_understanding.contracts.request_goal_candidate_schema import (  # noqa: E501
    identify_goal_output_schema,
)
from google_work_agent.application.agents.request_understanding.contracts.work_unit_binding import (
    validate_requested_work_definition,
)
from google_work_agent.application.agents.request_understanding.identify_source_status import (
    identify_source_status,
    normalize_source_status_constraints,
)
from google_work_agent.application.prompt_runtime.assemble_prompt import assemble_prompt
from google_work_agent.application.prompt_runtime.prompt_registry import (
    EVALUATION,
    PromptRegistry,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.runtime_selection import OLLAMA_FIXED_LOOPBACK_ENDPOINT
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferenceResultV1

ROOT = Path(__file__).resolve().parents[1]
PROMPT_ID = "request_understanding.identify_source_status"
MODEL_ID = "qwen3.5:9b"
SEED = 20260923
POLICY = {
    "temperature": 0.0,
    "seed": SEED,
    "num_ctx": OLLAMA_PRODUCT_CONTEXT_TOKENS,
    "think": False,
    "timeout_seconds": 180,
    "schema_repair_budget": 1,
    "semantic_revision_budget": 0,
    "transport_retry_budget": 0,
    "rerun_to_pass": 0,
}
_CASE_IDS = (
    "SYNTH-STATUS-TASK-OPPOSITE",
    "SYNTH-STATUS-MAIL-OPPOSITE",
    "SYNTH-STATUS-SHARED",
    "SYNTH-STATUS-NONE",
    "CASE-CORE-005",
    "CASE-CORE-060",
)


def fixed_cases() -> list[dict[str, Any]]:
    specifications = [
        (
            _CASE_IDS[0],
            ["미완료 Task는 요약해줘.", "완료 Task는 별도 목록으로 보여줘."],
            "TASK",
            ["INCOMPLETE", "COMPLETED"],
        ),
        (
            _CASE_IDS[1],
            [
                "Gmail 임시보관 메일의 제목을 요약해줘.",
                "이미 발송된 메일의 제목을 별도로 나열해줘.",
            ],
            "GMAIL_THREAD",
            ["DRAFT", "SENT"],
        ),
        (
            _CASE_IDS[2],
            ["미완료 Task들의 제목 목록을 만들어줘.", "같은 미완료 Task들의 기한도 요약해줘."],
            "TASK",
            ["INCOMPLETE", "INCOMPLETE"],
        ),
        (
            _CASE_IDS[3],
            ["Task들의 현재 상태를 요약해줘.", "같은 Task들의 기한도 별도로 정리해줘."],
            "TASK",
            [],
        ),
    ]
    cases = [
        _case(case_id, " ".join(spans), spans, resource, statuses)
        for case_id, spans, resource, statuses in specifications
    ]
    canonical = load_cases()
    for case_id in _CASE_IDS[4:]:
        source = canonical[case_id].raw
        request = source["canonical_user_prompt"]
        case = _case(case_id, request, [request], "TASK", [])
        case["origin"] = "CANONICAL_CORE_REQUEST_CONTROL"
        case["reference_time"] = source.get("evaluation_context", {}).get("run_reference_time")
        case["fault_profile"] = source["evaluation_gold"].get("fault_profile")
        case["prompt_input"]["selected_resource_refs"] = [
            {
                "connector_id": "google_workspace",
                "resource_type": item["resource_type"],
                "resource_id": item["resource_id"],
                "parent_resource_id": item.get("parent_id"),
            }
            for item in source["selected_resource_bindings"]
        ]
        case["responsibilities"]["source_reads"][0]["target_scope"] = "SINGULAR"
        case["goal_candidate"]["constraints"]["coverage_requirement"]["value"] = "NOT_COLLECTION"
        if case_id == "CASE-CORE-060":
            case["responsibilities"]["outputs"] = [
                {"resource_type": "TASK", "effect": "UPDATE", "work_unit_ids": ["work-1"]}
            ]
        case["expectation_basis"] = (
            "Current status is requested as an answer, not a search-state restriction."
            if case_id == "CASE-CORE-005"
            else "Completion is the requested UPDATE effect, not an existing-source state filter."
        )
        cases.append(case)
    return cases


def _case(
    case_id: str, request: str, spans: list[str], resource: str, statuses: list[str]
) -> dict[str, Any]:
    units = [
        {
            "unit_id": f"work-{index + 1}",
            "request_provenance": [
                {
                    "source": "USER_REQUEST",
                    "start_offset": request.index(span),
                    "end_offset": request.index(span) + len(span),
                    "source_text": span,
                }
            ],
        }
        for index, span in enumerate(spans)
    ]
    work = {"work_units": units, "work_relations": []}
    ids = [unit["unit_id"] for unit in units]
    goal = {
        "goal": request,
        "completion_conditions": [request],
        "analysis_requirement": "NONE",
        "constraints": {
            **{
                field: []
                for field in (
                    "search_terms",
                    "business_concepts",
                    "person",
                    "sender",
                    "recipient",
                    "subject",
                    "period",
                    "additional_constraints",
                )
            },
            "coverage_requirement": {"value": "ALL_ITEMS", "work_unit_ids": ids},
        },
    }
    return {
        "case_id": case_id,
        "origin": "SYNTHETIC_OWNER_DIAGNOSTIC",
        "upstream_authority": "EXPLICIT_TYPED_FIXTURE_NOT_MODEL_DECOMPOSITION",
        "prompt_input": {
            "user_request": request,
            "selected_resource_refs": [],
            "requested_work": work,
        },
        "goal_candidate": goal,
        "responsibilities": {
            "source_reads": [
                {
                    "resource_type": resource,
                    "required_information": ["subject"]
                    if resource == "GMAIL_THREAD"
                    else ["title", "status", "due"],
                    "target_scope": "CRITERIA",
                    "work_unit_ids": [unit_id],
                }
                for unit_id in ids
            ],
            "outputs": [],
        },
        "expected_bindings": sorted(
            [[resource, value, ids[index]] for index, value in enumerate(statuses)]
        ),
        "expectation_basis": "Explicit source filters only; per-item grouping is not scored.",
        "reference_time": None,
        "fault_profile": None,
    }


class _Capture:
    def infer(self, mode: Any, ref: Any, projection: Any, schema: Any) -> Any:
        self.projection, self.schema = deepcopy(projection), schema
        return StructuredInferenceResultV1(
            1, {"statuses": []}, "FIXTURE", "NONE", "LOCAL_GPU", 0, 0, 0, None
        )


def owner_input(
    case: dict[str, Any], arm: str, prompt_ref: PromptReference
) -> tuple[dict[str, Any], OutputSchemaDefinition]:
    capture = _Capture()
    operation = identify_source_status if arm == "baseline" else identify_work_bound_source_status
    operation(
        llm_runtime=capture,
        requested_mode="LOCAL_GPU",
        prompt_ref=prompt_ref,
        prompt_input=case["prompt_input"],
        goal_candidate=case["goal_candidate"],
        responsibilities=case["responsibilities"],
    )
    return capture.projection, capture.schema


def owner_instruction(
    projection: dict[str, Any], ref: PromptReference, registry: PromptRegistry
) -> str:
    """Change only assembled current-input JSON; the Product instruction is identical."""
    product_projection = deepcopy(projection)
    base = product_projection.get("base_projection", product_projection)
    candidate_base = projection.get("base_projection", projection)
    base.pop("requested_work", None)
    instruction = assemble_prompt(
        ref, product_projection, registry=registry, execution_scope=EVALUATION
    )
    if "requested_work" not in candidate_base:
        return instruction
    before = json.dumps(base, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    after = json.dumps(candidate_base, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    marker = "Allowed current-Run input projection (JSON):\n"
    if instruction.count(marker + before) != 1:
        raise ValueError("candidate input is not the unique assembled Product projection")
    return instruction.replace(marker + before, marker + after, 1)


def make_plan(*, model_digest: str | None) -> dict[str, Any]:
    registry = PromptRegistry()
    ref = registry.lookup_for_evaluation(PROMPT_ID)
    cases = fixed_cases()
    for case in cases:
        request = case["prompt_input"]["user_request"]
        work = validate_requested_work_definition(
            case["prompt_input"]["requested_work"], user_request=request
        )
        ids = [unit["unit_id"] for unit in work["work_units"]]
        errors = validate_output_schema(
            case["goal_candidate"], identify_goal_output_schema(ids).json_schema
        )
        if errors:
            raise ValueError(f"fixed Goal fixture invalid: {errors}")
        case["arms"] = {}
        for arm in ("baseline", "candidate"):
            projection, schema = owner_input(case, arm, ref)
            instruction = owner_instruction(projection, ref, registry)
            case["arms"][arm] = {
                "input": projection,
                "schema": asdict(schema),
                "input_sha256": object_hash(projection),
                "schema_sha256": object_hash(schema.json_schema),
                "assembled_instruction_sha256": hashlib.sha256(instruction.encode()).hexdigest(),
                "prompt_source_sha256": ref.content_hash,
            }
    sources = [
        Path(__file__),
        ROOT / "scripts/ru_work_bound_source_status_candidate.py",
        ROOT
        / "src/google_work_agent/application/agents/request_understanding"
        / "identify_source_status.py",
        ROOT / "src/google_work_agent/adapters/llm/ollama/transport.py",
        ROOT / "src/google_work_agent/adapters/llm/runtime/schema_repair_scope.py",
        ROOT
        / "src/google_work_agent/application/prompt_runtime/sources"
        / "request_understanding.identify_source_status.md",
    ]
    binding = {
        "candidate_id": "work-bound-source-status-v1",
        "activation_status": "DRAFT",
        "source_prompt_ref": asdict(ref),
        "candidate_input_version": 2,
        "candidate_output_version": 3,
        "same_product_instruction": True,
        "product_activation": False,
    }
    return {
        "scope": "SOURCE_STATUS_OWNER_ONLY_NOT_CORE92_OR_DECOMPOSITION_SCORE",
        "sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_hashes": {
            str(path.relative_to(ROOT)).replace("\\", "/"): normalized_sha256(path)
            for path in sources
        },
        "dataset_sha256": normalized_sha256(DEFAULT_DATASET_PATH),
        "provider_fixture_sha256": normalized_sha256(DEFAULT_PROVIDER_FIXTURE_PATH),
        "model_id": MODEL_ID,
        "model_digest": model_digest,
        "runtime_policy": deepcopy(POLICY),
        "candidate_binding": binding,
        "candidate_binding_sha256": object_hash(binding),
        "case_ids": list(_CASE_IDS),
        "trials_per_arm_case": 1,
        "order": "case order fixed; baseline then candidate for every case",
        "max_first_calls": 12,
        "max_total_calls_with_schema_repair": 24,
        "semantic_revision_calls": 0,
        "provider_reads": 0,
        "provider_writes": 0,
        "cases": cases,
        "dry_validation": "PASS",
        "model_evaluation": "NOT_RUN",
    }


def _parse(content: object, schema: OutputSchemaDefinition) -> tuple[Any, list[str]]:
    try:
        value = json.loads(content) if isinstance(content, str) else content
    except json.JSONDecodeError:
        return content, ["$: provider output is not valid JSON"]
    return value, validate_output_schema(value, schema.json_schema)


def _grade(raw: object, case: dict[str, Any], arm: str) -> dict[str, Any]:
    try:
        kwargs = {
            "responsibilities": case["responsibilities"],
            "provenance_sources": {"USER_REQUEST": case["prompt_input"]["user_request"]},
        }
        normalized = (
            normalize_source_status_constraints(raw, **kwargs)
            if arm == "baseline"
            else normalize_work_bound_source_statuses(
                raw,
                requested_work=case["prompt_input"]["requested_work"],
                **kwargs,
            )
        )
        actual = sorted(
            {
                (item["source_resource_type"], item["value"], unit)
                for item in normalized
                for unit in item["work_unit_ids"]
            }
        )
        expected = {tuple(row) for row in case["expected_bindings"]}
        missing, extra = sorted(expected - set(actual)), sorted(set(actual) - expected)
        return {
            "owner_result": "PASS" if not missing and not extra else "FAIL",
            "normalized": normalized,
            "actual_bindings": actual,
            "missing_bindings": missing,
            "extra_bindings": extra,
        }
    except ValueError as error:
        return {"owner_result": "FAIL", "error_type": type(error).__name__, "error": str(error)}


def run_arm(
    case: dict[str, Any], arm: str, client: OllamaHTTPClient, registry: PromptRegistry
) -> dict[str, Any]:
    source_ref = registry.lookup_for_evaluation(PROMPT_ID)
    ref = (
        source_ref
        if arm == "baseline"
        else replace(
            source_ref,
            prompt_version="work-bound-status-v1-eval",
            input_schema_version="2",
            output_schema_version="3",
        )
    )
    frozen = case["arms"][arm]
    schema = OutputSchemaDefinition(**frozen["schema"])
    projection = deepcopy(frozen["input"])
    result: dict[str, Any] = {
        "case_id": case["case_id"],
        "arm": arm,
        "attempts": [],
        "transport_calls": [],
    }
    first_raw: object = None
    first_errors: list[str] = []
    with observe_local_calls(result["transport_calls"]):
        for attempt in range(2):
            label = "FIRST" if attempt == 0 else "SCHEMA_REPAIR"
            event: dict[str, Any] = {"attempt": label}
            result["attempts"].append(event)
            try:
                response = client.invoke_structured(
                    endpoint=OLLAMA_FIXED_LOOPBACK_ENDPOINT,
                    model_id=MODEL_ID,
                    prompt_ref=ref,
                    prompt_input=projection,
                    output_schema=schema,
                    timeout_seconds=180,
                    instruction_text=owner_instruction(projection, source_ref, registry),
                    sampling_temperature=0.0,
                    sampling_seed=SEED,
                )
                raw, errors = _parse(response.content, schema)
                event.update(raw_output=raw, schema_errors=errors)
                if attempt == 1 and not errors:
                    paths = tuple(
                        sorted(
                            {
                                match.group(0)
                                for error in first_errors
                                if (match := re.match(r"^\$[\w.\[\]]*", error))
                                and match.group(0) != "$"
                            }
                        )
                    )
                    changed = find_out_of_scope_schema_repair_changes(
                        failed_output=first_raw,
                        repaired_output=raw,
                        affected_field_paths=paths,
                        output_schema=schema.json_schema,
                    )
                    event["out_of_scope_repair_changes"] = list(changed)
                    if changed:
                        raise ValueError("schema repair changed unaffected fields")
                if not errors:
                    event["semantic_evaluation"] = _grade(raw, case, arm)
                    result["final"] = deepcopy(event["semantic_evaluation"])
                    break
                if attempt == 0:
                    first_raw, first_errors = deepcopy(raw), list(errors)
                    projection = _build_repair_input(
                        prompt_ref=ref,
                        prompt_input=frozen["input"],
                        failed_output=raw,
                        attempt_no=1,
                        max_attempts=1,
                        failure_reason_code="OUTPUT_SCHEMA_INVALID",
                        validator_errors=tuple(errors),
                    )
                else:
                    result["final"] = {
                        "owner_result": "FAIL",
                        "error": "SCHEMA_INVALID_AFTER_REPAIR",
                    }
            except Exception as error:
                event.update(error_type=type(error).__name__, error=str(error))
                result["final"] = {
                    "owner_result": "FAIL",
                    "error_type": type(error).__name__,
                    "error": str(error),
                }
                break
    result["metrics"] = metrics(result["transport_calls"])
    return result


def _write(path: Path, document: object, *, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x" if exclusive else "w", encoding="utf-8", newline="\n") as stream:
        json.dump(document, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result-dir", type=Path, required=True)
    parser.add_argument("--execute-plan", type=Path)
    parser.add_argument("--expected-plan-sha256")
    args = parser.parse_args()
    result_dir = args.result_dir.resolve()
    if not result_dir.is_relative_to((ROOT / "evaluation/results").resolve()):
        raise ValueError("owner diagnostic artifacts must remain in evaluation/results")
    model = next(
        (item for item in OllamaHTTPClient().list_installed_models() if item.model_id == MODEL_ID),
        None,
    )
    if model is None or not model.digest:
        raise ValueError("the installed 9B model digest must be verified before registration")
    if args.execute_plan is None:
        plan = make_plan(model_digest=model.digest)
        path = result_dir / "preregistered-plan.json"
        _write(path, plan, exclusive=True)
        print(
            json.dumps(
                {
                    "dry_validation": "PASS",
                    "plan": str(path),
                    "plan_sha256": normalized_sha256(path),
                    "calls": 0,
                }
            )
        )
        return
    if normalized_sha256(args.execute_plan) != args.expected_plan_sha256:
        raise ValueError("preregistered plan hash mismatch")
    plan = json.loads(args.execute_plan.read_text(encoding="utf-8"))
    current = make_plan(model_digest=model.digest)
    if object_hash(current) != object_hash(plan):
        raise ValueError("code/input/schema/runtime/HEAD changed after preregistration")
    raw_path = result_dir / "raw.json"
    raw: dict[str, Any] = {"plan_sha256": args.expected_plan_sha256, "binding": plan, "results": []}
    _write(raw_path, raw, exclusive=True)
    registry = PromptRegistry()
    client = OllamaHTTPClient()
    for case in plan["cases"]:
        for arm in ("baseline", "candidate"):
            record = run_arm(case, arm, client, registry)
            raw["results"].append(record)
            _write(raw_path, raw)
            print(
                json.dumps(
                    {
                        "case_id": case["case_id"],
                        "arm": arm,
                        "result": record["final"],
                        "metrics": record["metrics"],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    raw["summary"] = {
        arm: {
            "pass": sum(
                row["final"]["owner_result"] == "PASS"
                for row in raw["results"]
                if row["arm"] == arm
            ),
            "fail": sum(
                row["final"]["owner_result"] == "FAIL"
                for row in raw["results"]
                if row["arm"] == arm
            ),
            "metrics": metrics(
                [
                    call
                    for row in raw["results"]
                    if row["arm"] == arm
                    for call in row["transport_calls"]
                ]
            ),
        }
        for arm in ("baseline", "candidate")
    }
    raw["completed"] = True
    _write(raw_path, raw)


if __name__ == "__main__":
    main()
