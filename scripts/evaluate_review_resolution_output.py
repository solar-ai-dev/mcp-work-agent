"""Probe a separated prior-issue assessment and fresh-finding RECHECK output."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from scripts.evaluate_review_decomposition_node import MODEL_ID, _runtime
from scripts.evaluate_review_proposal_transition import _fingerprint, _proposal_transition
from scripts.evaluate_review_reference_time_node import _candidate_manifest

from google_work_agent.adapters.llm.ollama.transport import OllamaHTTPClient
from google_work_agent.application.agents.review.contracts.review_findings import (
    review_recheck_output_schema,
)
from google_work_agent.application.prompt_runtime.prompt_registry import (
    DEVELOPMENT_SMOKE,
    load_prompt_reference,
)
from google_work_agent.application.use_cases.run.account_provider_dispatch import (
    provider_dispatch_budget_scope,
    provider_dispatch_execution_scope,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.llm.structured_inference_contracts import OutputSchemaDefinition

PROMPT_ID = "review.recheck_affected_dimensions"
ORDER = (
    ("WRONG_DATE_023", "corrected"),
    ("FORBIDDEN_ATTENDEE_023", "corrected"),
    ("WRONG_DATE_023", "unresolved"),
    ("FORBIDDEN_ATTENDEE_023", "unresolved"),
)
SOURCE = """# 역할과 권위

실행 전 수정 제안 planning_result를 현재 request_intent와 대조한다. supplied
evidence, tool_route_plan, work_analysis, policy_summary는 실제 제공된 범위에서만
사용한다. proposal_transition은 같은 route의 수정 전후 제안 관계와 과거
Review issue를 보여주는 검토 이력이다. 과거 issue는 사용자 요구나 현재
결함의 증거가 아니다. 이전 Action ID와 현재 Action ID는 서로 다를 수 있다.

# 두 판단을 분리

먼저 historical_review_issues를 index 순서로 현재 제안에 대해 평가한다.
수정으로 문제가 없어졌으면 RESOLVED, 같은 문제가 남았으면 UNRESOLVED,
현재 입력만으로 판별할 수 없으면 UNCERTAIN이다. 각각 현재 Plan·요구·근거에서
관측되는 짧은 이유를 적는다. 이 상태는 routing disposition이 아니다.

다음으로 현재 제안에 실제 남아 있는 결함만 findings에 새로 쓴다.
해결된 이전 issue를 옮겨 쓰거나, 아직 Provider WRITE 전인 제안에 실제
생성·승인·실행·검증 결과를 요구하지 않는다. 사용자 요구가 이미 명확하면
재확인하지 않는다. 요청 밖의 완벽한 상세나 모든 외부 자료를 설명에
복사하는 것을 요구하지 않는다. 실제 필요한 근거가 없는 경우만
EVIDENCE_GAP, 근거는 있는데 Plan이 잘못 사용한 경우는 ISSUE,
사용자만 결정할 미확정 선택은 CONFIRMATION이다. 영향을 받은 dimension만
검토하며 다른 조건·금지·Evidence는 보존한다.

# 출력

