"""Preregister a seven-first-call Source representation comparison; dry by default.

Three real owner inputs and their complete baseline attempts are frozen from a
recorded Product Source trial. Two synthetic boundaries add no Provider data.
Only the REQUIRED payload representation/its shape wording differ between arms.
This is not a Core92, upstream RU, connected workflow or business-success score.
"""

from __future__ import annotations

import argparse
import hashlib
import json
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
from scripts.ru_source_requirements_candidate import (
    CANDIDATE_SCHEMA_VERSION,
    build_source_requirements_output_schema,
    merge_source_requirements_candidate,
)

from google_work_agent.adapters.llm.ollama.transport import (
    OLLAMA_PRODUCT_CONTEXT_TOKENS,
    OllamaHTTPClient,
)
from google_work_agent.adapters.llm.runtime.prompt_repair_schema_repairer import _build_repair_input
from google_work_agent.adapters.llm.runtime.schema_repair_scope import (
    find_out_of_scope_schema_repair_changes,
)
from google_work_agent.adapters.llm.runtime.structured_inference_router import (
    _runtime_policy_for_prompt,
)
from google_work_agent.application.agents.request_understanding import (
    identify_source_dependencies as source_ops,
)
from google_work_agent.application.agents.request_understanding import (
    merge_resource_responsibilities as merge_ops,
)
from google_work_agent.application.agents.request_understanding.contracts import (
    request_goal_candidate_schema as goal_schema,
)
from google_work_agent.application.agents.request_understanding.contracts.work_unit_binding import (
    validate_requested_work_definition,
)
from google_work_agent.application.prompt_runtime.assemble_prompt import assemble_prompt
from google_work_agent.application.prompt_runtime.prompt_registry import EVALUATION, PromptRegistry
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.runtime_selection import OLLAMA_FIXED_LOOPBACK_ENDPOINT
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
    RuntimePolicy,
)

ROOT = Path(__file__).resolve().parents[1]
PROMPT_ID = "request_understanding.identify_source_dependencies"
MODEL_ID = "qwen3.5:9b"
CONTROL_IDS = ("CASE-CORE-001", "CASE-CORE-013", "CASE-CORE-023")
DEFAULT_BASELINE_RAW = ROOT / "evaluation/results/064-source-paired-baseline-v22-t1/raw.json"
POLICY: dict[str, Any] = {
    "temperature": 0.05,
    "seed": 20260923,
    "num_ctx": OLLAMA_PRODUCT_CONTEXT_TOKENS,
    "think": False,
    "timeout_seconds": 180,
    "schema_repair_budget": 1,
    "semantic_revision_budget": 0,
    "transport_retry_budget": 0,
    "rerun_to_pass": 0,
}
_SOURCE_DIRECTORY = ROOT / "src/google_work_agent/application/prompt_runtime/sources"
_PROMPT_PATH = _SOURCE_DIRECTORY / f"{PROMPT_ID}.md"
_SHAPE_REPLACEMENTS = (
    (
        "`SOURCE_REQUIRED` 판정에는 해당 Source가 필요한 현재 `unit_id`를 "
        "`work_unit_ids`에 직접 기록한다.",
        "`SOURCE_REQUIRED`의 `requirements` 각 항목에는 해당 정보·대상 범위가 필요한 "
        "현재 `unit_id`를 `work_unit_ids`에 직접 기록한다.",
    ),
    (
        "4. 하나 이상의 필요 사실이 결속된 후보만 `SOURCE_REQUIRED`로 판정하고, 결속된 "
        "사실을 `required_information`에 쓴다. 이 Source가 특정 existing Resource 하나를 "
        "뜻하면 `target_scope=SINGULAR`, 조건에 맞는 Resource 조회를 뜻하면 "
        "`target_scope=CRITERIA`로 독립 판정한다. 나머지 후보는 `SOURCE_NOT_REQUIRED`다.",
        "4. 하나 이상의 필요 사실이 결속된 후보만 `SOURCE_REQUIRED`로 판정하고, "
        "`requirements`에 정보·대상 범위·업무 귀속별 항목을 쓴다. 각 항목의 결속된 사실은 "
        "`required_information`에 쓴다. 그 항목이 특정 existing Resource 하나를 뜻하면 "
        "`target_scope=SINGULAR`, 조건에 맞는 Resource 조회를 뜻하면 "
        "`target_scope=CRITERIA`로 독립 판정한다. 나머지 후보는 `SOURCE_NOT_REQUIRED`다.",
    ),
    (
        "각 `SOURCE_REQUIRED`의 두 판정이 서로 바뀌지 않았는지를 함께 확인한다.",
        "각 `requirements` 항목의 두 판정이 서로 바뀌지 않았는지를 함께 확인한다.",
    ),
    (
        "`required_information`에는 사용자가 최종 결과에서 필요로 하는 "
        "Source fact·state·content만 둔다.",
        "`requirements[].required_information`에는 사용자가 최종 결과에서 필요로 하는 "
        "Source fact·state·content만 둔다.",
    ),
)


