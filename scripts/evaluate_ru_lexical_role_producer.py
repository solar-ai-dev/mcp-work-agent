"""Evaluate an inactive lexical-role field in the existing RU Goal call."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import cast

from scripts.evaluate_retrieval_plan_query_node import _load_latest_state

from google_work_agent.adapters.llm.ollama.transport import OllamaHTTPClient
from google_work_agent.application.agents.request_understanding import identify_goal
from google_work_agent.application.agents.request_understanding.contracts import (
    request_goal_candidate_schema as goal_schema,
)
from google_work_agent.application.prompt_runtime.assemble_prompt import assemble_prompt
from google_work_agent.application.prompt_runtime.prompt_registry import (
    DEVELOPMENT_SMOKE,
    PromptRegistry,
    default_prompt_manifest_path,
    load_prompt_reference,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.runtime_selection import OLLAMA_FIXED_LOOPBACK_ENDPOINT
from google_work_agent.ports.llm.structured_inference_contracts import OutputSchemaDefinition
from google_work_agent.ports.system.contracts.workflow_execution import WorkflowStartRequest

MODEL_ID = "qwen3.5:9b"
EXPECTED_MODEL_DIGEST = "6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7"
DEFAULT_MANIFEST = Path("evaluation/derived_queries/source-query-diversity-v1.json")
INPUTS = (
    ("CASE-CORE-007", "A"),
    ("CASE-CORE-007", "B"),
    ("CASE-CORE-008", "A"),
    ("CASE-CORE-008", "B"),
    ("CASE-CORE-010", "A"),
    ("CASE-CORE-010", "B"),
    ("CASE-CORE-023", "A"),
    ("CASE-CORE-023", "B"),
    ("CASE-CORE-007", "D"),
    ("CASE-CORE-006", "D"),
)
SYNTHETIC = (
    ("SYNTH-TITLE", '제목이 "Q4 Audit Ledger"인 메일을 찾아줘. 비슷한 제목으로 바꾸지 마.'),
    (
        "SYNTH-DESCRIPTION",
        "지난주 포장 승인 절차를 설명한 메일을 찾아 핵심 내용을 요약해줘. "
        "특정 제목은 지정하지 않았어.",
    ),
)
_BASE_SEARCH_PROMPT_LINE = "- `search_terms`: 조회에 필요한 원문 고유명·프로젝트·literal anchor."
_REPLACEMENT_SEARCH_PROMPT_LINE = (
    "- `lexical_terms`: 현재 원문의 검색 표현을 역할과 함께 둔다. "
    "EXACT_ENTITY는 구별 대상의 완전한 이름, EXACT_TITLE은 명시적 정확 제목, "
    "EXPLORATORY는 바꿀 수 있는 자료 설명이다. 날짜·시간·상태·Source·답변 내용은 "
    "기존 슬롯에만 둔다. 원문에 없는 별칭은 만들지 않는다."
)


def _sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _lexical_roles_property() -> dict[str, object]:
    return {
        "type": "array",
        "maxItems": 6,
        "uniqueItems": True,
        "description": (
            "검색용 원문 lexical span과 그 역할만 둔다. EXACT_ENTITY는 사용자가 명시한 "
            "구별 대상의 완전한 고유명, EXACT_TITLE은 사용자가 정확한 제목으로 지정한 "
            "구절, EXPLORATORY는 교체 가능한 자료·업무 설명이다. 모호하면 exact로 "
            "승격하지 않는다. 날짜·기간·시간·상태·Source·사람·답변 요구·금지 지시는 "
            "기존 constraint/goal 책임이며 여기에 중복하지 않는다. 원문에 없는 별칭이나 "
            "새 사실을 만들지 않고 검색이 필요 없으면 빈 배열을 반환한다."
        ),
        "items": {
            "type": "object",
            "additionalProperties": False,
            "required": ["role", "value"],
            "properties": {
                "role": {"enum": ["EXACT_ENTITY", "EXACT_TITLE", "EXPLORATORY"]},
                "value": {
                    "type": "string",
                    "minLength": 1,
                    "description": "현재 사용자 요청에서 공백·문장부호를 바꾸지 않고 복사한 span",
                },
            },
        },
    }


def _candidate_schema(variant: str) -> OutputSchemaDefinition:
    schema = deepcopy(goal_schema.IDENTIFY_GOAL_OUTPUT_SCHEMA.json_schema)
    required = cast(list[str], schema["required"])
    properties = cast(dict[str, object], schema["properties"])
    if variant == "parallel":
        required.append("lexical_roles")
        properties["lexical_roles"] = _lexical_roles_property()
    elif variant == "replacement":
        constraints = cast(dict[str, object], properties["constraints"])
        constraints["description"] = (
            "원문 검색 표현은 lexical_terms의 역할과 함께 보존한다. "
            "EXACT_ENTITY/EXACT_TITLE은 명시된 구별 대상/정확 제목이며, "
            "EXPLORATORY는 교체 가능한 자료 설명이다. business_concepts와 "
            "기간·상태·사람·실행 값의 기존 슬롯은 별도로 유지한다."
        )
        constraint_required = cast(list[str], constraints["required"])
        constraint_properties = cast(dict[str, object], constraints["properties"])
        constraint_required.remove("search_terms")
        constraint_required.append("lexical_terms")
        del constraint_properties["search_terms"]
        constraint_properties["lexical_terms"] = _lexical_roles_property()
    else:
        raise ValueError("unknown lexical-role candidate variant")
    return OutputSchemaDefinition(
        schema_version=f"request-goal-candidate-v16-{variant}-lexical-role-eval",
        json_schema=schema,
    )


def _legacy_projection(output: dict[str, object], variant: str) -> dict[str, object]:
    normalized = deepcopy(output)
    if variant == "parallel":
        normalized.pop("lexical_roles", None)
    else:
        constraints = normalized.get("constraints")
        if isinstance(constraints, dict):
            lexical = constraints.pop("lexical_terms", [])
            constraints["search_terms"] = [
                item["value"]
                for item in lexical
                if isinstance(item, dict) and isinstance(item.get("value"), str)
            ]
    return normalized


def _write(path: Path, result: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _prepare_inputs(checkpoint_root: Path) -> list[tuple[str, WorkflowStartRequest]]:
    manifest = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    items = {(item["origin_case_id"], item["variant"]): item for item in manifest["cases"]}
    if any(key not in items for key in INPUTS):
        raise ValueError("fixed lexical-role input missing from manifest")
    requests: dict[str, WorkflowStartRequest] = {}
    prepared: list[tuple[str, WorkflowStartRequest]] = []
    for case_id, variant in INPUTS:
        if case_id not in requests:
            database = checkpoint_root / case_id / "state" / "data" / "google_work_agent.db"
            request = _load_latest_state(database).get("__request__")
            if not isinstance(request, WorkflowStartRequest):
                raise ValueError(f"{case_id}: checkpoint request unavailable")
            requests[case_id] = request
        original = requests[case_id]
        text = items[(case_id, variant)]["request"]
        if variant == "A" and original.request_text != text:
            raise ValueError(f"{case_id}: A request differs from checkpoint")
        prepared.append((f"{case_id}-{variant}", replace(original, request_text=text)))
    base = requests["CASE-CORE-007"]
    prepared.extend(
        (label, replace(base, request_text=text, selected_resources=()))
        for label, text in SYNTHETIC
    )
    if len(prepared) != 12 or len({label for label, _ in prepared}) != 12:
        raise ValueError("fixed lexical-role comparison must have 12 unique inputs")
    return prepared


def evaluate(checkpoint_root: Path, result_path: Path, *, variant: str) -> dict[str, object]:
    if result_path.exists():
        raise ValueError("result path already exists; preserve every prior trial")
    prepared = _prepare_inputs(checkpoint_root)
    schema = _candidate_schema(variant)
    prompt_ref = load_prompt_reference(
        "request_understanding.identify_goal",
        default_prompt_manifest_path(),
        execution_scope=DEVELOPMENT_SMOKE,
    )
    candidate_prompt_hash = prompt_ref.content_hash
    if variant == "replacement":
        source = PromptRegistry().source_text(prompt_ref.prompt_id).rstrip()
        if source.count(_BASE_SEARCH_PROMPT_LINE) != 1:
            raise ValueError("RU Goal Prompt search slot text changed")
        candidate_source = source.replace(_BASE_SEARCH_PROMPT_LINE, _REPLACEMENT_SEARCH_PROMPT_LINE)
        candidate_prompt_hash = hashlib.sha256(candidate_source.encode("utf-8")).hexdigest()
    client = OllamaHTTPClient()
    digest = next(
        (model.digest for model in client.list_installed_models() if model.model_id == MODEL_ID),
        None,
    )
    if digest != EXPECTED_MODEL_DIGEST:
        raise ValueError("local model digest differs from the preregistered comparison")
    result: dict[str, object] = {
        "binding": {
            "baseline_sha": "9cfe70d0173b5b427601fb5e16558addc07eb7de",
            "manifest_sha256": hashlib.sha256(DEFAULT_MANIFEST.read_bytes()).hexdigest(),
            "checkpoint_corpus": checkpoint_root.name,
            "model": MODEL_ID,
            "model_digest": digest,
            "prompt_hash": candidate_prompt_hash,
            "schema_hash": _sha256(schema.json_schema),
            "variant": variant,
            "temperature": 0,
            "seed": 1729,
            "scope": "EVALUATION_ONLY_RU_GOAL_FIRST_CALL",
        },
        "cases": [],
    }
    _write(result_path, result)
    cases = cast(list[dict[str, object]], result["cases"])
    for label, request in prepared:
        prompt_input = identify_goal._prompt_input(
            request=request,
            confirmation_response=None,
        )
        instruction_text = assemble_prompt(
            prompt_ref,
            prompt_input,
            execution_scope=DEVELOPMENT_SMOKE,
        )
        candidate_ref = prompt_ref
        if variant == "replacement":
            if not instruction_text.startswith(source):
                raise ValueError("RU Goal Prompt assembly changed")
            instruction_text = candidate_source + instruction_text[len(source) :]
            candidate_ref = replace(
                prompt_ref,
                prompt_version="lexical-replacement-eval",
                content_hash=candidate_prompt_hash,
            )
        record: dict[str, object] = {
            "input_id": label,
            "request": request.request_text,
            "request_sha256": hashlib.sha256(request.request_text.encode()).hexdigest(),
            "prompt_input_sha256": _sha256(prompt_input),
            "dispatch_count": 0,
        }
        cases.append(record)
        _write(result_path, result)
        started = time.perf_counter()
        try:
            record["dispatch_count"] = 1
            response = client.invoke_structured(
                endpoint=OLLAMA_FIXED_LOOPBACK_ENDPOINT,
                model_id=MODEL_ID,
                prompt_ref=candidate_ref,
                prompt_input=prompt_input,
                output_schema=schema,
                timeout_seconds=180,
                instruction_text=instruction_text,
                sampling_temperature=0.0,
                sampling_seed=1729,
            )
            record["input_tokens"] = response.input_tokens
            record["output_tokens"] = response.output_tokens
            record["provider_latency_ms"] = response.latency_ms
            record["raw_content"] = response.content
            output = json.loads(response.content)
            record["output"] = output
            errors = validate_output_schema(output, schema.json_schema)
            if isinstance(output, dict):
                output_constraints = output.get("constraints")
                roles = (
                    output.get("lexical_roles")
                    if variant == "parallel"
                    else output_constraints.get("lexical_terms")
                    if isinstance(output_constraints, dict)
                    else None
                )
                if isinstance(roles, list):
                    for index, item in enumerate(roles):
                        if not isinstance(item, dict) or not isinstance(item.get("value"), str):
                            continue
                        if item["value"] not in request.request_text:
                            errors.append(f"lexical_roles[{index}] is not an exact source span")
                normalized = _legacy_projection(output, variant)
                errors.extend(
                    f"existing_goal:{error}"
                    for error in validate_output_schema(
                        normalized, goal_schema.IDENTIFY_GOAL_OUTPUT_SCHEMA.json_schema
                    )
                )
            record["validation_errors"] = errors
            record["status"] = "SCHEMA_AND_SPAN_VALID" if not errors else "INVALID"
        except Exception as error:
            record["status"] = "CALL_FAILED"
            record["error_type"] = type(error).__name__
            record["error_message"] = str(error)[:240]
        record["wall_ms"] = round((time.perf_counter() - started) * 1000, 3)
        _write(result_path, result)
        print(json.dumps({"input_id": label, "status": record["status"]}), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint-root", type=Path, required=True)
    parser.add_argument("--result-path", type=Path, required=True)
    parser.add_argument("--variant", choices=("parallel", "replacement"), default="parallel")
    arguments = parser.parse_args()
    evaluate(
        arguments.checkpoint_root.resolve(),
        arguments.result_path.resolve(),
        variant=arguments.variant,
    )
