"""Probe narrow Review responsibilities using frozen inputs and development prompts."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import time
from dataclasses import fields
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from scripts.evaluate_review_reference_time_node import _candidate_manifest

from google_work_agent.adapters.llm.ollama.transport import OllamaHTTPClient
from google_work_agent.adapters.llm.runtime.llm_credential_router import (
    SessionMemorySecretStore,
)
from google_work_agent.api.composition import ProductionRuntimeConfig, build_production_runtime
from google_work_agent.application.agents.project_run_reference_time import (
    project_run_reference_time,
)
from google_work_agent.application.agents.review.contracts.review_findings import (
    review_inspector_output_schema,
    validate_review_inspector_result,
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
from google_work_agent.application.use_cases.setting.update_settings import (
    UpdateSettingsCommand,
)
from google_work_agent.ports.system.settings_port import SettingsPatchV1

PROMPT_ID = "review.inspect_goal_and_evidence"
MODEL_ID = "qwen3.5:9b"
GOAL_SOURCE = """# 책임
실행 전 제안 planning_result가 현재 request_intent 및 명시된 사용자 Preview 수정과
일치하는지만 검사한다. 아직 실행되지 않았다는 사실은 결함이 아니다. 상대 날짜는
제공된 current-Run run_reference_time을 기준으로 대조한다. 이 호출에는 외부
자료가 없으며 외부 근거의 존재·부족을 판단하지 않는다.

# 출력
요청과 제안의 대상·효과·내용·날짜·시간·금지 조건이 다르면 ISSUE, 현재 입력으로
확정할 수 없는 사용자 선택만 CONFIRMATION이다. 외부 사실 부족 EVIDENCE_GAP를
생성하지 않는다. 문제가 없으면 findings=[]이다. supplied output schema의
dimension과 findings를 JSON 객체 하나로 반환한다. 설명은 자연스러운 한국어다.
"""
EVIDENCE_SOURCE = """# 책임
실행 전 제안 planning_result에 필요한 외부 사실이 supplied evidence와 optional
work_analysis에 실제로 있는지, 근거에 반하는 주장이나 필요한 내용 누락이 있는지
검사한다. request_intent는 사용자 요구이며 Evidence 내용은 외부 사실이다.
자료의 수신·수정 시각은 해당 Resource의 metadata이지 사용자 요청 기준시각이나
본문에서 언급한 업무일이 아니다. 실행·승인·검증 결과는 아직 없는 것이 정상이다.

