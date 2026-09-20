"""Compare flat RequestIntent with a minimal WorkUnit/WorkRelation projection.

This is an evaluation-only #287 diagnostic.  It deliberately does not run
Tool Routing, Retrieval, Work Analysis, Planning, or any Provider operation.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from argparse import ArgumentParser
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from evaluation.dataset_v8 import load_cases, normalized_sha256

from google_work_agent.adapters.llm.ollama.transport import OllamaHTTPClient
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.runtime_selection import OLLAMA_FIXED_LOOPBACK_ENDPOINT
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)

MODEL_ID = "qwen3.5:9b"
EXPECTED_MODEL_DIGEST = (
    "6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7"
)
DATASET = Path("evaluation/datasets/e2e/canonical_cases_v8.jsonl")
CANDIDATE_PROMPT = Path(
    "evaluation/prompt_candidates/ru-requested-work-decomposition-v1/sources/"
    "request_understanding.decompose_requested_work.md"
)


@dataclass(frozen=True, slots=True)
class DecompositionExpectation:
    expected_units: tuple[str, ...]
    expected_relations: tuple[tuple[int, int], ...] = ()


# Preregistered semantic projection from Canonical Core.  The descriptions are
# grader-only expectations and are never sent to the candidate model.
CORE24_EXPECTATIONS: dict[str, DecompositionExpectation] = {
    "CASE-CORE-001": DecompositionExpectation(
        ("선택한 Boreal 메일에서 최종 서명 기한과 법무 담당을 답한다",)
    ),
    "CASE-CORE-006": DecompositionExpectation(
        ("Atlas 최종 출고일과 담당자를 찾아 답한다",)
    ),
    "CASE-CORE-009": DecompositionExpectation(
        ("메일과 작업을 근거로 Kestrel 공급 지연의 현재 상태를 답한다",)
    ),
    "CASE-CORE-010": DecompositionExpectation(
        ("Harbor 메일의 실제 업무만 안전하게 요약한다",)
    ),
    "CASE-CORE-011": DecompositionExpectation(
        ("Atlas 작업과 슬롯을 반영한 현재 준비 상태 회신 초안을 만든다",)
    ),
    "CASE-CORE-012": DecompositionExpectation(
        ("Echo 작업과 오늘 일정을 반영한 진행 상황 메일 초안을 만든다",)
    ),
    "CASE-CORE-019": DecompositionExpectation(
        (
            "다음 주 화요일 오후에 Fjord 고객 워크숍 일정을 잡는다",
            "그 워크숍 일정의 고객 안내 메일 초안을 만든다",
        ),
        ((0, 1),),
    ),
    "CASE-CORE-020": DecompositionExpectation(
        ("Ion 작업과 이번 주 일정을 반영한 준비 상태 메일 초안을 만든다",)
    ),
    "CASE-CORE-021": DecompositionExpectation(
        ("Atlas 메일과 작업을 반영해 지정 시각의 내부 점검 일정을 만든다",)
    ),
    "CASE-CORE-026": DecompositionExpectation(
        ("Atlas 자료에서 가능한 시간을 골라 내부 점검 일정을 제안한다",)
    ),
    "CASE-CORE-027": DecompositionExpectation(
        ("Echo 마감 전 오늘 한 시간의 가용 여부만 답하고 일정은 만들지 않는다",)
    ),
    "CASE-CORE-028": DecompositionExpectation(
        ("Kestrel 자료를 반영해 내일 가능한 30분 슬롯에 점검 일정을 잡는다",)
    ),
    "CASE-CORE-031": DecompositionExpectation(
        ("Atlas 자료를 반영해 지정 기한의 인쇄소 인계 확인 작업을 만든다",)
    ),
    "CASE-CORE-036": DecompositionExpectation(
        ("Ion 자료를 반영해 다음 주 월요일까지 온보딩 체크리스트를 만든다",)
    ),
    "CASE-CORE-037": DecompositionExpectation(
        ("Atlas 자료를 반영해 기존 QR 작업 기한을 8월 15일로 변경한다",)
    ),
    "CASE-CORE-040": DecompositionExpectation(
        ("Kestrel 자료를 반영해 기존 작업 메모에 선적 2일 지연을 추가한다",)
    ),
    "CASE-CORE-041": DecompositionExpectation(
        ("Atlas 메일·작업·슬롯을 대조해 준비 순서 위험을 답한다",)
    ),
    "CASE-CORE-046": DecompositionExpectation(
        (
            "Atlas 자료를 반영해 지정 시각의 점검 일정을 만든다",
            "그 점검 일정의 안내 메일 초안을 만든다",
        ),
        ((0, 1),),
    ),
    "CASE-CORE-048": DecompositionExpectation(
        (
            "기존 Kestrel 작업 메모에 2일 지연을 추가한다",
            "지정 시각의 Kestrel 점검 일정을 만든다",
            "Kestrel 회신 메일 초안을 만든다",
        )
    ),
    "CASE-CORE-050": DecompositionExpectation(
        (
            "Echo 최종 의견 전달 작업을 지정 기한까지 만든다",
            "지정 시각의 Echo 정리 일정을 만든다",
            "Echo 메일 초안을 만든다",
        )
    ),
    "CASE-CORE-051": DecompositionExpectation(
        ("박민수 메일을 근거로 다음 주 웨비나 검토 회의 준비 내용을 정리한다",)
    ),
    "CASE-CORE-054": DecompositionExpectation(
        (
            "Grove 결과를 정리한다",
            "정리한 Grove 결과를 반영한 답장 초안을 만든다",
        ),
        ((0, 1),),
    ),
    "CASE-CORE-056": DecompositionExpectation(
        (
            "Harbor 보안 사고 메일을 요약한다",
            "사용자가 해야 할 대응만 정리한다",
        )
    ),
    "CASE-CORE-059": DecompositionExpectation(
        (
            "Quartz 납품 일정이 확인됐는지 확인한다",
            "확인 결과를 바탕으로 답장을 보낸다",
        ),
        ((0, 1),),
    ),
}


DECOMPOSITION_SCHEMA = OutputSchemaDefinition(
    schema_version="requested-work-decomposition-v1-eval",
    json_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["work_units", "work_relations"],
        "properties": {
            "work_units": {
                "type": "array",
                "minItems": 1,
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["unit_id", "objective"],
                    "properties": {
                        "unit_id": {"type": "string", "minLength": 1},
                        "objective": {"type": "string", "minLength": 1},
                    },
                },
            },
            "work_relations": {
                "type": "array",
                "maxItems": 12,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["source_unit_id", "target_unit_id", "kind"],
                    "properties": {
                        "source_unit_id": {"type": "string", "minLength": 1},
                        "target_unit_id": {"type": "string", "minLength": 1},
                        "kind": {"const": "PROVIDES_INPUT_TO"},
                    },
                },
            },
        },
    },
)


def main() -> None:
    parser = ArgumentParser()
    parser.add_argument("--result-path", type=Path, required=True)
    parser.add_argument("--case", action="append")
    parser.add_argument("--sampling-seed", type=int, default=20260920)
    parser.add_argument("--candidate-path", type=Path, default=CANDIDATE_PROMPT)
    parser.add_argument("--candidate-id", default="ru-requested-work-decomposition-v1")
    arguments = parser.parse_args()
    if arguments.result_path.exists():
        raise ValueError("result path already exists; preserve every prior trial")

    case_ids = arguments.case or list(CORE24_EXPECTATIONS)
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("duplicate Case ID")
    if any(case_id not in CORE24_EXPECTATIONS for case_id in case_ids):
        raise ValueError("requested Case is not in the preregistered Core projection")

    cases = load_cases()
    prompt_bytes = arguments.candidate_path.read_bytes()
    prompt_text = prompt_bytes.decode("utf-8").rstrip()
    prompt_hash = hashlib.sha256(prompt_bytes).hexdigest()
    expectation_hash = _sha256(
        {
            case_id: {
                "expected_units": expectation.expected_units,
                "expected_relations": expectation.expected_relations,
            }
            for case_id, expectation in CORE24_EXPECTATIONS.items()
        }
    )
    client = OllamaHTTPClient()
    model_digest = next(
        (model.digest for model in client.list_installed_models() if model.model_id == MODEL_ID),
        None,
    )
    if model_digest != EXPECTED_MODEL_DIGEST:
        raise ValueError("local model digest differs from the preregistered comparison")

    prompt_ref = PromptReference(
        prompt_bundle_version="evaluation-only",
        prompt_id="request_understanding.decompose_requested_work",
        prompt_version="requested-work-decomposition-v1-eval",
        content_hash=prompt_hash,
        agent_role="REQUEST_UNDERSTANDING",
        subgraph_name="request_understanding",
        node_name="decompose_requested_work",
        node_state="INITIAL",
        purpose="EVALUATION_ONLY_REQUESTED_WORK_DECOMPOSITION",
        input_schema_version="user-request-only-v1",
        output_schema_version=DECOMPOSITION_SCHEMA.schema_version,
    )
    result: dict[str, object] = {
        "binding": {
            "product_sha": _git_head(),
            "dataset_sha256": normalized_sha256(DATASET),
            "expectation_sha256": expectation_hash,
            "prompt_sha256": prompt_hash,
            "candidate_id": arguments.candidate_id,
            "model_id": MODEL_ID,
            "model_digest": model_digest,
            "temperature": 0.0,
            "seed": arguments.sampling_seed,
            "scope": "EVALUATION_ONLY_RU_REQUESTED_WORK_DECOMPOSITION",
            "candidate_calls_per_case": 1,
            "provider_read_count": 0,
            "provider_write_count": 0,
        },
        "summary": {
            "case_count": len(case_ids),
            "baseline_structure_matches": 0,
            "candidate_structure_matches": 0,
            "schema_valid": 0,
        },
        "cases": [],
    }
    _write(arguments.result_path, result)
    records = cast(list[dict[str, object]], result["cases"])
    summary = cast(dict[str, object], result["summary"])

    for case_id in case_ids:
        raw = cases[case_id].raw
        if raw.get("split") != "CORE":
            raise ValueError(f"{case_id}: Holdout/Stress is not allowed for tuning")
        expectation = CORE24_EXPECTATIONS[case_id]
        request = str(raw["canonical_user_prompt"])
        baseline_units = 1
        baseline_relations = 0
        baseline_matches = (
            len(expectation.expected_units) == baseline_units
            and len(expectation.expected_relations) == baseline_relations
        )

        started = time.perf_counter()
        response = client.invoke_structured(
            endpoint=OLLAMA_FIXED_LOOPBACK_ENDPOINT,
            model_id=MODEL_ID,
            prompt_ref=prompt_ref,
            prompt_input={"user_request": request},
            output_schema=DECOMPOSITION_SCHEMA,
            timeout_seconds=180,
            instruction_text=prompt_text,
            sampling_temperature=0.0,
            sampling_seed=arguments.sampling_seed,
        )
        candidate = json.loads(cast(str, response.content))
        validation_errors = [
            *validate_output_schema(candidate, DECOMPOSITION_SCHEMA.json_schema),
            *_validate_decomposition(candidate),
        ]
        units = candidate.get("work_units", []) if isinstance(candidate, dict) else []
        relations = (
            candidate.get("work_relations", []) if isinstance(candidate, dict) else []
        )
        structure_matches = (
            not validation_errors
            and len(units) == len(expectation.expected_units)
            and len(relations) == len(expectation.expected_relations)
        )
        record = {
            "case_id": case_id,
            "category": raw["category"],
            "user_request": request,
            "expectation": {
                "units": list(expectation.expected_units),
                "relations_by_unit_index": [list(item) for item in expectation.expected_relations],
            },
            "baseline": {
                "representation": "FLAT_REQUEST_INTENT_V2",
                "unit_count": baseline_units,
                "relation_count": baseline_relations,
                "structure_matches": baseline_matches,
            },
            "candidate": candidate,
            "candidate_schema_errors": validation_errors,
            "candidate_structure_matches": structure_matches,
            "candidate_input_tokens": response.input_tokens,
            "candidate_output_tokens": response.output_tokens,
            "candidate_latency_ms": response.latency_ms,
            "wall_ms": int((time.perf_counter() - started) * 1_000),
        }
        records.append(record)
        summary["baseline_structure_matches"] = cast(
            int, summary["baseline_structure_matches"]
        ) + int(baseline_matches)
        summary["candidate_structure_matches"] = cast(
            int, summary["candidate_structure_matches"]
        ) + int(structure_matches)
        summary["schema_valid"] = cast(int, summary["schema_valid"]) + int(
            not validation_errors
        )
        _write(arguments.result_path, result)
        print(
            json.dumps(
                {
                    "case_id": case_id,
                    "expected_units": len(expectation.expected_units),
                    "actual_units": len(units),
                    "expected_relations": len(expectation.expected_relations),
                    "actual_relations": len(relations),
                    "structure_matches": structure_matches,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )


def _validate_decomposition(value: object) -> list[str]:
    if not isinstance(value, dict):
        return ["candidate is not an object"]
    units = value.get("work_units")
    relations = value.get("work_relations")
    if not isinstance(units, list) or not isinstance(relations, list):
        return []
    unit_ids = [
        str(unit.get("unit_id"))
        for unit in units
        if isinstance(unit, dict) and isinstance(unit.get("unit_id"), str)
    ]
    errors: list[str] = []
    if len(unit_ids) != len(set(unit_ids)):
        errors.append("work unit ids must be unique")
    known_ids = set(unit_ids)
    edges: set[tuple[str, str]] = set()
    for index, relation in enumerate(relations):
        if not isinstance(relation, dict):
            continue
        source = relation.get("source_unit_id")
        target = relation.get("target_unit_id")
        edge = (str(source), str(target))
        if source not in known_ids or target not in known_ids or source == target:
            errors.append(f"$.work_relations[{index}] has invalid endpoints")
        if edge in edges:
            errors.append(f"$.work_relations[{index}] duplicates an existing relation")
        edges.add(edge)
    if _has_cycle(unit_ids, edges):
        errors.append("work relations must be acyclic")
    return errors


def _has_cycle(unit_ids: list[str], edges: set[tuple[str, str]]) -> bool:
    outgoing: dict[str, set[str]] = {unit_id: set() for unit_id in unit_ids}
    indegree = {unit_id: 0 for unit_id in unit_ids}
    for source, target in edges:
        if source not in outgoing or target not in indegree:
            continue
        if target not in outgoing[source]:
            outgoing[source].add(target)
            indegree[target] += 1
    ready = [unit_id for unit_id, degree in indegree.items() if degree == 0]
    visited = 0
    while ready:
        current = ready.pop()
        visited += 1
        for target in outgoing[current]:
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
    return visited != len(unit_ids)


def _sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


if __name__ == "__main__":
    main()