def candidate_source_text(source: str) -> str:
    """Explicit evaluation artifact, not a mutated Product Prompt registry entry."""
    for original, replacement in _SHAPE_REPLACEMENTS:
        if source.count(original) != 1:
            raise ValueError("Product Source shape wording changed; review the candidate")
        source = source.replace(original, replacement, 1)
    return source


def owner_instruction(projection: dict[str, Any], arm: str, registry: PromptRegistry) -> str:
    if arm not in {"baseline", "candidate"}:
        raise ValueError("unknown Source comparison arm")
    ref = registry.lookup_for_evaluation(PROMPT_ID)
    instruction = assemble_prompt(ref, projection, registry=registry, execution_scope=EVALUATION)
    if arm == "baseline":
        return instruction
    source = registry.source_text(PROMPT_ID).rstrip()
    if not instruction.startswith(source + "\n"):
        raise ValueError("assembled Source instruction no longer starts with its artifact")
    return candidate_source_text(source) + instruction[len(source) :]


def _ids(projection: dict[str, Any]) -> list[str]:
    work = validate_requested_work_definition(
        projection["requested_work"], user_request=projection["user_request"]
    )
    return [unit["unit_id"] for unit in work["work_units"]]


def _schemas(projection: dict[str, Any], require_source: bool) -> dict[str, OutputSchemaDefinition]:
    kwargs: dict[str, Any] = {
        "work_unit_ids": _ids(projection),
        "require_at_least_one_source": require_source,
    }
    candidates = projection["source_candidates"]
    return {
        "baseline": source_ops.build_source_dependency_output_schema(candidates, **kwargs),
        "candidate": build_source_requirements_output_schema(candidates, **kwargs),
    }


def _parse(content: object, schema: OutputSchemaDefinition) -> tuple[object, list[str]]:
    try:
        value = json.loads(content) if isinstance(content, str) else content
    except json.JSONDecodeError:
        return content, ["$: provider output is not valid JSON"]
    return value, validate_output_schema(value, schema.json_schema)


def observed_semantics(raw: object, case: dict[str, Any], arm: str) -> dict[str, Any]:
    """Expose bindings for evidence-backed review; resource names alone never earn PASS."""
    kwargs = {
        "source_decisions": raw,
        "source_candidates": case["input"]["source_candidates"],
        "output_decisions": {"output_responsibilities": []},
        "output_candidates": (),
    }
    if arm == "candidate":
        responsibilities = merge_source_requirements_candidate(
            **kwargs,
            work_unit_ids=_ids(case["input"]),
            require_at_least_one_source=case["require_at_least_one_source"],
        )
    else:
        source_ops.validate_source_dependency_candidate(
            raw,
            source_candidates=kwargs["source_candidates"],
            work_unit_ids=_ids(case["input"]),
        )
        responsibilities = merge_ops.merge_resource_responsibilities(**kwargs)
    sources = responsibilities["source_reads"]
    return {
        "structural_validation": "PASS",
        "source_items": sources,
        "work_binding_projection": {
            unit: [item for item in sources if unit in item["work_unit_ids"]]
            for unit in _ids(case["input"])
        },
        "semantic_evaluation": "PENDING_EVIDENCE_REVIEW",
        "business_success": "NOT_EVALUATED",
    }


