"""Six preregistered SourceStatus owner comparisons, not upstream/Core92 scores.

The original comparison keeps Product Prompt text unchanged; explicit-slot mode
aligns only its output-shape wording. Both use Product transport/schema/repair
guards. Upstream work and responsibilities are explicit fixtures, not model
decomposition. No Graph, Connector, credentials or activation is constructed.
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
from scripts.ru_source_status_slot_candidate import (
    build_slot_source_status_schema,
    project_slot_source_statuses,
    slot_source_status_instruction,
)
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
PRODUCT_V26 = "product-v26"
V26_V27 = "v26-v27"
_SOURCE_PATH = (
    ROOT
    / "src/google_work_agent/application/prompt_runtime/sources"
    / "request_understanding.identify_source_status.md"
)
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


def _slot_source_hash() -> str:
    marker = "Allowed current-Run input projection (JSON):\n"
    source = _SOURCE_PATH.read_text(encoding="utf-8")
    transformed = slot_source_status_instruction(source + marker + "{}").partition(marker)[0]
    return hashlib.sha256(transformed.encode()).hexdigest()


def _arm_instruction(
    projection: dict[str, Any],
    ref: PromptReference,
    registry: PromptRegistry,
    representation: str,
) -> str:
    instruction = owner_instruction(projection, ref, registry)
    return (
        slot_source_status_instruction(instruction)
        if representation == "explicit-slots"
        else instruction
    )


def make_plan(
    *,
    model_digest: str | None,
    comparison: str = PRODUCT_V26,
    baseline_raw_path: Path | None = None,
) -> dict[str, Any]:
    if comparison not in (PRODUCT_V26, V26_V27):
        raise ValueError("unknown preregistered comparison")
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
            representation = "product" if arm == "baseline" else "work-bound"
            projection, schema = owner_input(
                case, "candidate" if comparison == V26_V27 else arm, ref
            )
            if comparison == V26_V27:
                representation = "work-bound" if arm == "baseline" else "explicit-slots"
                if arm == "candidate":
                    schema = build_slot_source_status_schema(case["responsibilities"], work)
            instruction = _arm_instruction(projection, ref, registry, representation)
            case["arms"][arm] = {
                "representation": representation,
                "input": projection,
                "schema": asdict(schema),
                "input_sha256": object_hash(projection),
                "schema_sha256": object_hash(schema.json_schema),
                "assembled_instruction_sha256": hashlib.sha256(instruction.encode()).hexdigest(),
                "prompt_source_sha256": (
                    _slot_source_hash() if representation == "explicit-slots" else ref.content_hash
                ),
            }
        if comparison == V26_V27:
            assert case["arms"]["baseline"]["input"] == case["arms"]["candidate"]["input"]
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
    if comparison == V26_V27:
        sources.append(ROOT / "scripts/ru_source_status_slot_candidate.py")
    binding = {
        "candidate_id": (
            "explicit-slot-source-status-v1"
            if comparison == V26_V27
            else "work-bound-source-status-v1"
        ),
        "activation_status": "DRAFT",
        "source_prompt_ref": asdict(ref),
        "candidate_input_version": 2,
        "candidate_output_version": 4 if comparison == V26_V27 else 3,
        "same_product_instruction": comparison == PRODUCT_V26,
        "prompt_change": "OUTPUT_SHAPE_ONLY" if comparison == V26_V27 else "NONE",
        "product_activation": False,
    }
    plan: dict[str, Any] = {
        "scope": "SOURCE_STATUS_OWNER_ONLY_NOT_CORE92_OR_DECOMPOSITION_SCORE",
        "comparison": comparison,
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
        "upstream_fixed_fixture_limitations": [
            "WorkUnit/Goal/Source/Output are supplied fixtures, not upstream model results.",
            (
                "Synthetic required_information includes title/status/due even if the request "
                "is narrower; preserved across arms."
            ),
            (
                "CORE005 redundant opposite filters violate owner contract but do not by "
                "themselves prove business failure."
            ),
        ],
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
    if baseline_raw_path is not None:
        if comparison != V26_V27:
            raise ValueError("historical v26 reuse is only supported for the v26-v27 comparison")
        rows = load_reusable_baseline(baseline_raw_path, plan)
        plan["baseline_reuse"] = {
            "raw_path": str(baseline_raw_path.resolve().relative_to(ROOT)).replace("\\", "/"),
            "raw_sha256": normalized_sha256(baseline_raw_path),
            "original_arm": "candidate",
            "new_call": False,
            "reused_records": len(rows),
            "reused_calls": sum(len(row["transport_calls"]) for row in rows.values()),
            "record_sha256": {case_id: object_hash(row) for case_id, row in rows.items()},
        }
        plan["order"] = "case order fixed; baseline reused, candidate executed once"
        plan["max_first_calls"] = len(cases)
        plan["max_total_calls_with_schema_repair"] = len(cases) * 2
    return plan


def load_reusable_baseline(path: Path, plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Accept only the fixed v26 owner trial under identical semantic/runtime inputs."""
    path = path.resolve()
    if not path.is_relative_to((ROOT / "evaluation/results").resolve()):
        raise ValueError("baseline raw must be in evaluation/results")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("completed") is not True:
        raise ValueError("baseline trial is incomplete")
    binding = raw["binding"]
    for field in (
        "scope",
        "dataset_sha256",
        "provider_fixture_sha256",
        "model_id",
        "model_digest",
        "runtime_policy",
        "case_ids",
    ):
        if binding[field] != plan[field]:
            raise ValueError(f"baseline {field} does not match the current comparison")
    if binding["candidate_binding"]["candidate_id"] != "work-bound-source-status-v1":
        raise ValueError("baseline origin must be the historical work-bound candidate")
    for filename, digest in binding["source_hashes"].items():
        # Runner changes add this reuse mechanism; semantic owner/transport/guard code cannot drift.
        if (
            filename != "scripts/evaluate_work_bound_source_status.py"
            and plan["source_hashes"].get(filename) != digest
        ):
            raise ValueError(f"baseline owner/runtime code changed: {filename}")
    original_cases = {case["case_id"]: case for case in binding["cases"]}
    originals = [row for row in raw["results"] if row["arm"] == "candidate"]
    rows = {row["case_id"]: row for row in originals}
    if len(rows) != len(originals) or set(rows) != set(plan["case_ids"]):
        raise ValueError("baseline must contain exactly one candidate trial for every fixed case")
    for case in plan["cases"]:
        case_id = case["case_id"]
        original = original_cases[case_id]
        for field in (
            "prompt_input",
            "goal_candidate",
            "responsibilities",
            "reference_time",
            "fault_profile",
            "expected_bindings",
        ):
            if object_hash(original[field]) != object_hash(case[field]):
                raise ValueError(f"baseline {case_id} {field} changed")
        previous_arm, current_arm = original["arms"]["candidate"], case["arms"]["baseline"]
        for field in ("input", "schema"):
            if object_hash(previous_arm[field]) != object_hash(current_arm[field]):
                raise ValueError(f"baseline {case_id} {field} changed")
        for field in (
            "input_sha256",
            "schema_sha256",
            "assembled_instruction_sha256",
            "prompt_source_sha256",
        ):
            if previous_arm[field] != current_arm[field]:
                raise ValueError(f"baseline {case_id} {field} changed")
        row = rows[case_id]
        calls = row["transport_calls"]
        if not calls or len(calls) > 1 + POLICY["schema_repair_budget"]:
            raise ValueError("baseline calls are missing or exceed the preregistered budget")
        for call in calls:
            for field, expected in (
                ("model", MODEL_ID),
                ("temperature", POLICY["temperature"]),
                ("seed", POLICY["seed"]),
                ("timeout_seconds", POLICY["timeout_seconds"]),
                ("schema_sha256", current_arm["schema_sha256"]),
            ):
                if call[field] != expected:
                    raise ValueError(f"baseline {case_id} observed {field} changed")
        if calls[0]["input_sha256"] != current_arm["input_sha256"]:
            raise ValueError(f"baseline {case_id} observed first input changed")
        if calls[0]["instruction_sha256"] != current_arm["assembled_instruction_sha256"]:
            raise ValueError(f"baseline {case_id} observed instruction changed")
        if row["attempts"][-1].get("semantic_evaluation") is not None:
            current_grade = _grade(row["attempts"][-1]["raw_output"], case, "candidate")
            if object_hash(current_grade) != object_hash(row["final"]):
                raise ValueError(f"baseline {case_id} semantic grading changed")
    return deepcopy(rows)


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
    ref = source_ref
    frozen = case["arms"][arm]
    representation = frozen.get("representation", "product" if arm == "baseline" else "work-bound")
    if representation == "explicit-slots":
        ref = replace(
            source_ref,
            prompt_version="explicit-slot-status-v1-eval",
            input_schema_version="2",
            output_schema_version="4",
            content_hash=frozen["prompt_source_sha256"],
        )
    elif representation == "work-bound":
        ref = replace(
            source_ref,
            prompt_version="work-bound-status-v1-eval",
            input_schema_version="2",
            output_schema_version="3",
        )
    schema = OutputSchemaDefinition(**frozen["schema"])
    projection = deepcopy(frozen["input"])
    result: dict[str, Any] = {
        "case_id": case["case_id"],
        "arm": arm,
        "new_call": True,
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
                    instruction_text=_arm_instruction(
                        projection, source_ref, registry, representation
                    ),
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
                    projected = raw
                    if representation == "explicit-slots":
                        projected = project_slot_source_statuses(
                            raw,
                            responsibilities=case["responsibilities"],
                            requested_work=case["prompt_input"]["requested_work"],
                        )
                        event["deterministic_status_projection"] = deepcopy(projected)
                    event["semantic_evaluation"] = _grade(
                        projected, case, "baseline" if representation == "product" else "candidate"
                    )
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


def summarize_results(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        arm: {
            "pass": sum(
                row["final"]["owner_result"] == "PASS" for row in rows if row["arm"] == arm
            ),
            "fail": sum(
                row["final"]["owner_result"] == "FAIL" for row in rows if row["arm"] == arm
            ),
            "metrics": metrics(
                [call for row in rows if row["arm"] == arm for call in row["transport_calls"]]
            ),
            "new_call_metrics": metrics(
                [
                    call
                    for row in rows
                    if row["arm"] == arm and row["new_call"]
                    for call in row["transport_calls"]
                ]
            ),
            "reused_call_metrics": metrics(
                [
                    call
                    for row in rows
                    if row["arm"] == arm and not row["new_call"]
                    for call in row["transport_calls"]
                ]
            ),
        }
        for arm in ("baseline", "candidate")
    }


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
    parser.add_argument("--comparison", choices=(PRODUCT_V26, V26_V27), default=PRODUCT_V26)
    parser.add_argument("--reuse-baseline-raw", type=Path)
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
        plan = make_plan(
            model_digest=model.digest,
            comparison=args.comparison,
            baseline_raw_path=args.reuse_baseline_raw,
        )
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
    reuse = plan.get("baseline_reuse")
    reuse_path = ROOT / reuse["raw_path"] if reuse else None
    current = make_plan(
        model_digest=model.digest,
        comparison=plan.get("comparison", PRODUCT_V26),
        baseline_raw_path=reuse_path,
    )
    if object_hash(current) != object_hash(plan):
        raise ValueError("code/input/schema/runtime/HEAD changed after preregistration")
    raw_path = result_dir / "raw.json"
    raw: dict[str, Any] = {"plan_sha256": args.expected_plan_sha256, "binding": plan, "results": []}
    _write(raw_path, raw, exclusive=True)
    registry = PromptRegistry()
    client = OllamaHTTPClient()
    reused_rows = load_reusable_baseline(reuse_path, plan) if reuse_path is not None else {}
    for case in plan["cases"]:
        for arm in ("baseline", "candidate"):
            if arm == "baseline" and reused_rows:
                record = deepcopy(reused_rows[case["case_id"]])
                record.update(
                    arm="baseline",
                    new_call=False,
                    origin={
                        "raw_path": reuse["raw_path"],
                        "raw_sha256": reuse["raw_sha256"],
                        "original_arm": "candidate",
                        "record_sha256": reuse["record_sha256"][case["case_id"]],
                    },
                )
            else:
                record = run_arm(case, arm, client, registry)
            raw["results"].append(record)
            _write(raw_path, raw)
            print(
                json.dumps(
                    {
                        "case_id": case["case_id"],
                        "arm": arm,
                        "new_call": record["new_call"],
                        "result": record["final"],
                        "metrics": record["metrics"],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    raw["summary"] = summarize_results(raw["results"])
    raw["completed"] = True
    _write(raw_path, raw)


if __name__ == "__main__":
    main()
