"""Compare one output-responsibility Prompt candidate on Canonical Core inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import time
from dataclasses import fields, replace
from pathlib import Path
from typing import cast
from uuid import uuid4

from evaluation.dataset_v8 import load_cases, normalized_sha256
from scripts.evaluate_retrieval_plan_query_node import _load_latest_state
from scripts.evaluate_ru_source_status_prompt import (
    DATASET,
    EXPECTED_MODEL_DIGEST,
    MODEL_ID,
    _git_head,
    _RecordingInferencePort,
    _sha256,
    _write,
)

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
from google_work_agent.application.agents.request_understanding import (
    identify_source_dependencies as source_ops,
)
from google_work_agent.application.agents.request_understanding import (
    preserve_explicit_search_anchors as anchor_ops,
)
from google_work_agent.application.agents.request_understanding.contracts import (
    request_goal_candidate_schema,
)
from google_work_agent.application.prompt_runtime.assemble_prompt import assemble_prompt
from google_work_agent.application.prompt_runtime.prompt_registry import (
    DEVELOPMENT_SMOKE,
    PromptRegistry,
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
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.application.use_cases.setting.update_settings import UpdateSettingsCommand
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.runtime_selection import OLLAMA_FIXED_LOOPBACK_ENDPOINT
from google_work_agent.ports.system.settings_port import SettingsPatchV1

CANDIDATE = Path(
    "evaluation/prompt_candidates/ru-output-responsibility-contrast-v1/sources/"
    "request_understanding.identify_output_responsibilities.md"
)
EXPECTED_OUTPUTS: dict[str, list[list[str]]] = {
    "CASE-CORE-001": [],
    "CASE-CORE-006": [],
    "CASE-CORE-009": [],
    "CASE-CORE-010": [],
    "CASE-CORE-012": [["GMAIL_DRAFT", "CREATE"]],
    "CASE-CORE-019": [["CALENDAR_EVENT", "CREATE"], ["GMAIL_DRAFT", "CREATE"]],
    "CASE-CORE-023": [["CALENDAR_EVENT", "CREATE"]],
    "CASE-CORE-046": [["CALENDAR_EVENT", "CREATE"], ["GMAIL_DRAFT", "CREATE"]],
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint-root", type=Path, required=True)
    parser.add_argument("--result-path", type=Path, required=True)
    parser.add_argument("--case", action="append", required=True)
    parser.add_argument("--sampling-seed", type=int, default=20260914)
    parser.add_argument("--candidate-path", type=Path, default=CANDIDATE)
    parser.add_argument("--candidate-id", default="ru-output-responsibility-contrast-v1")
    arguments = parser.parse_args()
    if arguments.result_path.exists():
        raise ValueError("result path already exists; preserve every prior trial")
    if any(case_id not in EXPECTED_OUTPUTS for case_id in arguments.case):
        raise ValueError("requested Case has no preregistered output expectation")
    cases = load_cases()
    if any(cases[case_id].raw.get("split") != "CORE" for case_id in arguments.case):
        raise ValueError("this tuning diagnostic accepts Canonical Core only")

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
            "request_understanding.identify_source_dependencies",
            "request_understanding.identify_output_responsibilities",
        )
    }
    candidate_bytes = arguments.candidate_path.read_bytes()
    candidate_source = candidate_bytes.decode("utf-8").rstrip()
    candidate_hash = hashlib.sha256(candidate_bytes).hexdigest()
    baseline_source = (
        PromptRegistry()
        .source_text("request_understanding.identify_output_responsibilities")
        .rstrip()
    )
    client = OllamaHTTPClient()
    model_digest = next(
        (model.digest for model in client.list_installed_models() if model.model_id == MODEL_ID),
        None,
    )
    if model_digest != EXPECTED_MODEL_DIGEST:
        raise ValueError("local model digest differs from the preregistered comparison")

    config = ProductionRuntimeConfig.development(
        runtime_root=Path(tempfile.mkdtemp(prefix="gwa-ru-output-prompt-")),
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
        service_instance_id=f"ru-output-prompt-{uuid4()}",
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
    tool_catalog = load_development_tool_registry()
    source_candidates = source_ops.build_source_dependency_candidates(tool_catalog)
    output_candidates = output_ops.build_output_responsibility_candidates(tool_catalog)
    result: dict[str, object] = {
        "binding": {
            "product_sha": _git_head(),
            "product_src_tree_note": "source-status candidate adopted before this comparison",
            "dataset_sha256": normalized_sha256(DATASET),
            "checkpoint_corpus": arguments.checkpoint_root.name,
            "model_id": MODEL_ID,
            "model_digest": model_digest,
            "temperature": 0.0,
            "seed": arguments.sampling_seed,
            "baseline_prompt_hash": refs[
                "request_understanding.identify_output_responsibilities"
            ].content_hash,
            "candidate_prompt_hash": candidate_hash,
            "candidate_id": arguments.candidate_id,
            "scope": "EVALUATION_ONLY_RU_OUTPUT_RESPONSIBILITY_PAIRED",
            "provider_read_count": 0,
            "provider_write_count": 0,
        },
        "cases": [],
    }
    _write(arguments.result_path, result)
    records = cast(list[dict[str, object]], result["cases"])

    for case_id in arguments.case:
        database = arguments.checkpoint_root / case_id / "state" / "data" / "google_work_agent.db"
        request = _load_latest_state(database).get("__request__")
        if request is None:
            raise ValueError(f"{case_id}: checkpoint request unavailable")
        request = replace(request, requested_mode="LOCAL_GPU")
        prompt_input = goal_ops._prompt_input(request=request, confirmation_response=None)
        recorder.calls.clear()
        started = time.perf_counter()
        budget = build_default_run_budget(started_at_ms=int(time.time() * 1_000))
        with (
            provider_dispatch_execution_scope(
                run_id=f"ru-output-{case_id}-{uuid4()}",
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
            source_ops.identify_source_dependencies(
                llm_runtime=recorder,
                requested_mode="LOCAL_GPU",
                prompt_ref=refs["request_understanding.identify_source_dependencies"],
                prompt_input=prompt_input,
                goal_candidate=anchor_ops.project_extractive_source_goal(
                    goal_output,
                    request_text=request.request_text,
                ),
                source_candidates=source_candidates,
            )
            baseline = output_ops.identify_output_responsibilities(
                llm_runtime=recorder,
                requested_mode="LOCAL_GPU",
                prompt_ref=refs["request_understanding.identify_output_responsibilities"],
                prompt_input=prompt_input,
                goal_candidate=goal_output,
                output_candidates=output_candidates,
                effect_prohibitions=prohibitions,
            )

        base_projection = {
            **prompt_input,
            "goal_candidate": dict(goal_output),
            "output_candidates": [dict(candidate) for candidate in output_candidates],
            "effect_prohibitions": list(prohibitions["effect_prohibitions"]),
        }
        schema = output_ops.build_output_responsibility_output_schema(output_candidates)
        baseline_instruction = assemble_prompt(
            refs["request_understanding.identify_output_responsibilities"],
            base_projection,
            execution_scope=DEVELOPMENT_SMOKE,
        )
        if not baseline_instruction.startswith(baseline_source):
            raise ValueError("output Prompt assembly did not preserve the registered base")
        candidate_instruction = candidate_source + baseline_instruction[len(baseline_source) :]
        candidate_ref = replace(
            refs["request_understanding.identify_output_responsibilities"],
            prompt_version="contrast-v1-eval",
            content_hash=candidate_hash,
        )
        response = client.invoke_structured(
            endpoint=OLLAMA_FIXED_LOOPBACK_ENDPOINT,
            model_id=MODEL_ID,
            prompt_ref=candidate_ref,
            prompt_input=base_projection,
            output_schema=schema,
            timeout_seconds=180,
            instruction_text=candidate_instruction,
            sampling_temperature=0.0,
            sampling_seed=arguments.sampling_seed,
        )
        candidate = json.loads(cast(str, response.content))
        validation_errors = validate_output_schema(candidate, schema.json_schema)
        expected = sorted(EXPECTED_OUTPUTS[case_id])
        baseline_pairs = _output_pairs(baseline)
        candidate_pairs = _output_pairs(candidate)
        record = {
            "case_id": case_id,
            "request_sha256": hashlib.sha256(request.request_text.encode("utf-8")).hexdigest(),
            "prompt_input_sha256": _sha256(base_projection),
            "expected_output_pairs": expected,
            "baseline_output_pairs": baseline_pairs,
            "candidate_output_pairs": candidate_pairs,
            "baseline_semantic_valid": baseline_pairs == expected,
            "candidate_semantic_valid": not validation_errors and candidate_pairs == expected,
            "candidate_validation_errors": validation_errors,
            "upstream_calls": len(recorder.calls) - 1,
            "baseline_calls": 1,
            "candidate_calls": 1,
            "upstream_input_tokens": sum(
                cast(int, call["input_tokens"]) for call in recorder.calls[:-1]
            ),
            "upstream_output_tokens": sum(
                cast(int, call["output_tokens"]) for call in recorder.calls[:-1]
            ),
            "baseline_input_tokens": recorder.calls[-1]["input_tokens"],
            "baseline_output_tokens": recorder.calls[-1]["output_tokens"],
            "baseline_latency_ms": recorder.calls[-1]["latency_ms"],
            "candidate_input_tokens": response.input_tokens,
            "candidate_output_tokens": response.output_tokens,
            "candidate_latency_ms": response.latency_ms,
            "wall_ms": int((time.perf_counter() - started) * 1_000),
        }
        records.append(record)
        _write(arguments.result_path, result)
        print(
            json.dumps(
                {
                    "case_id": case_id,
                    "baseline": baseline_pairs,
                    "candidate": candidate_pairs,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )


def _output_pairs(value: object) -> list[list[str]]:
    if not isinstance(value, dict) or not isinstance(value.get("output_responsibilities"), list):
        return []
    return sorted(
        [
            [str(item.get("resource_type")), str(item.get("effect"))]
            for item in value["output_responsibilities"]
            if isinstance(item, dict)
        ]
    )


if __name__ == "__main__":
    main()
