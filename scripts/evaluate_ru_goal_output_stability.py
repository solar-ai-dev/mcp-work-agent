"""Measure goal-to-output stability on fixed Canonical Core projections."""

from __future__ import annotations

import json
import tempfile
import time
from argparse import ArgumentParser
from dataclasses import fields
from pathlib import Path
from typing import cast
from uuid import uuid4

from scripts.evaluate_ru_output_input_projection import (
    EXPECTED_OUTPUTS,
    _output_pairs,
    _request,
)
from scripts.evaluate_ru_source_status_prompt import (
    DATASET,
    EXPECTED_MODEL_DIGEST,
    MODEL_ID,
    _git_head,
    _RecordingInferencePort,
    _sha256,
    _write,
)

from evaluation.dataset_v8 import load_cases, normalized_sha256
from google_work_agent.adapters.llm.ollama.transport import OllamaHTTPClient
from google_work_agent.adapters.llm.runtime.llm_credential_router import (
    SessionMemorySecretStore,
)
from google_work_agent.api.composition import ProductionRuntimeConfig, build_production_runtime
from google_work_agent.application.agents.request_understanding import (
    identify_effect_prohibitions as prohibition_ops,
)
from google_work_agent.application.agents.request_understanding import identify_goal as goal_ops
from google_work_agent.application.agents.request_understanding import (
    identify_output_responsibilities as output_ops,
)
from google_work_agent.application.agents.request_understanding.contracts import (
    request_goal_candidate_schema,
)
from google_work_agent.application.prompt_runtime.prompt_registry import (
    DEVELOPMENT_SMOKE,
    default_prompt_manifest_path,
    load_prompt_reference,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_development_tool_registry,
)
from google_work_agent.application.use_cases.run.account_provider_dispatch import (
    provider_dispatch_budget_scope,
    provider_dispatch_execution_scope,
)
from google_work_agent.application.use_cases.run.guard_run_budget import (
    build_default_run_budget,
)
from google_work_agent.application.use_cases.setting.update_settings import (
    UpdateSettingsCommand,
)
from google_work_agent.ports.system.settings_port import SettingsPatchV1


