"""Evaluate an offline WorkUnit/WorkRelation Request Understanding candidate."""

from __future__ import annotations

import hashlib
import json
import tempfile
import time
from argparse import ArgumentParser
from dataclasses import fields, replace
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
from google_work_agent.application.agents.request_understanding import (
    identify_source_dependencies as source_ops,
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
from google_work_agent.ports.system.settings_port import SettingsPatchV1

CANDIDATE_PROMPT = Path(
    "evaluation/prompt_candidates/ru-work-unit-v1/sources/" "request_understanding.work_units.md"
)


def main() -> None:
    parser = ArgumentParser()
    parser.add_argument("--result-path", type=Path, required=True)
    parser.add_argument("--case", action="append", required=True)
    parser.add_argument("--sampling-seed", type=int, default=20260914)
    parser.add_argument("--candidate-path", type=Path, default=CANDIDATE_PROMPT)
    parser.add_argument("--candidate-id", default="ru-work-unit-v1")
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
    candidate_bytes = arguments.candidate_path.read_bytes()
    candidate_source = candidate_bytes.decode("utf-8").rstrip()
    candidate_hash = hashlib.sha256(candidate_bytes).hexdigest()
    client = OllamaHTTPClient()
    model_digest = next(
        (model.digest for model in client.list_installed_models() if model.model_id == MODEL_ID),
        None,
    )
    if model_digest != EXPECTED_MODEL_DIGEST:
        raise ValueError("local model digest differs from the preregistered comparison")

    config = ProductionRuntimeConfig.development(
        runtime_root=Path(tempfile.mkdtemp(prefix="gwa-ru-work-unit-")),
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
        service_instance_id=f"ru-work-unit-{uuid4()}",
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
    registry = load_development_tool_registry()
    output_candidates = output_ops.build_output_responsibility_candidates(registry)
    source_candidates = source_ops.build_source_dependency_candidates(registry)
    source_resource_types = sorted(
        {str(candidate["resource_type"]) for candidate in source_candidates}
    )
    output_ref = refs["request_understanding.identify_output_responsibilities"]
    baseline_source = (
        PromptRegistry()
        .source_text("request_understanding.identify_output_responsibilities")
        .rstrip()
    )
    result: dict[str, object] = {
        "binding": {
            "product_sha": _git_head(),
            "dataset_sha256": normalized_sha256(DATASET),
            "model_id": MODEL_ID,
            "model_digest": model_digest,
            "temperature": 0.0,
            "seed": arguments.sampling_seed,
            "baseline_prompt_hash": output_ref.content_hash,
            "candidate_prompt_hash": candidate_hash,
            "candidate_id": arguments.candidate_id,
            "scope": "EVALUATION_ONLY_RU_WORK_UNIT_PAIRED",
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
                run_id=f"ru-work-unit-{case_id}-{uuid4()}",
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

        projection = {
            **prompt_input,
            "goal_candidate": dict(goal_output),
            "output_candidates": [dict(candidate) for candidate in output_candidates],
            "effect_prohibitions": list(prohibitions["effect_prohibitions"]),
        }
        prohibited = output_ops.resolve_prohibited_effects(prohibitions)
        schema = _work_unit_schema(
            source_resource_types=source_resource_types,
            output_candidates=output_candidates,
            prohibited_effects=prohibited,
        )
        baseline_instruction = assemble_prompt(
            output_ref,
            projection,
            execution_scope=DEVELOPMENT_SMOKE,
        )
        if not baseline_instruction.startswith(baseline_source):
            raise ValueError("output Prompt assembly did not preserve the registered base")
        candidate_ref = replace(
            output_ref,
            prompt_id="request_understanding.work_units",
            prompt_version="work-unit-v1-eval",
            content_hash=candidate_hash,
        )
        response = client.invoke_structured(
            endpoint=OLLAMA_FIXED_LOOPBACK_ENDPOINT,
            model_id=MODEL_ID,
            prompt_ref=candidate_ref,
            prompt_input=projection,
            output_schema=schema,
            timeout_seconds=180,
            instruction_text=(candidate_source + baseline_instruction[len(baseline_source) :]),
            sampling_temperature=0.0,
            sampling_seed=arguments.sampling_seed,
        )
        candidate = json.loads(cast(str, response.content))
        validation_errors = [
            *validate_output_schema(candidate, schema.json_schema),
            *_validate_work_units(candidate),
        ]
        candidate_output = _project_outputs(candidate)
        expected = sorted(EXPECTED_OUTPUTS[case_id])
        baseline_pairs = _output_pairs(baseline)
        candidate_pairs = _output_pairs(candidate_output)
        record = {
            "case_id": case_id,
            "expected_output_pairs": expected,
            "baseline_output_pairs": baseline_pairs,
            "candidate_output_pairs": candidate_pairs,
            "baseline_semantic_valid": baseline_pairs == expected,
            "candidate_semantic_valid": not validation_errors and candidate_pairs == expected,
            "candidate_validation_errors": validation_errors,
            "candidate_work_units": candidate.get("work_units", []),
            "candidate_relations": candidate.get("relations", []),
            "prompt_input_sha256": _sha256(projection),
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


def _work_unit_schema(
    *,
    source_resource_types: list[str],
    output_candidates: list[dict[str, object]],
    prohibited_effects: set[str],
) -> OutputSchemaDefinition:
    variants: list[dict[str, object]] = [
        _unit_variant("ANSWER", "NONE", ["NONE"]),
        *[
            _unit_variant("SOURCE_READ", resource_type, ["NONE"])
            for resource_type in source_resource_types
        ],
    ]
    for candidate in output_candidates:
        effects = [
            str(effect)
            for effect in cast(list[object], candidate["allowed_output_effects"])
            if str(effect) not in prohibited_effects
        ]
        if effects:
            variants.append(
                _unit_variant(
                    "OUTPUT_CHANGE",
                    str(candidate["resource_type"]),
                    effects,
                )
            )
    return OutputSchemaDefinition(
        schema_version="request-work-unit-v1-eval",
        json_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["work_units", "relations"],
            "properties": {
                "work_units": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 12,
                    "items": {"oneOf": variants},
                },
                "relations": {
                    "type": "array",
                    "maxItems": 16,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["from_unit_id", "to_unit_id", "kind"],
                        "properties": {
                            "from_unit_id": {"type": "string", "minLength": 1},
                            "to_unit_id": {"type": "string", "minLength": 1},
                            "kind": {"const": "PROVIDES_INPUT_TO"},
                        },
                    },
                },
            },
        },
    )


def _unit_variant(
    responsibility: str,
    resource_type: str,
    effects: list[str],
) -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["unit_id", "responsibility", "resource_type", "effect"],
        "properties": {
            "unit_id": {"type": "string", "minLength": 1},
            "responsibility": {"const": responsibility},
            "resource_type": {"const": resource_type},
            "effect": {"enum": effects},
        },
    }


def _validate_work_units(value: object) -> list[str]:
    if not isinstance(value, dict):
        return ["candidate is not an object"]
    units = value.get("work_units")
    relations = value.get("relations")
    if not isinstance(units, list) or not isinstance(relations, list):
        return []
    unit_ids = [
        str(unit["unit_id"]) for unit in units if isinstance(unit, dict) and "unit_id" in unit
    ]
    errors: list[str] = []
    if len(unit_ids) != len(set(unit_ids)):
        errors.append("work unit ids must be unique")
    known_ids = set(unit_ids)
    for index, relation in enumerate(relations):
        if not isinstance(relation, dict):
            continue
        source = relation.get("from_unit_id")
        target = relation.get("to_unit_id")
        if source not in known_ids or target not in known_ids or source == target:
            errors.append(f"$.relations[{index}] has invalid endpoints")
    outputs = [
        (unit.get("resource_type"), unit.get("effect"))
        for unit in units
        if isinstance(unit, dict) and unit.get("responsibility") == "OUTPUT_CHANGE"
    ]
    if len(outputs) != len(set(outputs)):
        errors.append("output work units must be unique")
    return errors


def _project_outputs(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not isinstance(value.get("work_units"), list):
        return {"output_responsibilities": []}
    return {
        "output_responsibilities": [
            {
                "resource_type": unit["resource_type"],
                "effect": unit["effect"],
            }
            for unit in value["work_units"]
            if isinstance(unit, dict) and unit.get("responsibility") == "OUTPUT_CHANGE"
        ]
    }


if __name__ == "__main__":
    main()
