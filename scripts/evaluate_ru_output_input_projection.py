"""Compare output responsibility across bounded upstream goal projections."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import time
from copy import deepcopy
from dataclasses import fields, replace
from datetime import datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

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
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.system.contracts.workflow_execution import (
    SelectedResourceRef,
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)
from google_work_agent.ports.system.settings_port import SettingsPatchV1

EXPECTED_OUTPUTS: dict[str, list[list[str]]] = {
    "CASE-CORE-001": [],
    "CASE-CORE-006": [],
    "CASE-CORE-009": [],
    "CASE-CORE-010": [],
    "CASE-CORE-011": [["GMAIL_DRAFT", "CREATE"]],
    "CASE-CORE-012": [["GMAIL_DRAFT", "CREATE"]],
    "CASE-CORE-019": [["CALENDAR_EVENT", "CREATE"], ["GMAIL_DRAFT", "CREATE"]],
    "CASE-CORE-023": [["CALENDAR_EVENT", "CREATE"]],
    "CASE-CORE-027": [],
    "CASE-CORE-031": [["TASK", "CREATE"]],
    "CASE-CORE-035": [["TASK", "CREATE"]],
    "CASE-CORE-037": [["TASK", "UPDATE"]],
    "CASE-CORE-040": [["TASK", "UPDATE"]],
    "CASE-CORE-041": [],
    "CASE-CORE-046": [["CALENDAR_EVENT", "CREATE"], ["GMAIL_DRAFT", "CREATE"]],
    "CASE-CORE-047": [["CALENDAR_EVENT", "CREATE"], ["TASK", "UPDATE"]],
    "CASE-CORE-048": [
        ["CALENDAR_EVENT", "CREATE"],
        ["GMAIL_DRAFT", "CREATE"],
        ["TASK", "UPDATE"],
    ],
    "CASE-CORE-049": [
        ["CALENDAR_EVENT", "CREATE"],
        ["GMAIL_DRAFT", "CREATE"],
        ["TASK", "CREATE"],
    ],
    "CASE-CORE-053": [["CALENDAR_EVENT", "CREATE"]],
    "CASE-CORE-054": [["GMAIL_DRAFT", "CREATE"]],
    "CASE-CORE-056": [],
    "CASE-CORE-059": [["GMAIL_MESSAGE", "SEND"]],
    "CASE-CORE-060": [["TASK", "UPDATE"]],
}
EXPLICIT_DISPOSITION_PROMPT = Path(
    "evaluation/prompt_candidates/ru-output-explicit-disposition-v1/sources/"
    "request_understanding.identify_output_responsibilities.md"
)
CHANGE_GATE_PROMPT = Path(
    "evaluation/prompt_candidates/ru-output-change-gate-v1/sources/"
    "request_understanding.identify_output_responsibilities.md"
)
OUTPUT_PROVENANCE_PROMPT = Path(
    "evaluation/prompt_candidates/ru-output-provenance-v1/sources/"
    "request_understanding.identify_output_responsibilities.md"
)
CHANGE_SPANS_PROMPT = Path(
    "evaluation/prompt_candidates/ru-output-change-spans-v1/sources/"
    "request_understanding.extract_output_change_spans.md"
)
CHANGE_SPAN_MAPPING_PROMPT = Path(
    "evaluation/prompt_candidates/ru-output-change-spans-v1/sources/"
    "request_understanding.map_output_change_spans.md"
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result-path", type=Path, required=True)
    parser.add_argument("--case", action="append", required=True)
    parser.add_argument("--sampling-seed", type=int, default=20260914)
    parser.add_argument(
        "--candidate-projection",
        choices=(
            "empty",
            "bounded",
            "per-resource",
            "explicit-disposition",
            "two-stage-disposition",
            "output-provenance",
            "without-reference-time",
            "two-stage-change-spans",
        ),
        default="empty",
    )
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
        runtime_root=Path(tempfile.mkdtemp(prefix="gwa-ru-output-projection-")),
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
        service_instance_id=f"ru-output-projection-{uuid4()}",
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
    output_schema = output_ops.build_output_responsibility_output_schema(output_candidates)
    output_ref = refs["request_understanding.identify_output_responsibilities"]
    candidate_prompt_hash = _candidate_prompt_hash(
        arguments.candidate_projection,
        baseline_hash=output_ref.content_hash,
    )
    result: dict[str, object] = {
        "binding": {
            "product_sha": _git_head(),
            "dataset_sha256": normalized_sha256(DATASET),
            "model_id": MODEL_ID,
            "model_digest": model_digest,
            "temperature": 0.0,
            "seed": arguments.sampling_seed,
            "prompt_hash": output_ref.content_hash,
            "candidate_prompt_hash": candidate_prompt_hash,
            "candidate_id": f"ru-output-{arguments.candidate_projection}-goal-envelope-v1",
            "scope": "EVALUATION_ONLY_RU_OUTPUT_INPUT_PROJECTION_PAIRED",
            "provider_read_count": 0,
            "provider_write_count": 0,
        },
        "cases": [],
    }
    _write(arguments.result_path, result)
    records = cast(list[dict[str, object]], result["cases"])

    for case_id in arguments.case:
        request = _request(case_id, cases[case_id].raw)
        prompt_input = goal_ops._prompt_input(request=request, confirmation_response=None)
        recorder.calls.clear()
        started = time.perf_counter()
        budget = build_default_run_budget(started_at_ms=int(time.time() * 1_000))
        with (
            provider_dispatch_execution_scope(
                run_id=f"ru-output-projection-{case_id}-{uuid4()}",
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
            baseline = output_ops.identify_output_responsibilities(
                llm_runtime=recorder,
                requested_mode="LOCAL_GPU",
                prompt_ref=output_ref,
                prompt_input=prompt_input,
                goal_candidate=goal_output,
                output_candidates=output_candidates,
                effect_prohibitions=prohibitions,
            )

        baseline_projection = {
            **prompt_input,
            "goal_candidate": dict(goal_output),
            "output_candidates": [dict(candidate) for candidate in output_candidates],
            "effect_prohibitions": list(prohibitions["effect_prohibitions"]),
        }
        candidate_goal = _candidate_goal_projection(
            goal_output,
            projection=arguments.candidate_projection,
        )
        candidate_prompt_input = dict(prompt_input)
        if arguments.candidate_projection == "without-reference-time":
            candidate_prompt_input.pop("run_reference_time", None)
        candidate_projection = {
            **candidate_prompt_input,
            "goal_candidate": candidate_goal,
            "output_candidates": [dict(candidate) for candidate in output_candidates],
            "effect_prohibitions": list(prohibitions["effect_prohibitions"]),
        }
        candidate, candidate_responses, candidate_contract_errors = _invoke_candidate(
            client=client,
            prompt_ref=output_ref,
            prompt_input=candidate_prompt_input,
            goal_candidate=candidate_goal,
            output_candidates=output_candidates,
            effect_prohibitions=prohibitions,
            projection=arguments.candidate_projection,
            sampling_seed=arguments.sampling_seed,
        )
        validation_errors = [
            *candidate_contract_errors,
            *validate_output_schema(candidate, output_schema.json_schema),
        ]
        expected = sorted(EXPECTED_OUTPUTS[case_id])
        baseline_pairs = _output_pairs(baseline)
        candidate_pairs = _output_pairs(candidate)
        record = {
            "case_id": case_id,
            "expected_output_pairs": expected,
            "baseline_output_pairs": baseline_pairs,
            "candidate_output_pairs": candidate_pairs,
            "baseline_semantic_valid": baseline_pairs == expected,
            "candidate_semantic_valid": not validation_errors and candidate_pairs == expected,
            "candidate_validation_errors": validation_errors,
            "baseline_projection_sha256": _sha256(baseline_projection),
            "candidate_projection_sha256": _sha256(candidate_projection),
            "upstream_calls": len(recorder.calls) - 1,
            "baseline_calls": 1,
            "candidate_calls": len(candidate_responses),
            "upstream_input_tokens": sum(
                cast(int, call["input_tokens"]) for call in recorder.calls[:-1]
            ),
            "upstream_output_tokens": sum(
                cast(int, call["output_tokens"]) for call in recorder.calls[:-1]
            ),
            "baseline_input_tokens": recorder.calls[-1]["input_tokens"],
            "baseline_output_tokens": recorder.calls[-1]["output_tokens"],
            "baseline_latency_ms": recorder.calls[-1]["latency_ms"],
            "candidate_input_tokens": sum(
                response.input_tokens for response in candidate_responses
            ),
            "candidate_output_tokens": sum(
                response.output_tokens for response in candidate_responses
            ),
            "candidate_latency_ms": sum(response.latency_ms for response in candidate_responses),
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


def _request(case_id: str, raw: dict[str, object]) -> WorkflowStartRequest:
    selected: list[SelectedResourceRef] = []
    bindings = raw.get("selected_resource_bindings", [])
    if isinstance(bindings, list):
        for index, binding in enumerate(bindings):
            if not isinstance(binding, dict):
                raise ValueError(f"{case_id}: selected binding must be an object")
            resource_type = str(binding["resource_type"])
            selected.append(
                SelectedResourceRef(
                    resource_ref_id=f"eval-{case_id}-{index}",
                    connector_id=(
                        "github" if resource_type == "github_issue" else "google_workspace"
                    ),
                    resource_type=resource_type,
                    resource_id=str(binding["resource_id"]),
                    parent_resource_id=(
                        str(binding["parent_id"]) if binding.get("parent_id") else None
                    ),
                )
            )
    started_at_ms = int(time.time() * 1_000)
    context = raw.get("evaluation_context")
    if isinstance(context, dict) and isinstance(context.get("run_reference_time"), str):
        started_at_ms = int(
            datetime.fromisoformat(str(context["run_reference_time"])).timestamp() * 1_000
        )
    return WorkflowStartRequest(
        run_id=str(uuid4()),
        conversation_id=str(uuid4()),
        workflow_key=str(uuid4()),
        entry_mode=str(raw["entry_mode"]),
        requested_mode="LOCAL_GPU",
        request_text=str(raw["canonical_user_prompt"]),
        selected_resource_ids=tuple(ref.resource_id for ref in selected),
        selected_resources=tuple(selected),
        correlation=WorkflowCorrelationContext(str(uuid4()), None, "1"),
        run_budget=build_default_run_budget(started_at_ms=started_at_ms),
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


def _candidate_goal_projection(
    goal_output: object,
    *,
    projection: str,
) -> dict[str, object]:
    if projection == "empty":
        return {}
    if projection in {
        "per-resource",
        "explicit-disposition",
        "two-stage-disposition",
        "output-provenance",
        "without-reference-time",
        "two-stage-change-spans",
    }:
        if not isinstance(goal_output, dict):
            raise ValueError("goal output must be an object")
        return dict(goal_output)
    if projection != "bounded" or not isinstance(goal_output, dict):
        raise ValueError(f"unsupported candidate projection: {projection}")
    return {
        field: goal_output[field]
        for field in ("goal", "completion_conditions", "analysis_requirement")
        if field in goal_output
    }


def _invoke_candidate(
    *,
    client: OllamaHTTPClient,
    prompt_ref: PromptReference,
    prompt_input: dict[str, object],
    goal_candidate: dict[str, object],
    output_candidates: list[dict[str, object]],
    effect_prohibitions: dict[str, object],
    projection: str,
    sampling_seed: int,
) -> tuple[dict[str, object], list[object], list[str]]:
    if projection == "two-stage-change-spans":
        return _invoke_change_span_candidate(
            client=client,
            prompt_ref=prompt_ref,
            prompt_input=prompt_input,
            output_candidates=output_candidates,
            effect_prohibitions=effect_prohibitions,
            sampling_seed=sampling_seed,
        )
    if projection == "output-provenance":
        return _invoke_output_provenance_candidate(
            client=client,
            prompt_ref=prompt_ref,
            prompt_input=prompt_input,
            goal_candidate=goal_candidate,
            output_candidates=output_candidates,
            effect_prohibitions=effect_prohibitions,
            sampling_seed=sampling_seed,
        )
    if projection == "two-stage-disposition":
        gate_response, has_external_change, gate_errors = _invoke_change_gate(
            client=client,
            prompt_ref=prompt_ref,
            prompt_input=prompt_input,
            goal_candidate=goal_candidate,
            output_candidates=output_candidates,
            effect_prohibitions=effect_prohibitions,
            sampling_seed=sampling_seed,
        )
        if gate_errors or not has_external_change:
            return {"output_responsibilities": []}, [gate_response], gate_errors
        candidate, responses, errors = _invoke_explicit_disposition_candidate(
            client=client,
            prompt_ref=prompt_ref,
            prompt_input=prompt_input,
            goal_candidate=goal_candidate,
            output_candidates=output_candidates,
            effect_prohibitions=effect_prohibitions,
            sampling_seed=sampling_seed,
        )
        return candidate, [gate_response, *responses], errors
    if projection == "explicit-disposition":
        return _invoke_explicit_disposition_candidate(
            client=client,
            prompt_ref=prompt_ref,
            prompt_input=prompt_input,
            goal_candidate=goal_candidate,
            output_candidates=output_candidates,
            effect_prohibitions=effect_prohibitions,
            sampling_seed=sampling_seed,
        )
    candidate_groups = (
        [[candidate] for candidate in output_candidates]
        if projection == "per-resource"
        else [output_candidates]
    )
    responses = []
    responsibilities: list[object] = []
    prohibited = output_ops.resolve_prohibited_effects(effect_prohibitions)
    for candidates in candidate_groups:
        projection_input = {
            **prompt_input,
            "goal_candidate": goal_candidate,
            "output_candidates": [dict(candidate) for candidate in candidates],
            "effect_prohibitions": list(effect_prohibitions["effect_prohibitions"]),
        }
        schema = output_ops.build_output_responsibility_output_schema(
            candidates,
            prohibited_effects=prohibited,
        )
        response = client.invoke_structured(
            endpoint=OLLAMA_FIXED_LOOPBACK_ENDPOINT,
            model_id=MODEL_ID,
            prompt_ref=prompt_ref,
            prompt_input=projection_input,
            output_schema=schema,
            timeout_seconds=180,
            instruction_text=assemble_prompt(
                prompt_ref,
                projection_input,
                execution_scope=DEVELOPMENT_SMOKE,
            ),
            sampling_temperature=0.0,
            sampling_seed=sampling_seed,
        )
        responses.append(response)
        group_result = json.loads(cast(str, response.content))
        responsibilities.extend(group_result["output_responsibilities"])
    return {"output_responsibilities": responsibilities}, responses, []


def _invoke_change_gate(
    *,
    client: OllamaHTTPClient,
    prompt_ref: PromptReference,
    prompt_input: dict[str, object],
    goal_candidate: dict[str, object],
    output_candidates: list[dict[str, object]],
    effect_prohibitions: dict[str, object],
    sampling_seed: int,
) -> tuple[object, bool, list[str]]:
    projection_input = {
        **prompt_input,
        "goal_candidate": goal_candidate,
        "output_candidates": [dict(candidate) for candidate in output_candidates],
        "effect_prohibitions": list(effect_prohibitions["effect_prohibitions"]),
    }
    schema = OutputSchemaDefinition(
        schema_version="request-output-change-gate-v1-eval",
        json_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["external_change_requirement"],
            "properties": {"external_change_requirement": {"enum": ["NONE", "PRESENT"]}},
        },
    )
    candidate_bytes = CHANGE_GATE_PROMPT.read_bytes()
    candidate_source = candidate_bytes.decode("utf-8").rstrip()
    baseline_source = (
        PromptRegistry()
        .source_text("request_understanding.identify_output_responsibilities")
        .rstrip()
    )
    baseline_instruction = assemble_prompt(
        prompt_ref,
        projection_input,
        execution_scope=DEVELOPMENT_SMOKE,
    )
    if not baseline_instruction.startswith(baseline_source):
        raise ValueError("output Prompt assembly did not preserve the registered base")
    candidate_ref = replace(
        prompt_ref,
        prompt_version="change-gate-v1-eval",
        content_hash=hashlib.sha256(candidate_bytes).hexdigest(),
    )
    response = client.invoke_structured(
        endpoint=OLLAMA_FIXED_LOOPBACK_ENDPOINT,
        model_id=MODEL_ID,
        prompt_ref=candidate_ref,
        prompt_input=projection_input,
        output_schema=schema,
        timeout_seconds=180,
        instruction_text=(candidate_source + baseline_instruction[len(baseline_source) :]),
        sampling_temperature=0.0,
        sampling_seed=sampling_seed,
    )
    raw = json.loads(cast(str, response.content))
    errors = validate_output_schema(raw, schema.json_schema)
    return (
        response,
        isinstance(raw, dict) and raw.get("external_change_requirement") == "PRESENT",
        errors,
    )


def _invoke_explicit_disposition_candidate(
    *,
    client: OllamaHTTPClient,
    prompt_ref: PromptReference,
    prompt_input: dict[str, object],
    goal_candidate: dict[str, object],
    output_candidates: list[dict[str, object]],
    effect_prohibitions: dict[str, object],
    sampling_seed: int,
) -> tuple[dict[str, object], list[object], list[str]]:
    projection_input = {
        **prompt_input,
        "goal_candidate": goal_candidate,
        "output_candidates": [dict(candidate) for candidate in output_candidates],
        "effect_prohibitions": list(effect_prohibitions["effect_prohibitions"]),
    }
    schema = _explicit_disposition_schema(
        output_candidates,
        prohibited_effects=output_ops.resolve_prohibited_effects(effect_prohibitions),
    )
    candidate_bytes = EXPLICIT_DISPOSITION_PROMPT.read_bytes()
    candidate_source = candidate_bytes.decode("utf-8").rstrip()
    baseline_source = (
        PromptRegistry()
        .source_text("request_understanding.identify_output_responsibilities")
        .rstrip()
    )
    baseline_instruction = assemble_prompt(
        prompt_ref,
        projection_input,
        execution_scope=DEVELOPMENT_SMOKE,
    )
    if not baseline_instruction.startswith(baseline_source):
        raise ValueError("output Prompt assembly did not preserve the registered base")
    candidate_ref = replace(
        prompt_ref,
        prompt_version="explicit-disposition-v1-eval",
        content_hash=hashlib.sha256(candidate_bytes).hexdigest(),
    )
    response = client.invoke_structured(
        endpoint=OLLAMA_FIXED_LOOPBACK_ENDPOINT,
        model_id=MODEL_ID,
        prompt_ref=candidate_ref,
        prompt_input=projection_input,
        output_schema=schema,
        timeout_seconds=180,
        instruction_text=(candidate_source + baseline_instruction[len(baseline_source) :]),
        sampling_temperature=0.0,
        sampling_seed=sampling_seed,
    )
    raw = json.loads(cast(str, response.content))
    errors = validate_output_schema(raw, schema.json_schema)
    decisions = raw.get("decisions", []) if isinstance(raw, dict) else []
    responsibilities = [
        {
            "resource_type": decision["resource_type"],
            "effect": decision["effect"],
        }
        for decision in decisions
        if isinstance(decision, dict) and decision.get("disposition") == "REQUESTED"
    ]
    return {"output_responsibilities": responsibilities}, [response], errors


def _invoke_output_provenance_candidate(
    *,
    client: OllamaHTTPClient,
    prompt_ref: PromptReference,
    prompt_input: dict[str, object],
    goal_candidate: dict[str, object],
    output_candidates: list[dict[str, object]],
    effect_prohibitions: dict[str, object],
    sampling_seed: int,
) -> tuple[dict[str, object], list[object], list[str]]:
    projection_input = {
        **prompt_input,
        "goal_candidate": goal_candidate,
        "output_candidates": [dict(candidate) for candidate in output_candidates],
        "effect_prohibitions": list(effect_prohibitions["effect_prohibitions"]),
    }
    schema = _output_provenance_schema(
        output_candidates,
        prohibited_effects=output_ops.resolve_prohibited_effects(effect_prohibitions),
    )
    candidate_bytes = OUTPUT_PROVENANCE_PROMPT.read_bytes()
    candidate_source = candidate_bytes.decode("utf-8").rstrip()
    baseline_source = (
        PromptRegistry()
        .source_text("request_understanding.identify_output_responsibilities")
        .rstrip()
    )
    baseline_instruction = assemble_prompt(
        prompt_ref,
        projection_input,
        execution_scope=DEVELOPMENT_SMOKE,
    )
    if not baseline_instruction.startswith(baseline_source):
        raise ValueError("output Prompt assembly did not preserve the registered base")
    candidate_ref = replace(
        prompt_ref,
        prompt_version="output-provenance-v1-eval",
        content_hash=hashlib.sha256(candidate_bytes).hexdigest(),
    )
    response = client.invoke_structured(
        endpoint=OLLAMA_FIXED_LOOPBACK_ENDPOINT,
        model_id=MODEL_ID,
        prompt_ref=candidate_ref,
        prompt_input=projection_input,
        output_schema=schema,
        timeout_seconds=180,
        instruction_text=(candidate_source + baseline_instruction[len(baseline_source) :]),
        sampling_temperature=0.0,
        sampling_seed=sampling_seed,
    )
    raw = json.loads(cast(str, response.content))
    errors = validate_output_schema(raw, schema.json_schema)
    request_text = str(prompt_input["user_request"])
    raw_responsibilities = raw.get("output_responsibilities", []) if isinstance(raw, dict) else []
    responsibilities: list[dict[str, object]] = []
    for index, responsibility in enumerate(raw_responsibilities):
        if not isinstance(responsibility, dict):
            continue
        source_text = responsibility.get("source_text")
        if not isinstance(source_text, str) or source_text not in request_text:
            errors.append(
                f"$.output_responsibilities[{index}].source_text is not an exact user span"
            )
        responsibilities.append(
            {
                "resource_type": responsibility.get("resource_type"),
                "effect": responsibility.get("effect"),
            }
        )
    return {"output_responsibilities": responsibilities}, [response], errors


def _invoke_change_span_candidate(
    *,
    client: OllamaHTTPClient,
    prompt_ref: PromptReference,
    prompt_input: dict[str, object],
    output_candidates: list[dict[str, object]],
    effect_prohibitions: dict[str, object],
    sampling_seed: int,
) -> tuple[dict[str, object], list[object], list[str]]:
    base_projection = {
        **prompt_input,
        "goal_candidate": {},
        "output_candidates": [dict(candidate) for candidate in output_candidates],
        "effect_prohibitions": list(effect_prohibitions["effect_prohibitions"]),
    }
    span_schema = OutputSchemaDefinition(
        schema_version="request-output-change-spans-v1-eval",
        json_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["requested_changes"],
            "properties": {
                "requested_changes": {
                    "type": "array",
                    "maxItems": 8,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["source_text"],
                        "properties": {"source_text": {"type": "string", "minLength": 1}},
                    },
                }
            },
        },
    )
    span_response = _invoke_prompt_candidate(
        client=client,
        prompt_ref=prompt_ref,
        projection=base_projection,
        output_schema=span_schema,
        candidate_path=CHANGE_SPANS_PROMPT,
        candidate_version="change-spans-v1-eval",
        sampling_seed=sampling_seed,
    )
    span_output = json.loads(cast(str, span_response.content))
    errors = validate_output_schema(span_output, span_schema.json_schema)
    requested_changes = (
        span_output.get("requested_changes", []) if isinstance(span_output, dict) else []
    )
    request_text = str(prompt_input["user_request"])
    for index, change in enumerate(requested_changes):
        source_text = change.get("source_text") if isinstance(change, dict) else None
        if not isinstance(source_text, str) or source_text not in request_text:
            errors.append(f"$.requested_changes[{index}].source_text is not an exact user span")
    if errors or not requested_changes:
        return {"output_responsibilities": []}, [span_response], errors

    mapping_projection = {
        **prompt_input,
        "goal_candidate": {"requested_changes": requested_changes},
        "output_candidates": [dict(candidate) for candidate in output_candidates],
        "effect_prohibitions": list(effect_prohibitions["effect_prohibitions"]),
    }
    output_schema = output_ops.build_output_responsibility_output_schema(
        output_candidates,
        prohibited_effects=output_ops.resolve_prohibited_effects(effect_prohibitions),
    )
    mapping_response = _invoke_prompt_candidate(
        client=client,
        prompt_ref=prompt_ref,
        projection=mapping_projection,
        output_schema=output_schema,
        candidate_path=CHANGE_SPAN_MAPPING_PROMPT,
        candidate_version="change-span-mapping-v1-eval",
        sampling_seed=sampling_seed,
    )
    mapped = json.loads(cast(str, mapping_response.content))
    errors.extend(validate_output_schema(mapped, output_schema.json_schema))
    return mapped, [span_response, mapping_response], errors


def _invoke_prompt_candidate(
    *,
    client: OllamaHTTPClient,
    prompt_ref: PromptReference,
    projection: dict[str, object],
    output_schema: OutputSchemaDefinition,
    candidate_path: Path,
    candidate_version: str,
    sampling_seed: int,
) -> object:
    candidate_bytes = candidate_path.read_bytes()
    candidate_source = candidate_bytes.decode("utf-8").rstrip()
    baseline_source = (
        PromptRegistry()
        .source_text("request_understanding.identify_output_responsibilities")
        .rstrip()
    )
    baseline_instruction = assemble_prompt(
        prompt_ref,
        projection,
        execution_scope=DEVELOPMENT_SMOKE,
    )
    if not baseline_instruction.startswith(baseline_source):
        raise ValueError("output Prompt assembly did not preserve the registered base")
    candidate_ref = replace(
        prompt_ref,
        prompt_version=candidate_version,
        content_hash=hashlib.sha256(candidate_bytes).hexdigest(),
    )
    return client.invoke_structured(
        endpoint=OLLAMA_FIXED_LOOPBACK_ENDPOINT,
        model_id=MODEL_ID,
        prompt_ref=candidate_ref,
        prompt_input=projection,
        output_schema=output_schema,
        timeout_seconds=180,
        instruction_text=(candidate_source + baseline_instruction[len(baseline_source) :]),
        sampling_temperature=0.0,
        sampling_seed=sampling_seed,
    )


def _explicit_disposition_schema(
    output_candidates: list[dict[str, object]],
    *,
    prohibited_effects: set[str],
) -> OutputSchemaDefinition:
    item_variants: list[dict[str, object]] = []
    exact_candidate_constraints: list[dict[str, object]] = []
    for candidate in output_candidates:
        resource_type = cast(str, candidate["resource_type"])
        effects = [
            str(effect)
            for effect in cast(list[object], candidate["allowed_output_effects"])
            if str(effect) not in prohibited_effects
        ]
        requested_variant: dict[str, object] = {
            "type": "object",
            "additionalProperties": False,
            "required": ["resource_type", "disposition", "effect"],
            "properties": {
                "resource_type": {"const": resource_type},
                "disposition": {"const": "NOT_REQUESTED"},
                "effect": {"const": "NONE"},
            },
        }
        variants = [requested_variant]
        if effects:
            variants.append(
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["resource_type", "disposition", "effect"],
                    "properties": {
                        "resource_type": {"const": resource_type},
                        "disposition": {"const": "REQUESTED"},
                        "effect": {"enum": effects},
                    },
                }
            )
        item_variants.extend(variants)
        exact_candidate_constraints.append(
            {
                "contains": {
                    "type": "object",
                    "properties": {"resource_type": {"const": resource_type}},
                    "required": ["resource_type"],
                },
                "minContains": 1,
                "maxContains": 1,
            }
        )
    return OutputSchemaDefinition(
        schema_version="request-output-explicit-disposition-v1-eval",
        json_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["decisions"],
            "properties": {
                "decisions": {
                    "type": "array",
                    "minItems": len(output_candidates),
                    "maxItems": len(output_candidates),
                    "allOf": exact_candidate_constraints,
                    "items": {"oneOf": item_variants},
                }
            },
        },
    )


def _output_provenance_schema(
    output_candidates: list[dict[str, object]],
    *,
    prohibited_effects: set[str],
) -> OutputSchemaDefinition:
    base = output_ops.build_output_responsibility_output_schema(
        output_candidates,
        prohibited_effects=prohibited_effects,
    )
    schema = deepcopy(base.json_schema)
    properties = cast(dict[str, object], schema["properties"])
    decisions = cast(dict[str, object], properties["output_responsibilities"])
    item = cast(dict[str, object], decisions["items"])
    required = cast(list[str], item["required"])
    required.append("source_text")
    item_properties = cast(dict[str, object], item["properties"])
    item_properties["source_text"] = {"type": "string", "minLength": 1}
    return OutputSchemaDefinition(
        schema_version="request-output-provenance-v1-eval",
        json_schema=schema,
    )


def _candidate_prompt_hash(projection: str, *, baseline_hash: str) -> str:
    if projection == "explicit-disposition":
        return hashlib.sha256(EXPLICIT_DISPOSITION_PROMPT.read_bytes()).hexdigest()
    if projection == "two-stage-disposition":
        digest = hashlib.sha256()
        digest.update(CHANGE_GATE_PROMPT.read_bytes())
        digest.update(EXPLICIT_DISPOSITION_PROMPT.read_bytes())
        return digest.hexdigest()
    if projection == "output-provenance":
        return hashlib.sha256(OUTPUT_PROVENANCE_PROMPT.read_bytes()).hexdigest()
    if projection == "two-stage-change-spans":
        digest = hashlib.sha256()
        digest.update(CHANGE_SPANS_PROMPT.read_bytes())
        digest.update(CHANGE_SPAN_MAPPING_PROMPT.read_bytes())
        return digest.hexdigest()
    return baseline_hash


if __name__ == "__main__":
    main()