def load_frozen_controls(path: Path, registry: PromptRegistry) -> tuple[list[dict[str, Any]], Any]:
    """Reject mismatched input/schema/instruction/runtime; preserve all original attempts."""
    if not path.resolve().is_relative_to((ROOT / "evaluation/results").resolve()):
        raise ValueError("baseline must be an evaluation/results artifact")
    document = json.loads(path.read_text(encoding="utf-8"))
    binding = document["binding"]
    for field, expected in (
        ("model_id", MODEL_ID),
        ("think", POLICY["think"]),
        ("num_ctx", POLICY["num_ctx"]),
        ("dataset_sha256", normalized_sha256(DEFAULT_DATASET_PATH)),
        ("fixture_sha256", normalized_sha256(DEFAULT_PROVIDER_FIXTURE_PATH)),
    ):
        if binding[field] != expected:
            raise ValueError(f"frozen baseline {field} does not match")
    if not binding.get("model_digest"):
        raise ValueError("frozen baseline lacks an actual model digest")
    canonical = load_cases()
    cases = []
    for case_id in CONTROL_IDS:
        matches = [row for row in document["cases"] if row["case_id"] == case_id]
        if len(matches) != 1:
            raise ValueError(f"expected exactly one recorded control: {case_id}")
        original = deepcopy(matches[0])
        calls = original["transport_calls"]
        if not 1 <= len(calls) <= 2:
            raise ValueError("frozen baseline violates the first+one-repair budget")
        projection = deepcopy(calls[0]["input"])
        if "base_projection" in projection:
            raise ValueError("control must start with a real FIRST owner input, not revision")
        if projection["user_request"] != canonical[case_id].raw["canonical_user_prompt"]:
            raise ValueError(f"canonical request changed: {case_id}")
        possible = [
            require
            for require in (False, True)
            if object_hash(_schemas(projection, require)["baseline"].json_schema)
            == calls[0]["schema_sha256"]
        ]
        if len(possible) != 1:
            raise ValueError(f"recorded Product schema cannot be reproduced: {case_id}")
        case = {
            "case_id": case_id,
            "origin": "RECORDED_PRODUCT_SOURCE_OWNER_INPUT",
            "input": projection,
            "require_at_least_one_source": possible[0],
            "reference_time": original.get("reference_time"),
            "actual_owner_reference_time": projection.get("run_reference_time"),
            "fault_profile": original.get("fault_profile"),
            "canonical_case_sha256": object_hash(canonical[case_id].raw),
            "evaluation_authority": deepcopy(canonical[case_id].gold),
            "baseline_record": original,
            "baseline_record_sha256": object_hash(original),
        }
        schema = _schemas(projection, possible[0])["baseline"]
        attempts = []
        previous_raw: object = None
        previous_errors: list[str] = []
        for index, call in enumerate(calls):
            for field, expected in (
                ("prompt_id", PROMPT_ID),
                ("model", MODEL_ID),
                ("temperature", POLICY["temperature"]),
                ("seed", POLICY["seed"]),
                ("timeout_seconds", POLICY["timeout_seconds"]),
                ("schema_sha256", object_hash(schema.json_schema)),
                ("input_sha256", object_hash(call["input"])),
                (
                    "instruction_sha256",
                    hashlib.sha256(
                        owner_instruction(call["input"], "baseline", registry).encode()
                    ).hexdigest(),
                ),
            ):
                if call[field] != expected:
                    raise ValueError(f"frozen {case_id} attempt {index} {field} changed")
            if index:
                expected_repair = _repair_input(projection, previous_raw, previous_errors, registry)
                if not previous_errors or call["input"] != expected_repair:
                    raise ValueError("second baseline call is not the unchanged bounded repair")
            raw, errors = _parse(call["content"], schema)
            event = {"attempt": "FIRST" if not index else "SCHEMA_REPAIR", "raw_output": raw}
            event["current_schema_errors"] = errors
            event["semantic_review"] = "PENDING_FIRST_AND_REPAIR_SEPARATE_REVIEW"
            if index and not errors:
                event["current_repair_guard_changes"] = list(
                    find_out_of_scope_schema_repair_changes(
                        failed_output=previous_raw,
                        repaired_output=raw,
                        affected_field_paths=tuple(
                            call["input"]["failure_record"]["affected_field_paths"]
                        ),
                        output_schema=schema.json_schema,
                    )
                )
            if not errors and not event.get("current_repair_guard_changes"):
                try:
                    event["current_observation"] = observed_semantics(raw, case, "baseline")
                except ValueError as error:
                    event["current_validation_error"] = str(error)
            attempts.append(event)
            previous_raw, previous_errors = raw, errors
        case["baseline_revalidation"] = attempts
        final = attempts[-1]
        case["baseline_current_gate"] = (
            "FAIL"
            if (
                final["current_schema_errors"]
                or final.get("current_repair_guard_changes")
                or final.get("current_validation_error")
            )
            else "PASS_STRUCTURE_ONLY_SEMANTIC_REVIEW_PENDING"
        )
        cases.append(case)
    return cases, binding