# 출력
필요한 외부 정보가 실제로 없다면 EVIDENCE_GAP, 이미 제공된 근거를 Plan이 잘못
사용하거나 빠뜨렸다면 ISSUE다. 사용자에게만 물을 수 있는 미확정 선택은
CONFIRMATION이다. 결함이 없으면 findings=[]이다. supplied output schema의
dimension과 findings를 JSON 객체 하나로 반환한다. 설명은 자연스러운 한국어다.
"""


def _bundle(root: Path, source: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = _candidate_manifest(root, optional_field="run_reference_time")
    path = manifest_path.parent / "sources" / f"{PROMPT_ID}.md"
    path.write_text(source, encoding="utf-8")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = next(item for item in manifest["slots"] if item["prompt_slot_id"] == PROMPT_ID)
    entry["content_hash"] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    load_prompt_reference(PROMPT_ID, manifest_path, execution_scope=DEVELOPMENT_SMOKE)
    return manifest_path


def _runtime(root: Path, manifest_path: Path) -> Any:
    config = ProductionRuntimeConfig.development(
        runtime_root=root,
        working_directory=Path(__file__).resolve().parents[1],
        mcp_manifest_version="2026-08-07.p0",
        keyring_store=SessionMemorySecretStore(),
        prompt_manifest_path=manifest_path,
        sampling_temperature=0.0,
        sampling_seed=1729,
    )
    container = build_production_runtime(
        **{item.name: getattr(config, item.name) for item in fields(config)},
        bootstrap_secret=uuid4().hex,
        service_instance_id=f"review-decomposition-{uuid4()}",
    )
    runtime = container.structured_inference_port
    settings = container.update_settings_handler
    if runtime is None or settings is None:
        raise RuntimeError("local inference runtime is unavailable")
    runtime.run_context_provider = lambda: None
    settings(
        UpdateSettingsCommand(
            str(uuid4()),
            SettingsPatchV1(
                schema_version=1,
                preferred_local_model_id=MODEL_ID,
                preferred_llm_mode="LOCAL_GPU",
                external_llm_consent=False,
            ),
        )
    )
    return runtime


def _goal_input(original: dict[str, object], started_at_ms: int) -> dict[str, object]:
    reference = project_run_reference_time({"started_at_ms": started_at_ms})
    if reference is None:
        raise ValueError("current-Run reference time is unavailable")
    result = {
        "request_intent": original["request_intent"],
        "planning_result": original["planning_result"],
        "evidence": [],
        "run_reference_time": reference,
    }
    for field in ("confirmation_response", "user_action_modifications"):
        if field in original:
            result[field] = original[field]
    return result


def _tasks(source: dict[str, object]) -> list[tuple[str, str, dict[str, object], int]]:
    cases = {
        item["label"]: item
        for item in cast(list[dict[str, object]], source["cases"])
    }
    labels_by_arm = {
        "CASE-CORE-023": ("GOAL", "EVIDENCE"),
        "CASE-CORE-028": ("GOAL", "EVIDENCE"),
        "WRONG_ACTION_DATE": ("GOAL",),
        "USER_PREVIEW_EDIT": ("GOAL",),
        "MISSING_EXTERNAL_MAIL": ("EVIDENCE",),
        "FORBIDDEN_ATTENDEE": ("GOAL",),
    }
    tasks: list[tuple[str, str, dict[str, object], int]] = []
    for label, arms in labels_by_arm.items():
        item = cases[label]
        original = cast(dict[str, object], item["baseline_input"])
        started_at_ms = cast(int, item["started_at_ms"])
        for arm in arms:
            tasks.append(
                (
                    label,
                    arm,
                    _goal_input(original, started_at_ms) if arm == "GOAL" else original,
                    started_at_ms,
                )
            )
    return tasks


def evaluate(source_path: Path, output_path: Path) -> dict[str, object]:
    source = json.loads(source_path.read_text(encoding="utf-8"))
    if source["binding"]["model_id"] != MODEL_ID:
        raise ValueError("saved model differs from fixed comparison model")
    installed = {
        item.model_id: item.digest for item in OllamaHTTPClient().list_installed_models()
    }
    if installed.get(MODEL_ID) != source["binding"]["model_digest"]:
        raise ValueError("installed model digest differs from fixed comparison model")
    tasks = _tasks(source)
    if len(tasks) != 8:
        raise ValueError("predeclared diagnostic call count changed")
    root = Path(tempfile.mkdtemp(prefix="gwa-review-decomposition-"))
    arms: dict[str, tuple[Any, Path]] = {}
    for arm, text in (("GOAL", GOAL_SOURCE), ("EVIDENCE", EVIDENCE_SOURCE)):
        manifest_path = _bundle(root / f"{arm.lower()}-bundle", text)
        arms[arm] = (_runtime(root / arm.lower(), manifest_path), manifest_path)
    refs = {
        arm: load_prompt_reference(
            PROMPT_ID, manifest_path, execution_scope=DEVELOPMENT_SMOKE
        )
        for arm, (_runtime_instance, manifest_path) in arms.items()
    }
    schema = review_inspector_output_schema(PROMPT_ID)
    result: dict[str, object] = {
        "binding": {
            "source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
            "baseline_sha": "2523f699",
            "model_id": MODEL_ID,
            "model_digest": installed[MODEL_ID],
            "sampling_temperature": 0.0,
            "sampling_seed": 1729,
            "goal_prompt_sha256": refs["GOAL"].content_hash,
            "evidence_prompt_sha256": refs["EVIDENCE"].content_hash,
            "new_call_limit": 8,
            "provider_read_enabled": False,
            "provider_write_enabled": False,
        },
        "trials": [],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    for label, arm, prompt_input, started_at_ms in tasks:
        runtime = arms[arm][0]
        reference = refs[arm]
        started = time.perf_counter()
        trial: dict[str, object] = {
            "label": label,
            "arm": arm,
            "input_sha256": hashlib.sha256(
                json.dumps(prompt_input, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest(),
            "prompt_input": prompt_input,
        }
        try:
            with (
                provider_dispatch_execution_scope(
                    run_id=f"review-decomposition-{label}-{arm}",
                    now_ms=lambda started_at_ms=started_at_ms, started=started: (
                        started_at_ms + int((time.perf_counter() - started) * 1_000)
                    ),
                ),
                provider_dispatch_budget_scope(
                    build_default_run_budget(started_at_ms=started_at_ms)
                ),
            ):
                inference = runtime.infer("LOCAL_GPU", reference, prompt_input, schema)
            validated = validate_review_inspector_result(
                inference.structured_output, expected_dimension=PROMPT_ID
            )
            trial.update(
                {
                    "outcome": "COMPLETED",
                    "structured_output": validated,
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
                }
            )
        trial["duration_ms"] = int((time.perf_counter() - started) * 1_000)
        cast(list[dict[str, object]], result["trials"]).append(trial)
        output_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(label, arm, trial["outcome"], trial["duration_ms"], flush=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evaluate(args.input, args.output)


if __name__ == "__main__":
    main()
