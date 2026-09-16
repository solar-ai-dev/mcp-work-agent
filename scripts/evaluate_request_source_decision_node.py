"""Replay Request Understanding goal and source decisions without the full Graph."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import time
from dataclasses import fields, replace
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from evaluation.dataset_v8 import load_cases
from scripts.evaluate_retrieval_plan_query_node import _load_latest_state

from google_work_agent.adapters.llm.ollama.transport import OllamaHTTPClient
from google_work_agent.adapters.llm.runtime.llm_credential_router import (
    SessionMemorySecretStore,
)
from google_work_agent.api.composition import (
    ProductionRuntimeConfig,
    build_production_runtime,
)
from google_work_agent.application.agents.request_understanding import (
    identify_goal as goal_ops,
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
from google_work_agent.application.use_cases.run.guard_run_budget import (
    build_default_run_budget,
)
from google_work_agent.application.use_cases.setting.update_settings import (
    UpdateSettingsCommand,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.runtime_selection import OLLAMA_FIXED_LOOPBACK_ENDPOINT
from google_work_agent.ports.llm.structured_inference_contracts import OutputSchemaDefinition
from google_work_agent.ports.system.contracts.workflow_execution import WorkflowStartRequest
from google_work_agent.ports.system.settings_port import SettingsPatchV1


class _RecordingInferencePort:
    def __init__(self, delegate: Any) -> None:
        self.delegate = delegate
        self.calls: list[dict[str, object]] = []

    def infer(self, *args: Any, **kwargs: Any) -> Any:
        result = self.delegate.infer(*args, **kwargs)
        prompt_ref = args[1]
        self.calls.append(
            {
                "prompt_id": prompt_ref.prompt_id,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "latency_ms": result.latency_ms,
            }
        )
        return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint-root", type=Path, required=True)
    parser.add_argument("--result-path", type=Path, required=True)
    parser.add_argument("--case", action="append", required=True)
    parser.add_argument("--model", default="qwen3.5:9b")
    parser.add_argument("--sampling-seed", type=int, default=1729)
    parser.add_argument("--compare-request-only", action="store_true")
    parser.add_argument("--compare-sparse", action="store_true")
    arguments = parser.parse_args()
    if arguments.model != "qwen3.5:9b":
        raise ValueError("this diagnostic is bound to qwen3.5:9b")

    manifest_path = default_prompt_manifest_path()
    goal_ref = load_prompt_reference(
        "request_understanding.identify_goal",
        manifest_path,
        execution_scope=DEVELOPMENT_SMOKE,
    )
    source_ref = load_prompt_reference(
        "request_understanding.identify_source_dependencies",
        manifest_path,
        execution_scope=DEVELOPMENT_SMOKE,
    )
    model_digest = next(
        (
            model.digest
            for model in OllamaHTTPClient().list_installed_models()
            if model.model_id == arguments.model
        ),
        None,
    )
    config = ProductionRuntimeConfig.development(
        runtime_root=Path(tempfile.mkdtemp(prefix="gwa-request-source-node-")),
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
        service_instance_id=f"request-source-node-{uuid4()}",
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
                preferred_local_model_id="qwen3.5:9b",
                preferred_llm_mode="LOCAL_GPU",
                external_llm_consent=False,
            ),
        )
    )
    dispatch_count = 0
    before_dispatch = runtime.before_provider_dispatch

    def count_dispatch() -> None:
        nonlocal dispatch_count
        before_dispatch()
        dispatch_count += 1

    runtime.before_provider_dispatch = count_dispatch
    recorder = _RecordingInferencePort(runtime)
    candidates = source_ops.build_source_dependency_candidates(load_development_tool_registry())
    cases = load_cases()
    records: list[dict[str, object]] = []
    for case_id in arguments.case:
        case = cases[case_id]
        database = arguments.checkpoint_root / case_id / "state" / "data" / "google_work_agent.db"
        state = _load_latest_state(database)
        request = state.get("__request__")
        if not isinstance(request, WorkflowStartRequest):
            records.append({"case_id": case_id, "outcome": "SKIP_NO_REQUEST"})
            continue
        prompt_input = goal_ops._prompt_input(
            request=request,
            confirmation_response=None,
        )
        started = time.perf_counter()
        before = dispatch_count
        recorder.calls.clear()
        budget = build_default_run_budget(started_at_ms=int(time.time() * 1_000))
        try:
            with (
                provider_dispatch_execution_scope(
                    run_id=f"request-source-{case_id}-{uuid4()}",
                    now_ms=lambda: int(time.time() * 1_000),
                ),
                provider_dispatch_budget_scope(budget),
            ):
                goal_output = recorder.infer(
                    "LOCAL_GPU",
                    goal_ref,
                    prompt_input,
                    request_goal_candidate_schema.IDENTIFY_GOAL_OUTPUT_SCHEMA,
                ).structured_output
                goal_dispatches = dispatch_count - before
                source_goal = anchor_ops.project_extractive_source_goal(
                    goal_output,
                    request_text=request.request_text,
                )
                source_output = source_ops.identify_source_dependencies(
                    llm_runtime=recorder,
                    requested_mode="LOCAL_GPU",
                    prompt_ref=source_ref,
                    prompt_input=prompt_input,
                    goal_candidate=source_goal,
                    source_candidates=candidates,
                )
                source_dispatches = dispatch_count - before - goal_dispatches
                candidate_output = None
                candidate_dispatches = 0
                if arguments.compare_request_only:
                    request_only_goal = dict(source_goal)
                    constraints = source_goal.get("constraints")
                    request_only_goal["constraints"] = (
                        {key: [] for key in constraints} if isinstance(constraints, dict) else {}
                    )
                    candidate_output = source_ops.identify_source_dependencies(
                        llm_runtime=recorder,
                        requested_mode="LOCAL_GPU",
                        prompt_ref=source_ref,
                        prompt_input=prompt_input,
                        goal_candidate=request_only_goal,
                        source_candidates=candidates,
                    )
                    candidate_dispatches = (
                        dispatch_count - before - goal_dispatches - source_dispatches
                    )
                sparse_result = None
                if arguments.compare_sparse:
                    sparse_result = _sparse_source_candidate(
                        prompt_ref=source_ref,
                        prompt_input=prompt_input,
                        source_goal=source_goal,
                        source_candidates=candidates,
                        model_id=arguments.model,
                        sampling_seed=arguments.sampling_seed,
                    )
            source_types = [
                decision["resource_type"]
                for decision in source_output["source_dependencies"]
                if decision["dependency"] == "SOURCE_REQUIRED"
            ]
            saved_intent = state.get("request_intent")
            saved_responsibilities = (
                saved_intent.get("resource_responsibilities", {})
                if isinstance(saved_intent, dict)
                else {}
            )
            records.append(
                {
                    "case_id": case_id,
                    "outcome": "SCHEMA_VALID_SEMANTICS_UNREVIEWED",
                    "category": case.raw.get("category"),
                    "goal_constraint_fields": sorted(
                        cast(dict[str, object], goal_output["constraints"]).keys()
                    ),
                    "source_types": source_types,
                    "request_only_source_types": (
                        [
                            decision["resource_type"]
                            for decision in candidate_output["source_dependencies"]
                            if decision["dependency"] == "SOURCE_REQUIRED"
                        ]
                        if candidate_output is not None
                        else None
                    ),
                    "saved_source_types": [
                        item["resource_type"]
                        for item in saved_responsibilities.get("source_reads", [])
                    ],
                    "goal_provider_calls": goal_dispatches,
                    "source_provider_calls": source_dispatches,
                    "request_only_provider_calls": candidate_dispatches,
                    "sparse_candidate": sparse_result,
                    "goal_output_hash": hashlib.sha256(
                        json.dumps(goal_output, ensure_ascii=False, sort_keys=True).encode("utf-8")
                    ).hexdigest(),
                    "input_tokens": sum(cast(int, call["input_tokens"]) for call in recorder.calls),
                    "output_tokens": sum(
                        cast(int, call["output_tokens"]) for call in recorder.calls
                    ),
                    "latency_ms": sum(cast(int, call["latency_ms"]) for call in recorder.calls),
                    "duration_ms": int((time.perf_counter() - started) * 1_000),
                }
            )
        except Exception as error:
            records.append(
                {
                    "case_id": case_id,
                    "outcome": "FAILED",
                    "error_type": type(error).__name__,
                    "reason_code": getattr(error, "reason_code", None),
                    "provider_calls": dispatch_count - before,
                    "duration_ms": int((time.perf_counter() - started) * 1_000),
                }
            )
        print(json.dumps(records[-1], ensure_ascii=False, sort_keys=True), flush=True)

    result = {
        "binding": {
            "checkpoint_corpus": arguments.checkpoint_root.name,
            "model_id": arguments.model,
            "model_digest": model_digest,
            "sampling_temperature": 0.0,
            "sampling_seed": arguments.sampling_seed,
            "goal_prompt_hash": goal_ref.content_hash,
            "source_prompt_hash": source_ref.content_hash,
            "compare_request_only": arguments.compare_request_only,
            "compare_sparse": arguments.compare_sparse,
            "connector_dispatch_enabled": False,
            "product_graph_compiled": False,
        },
        "cases": records,
    }
    arguments.result_path.parent.mkdir(parents=True, exist_ok=True)
    arguments.result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sparse_source_candidate(
    *,
    prompt_ref: Any,
    prompt_input: dict[str, object],
    source_goal: dict[str, object],
    source_candidates: tuple[Any, ...],
    model_id: str,
    sampling_seed: int,
) -> dict[str, object]:
    candidate_path = (
        Path(__file__).resolve().parents[1]
        / "evaluation"
        / "prompt_candidates"
        / "request-source-sparse-v1"
        / "sources"
        / "request_understanding.identify_source_dependencies.md"
    )
    candidate_bytes = candidate_path.read_bytes()
    candidate_source = candidate_bytes.decode("utf-8").rstrip()
    base_projection = {
        **prompt_input,
        "goal_candidate": source_goal,
        "source_candidates": [dict(candidate) for candidate in source_candidates],
    }
    baseline_source = PromptRegistry().source_text(prompt_ref.prompt_id).rstrip()
    baseline_instruction = assemble_prompt(
        prompt_ref,
        base_projection,
        execution_scope=DEVELOPMENT_SMOKE,
    )
    if not baseline_instruction.startswith(baseline_source):
        raise ValueError("source Prompt assembly did not preserve the registered base")
    instruction_text = candidate_source + baseline_instruction[len(baseline_source) :]
    candidate_ref = replace(
        prompt_ref,
        prompt_version="sparse-v1-dev",
        content_hash=hashlib.sha256(candidate_bytes).hexdigest(),
    )
    schema = _sparse_output_schema(source_candidates)
    response = OllamaHTTPClient().invoke_structured(
        endpoint=OLLAMA_FIXED_LOOPBACK_ENDPOINT,
        model_id=model_id,
        prompt_ref=candidate_ref,
        prompt_input=base_projection,
        output_schema=schema,
        timeout_seconds=180,
        instruction_text=instruction_text,
        sampling_temperature=0.0,
        sampling_seed=sampling_seed,
    )
    try:
        payload = json.loads(response.content if isinstance(response.content, str) else "")
    except json.JSONDecodeError:
        return {
            "outcome": "JSON_INVALID",
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "latency_ms": response.latency_ms,
        }
    errors = validate_output_schema(payload, schema.json_schema)
    if errors:
        return {
            "outcome": "SCHEMA_INVALID",
            "error_count": len(errors),
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "latency_ms": response.latency_ms,
        }
    selected = payload["source_reads"]
    selected_types = [item["resource_type"] for item in selected]
    return {
        "outcome": (
            "SCHEMA_VALID_SEMANTICS_UNREVIEWED"
            if len(selected_types) == len(set(selected_types))
            else "DUPLICATE_SOURCE_TYPE"
        ),
        "source_types": selected_types,
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "latency_ms": response.latency_ms,
    }


def _sparse_output_schema(source_candidates: tuple[Any, ...]) -> OutputSchemaDefinition:
    resource_types = [candidate["resource_type"] for candidate in source_candidates]
    return OutputSchemaDefinition(
        schema_version="request-source-sparse-dev-v1",
        json_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["source_reads"],
            "properties": {
                "source_reads": {
                    "type": "array",
                    "maxItems": len(resource_types),
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["resource_type", "required_information", "target_scope"],
                        "properties": {
                            "resource_type": {"enum": resource_types},
                            "required_information": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": 8,
                                "uniqueItems": True,
                                "items": {"type": "string", "minLength": 1},
                            },
                            "target_scope": {"enum": ["SINGULAR", "CRITERIA"]},
                        },
                    },
                }
            },
        },
    )


if __name__ == "__main__":
    main()