def synthetic_cases(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Owner-input fixtures, not model-generated upstream success or new Canonical Gold."""
    cases = []
    for action in (False, True):
        parts = (
            (
                "선택한 계약 메일 스레드 하나의 전체 내용을 요약한 초안 하나를 준비해줘.",
                "별도로 결제 관련 메일 스레드들의 제목만 나열한 초안 하나를 준비해줘.",
            )
            if action
            else (
                "선택한 계약 메일 스레드 하나의 전체 내용을 요약해줘.",
                "별도로 결제 관련 메일 스레드들의 제목만 목록으로 보여줘.",
            )
        )
        prohibition = "실제 전송은 하지 말고 Task와 Calendar는 조회하지 마."
        request = " ".join((*parts, prohibition))
        ids = ["work-1", "work-2"]

        def span(text: str, request: str = request) -> dict[str, Any]:
            start = request.index(text)
            return {
                "source": "USER_REQUEST",
                "start_offset": start,
                "end_offset": start + len(text),
                "source_text": text,
            }

        projection = {
            "user_request": request,
            "selected_resource_refs": [
                {
                    "resource_ref_id": "synthetic-selected-thread",
                    "connector_id": "google_workspace",
                    "resource_type": "gmail_thread",
                    "resource_id": "synthetic-thread-not-a-provider-object",
                    "parent_resource_id": None,
                }
            ],
            "requested_work": {
                "work_units": [
                    {"unit_id": unit, "request_provenance": [span(part), span(prohibition)]}
                    for unit, part in zip(ids, parts, strict=True)
                ],
                "work_relations": [],
            },
            "goal_candidate": {
                "goal": request,
                "completion_conditions": [],
                "analysis_requirement": "NONE",
                "constraints": {
                    **{
                        key: []
                        for key in (
                            "business_concepts",
                            "person",
                            "sender",
                            "recipient",
                            "subject",
                            "period",
                            "additional_constraints",
                        )
                    },
                    "search_terms": [{"value": "결제", "work_unit_ids": ["work-2"]}],
                    "coverage_requirement": {"value": "LIMITED_ITEMS", "work_unit_ids": ids},
                },
            },
            "source_candidates": deepcopy(candidates),
        }
        cases.append(
            {
                "case_id": "SYNTH-SOURCE-INDEPENDENT-DRAFTS" if action else "SYNTH-SOURCE-READ",
                "origin": "SYNTHETIC_OWNER_BOUNDARY_NOT_CANONICAL_SCORE",
                "input": projection,
                "require_at_least_one_source": False,
                "reference_time": None,
                "actual_owner_reference_time": None,
                "fault_profile": None,
                "evaluation_authority": {
                    "origin": "EXPLICIT_REQUEST_MEANING_NOT_ONE_EXPECTED_DECOMPOSITION",
                    "source_information": {
                        "work-1": "선택한 스레드의 전체 내용, 특정 한 대상(SINGULAR)",
                        "work-2": "결제 관련 스레드들의 제목만, 조건별 조회(CRITERIA)",
                    },
                    "forbidden": [
                        "work-1의 전체 내용 요구를 work-2에 부과하거나 그 반대로 전달",
                        "선택된 한 대상의 범위를 별도 조건 조회 업무까지 확장",
                        "Task/Calendar Source 추가; SEND 실행",
                        "새 Draft를 기존 Draft 조회 요구로 바꾸기",
                    ],
                    "independent_outputs": [
                        {
                            "resource_type": "GMAIL_DRAFT",
                            "effect": "CREATE",
                            "work_unit_ids": [unit],
                        }
                        for unit in ids
                    ]
                    if action
                    else [],
                    "accepted": "동등한 fact 표현/그룹을 허용하되 정보·scope·업무 귀속 보존",
                },
            }
        )
    return cases


def make_plan(baseline_raw_path: Path = DEFAULT_BASELINE_RAW) -> dict[str, Any]:
    registry = PromptRegistry()
    product_ref = registry.lookup_for_evaluation(PROMPT_ID)
    actual_policy = _runtime_policy_for_prompt(
        RuntimePolicy(sampling_seed=POLICY["seed"]), product_ref
    )
    if (
        actual_policy.sampling_temperature != POLICY["temperature"]
        or actual_policy.local_timeout_seconds != POLICY["timeout_seconds"]
        or actual_policy.structured_output_repair_budget != POLICY["schema_repair_budget"]
    ):
        raise ValueError("Product Source runtime policy changed; comparison requires review")
    controls, historical_binding = load_frozen_controls(baseline_raw_path, registry)
    cases = controls + synthetic_cases(controls[0]["input"]["source_candidates"])
    candidate_ref = replace(
        product_ref,
        prompt_version="source-requirements-v1-evaluation",
        output_schema_version=CANDIDATE_SCHEMA_VERSION,
        content_hash=hashlib.sha256(
            candidate_source_text(registry.source_text(PROMPT_ID)).encode()
        ).hexdigest(),
    )
    for case in cases:
        if case["origin"] == "SYNTHETIC_OWNER_BOUNDARY_NOT_CANONICAL_SCORE":
            errors = validate_output_schema(
                case["input"]["goal_candidate"],
                goal_schema.identify_goal_output_schema(_ids(case["input"])).json_schema,
            )
            if errors:
                raise ValueError(f"synthetic upstream Goal fixture invalid: {errors}")
        case["arms"] = {}
        for arm, schema in _schemas(case["input"], case["require_at_least_one_source"]).items():
            ref = product_ref if arm == "baseline" else candidate_ref
            case["arms"][arm] = {
                "input": deepcopy(case["input"]),
                "input_sha256": object_hash(case["input"]),
                "schema": asdict(schema),
                "schema_sha256": object_hash(schema.json_schema),
                "prompt_ref": asdict(ref),
                "instruction_sha256": hashlib.sha256(
                    owner_instruction(case["input"], arm, registry).encode()
                ).hexdigest(),
                "new_call": not (arm == "baseline" and case["case_id"] in CONTROL_IDS),
            }
    source_files = [
        Path(__file__),
        ROOT / "scripts/ru_source_requirements_candidate.py",
        _PROMPT_PATH,
        ROOT / "scripts/ru_observation.py",
        ROOT / "src/google_work_agent/adapters/llm/ollama/transport.py",
        ROOT / "src/google_work_agent/adapters/llm/runtime/schema_repair_scope.py",
        ROOT / "src/google_work_agent/adapters/llm/runtime/structured_inference_router.py",
        ROOT / "src/google_work_agent/adapters/llm/runtime/prompt_repair_schema_repairer.py",
        ROOT / "src/google_work_agent/application/prompt_runtime/assemble_prompt.py",
        ROOT / "src/google_work_agent/application/prompt_runtime/prompt_manifest.json",
        ROOT
        / "src/google_work_agent/application/prompt_runtime"
        / "prompt_runtime_input_contract_v1.json",
        ROOT
        / "src/google_work_agent/application/agents/request_understanding"
        / "identify_source_dependencies.py",
        ROOT
        / "src/google_work_agent/application/agents/request_understanding"
        / "merge_resource_responsibilities.py",
        ROOT
        / "src/google_work_agent/application/agents/request_understanding/contracts"
        / "request_goal_candidate_schema.py",
    ]
    return {
        "scope": "SOURCE_OWNER_REPRESENTATION_ONLY_NOT_CORE92_OR_BUSINESS_SUCCESS",
        "sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_hashes": {
            path.relative_to(ROOT).as_posix(): normalized_sha256(path) for path in source_files
        },
        "dataset_sha256": normalized_sha256(DEFAULT_DATASET_PATH),
        "fixture_sha256": normalized_sha256(DEFAULT_PROVIDER_FIXTURE_PATH),
        "model_id": MODEL_ID,
        "model_digest": historical_binding["model_digest"],
        "model_digest_authority": "HISTORICAL_ACTUAL; MATCH_LOCAL_CATALOG_BEFORE_EXECUTE",
        "runtime_policy": deepcopy(POLICY),
        "product_effective_source_policy": asdict(actual_policy),
        "baseline_binding": deepcopy(historical_binding),
        "baseline_raw_path": baseline_raw_path.resolve().relative_to(ROOT).as_posix(),
        "baseline_raw_sha256": normalized_sha256(baseline_raw_path),
        "candidate_contract": {
            "activation": "EVALUATION_ONLY_NOT_REGISTERED_IN_PRODUCT",
            "schema_version": CANDIDATE_SCHEMA_VERSION,
            "input": "IDENTICAL_PRODUCT_SOURCE_ALLOWLIST_AND_FROZEN_PROJECTION",
            "prompt_change": "SOURCE_REQUIRED_PAYLOAD_SHAPE_ONLY",
            "shape_replacements": [list(pair) for pair in _SHAPE_REPLACEMENTS],
            "product_prompt_ref": asdict(product_ref),
            "candidate_prompt_ref": asdict(candidate_ref),
        },
        "case_ids": [case["case_id"] for case in cases],
        "trials_per_arm_case": 1,
        "order": (
            "Fixed case order; frozen controls baseline reused; synthetic baseline then candidate"
        ),
        "max_new_first_calls": 7,
        "max_new_calls_with_schema_repair": 14,
        "reused_baseline_calls": sum(
            len(case["baseline_record"]["transport_calls"]) for case in controls
        ),
        "semantic_revision_calls": 0,
        "provider_reads": 0,
        "provider_writes": 0,
        "semantic_review_dimensions": [
            "required_information retained and bound to correct WorkUnit",
            "SINGULAR/CRITERIA retained independently, no cross-product",
            "missing Source versus excessive Source (including new Output as existing Source)",
            "explicit prohibitions and selected-identity scope",
            "first versus schema repair versus merge/normalization",
        ],
        "limitations": [
            "Frozen upstream WorkUnit/Goal mistakes are preserved, not silently corrected.",
            "CORE-001 upstream split the prohibition into work-2; "
            "this is not simple-work stability proof.",
            "CORE-023 is Kestrel mail+Task to a new Event, not a Calendar+Task summary.",
            "Synthetic upstream work/goal are fixtures, not RU model-generated success.",
            "Baseline historical repair is preserved with current guard revalidation separately.",
            "Historical/current guard differences are not gains of this representation candidate.",
            "No model effect is established by the component prototype or this dry plan.",
            "No automatic semantic PASS based on Resource exact set or fixed fact vocabulary.",
            "Each arm is one trial; not a repeated stability estimate.",
        ],
        "cases": cases,
        "dry_validation": "PASS",
        "model_evaluation": "NOT_RUN",
    }


def _repair_input(
    projection: dict[str, Any], raw: object, errors: list[str], registry: PromptRegistry
) -> dict[str, Any]:
    return _build_repair_input(
        prompt_ref=registry.lookup_for_evaluation(PROMPT_ID),
        prompt_input=projection,
        failed_output=raw,
        attempt_no=1,
        max_attempts=1,
        failure_reason_code="OUTPUT_SCHEMA_INVALID",
        validator_errors=tuple(errors),
    )


def run_arm(
    case: dict[str, Any], arm: str, client: OllamaHTTPClient, registry: PromptRegistry
) -> dict[str, Any]:
    frozen = case["arms"][arm]
    if not frozen["new_call"]:
        raise ValueError("frozen baseline must be reused; another baseline call is forbidden")
    schema = OutputSchemaDefinition(**frozen["schema"])
    ref = PromptReference(**frozen["prompt_ref"])
    projection = deepcopy(frozen["input"])
    result: dict[str, Any] = {
        "case_id": case["case_id"],
        "arm": arm,
        "new_call": True,
        "attempts": [],
        "transport_calls": [],
    }
    first_raw: object = None
    with observe_local_calls(result["transport_calls"]):
        for index in range(2):
            event: dict[str, Any] = {"attempt": "FIRST" if not index else "SCHEMA_REPAIR"}
            result["attempts"].append(event)
            try:
                response = client.invoke_structured(
                    endpoint=OLLAMA_FIXED_LOOPBACK_ENDPOINT,
                    model_id=MODEL_ID,
                    prompt_ref=ref,
                    prompt_input=projection,
                    output_schema=schema,
                    timeout_seconds=POLICY["timeout_seconds"],
                    instruction_text=owner_instruction(projection, arm, registry),
                    sampling_temperature=POLICY["temperature"],
                    sampling_seed=POLICY["seed"],
                )
                raw, errors = _parse(response.content, schema)
                event.update(raw_output=raw, schema_errors=errors)
                if index and not errors:
                    changed = find_out_of_scope_schema_repair_changes(
                        failed_output=first_raw,
                        repaired_output=raw,
                        affected_field_paths=tuple(
                            projection["failure_record"]["affected_field_paths"]
                        ),
                        output_schema=schema.json_schema,
                    )
                    event["out_of_scope_repair_changes"] = list(changed)
                    if changed:
                        raise ValueError("schema repair changed unaffected fields")
                if not errors:
                    result["final"] = observed_semantics(raw, case, arm)
                    break
                if not index:
                    first_raw = deepcopy(raw)
                    projection = _repair_input(frozen["input"], raw, errors, registry)
                else:
                    result["final"] = {
                        "structural_validation": "FAIL",
                        "error": "SCHEMA_INVALID_AFTER_REPAIR",
                    }
            except Exception as error:
                event.update(error_type=type(error).__name__, error=str(error))
                result["final"] = {"structural_validation": "FAIL", "error": str(error)}
                break
    result["metrics"] = metrics(result["transport_calls"])
    return result


def _write(path: Path, value: object, *, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x" if exclusive else "w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result-dir", type=Path, required=True)
    parser.add_argument("--baseline-raw", type=Path, default=DEFAULT_BASELINE_RAW)
    parser.add_argument("--execute-plan", type=Path)
    parser.add_argument("--expected-plan-sha256")
    args = parser.parse_args()
    directory = args.result_dir.resolve()
    if not directory.is_relative_to((ROOT / "evaluation/results").resolve()):
        raise ValueError("results must stay inside evaluation/results")
    if args.execute_plan is None:
        plan = make_plan(args.baseline_raw)
        path = directory / "preregistered-plan.json"
        _write(path, plan, exclusive=True)
        print(
            json.dumps(
                {
                    "dry_validation": "PASS",
                    "plan": str(path),
                    "sha256": normalized_sha256(path),
                    "model_calls": 0,
                }
            )
        )
        return
    if normalized_sha256(args.execute_plan) != args.expected_plan_sha256:
        raise ValueError("preregistered plan hash mismatch")
    plan = json.loads(args.execute_plan.read_text(encoding="utf-8"))
    current = make_plan(ROOT / plan["baseline_raw_path"])
    if object_hash(current) != object_hash(plan):
        raise ValueError("HEAD/code/input/prompt/schema/runtime changed after preregistration")
    client = OllamaHTTPClient()
    model = next(
        (item for item in client.list_installed_models() if item.model_id == MODEL_ID), None
    )
    if model is None or model.digest != plan["model_digest"]:
        raise ValueError("installed 9B digest does not match recorded baseline")
    raw_path = directory / "raw.json"
    raw: dict[str, Any] = {"binding": plan, "plan_sha256": args.expected_plan_sha256, "results": []}
    _write(raw_path, raw, exclusive=True)
    registry = PromptRegistry()
    for case in plan["cases"]:
        for arm in ("baseline", "candidate"):
            if not case["arms"][arm]["new_call"]:
                record = {
                    "case_id": case["case_id"],
                    "arm": arm,
                    "new_call": False,
                    "original_record": case["baseline_record"],
                    "current_revalidation": case["baseline_revalidation"],
                    "transport_calls": case["baseline_record"]["transport_calls"],
                }
            else:
                record = run_arm(case, arm, client, registry)
            raw["results"].append(record)
            _write(raw_path, raw)
    raw["completed"] = True
    raw["semantic_evaluation"] = "PENDING_EVIDENCE_REVIEW_NOT_AUTOMATIC_PASS"
    raw["new_call_metrics"] = metrics(
        [call for row in raw["results"] if row["new_call"] for call in row["transport_calls"]]
    )
    _write(raw_path, raw)
    print(json.dumps({"raw": str(raw_path), "new_call_metrics": raw["new_call_metrics"]}))


if __name__ == "__main__":
    main()
