"""Measure verified terminal-response prose through the production Ollama runtime.

The fixtures contain only synthetic, already-verified action projections.  This
runner does not construct a Product Graph, connector, approval, or provider
WRITE capability; Graph/commit integration is covered by the production-graph
tests.  JSON lines are written to stdout for a human-reviewed evaluation
artifact.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import fields
from io import TextIOWrapper
from pathlib import Path
from tempfile import mkdtemp
from typing import Literal, cast
from uuid import uuid4

from google_work_agent.adapters.llm.ollama.transport import OllamaHTTPClient
from google_work_agent.adapters.llm.runtime.llm_credential_router import (
    SessionMemorySecretStore,
)
from google_work_agent.api.composition import ProductionRuntimeConfig, build_production_runtime
from google_work_agent.application.prompt_runtime.prompt_registry import (
    DEVELOPMENT_SMOKE,
    default_prompt_manifest_path,
    load_prompt_reference,
)
from google_work_agent.application.use_cases.run.account_provider_dispatch import (
    provider_dispatch_budget_scope,
    provider_dispatch_execution_scope,
)
from google_work_agent.application.use_cases.run.build_terminal_message import (
    TerminalAssistantMessageInputV1,
)
from google_work_agent.application.use_cases.run.compose_terminal_response import (
    ComposeTerminalResponseCommandV1,
    ComposeTerminalResponseHandler,
    build_terminal_response_input,
)
from google_work_agent.application.use_cases.run.guard_run_budget import (
    build_default_run_budget,
)
from google_work_agent.application.use_cases.setting.update_settings import (
    UpdateSettingsCommand,
)
from google_work_agent.ports.system.settings_port import SettingsPatchV1

MODEL_IDS = ("qwen3.5:9b", "qwen3.5:4b")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--code-sha", required=True)
    parser.add_argument("--model", choices=MODEL_IDS, default="qwen3.5:9b")
    parser.add_argument("--trials", type=int, default=2)
    parser.add_argument("--sampling-temperature", type=float, default=0.2)
    parser.add_argument("--sampling-seed", type=int, default=1729)
    arguments = parser.parse_args()
    if arguments.trials != 2:
        raise ValueError("the fixed terminal-response evaluation requires exactly two trials")
    _measure(
        code_sha=arguments.code_sha,
        model=cast(Literal["qwen3.5:9b", "qwen3.5:4b"], arguments.model),
        trials=arguments.trials,
        sampling_temperature=arguments.sampling_temperature,
        sampling_seed=arguments.sampling_seed,
    )


def _measure(
    *,
    code_sha: str,
    model: Literal["qwen3.5:9b", "qwen3.5:4b"],
    trials: int,
    sampling_temperature: float,
    sampling_seed: int,
) -> None:
    runtime_root = mkdtemp(prefix="gwa-terminal-response-")
    prompt_manifest_path = default_prompt_manifest_path()
    config = ProductionRuntimeConfig.development(
        runtime_root=Path(runtime_root),
        working_directory=Path(__file__).resolve().parents[1],
        mcp_manifest_version="2026-08-07.p0",
        keyring_store=SessionMemorySecretStore(),
        prompt_manifest_path=prompt_manifest_path,
        sampling_temperature=sampling_temperature,
        sampling_seed=sampling_seed,
    )
    container = build_production_runtime(
        **{field.name: getattr(config, field.name) for field in fields(config)},
        bootstrap_secret=uuid4().hex,
        service_instance_id=f"terminal-response-measurement-{uuid4()}",
    )
    try:
        runtime = container.structured_inference_port
        update_settings = container.update_settings_handler
        if runtime is None or update_settings is None:
            raise RuntimeError("production LLM runtime is unavailable")
        # These synthetic node-only calls have no durable Run FK. Provider
        # dispatch accounting remains active through the scoped RunBudget.
        runtime.run_context_provider = lambda: None
        update_settings(
            UpdateSettingsCommand(
                str(uuid4()),
                SettingsPatchV1(
                    schema_version=1,
                    preferred_local_model_id=model,
                    preferred_llm_mode="LOCAL_GPU",
                    external_llm_consent=False,
                ),
            )
        )
        prompt_ref = load_prompt_reference(
            "run.compose_terminal_response",
            manifest_path=prompt_manifest_path,
            execution_scope=DEVELOPMENT_SMOKE,
        )
        installed = {
            item.model_id: item.digest
            for item in OllamaHTTPClient().list_installed_models()
        }
        binding = {
            "record_type": "runtime_binding",
            "code_sha": code_sha,
            "model": model,
            "model_digest": installed.get(model),
            "sampling_temperature": sampling_temperature,
            "sampling_seed": sampling_seed,
            "prompt_id": prompt_ref.prompt_id,
            "prompt_version": prompt_ref.prompt_version,
            "prompt_hash": prompt_ref.content_hash,
            "requested_mode": "LOCAL_GPU",
            "external_llm_consent": False,
            "fixture_set": "terminal-response-fixed-8-v1",
            "trials_per_case": trials,
        }
        print(json.dumps(binding, ensure_ascii=False), flush=True)
        handler = ComposeTerminalResponseHandler(llm_runtime=runtime, prompt_ref=prompt_ref)
        for response_input in _fixtures():
            for trial in range(1, trials + 1):
                run_id = f"terminal-response-{response_input['fixture_id']}-{trial}"
                typed_input = build_terminal_response_input(
                    user_request=cast(str, response_input["user_request"]),
                    result_kind=cast(str, response_input["result_kind"]),
                    actions=response_input["actions"],
                    send_not_dispatched_current_run=cast(
                        bool, response_input["send_not_dispatched_current_run"]
                    ),
                )
                budget = build_default_run_budget(started_at_ms=int(time.time() * 1_000))
                started = time.monotonic()
                with provider_dispatch_execution_scope(
                    run_id=run_id,
                    now_ms=lambda: int(time.time() * 1_000),
                ), provider_dispatch_budget_scope(budget):
                    result = handler(
                        ComposeTerminalResponseCommandV1(
                            schema_version=1,
                            run_id=run_id,
                            requested_mode="LOCAL_GPU",
                            response_input=typed_input,
                            fallback_message=TerminalAssistantMessageInputV1(
                                schema_version=1,
                                result_kind=typed_input.result_kind,
                                content="확인된 실행 결과를 반영했습니다.",
                                reason_codes=[],
                            ),
                        )
                    )
                print(
                    json.dumps(
                        {
                            "record_type": "trial",
                            "fixture_id": response_input["fixture_id"],
                            "case": response_input["case"],
                            "trial": trial,
                            "input_projection": typed_input.to_projection(),
                            "answer": result.terminal_message.content,
                            "result_kind": result.terminal_message.result_kind,
                            "generation_mode": result.generation_mode,
                            "fallback_reason": result.fallback_reason,
                            "provider": result.provider,
                            "model": result.model,
                            "actual_runtime": result.actual_runtime,
                            "provider_dispatches": budget["llm_calls_used"],
                            "input_tokens": result.input_tokens,
                            "output_tokens": result.output_tokens,
                            "provider_latency_ms": result.latency_ms,
                            "response_stage_latency_ms": int(
                                (time.monotonic() - started) * 1_000
                            ),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
    finally:
        for close in reversed(container.shutdown_callbacks):
            close()
        print(
            json.dumps(
                {"record_type": "diagnostic_runtime", "runtime_root": runtime_root},
                ensure_ascii=False,
            ),
            flush=True,
        )


def _fixtures() -> tuple[dict[str, object], ...]:
    return (
        _fixture(
            "TR-01",
            "Draft UPDATE + 현재 Run 미전송",
            "Quartz 납품 회신 검토 초안 끝에 확인 문장을 추가해줘. 보내지는 마.",
            "SUCCESS",
            (
                _action(
                    "gmail_draft",
                    "UPDATE",
                    "VERIFIED",
                    "Quartz 납품 회신 검토",
                    {"subject": "Quartz 납품 회신 검토", "body": "확인 문장을 반영했습니다."},
                ),
            ),
            send_not_dispatched_current_run=True,
        ),
        _fixture(
            "TR-02",
            "Draft CREATE",
            "Atlas 일정 검토 결과를 메일 초안으로 만들어줘. 보내지는 마.",
            "SUCCESS",
            (
                _action(
                    "gmail_draft",
                    "CREATE",
                    "VERIFIED",
                    "Atlas 일정 검토",
                    {
                        "subject": "Atlas 일정 검토",
                        "body": "검토 결과를 정리했습니다.",
                        "to": ["reviewer@example.test"],
                    },
                ),
            ),
            send_not_dispatched_current_run=True,
        ),
        _fixture(
            "TR-03",
            "SEND 검증 + 수신/열람 미확인",
            "검토 완료 메일을 담당자에게 보내줘.",
            "SUCCESS",
            (
                _action(
                    "gmail_message",
                    "SEND",
                    "VERIFIED",
                    "검토 완료 안내",
                    {"subject": "검토 완료 안내", "to": ["owner@example.test"]},
                ),
            ),
        ),
        _fixture(
            "TR-04",
            "Task 예정일과 업무 마감 구분",
            "납품 확인 태스크의 예정일을 9월 18일로 바꿔줘.",
            "SUCCESS",
            (
                _action(
                    "task",
                    "UPDATE",
                    "VERIFIED",
                    "납품 확인",
                    {
                        "title": "납품 확인",
                        "due": "2026-09-18",
                        "status": "needsAction",
                        "notes": "업무 마감은 2026-09-17 17:00입니다.",
                    },
                ),
            ),
        ),
        _fixture(
            "TR-05",
            "Calendar 시간 변경",
            "주간 검토 일정 시간을 9월 21일 오후 2시부터 3시로 변경해줘.",
            "SUCCESS",
            (
                _action(
                    "calendar_event",
                    "UPDATE",
                    "VERIFIED",
                    "주간 검토",
                    {
                        "title": "주간 검토",
                        "start": "2026-09-21T14:00:00+09:00",
                        "end": "2026-09-21T15:00:00+09:00",
                        "timezone": "Asia/Seoul",
                    },
                ),
            ),
        ),
        _fixture(
            "TR-06",
            "일부 VERIFIED + 일부 REJECTED/DEPENDENCY_BLOCKED",
            "검토 일정을 만들고 후속 태스크와 안내 초안도 준비해줘.",
            "PARTIAL",
            (
                _action(
                    "calendar_event",
                    "CREATE",
                    "VERIFIED",
                    "검토 일정",
                    {
                        "title": "검토 일정",
                        "start": "2026-09-22T10:00:00+09:00",
                        "end": "2026-09-22T11:00:00+09:00",
                        "timezone": "Asia/Seoul",
                    },
                ),
                _action("task", "CREATE", "REJECTED", "후속 태스크"),
                _action(
                    "gmail_draft",
                    "CREATE",
                    "DEPENDENCY_BLOCKED",
                    "검토 안내 초안",
                ),
            ),
        ),
        _fixture(
            "TR-07",
            "전부 거절 + 외부 WRITE 0",
            "두 개의 후속 태스크를 만들어줘.",
            "PARTIAL",
            (
                _action("task", "CREATE", "REJECTED", "자료 검토"),
                _action("task", "CREATE", "REJECTED", "담당자 확인"),
            ),
        ),
        _fixture(
            "TR-08",
            "재계획 이전의 실제 effect와 현재 결과 함께 설명",
            "검토 일정을 만든 뒤 안내 초안도 준비해줘.",
            "PARTIAL",
            (
                _action(
                    "calendar_event",
                    "CREATE",
                    "VERIFIED",
                    "검토 일정",
                    {
                        "title": "검토 일정",
                        "start": "2026-09-23T16:00:00+09:00",
                        "end": "2026-09-23T17:00:00+09:00",
                        "timezone": "Asia/Seoul",
                    },
                ),
                _action("gmail_draft", "CREATE", "REJECTED", "검토 안내 초안"),
            ),
            send_not_dispatched_current_run=True,
        ),
    )


def _fixture(
    fixture_id: str,
    case: str,
    user_request: str,
    result_kind: Literal["SUCCESS", "PARTIAL"],
    actions: tuple[dict[str, object], ...],
    *,
    send_not_dispatched_current_run: bool = False,
) -> dict[str, object]:
    return {
        "fixture_id": fixture_id,
        "case": case,
        "user_request": user_request,
        "result_kind": result_kind,
        "actions": actions,
        "send_not_dispatched_current_run": send_not_dispatched_current_run,
    }


def _action(
    resource_type: str,
    effect_type: str,
    status: str,
    target_label: str,
    verification_actual: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "connector_id": "google_workspace",
        "resource_type": resource_type,
        "effect_type": effect_type,
        "status": status,
        "target_display": {"title": target_label},
        "verification_actual": verification_actual,
    }


if __name__ == "__main__":
    if isinstance(sys.stdout, TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