supplied schema의 issue_assessments와 findings를 포함한 JSON 객체 하나만
반환한다. 모든 문제가 해결되고 새 결함이 없으면 findings=[]이다.
finding description과 required_information은 자연스러운 한국어다.
"""


def _bundle(root: Path) -> Path:
    manifest_path = _candidate_manifest(
        root, optional_field="proposal_transition", prompt_id=PROMPT_ID
    )
    source_path = manifest_path.parent / "sources" / f"{PROMPT_ID}.md"
    source_path.write_text(SOURCE, encoding="utf-8")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = next(item for item in manifest["slots"] if item["prompt_slot_id"] == PROMPT_ID)
    entry["content_hash"] = hashlib.sha256(source_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return manifest_path


def _schema(dimensions: tuple[str, ...], issue_count: int) -> OutputSchemaDefinition:
    original = review_recheck_output_schema(dimensions).json_schema
    return OutputSchemaDefinition(
        schema_version="review-recheck-resolution-result-v2",
        json_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["schema_version", "affected_dimensions", "issue_assessments", "findings"],
            "properties": {
                "schema_version": {"const": 2},
                "affected_dimensions": original["properties"]["affected_dimensions"],
                "issue_assessments": {
                    "type": "array",
                    "minItems": issue_count,
                    "maxItems": issue_count,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["issue_index", "state", "current_reason"],
                        "properties": {
                            "issue_index": {
                                "type": "integer",
                                "minimum": 0,
                                "maximum": issue_count - 1,
                            },
                            "state": {"enum": ["RESOLVED", "UNRESOLVED", "UNCERTAIN"]},
                            "current_reason": {"type": "string", "minLength": 1},
                        },
                    },
                },
                "findings": original["properties"]["findings"],
            },
        },
    )


def evaluate(cycle_path: Path, connected_path: Path, output_path: Path) -> None:
    cycle_bytes = cycle_path.read_bytes()
    connected_bytes = connected_path.read_bytes()
    cycle = json.loads(cycle_bytes)
    connected = json.loads(connected_bytes)
    installed = {item.model_id: item.digest for item in OllamaHTTPClient().list_installed_models()}
    if installed.get(MODEL_ID) != cycle["binding"]["model_digest"]:
        raise ValueError("installed model differs from frozen Review cycle")
    cases = {item["label"]: item for item in cycle["cases"]}
    upstream = {item["case_id"]: item for item in connected["cases"]}
    root = Path(tempfile.mkdtemp(prefix="gwa-review-resolution-output-"))
    manifest = _bundle(root)
    runtime = _runtime(root / "runtime", manifest)
    reference = load_prompt_reference(PROMPT_ID, manifest, execution_scope=DEVELOPMENT_SMOKE)
    result: dict[str, Any] = {
        "binding": {
            "baseline_sha": "53842ae6",
            "cycle_sha256": hashlib.sha256(cycle_bytes).hexdigest(),
            "connected_sha256": hashlib.sha256(connected_bytes).hexdigest(),
            "model_id": MODEL_ID,
            "model_digest": installed[MODEL_ID],
            "sampling_temperature": 0.0,
            "sampling_seed": 1729,
            "prompt_hash": reference.content_hash,
            "output_schema": "review-recheck-resolution-result-v2",
            "call_limit": len(ORDER),
            "provider_read_enabled": False,
            "provider_write_enabled": False,
        },
        "trials": [],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    for label, status in ORDER:
        case = cases[label]
        source = upstream[case["source_case"]]
        started_at_ms = source["reference_started_at_ms"]
        prompt_input = deepcopy(
            next(
                item["prompt_input"]
                for item in case["stages"][-1]["inference_details"]
                if item["prompt_id"] == PROMPT_ID
            )
        )
        if status == "unresolved":
            prompt_input["planning_result"] = deepcopy(case["plan_before"])
        prompt_input["proposal_transition"] = _proposal_transition(
            case, prompt_input["planning_result"]
        )
        started = time.perf_counter()
        trial: dict[str, Any] = {
            "label": label,
            "status": status,
            "input_sha256": _fingerprint(prompt_input),
            "prompt_input": prompt_input,
        }
        try:
            with (
                provider_dispatch_execution_scope(
                    run_id=f"review-resolution-{label}-{status}",
                    now_ms=lambda base=started_at_ms, start=started: (
                        base + int((time.perf_counter() - start) * 1_000)
                    ),
                ),
                provider_dispatch_budget_scope(
                    build_default_run_budget(started_at_ms=started_at_ms)
                ),
            ):
                inference = runtime.infer(
                    "LOCAL_GPU",
                    reference,
                    prompt_input,
                    _schema(
                        tuple(prompt_input["affected_dimensions"]),
                        len(prompt_input["proposal_transition"]["historical_review_issues"]),
                    ),
                )
            trial.update(
                {
                    "outcome": "COMPLETED",
                    "structured_output": inference.structured_output,
                    "input_tokens": inference.input_tokens,
                    "output_tokens": inference.output_tokens,
                    "provider_latency_ms": inference.latency_ms,
                }
            )
        except Exception as error:
            code = getattr(error, "code", None)
            trial.update(
                {
                    "outcome": "FAILED",
                    "error_type": type(error).__name__,
                    "error_code": getattr(code, "value", None),
                    "message": str(error),
                }
            )
        trial["duration_ms"] = int((time.perf_counter() - started) * 1_000)
        result["trials"].append(trial)
        output_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(label, status, trial["outcome"], flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycle", type=Path, required=True)
    parser.add_argument("--connected", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evaluate(args.cycle, args.connected, args.output)


if __name__ == "__main__":
    main()
