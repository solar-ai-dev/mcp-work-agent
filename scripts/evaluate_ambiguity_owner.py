"""Fixed six paired v29 ambiguity owner trials, not workflow/business success.

Upstream fixtures are explicit synthetic states or frozen observed Core producers.
Only the Prompt's global-count rules/examples differ. No semantic revision, live
Provider, graph execution, prompt activation or historical response reuse occurs.
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
from typing import Any, cast

from evaluation.dataset_v8 import (
    DEFAULT_DATASET_PATH,
    DEFAULT_PROVIDER_FIXTURE_PATH,
    load_cases,
    normalized_sha256,
)
from scripts.ru_ambiguity_owner_candidate import (
    CANDIDATE_ID,
    ambiguity_owner_instruction,
    candidate_source_hash,
)
from scripts.ru_observation import metrics, object_hash, observe_local_calls

from google_work_agent.adapters.llm.ollama.transport import (
    OLLAMA_PRODUCT_CONTEXT_TOKENS,
    OllamaHTTPClient,
)
from google_work_agent.adapters.llm.runtime.prompt_repair_schema_repairer import _build_repair_input
from google_work_agent.adapters.llm.runtime.schema_repair_scope import (
    find_out_of_scope_schema_repair_changes,
)
from google_work_agent.application.agents.request_understanding.contracts.request_goal_candidate_schema import (  # noqa: E501
    derive_requested_resource_fields,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestGoalCandidateV1,
)
from google_work_agent.application.agents.request_understanding.contracts.work_unit_binding import (
    validate_requested_work_definition,
)
from google_work_agent.application.agents.request_understanding.detect_ambiguity import (
    detect_ambiguity,
)
from google_work_agent.application.prompt_runtime.assemble_prompt import assemble_prompt
from google_work_agent.application.prompt_runtime.prompt_registry import EVALUATION, PromptRegistry
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.runtime_selection import OLLAMA_FIXED_LOOPBACK_ENDPOINT
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferenceResultV1
from google_work_agent.ports.system.contracts.workflow_execution import (
    SelectedResourceRef,
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)

ROOT = Path(__file__).resolve().parents[1]
PROMPT_ID = "request_understanding.detect_ambiguity"
MODEL_ID = "qwen3.5:9b"
SEED = 20260923
CORE_FIXTURE = ROOT / "evaluation/experiments/064-ambiguity-v29-frozen-inputs.json"
SOURCE_PATH = (
    ROOT
    / "src/google_work_agent/application/prompt_runtime/sources"
    / "request_understanding.detect_ambiguity.md"
)
POLICY = {
    "temperature": 0.0,
    "temperature_authority": "Product structured_inference_router._DETECT_AMBIGUITY_TEMPERATURE",
    "seed": SEED,
    "seed_authority": "preregistered evaluation setting, not a global Product default",
    "num_ctx": OLLAMA_PRODUCT_CONTEXT_TOKENS,
    "think": False,
    "timeout_seconds": 180,
    "schema_repair_budget": 1,
    "semantic_revision_budget": 0,
    "transport_retry_budget": 0,
    "rerun_to_pass": 0,
}


def _goal(request: str, spans: list[str], sources: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "goal": request,
        "completion_conditions": [request],
        "constraints": [],
        "analysis_requirement": "NONE",
        "effect_prohibitions": [],
        "requested_work": {
            "work_units": [
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
            ],
            "work_relations": [],
        },
        "resource_responsibilities": {"source_reads": sources, "outputs": []},
    }


def _synthetic_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for selected in (False, True):
        spans = [
            "선택한 일정의 시작 시각을 알려줘." if selected else "Alpha 일정의 시작 시각을 알려줘.",
            "그리고 다른 일정의 종료 시각도 알려줘.",
        ]
        request = " ".join(spans)
        goal = _goal(
            request,
            spans,
            [
                {
                    "resource_type": "CALENDAR_EVENT",
                    "required_information": ["event_identity", fact],
                    "target_scope": "SINGULAR",
                    "work_unit_ids": [f"work-{index + 1}"],
                }
                for index, fact in enumerate(("start", "end"))
            ],
        )
        refs = []
        if selected:
            refs = [
                {
                    "resource_ref_id": "selected-first-event",
                    "connector_id": "google_workspace",
                    "resource_type": "calendar_event",
                    "resource_id": "synthetic-first-event",
                    "parent_resource_id": "primary",
                }
            ]
        else:
            goal["constraints"] = [
                {
                    "kind": "USER_REQUIREMENT",
                    "field": "search_terms",
                    "value": "Alpha",
                    "work_unit_ids": ["work-1"],
                    "provenance": {"source": "USER_REQUEST", "start_offset": 0, "end_offset": 5},
                }
            ]
        cases.append(
            {
                "case_id": "SYNTH-AMBIGUITY-SELECTED-OTHER"
                if selected
                else "SYNTH-AMBIGUITY-ANCHOR-OTHER",
                "user_request": request,
                "goal_candidate": goal,
                "selected_resource_refs": refs,
                "expected_owners": ["USER"],
                "expectation_basis": (
                    "첫 업무 대상의 identity/anchor는 별도 업무의 미지정 대상을 해결하지 않는다."
                ),
            }
        )
    request = "내 작업 목록의 작업을 전부 제목과 상태로 알려줘."
    goal = _goal(
        request,
        [request],
        [
            {
                "resource_type": "TASK",
                "required_information": ["title", "completion_status"],
                "target_scope": "CRITERIA",
                "work_unit_ids": ["work-1"],
            }
        ],
    )
    goal["constraints"] = [
        {
            "kind": "SCOPE",
            "field": "coverage_requirement",
            "value": "EXHAUSTIVE",
            "work_unit_ids": ["work-1"],
        }
    ]
    cases.append(
        {
            "case_id": "SYNTH-AMBIGUITY-CRITERIA-COLLECTION",
            "user_request": request,
            "goal_candidate": goal,
            "selected_resource_refs": [],
            "expected_owners": ["CONNECTOR"],
            "expectation_basis": (
                "검색어가 없어도 명시된 전체 collection 조회의 대상 범위는 확정되어 있다."
            ),
        }
    )
    request = "작업 목록 demo-list에 '서류 정리'라는 새 작업을 만들어줘."
    goal = _goal(request, [request], [])
    goal["resource_responsibilities"]["outputs"] = [
        {
            "resource_type": "TASK",
            "effect": "CREATE",
            "work_unit_ids": ["work-1"],
        }
    ]
    goal["constraints"] = [
        {
            "kind": "RESOURCE",
            "field": field,
            "value": value,
            "work_unit_ids": ["work-1"],
        }
        for field, value in (("parent_id", "demo-list"), ("title", "서류 정리"))
    ]
    cases.append(
        {
            "case_id": "SYNTH-AMBIGUITY-PURE-CREATE",
            "user_request": request,
            "goal_candidate": goal,
            "selected_resource_refs": [],
            "expected_owners": ["NONE"],
            "expectation_basis": (
                "새 Task identity 선택은 필요하지 않으며 실제 생성은 기존 승인 경계 이후다."
            ),
        }
    )
    for case in cases:
        case.update(
            origin={"kind": "SYNTHETIC_TYPED_OWNER_FIXTURE_NOT_MODEL_UPSTREAM"},
            environment_assumption={
                "account": "synthetic-evaluation-account",
                "authenticated": True,
                "scope_and_parent_access": "fixture-authorized; no live account or Provider",
            },
            reference_time=None,
            fault_profile=None,
        )
    return cases


def freeze_observed_core(path: Path, case_id: str) -> dict[str, Any]:
    """Explicit one-time fixture extraction; never reuse historical model responses."""
    document = json.loads(path.read_text(encoding="utf-8"))
    row = next(row for row in document["cases"] if row["case_id"] == case_id)
    events = row["atomic"]
    ambiguity = next(event for event in events if event["prompt_id"] == PROMPT_ID)
    goal_event = next(event for event in events if event["prompt_id"].endswith(".identify_goal"))
    source_event = next(
        event for event in events if event["prompt_id"].endswith(".identify_source_status")
    )
    goal = deepcopy(ambiguity["input"]["goal_candidate"])
    original_sources = goal["resource_responsibilities"]["source_reads"]
    bound_sources = deepcopy(source_event["input"]["source_reads"])
    stripped = [
        {key: value for key, value in item.items() if key != "work_unit_ids"}
        for item in bound_sources
    ]
    if stripped != original_sources:
        raise ValueError("the observed Source authority differs at ambiguity handoff")
    goal["resource_responsibilities"]["source_reads"] = bound_sources
    goal["requested_work"] = deepcopy(goal_event["input"]["requested_work"])
    return {
        "case_id": case_id,
        "user_request": ambiguity["input"]["user_request"],
        "goal_candidate": goal,
        "selected_resource_refs": deepcopy(ambiguity["input"]["selected_resource_refs"]),
        "reference_time": row.get("reference_time"),
        "fault_profile": row.get("fault_profile"),
        "origin": {
            "kind": "OBSERVED_ATOMIC_PRODUCER_REPROJECTED_CURRENT_CODE_NOT_FRESH_UPSTREAM",
            "raw_path": path.relative_to(ROOT).as_posix(),
            "raw_sha256": normalized_sha256(path),
            "binding": document["binding"],
            "record_sha256": object_hash(row),
            "old_ambiguity_input_sha256": object_hash(ambiguity["input"]),
            "work_authority_input_sha256": object_hash(goal_event["input"]),
            "source_authority_input_sha256": object_hash(source_event["input"]),
            "old_response_reused": False,
            "changes": [
                "carry already-observed Work and Source work_unit_ids through current projector"
            ],
        },
        "expected_owners": ["CONNECTOR"] if case_id == "CASE-CORE-005" else ["CONNECTOR", "USER"],
        "expectation_basis": (
            "선택 Task 상태/기한은 Connector 조회이며 새 사용자 대상 선택이 아니다."
            if case_id == "CASE-CORE-005"
            else "관련 READ 후 시간/소요시간 확인 또는 현재 필요한 구체적 시간 확인 모두 허용. "
            "원래 Source 오판은 고치지 않으며 target/수신자 재확인은 별도 수동 의미 검수."
        ),
    }


def fixed_cases() -> list[dict[str, Any]]:
    observed = cast(list[dict[str, Any]], json.loads(CORE_FIXTURE.read_text(encoding="utf-8")))
    cases = _synthetic_cases() + observed
    canonical = load_cases()
    for case in cases:
        if case["case_id"].startswith("CASE-"):
            expected_request = canonical[case["case_id"]].raw["canonical_user_prompt"]
            if case["user_request"] != expected_request:
                raise ValueError("frozen original request no longer matches Canonical v8")
        goal = case["goal_candidate"]
        validate_requested_work_definition(
            goal["requested_work"], user_request=case["user_request"]
        )
        effects, resources, _ = derive_requested_resource_fields(goal["resource_responsibilities"])
        goal["requested_effect_hints"], goal["requested_resource_hints"] = effects, resources
    return cases


class _Capture:
    def __init__(self, output: object) -> None:
        self.output, self.calls = output, 0

    def infer(self, mode: Any, ref: Any, projection: Any, schema: Any) -> Any:
        self.calls += 1
        self.projection, self.schema = deepcopy(projection), schema
        return StructuredInferenceResultV1(
            1, cast(dict[str, object], self.output), "FIXTURE", "NONE", "LOCAL_GPU", 0, 0, 0, None
        )


def owner_result(
    case: dict[str, Any], raw: object, ref: PromptReference
) -> tuple[dict[str, Any], Any, Any]:
    selected = tuple(SelectedResourceRef(**item) for item in case["selected_resource_refs"])
    capture = _Capture(raw)
    request = WorkflowStartRequest(
        run_id="v29-owner",
        conversation_id="v29-owner",
        workflow_key="v29-owner",
        entry_mode="RESOURCE_SELECTED" if selected else "AGENT_SEARCH",
        requested_mode="LOCAL_GPU",
        request_text=case["user_request"],
        selected_resource_ids=tuple(item.resource_id for item in selected),
        selected_resources=selected,
        run_budget=build_default_run_budget(),
        correlation=WorkflowCorrelationContext("v29-owner", "v29-owner", "v1"),
    )
    result, _ = detect_ambiguity(
        llm_runtime=capture,
        request=request,
        goal_candidate=cast(RequestGoalCandidateV1, case["goal_candidate"]),
        prompt_ref=ref,
        retry_budget=build_default_run_budget(),
    )
    if capture.calls != 1:
        raise ValueError("fixed diagnostic must reach the ambiguity owner exactly once")
    return capture.projection, capture.schema, result


def owner_instruction(
    projection: dict[str, Any], ref: PromptReference, registry: PromptRegistry, arm: str
) -> str:
    instruction = assemble_prompt(ref, projection, registry=registry, execution_scope=EVALUATION)
    return ambiguity_owner_instruction(instruction) if arm == "candidate" else instruction


def make_plan(*, model_digest: str | None) -> dict[str, Any]:
    registry = PromptRegistry()
    ref = registry.lookup_for_evaluation(PROMPT_ID)
    cases = fixed_cases()
    source = SOURCE_PATH.read_text(encoding="utf-8")
    for case in cases:
        projection, schema, _ = owner_result(
            case, {"missing_information_owner": "NONE", "missing_fields": []}, ref
        )
        case["arms"] = {}
        for arm in ("baseline", "candidate"):
            instruction = owner_instruction(projection, ref, registry, arm)
            case["arms"][arm] = {
                "input": deepcopy(projection),
                "schema": asdict(schema),
                "input_sha256": object_hash(projection),
                "schema_sha256": object_hash(schema.json_schema),
                "assembled_instruction_sha256": hashlib.sha256(instruction.encode()).hexdigest(),
                "prompt_source_sha256": candidate_source_hash(source)
                if arm == "candidate"
                else ref.content_hash,
            }
    paths = [
        Path(__file__),
        ROOT / "scripts/ru_ambiguity_owner_candidate.py",
        ROOT / "scripts/ru_observation.py",
        CORE_FIXTURE,
        SOURCE_PATH,
    ]
    paths += [
        ROOT / "src/google_work_agent" / path
        for path in (
            "application/agents/request_understanding/detect_ambiguity.py",
            "application/agents/request_understanding/contracts/request_goal_candidate_schema.py",
            "application/agents/request_understanding/contracts/work_unit_binding.py",
            "application/prompt_runtime/assemble_prompt.py",
            "application/prompt_runtime/prompt_manifest.json",
            "application/prompt_runtime/prompt_runtime_input_contract_v1.json",
            "adapters/llm/ollama/transport.py",
            "adapters/llm/runtime/schema_repair_scope.py",
            "adapters/llm/runtime/prompt_repair_schema_repairer.py",
            "adapters/llm/runtime/structured_inference_router.py",
        )
    ]
    return {
        "candidate_id": CANDIDATE_ID,
        "scope": "AMBIGUITY_OWNER_ONLY_NOT_WORKFLOW_BUSINESS_SCORE",
        "sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_hashes": {
            path.relative_to(ROOT).as_posix(): normalized_sha256(path) for path in paths
        },
        "dataset_sha256": normalized_sha256(DEFAULT_DATASET_PATH),
        "provider_fixture_sha256": normalized_sha256(DEFAULT_PROVIDER_FIXTURE_PATH),
        "source_prompt_ref": asdict(ref),
        "runtime_policy": deepcopy(POLICY),
        "model_id": MODEL_ID,
        "model_digest": model_digest,
        "case_ids": [case["case_id"] for case in cases],
        "cases": cases,
        "order": "fixed case order, baseline then candidate",
        "trials_per_arm_case": 1,
        "max_first_calls": 12,
        "max_total_calls_with_schema_repair": 24,
        "semantic_revision_calls": 0,
        "provider_reads": 0,
        "provider_writes": 0,
        "production_prompt_changed": False,
        "product_activation": False,
        "gold": (
            "owner choice filter plus manual review of missing_fields; no exact Work count"
        ),
        "limitations": [
            "Four synthetic and two observed Core producer states; not fresh upstream/Core92.",
            "CORE019 v4 wrong GMAIL_DRAFT/CALENDAR Source choices are preserved, not corrected.",
            "Raw USER can be normalized by unchanged Product single-Work validator; report both.",
            "OWNER_CHOICE_PASS is not semantic PASS until concrete missing fields are reviewed.",
        ],
        "dry_validation": "PASS",
        "model_evaluation": "NOT_RUN",
    }


def _parse(content: object, schema: OutputSchemaDefinition) -> tuple[Any, list[str]]:
    try:
        raw = json.loads(content) if isinstance(content, str) else content
    except json.JSONDecodeError:
        return content, ["$: provider output is not valid JSON"]
    return raw, validate_output_schema(raw, schema.json_schema)


def grade_first(raw: Any, case: dict[str, Any]) -> dict[str, Any]:
    owner = raw.get("missing_information_owner") if isinstance(raw, dict) else None
    return {
        "owner_choice": "OWNER_CHOICE_PASS" if owner in case["expected_owners"] else "FAIL",
        "actual_owner": owner,
        "missing_fields": raw.get("missing_fields") if isinstance(raw, dict) else None,
        "semantic_review": (
            "REQUIRED: inspect concrete missing fields; this is not a final semantic PASS"
        ),
    }


def run_arm(
    case: dict[str, Any], arm: str, client: OllamaHTTPClient, registry: PromptRegistry
) -> dict[str, Any]:
    source_ref = registry.lookup_for_evaluation(PROMPT_ID)
    frozen = case["arms"][arm]
    ref = (
        replace(source_ref, prompt_version="v29-eval", content_hash=frozen["prompt_source_sha256"])
        if arm == "candidate"
        else source_ref
    )
    schema = OutputSchemaDefinition(**frozen["schema"])
    projection = deepcopy(frozen["input"])
    record: dict[str, Any] = {
        "case_id": case["case_id"],
        "arm": arm,
        "attempts": [],
        "transport_calls": [],
        "new_call": True,
    }
    first_raw: object = None
    first_errors: list[str] = []
    with observe_local_calls(record["transport_calls"]):
        for attempt in range(2):
            event: dict[str, Any] = {"attempt": "FIRST" if attempt == 0 else "SCHEMA_REPAIR"}
            record["attempts"].append(event)
            try:
                response = client.invoke_structured(
                    endpoint=OLLAMA_FIXED_LOOPBACK_ENDPOINT,
                    model_id=MODEL_ID,
                    prompt_ref=ref,
                    prompt_input=projection,
                    output_schema=schema,
                    timeout_seconds=180,
                    instruction_text=owner_instruction(projection, source_ref, registry, arm),
                    sampling_temperature=0.0,
                    sampling_seed=SEED,
                )
                raw, errors = _parse(response.content, schema)
                event.update(
                    raw_output=raw,
                    schema_errors=errors,
                    raw_owner_evaluation=grade_first(raw, case),
                )
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
                    actual_input, _, post = owner_result(case, raw, source_ref)
                    if actual_input != frozen["input"]:
                        raise ValueError("Product postvalidator replay changed the frozen input")
                    event["postvalidator_output"] = post
                    record["final"] = {
                        "structural_result": "PASS",
                        "raw_owner_evaluation": event["raw_owner_evaluation"],
                        "postvalidator_output": post,
                        "semantic_review": "PENDING_MANUAL_REVIEW",
                    }
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
                    record["final"] = {
                        "structural_result": "FAIL",
                        "error": "SCHEMA_INVALID_AFTER_REPAIR",
                    }
            except Exception as error:
                event.update(error_type=type(error).__name__, error=str(error))
                record["final"] = {
                    "structural_result": "FAIL",
                    "error_type": type(error).__name__,
                    "error": str(error),
                }
                break
    record["metrics"] = metrics(record["transport_calls"])
    return record


def _write(path: Path, value: object, *, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x" if exclusive else "w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result-dir", type=Path, required=True)
    parser.add_argument("--execute-plan", type=Path)
    parser.add_argument("--expected-plan-sha256")
    args = parser.parse_args()
    result_dir = args.result_dir.resolve()
    if not result_dir.is_relative_to((ROOT / "evaluation/results").resolve()):
        raise ValueError("artifacts must remain under evaluation/results")
    model = next(
        (
            model
            for model in OllamaHTTPClient().list_installed_models()
            if model.model_id == MODEL_ID
        ),
        None,
    )
    if model is None or not model.digest:
        raise ValueError("actual installed model digest required")
    current = make_plan(model_digest=model.digest)
    if args.execute_plan is None:
        path = result_dir / "preregistered-plan.json"
        _write(path, current, exclusive=True)
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
        raise ValueError("registered plan hash mismatch")
    plan = json.loads(args.execute_plan.read_text(encoding="utf-8"))
    if object_hash(current) != object_hash(plan):
        raise ValueError("HEAD/code/input/schema/model/runtime changed after registration")
    raw_path = result_dir / "raw.json"
    raw: dict[str, Any] = {"binding": plan, "plan_sha256": args.expected_plan_sha256, "results": []}
    _write(raw_path, raw, exclusive=True)
    client, registry = OllamaHTTPClient(), PromptRegistry()
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
    raw["metrics_by_arm"] = {
        arm: metrics(
            [call for row in raw["results"] if row["arm"] == arm for call in row["transport_calls"]]
        )
        for arm in ("baseline", "candidate")
    }
    raw["completed"] = True
    _write(raw_path, raw)


if __name__ == "__main__":
    main()