def main() -> None:
    parser = ArgumentParser()
    parser.add_argument("--result-path", type=Path, required=True)
    parser.add_argument("--case", action="append", required=True)
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--sampling-seed", type=int, default=20260914)
    arguments = parser.parse_args()
    if arguments.result_path.exists():
        raise ValueError("result path already exists; preserve every prior trial")
    if arguments.trials < 2:
        raise ValueError("stability measurement requires at least two trials")
    if any(case_id not in EXPECTED_OUTPUTS for case_id in arguments.case):
        raise ValueError("requested Case has no preregistered output expectation")

    cases = load_cases()
    if any(cases[case_id].raw.get("split") != "CORE" for case_id in arguments.case):
        raise ValueError("this stability diagnostic accepts Canonical Core only")
    requests = {case_id: _request(case_id, cases[case_id].raw) for case_id in arguments.case}
    prompt_inputs = {
        case_id: goal_ops._prompt_input(request=request, confirmation_response=None)
        for case_id, request in requests.items()
    }

    manifest_path = default_prompt_manifest_path()
    refs = {
        prompt_id: load_prompt_reference(
            prompt_id,
            manifest_path,
            execution_scope=DEVELOPMENT_SMOKE,
        )
        for prompt_id in (
            "request_understanding.identify_goal",
            "request_understanding.identify_effect_prohibitions",
            "request_understanding.identify_output_responsibilities",
        )
    }
    client = OllamaHTTPClient()
    model_digest = next(
        (model.digest for model in client.list_installed_models() if model.model_id == MODEL_ID),
        None,
    )
    if model_digest != EXPECTED_MODEL_DIGEST:
        raise ValueError("local model digest differs from the preregistered comparison")

    config = ProductionRuntimeConfig.development(
        runtime_root=Path(tempfile.mkdtemp(prefix="gwa-ru-stability-")),
        working_directory=Path(__file__).resolve().parents[1],
        mcp_manifest_version="2026-08-07.p0",
        keyring_store=SessionMemorySecretStore(),
        prompt_manifest_path=manifest_path,
        sampling_temperature=0.0,
        sampling_seed=arguments.sampling_seed,
    )
    container = build_production_runtime(
        **{field.name: getattr(config, field.name) for field in fields(config)},
        bootstrap_secret=uuid4().hex,
        service_instance_id=f"ru-stability-{uuid4()}",
    )
    runtime = container.structured_inference_port
    update_settings = container.update_settings_handler
    if runtime is None or update_settings is None:
        raise RuntimeError("production LLM runtime is unavailable")
    runtime.run_context_provider = lambda: None
    update_settings(
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
    recorder = _RecordingInferencePort(runtime)
    output_candidates = output_ops.build_output_responsibility_candidates(
        load_development_tool_registry()
    )
    result: dict[str, object] = {
        "binding": {
            "product_sha": _git_head(),
            "dataset_sha256": normalized_sha256(DATASET),
            "model_id": MODEL_ID,
            "model_digest": model_digest,
            "temperature": 0.0,
            "seed": arguments.sampling_seed,
            "trial_count": arguments.trials,
            "goal_prompt_hash": refs["request_understanding.identify_goal"].content_hash,
            "output_prompt_hash": refs[
                "request_understanding.identify_output_responsibilities"
            ].content_hash,
            "scope": "EVALUATION_ONLY_RU_GOAL_OUTPUT_STABILITY",
            "provider_read_count": 0,
            "provider_write_count": 0,
        },
        "trials": [],
    }
    _write(arguments.result_path, result)
    records = cast(list[dict[str, object]], result["trials"])

    for trial_no in range(1, arguments.trials + 1):
        for case_id in arguments.case:
            prompt_input = prompt_inputs[case_id]
            recorder.calls.clear()
            started = time.perf_counter()
            budget = build_default_run_budget(started_at_ms=int(time.time() * 1_000))
            with (
                provider_dispatch_execution_scope(
                    run_id=f"ru-stability-{case_id}-{trial_no}",
                    now_ms=lambda: int(time.time() * 1_000),
                ),
                provider_dispatch_budget_scope(budget),
            ):
                goal_output = recorder.infer(
                    "LOCAL_GPU",
                    refs["request_understanding.identify_goal"],
                    prompt_input,
                    request_goal_candidate_schema.IDENTIFY_GOAL_OUTPUT_SCHEMA,
                ).structured_output
                prohibitions = prohibition_ops.identify_effect_prohibitions(
                    llm_runtime=recorder,
                    requested_mode="LOCAL_GPU",
                    prompt_ref=refs["request_understanding.identify_effect_prohibitions"],
                    prompt_input=prompt_input,
                    goal_candidate=goal_output,
                    effect_candidates=prohibition_ops.build_effect_prohibition_candidates(
                        output_candidates
                    ),
                )
                output = output_ops.identify_output_responsibilities(
                    llm_runtime=recorder,
                    requested_mode="LOCAL_GPU",
                    prompt_ref=refs["request_understanding.identify_output_responsibilities"],
                    prompt_input=prompt_input,
                    goal_candidate=goal_output,
                    output_candidates=output_candidates,
                    effect_prohibitions=prohibitions,
                )
            output_pairs = _output_pairs(output)
            expected = sorted(EXPECTED_OUTPUTS[case_id])
            record = {
                "trial_no": trial_no,
                "case_id": case_id,
                "prompt_input_sha256": _sha256(prompt_input),
                "goal_candidate_sha256": _sha256(goal_output),
                "goal_candidate": goal_output,
                "output_pairs": output_pairs,
                "semantic_valid": output_pairs == expected,
                "calls": len(recorder.calls),
                "input_tokens": sum(cast(int, call["input_tokens"]) for call in recorder.calls),
                "output_tokens": sum(cast(int, call["output_tokens"]) for call in recorder.calls),
                "latency_ms": sum(cast(int, call["latency_ms"]) for call in recorder.calls),
                "wall_ms": int((time.perf_counter() - started) * 1_000),
            }
            records.append(record)
            _write(arguments.result_path, result)
            print(
                json.dumps(
                    {
                        "trial": trial_no,
                        "case_id": case_id,
                        "goal_hash": record["goal_candidate_sha256"],
                        "output": output_pairs,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )


if __name__ == "__main__":
    main()
