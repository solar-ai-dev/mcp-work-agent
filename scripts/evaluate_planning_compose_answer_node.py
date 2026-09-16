"""Replay production ``planning.compose_answer`` over persisted synthetic Run states.

The evaluator restores the actual pre-node Planning projection from Canonical v8
checkpoints.  It invokes only the answer composer and the evaluation-only semantic
judge; it does not compile the Product Graph or dispatch a Connector.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
import time
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Literal, cast
from uuid import uuid4

from evaluation.dataset_v8 import CanonicalCaseV8, load_cases
from evaluation.semantic_judge_v8 import review_semantics
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from google_work_agent.adapters.llm.ollama.transport import OllamaHTTPClient
from google_work_agent.adapters.llm.runtime.llm_credential_router import (
    SessionMemorySecretStore,
)
from google_work_agent.adapters.system.sqlite_checkpoint import _CHECKPOINT_VALUE_TYPES
from google_work_agent.api.composition import ProductionRuntimeConfig, build_production_runtime
from google_work_agent.application.agents.planning.compose_answer import (
    answer_draft_output_schema,
    answer_semantic_repair_output_schema,
    compose_answer,
)
from google_work_agent.application.agents.planning.outline_answer import (
    answer_confirmation_allowed,
    answer_outline_output_schema,
    outline_answer,
)
from google_work_agent.application.prompt_runtime.prompt_registry import (
    DEVELOPMENT_SMOKE,
    default_prompt_manifest_path,
    load_prompt_reference,
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
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
)
from google_work_agent.ports.system.settings_port import SettingsPatchV1

DEFAULT_MODEL_ID = "qwen3.5:9b"
SupportedModelId = Literal["qwen3.5:9b", "qwen3.5:4b"]


@dataclass
class _RecordingInferencePort:
    delegate: Any
    results: list[dict[str, object]]

    def infer(self, *args: Any, **kwargs: Any) -> Any:
        result = self.delegate.infer(*args, **kwargs)
        self.results.append(
            {
                "structured_output": result.structured_output,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "latency_ms": result.latency_ms,
            }
        )
        return result

    def reset(self) -> None:
        self.results.clear()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint-root", type=Path, required=True)
    parser.add_argument("--result-path", type=Path, required=True)
    parser.add_argument("--split", choices=("CORE", "STRESS", "HOLDOUT"), default="CORE")
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--model", default=DEFAULT_MODEL_ID)
    parser.add_argument("--sampling-temperature", type=float, default=0.0)
    parser.add_argument("--sampling-seed", type=int, default=1729)
    parser.add_argument("--candidate-id", default="working-tree")
    parser.add_argument(
        "--outline-mode",
        choices=("stored", "replay", "request-scope"),
        default="stored",
    )
    arguments = parser.parse_args()
    result = evaluate(
        checkpoint_root=arguments.checkpoint_root.resolve(),
        result_path=arguments.result_path.resolve(),
        split=arguments.split,
        case_ids=tuple(arguments.case),
        limit=arguments.limit,
        model_id=arguments.model,
        sampling_temperature=arguments.sampling_temperature,
        sampling_seed=arguments.sampling_seed,
        candidate_id=arguments.candidate_id,
        outline_mode=arguments.outline_mode,
    )
    print(json.dumps(result["summary"], ensure_ascii=False, sort_keys=True), flush=True)


def evaluate(
    *,
    checkpoint_root: Path,
    result_path: Path,
    split: str,
    case_ids: tuple[str, ...],
    limit: int | None,
    model_id: str,
    sampling_temperature: float,
    sampling_seed: int,
    candidate_id: str,
    outline_mode: str,
) -> dict[str, object]:
    if model_id not in {"qwen3.5:9b", "qwen3.5:4b"}:
        raise ValueError(f"unsupported local model for node replay: {model_id}")
    supported_model_id = cast(SupportedModelId, model_id)
    cases = load_cases()
    selected = [
        case
        for case in cases.values()
        if case.raw.get("split") == split and (not case_ids or case.case_id in case_ids)
    ]
    if limit is not None:
        selected = selected[:limit]
    if not selected:
        raise ValueError("no Canonical cases matched the requested node corpus")

    manifest_path = default_prompt_manifest_path()
    prompt_refs = {
        prompt_id: load_prompt_reference(
            prompt_id,
            manifest_path=manifest_path,
            execution_scope=DEVELOPMENT_SMOKE,
        )
        for prompt_id in ("planning.outline_answer", "planning.compose_answer")
    }
    installed_models = {
        model.model_id: model.digest for model in OllamaHTTPClient().list_installed_models()
    }
    runtime_root = Path(tempfile.mkdtemp(prefix="gwa-compose-answer-node-"))
    config = ProductionRuntimeConfig.development(
        runtime_root=runtime_root,
        working_directory=Path(__file__).resolve().parents[1],
        mcp_manifest_version="2026-08-07.p0",
        keyring_store=SessionMemorySecretStore(),
        prompt_manifest_path=manifest_path,
        sampling_temperature=sampling_temperature,
        sampling_seed=sampling_seed,
    )
    container = build_production_runtime(
        **{field.name: getattr(config, field.name) for field in fields(config)},
        bootstrap_secret=uuid4().hex,
        service_instance_id=f"compose-answer-node-{uuid4()}",
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
                preferred_local_model_id=supported_model_id,
                preferred_llm_mode="LOCAL_GPU",
                external_llm_consent=False,
            ),
        )
    )

    provider_dispatch_count = 0
    production_before_dispatch = runtime.before_provider_dispatch

    def count_provider_dispatch() -> None:
        nonlocal provider_dispatch_count
        production_before_dispatch()
        provider_dispatch_count += 1

    runtime.before_provider_dispatch = count_provider_dispatch
    recording_runtime = _RecordingInferencePort(runtime, [])
    records: list[dict[str, object]] = []
    started = time.perf_counter()
    for case in selected:
        before = provider_dispatch_count
        recording_runtime.reset()
        record = _evaluate_case(
            case=case,
            checkpoint_root=checkpoint_root,
            llm_runtime=recording_runtime,
            prompt_refs=prompt_refs,
            model_id=model_id,
            outline_mode=outline_mode,
        )
        provider_calls = provider_dispatch_count - before
        record["provider_call_count"] = provider_calls
        record["llm_inference_count"] = len(recording_runtime.results)
        record["input_tokens"] = sum(
            _as_int(result["input_tokens"]) for result in recording_runtime.results
        )
        record["output_tokens"] = sum(
            _as_int(result["output_tokens"]) for result in recording_runtime.results
        )
        record["provider_latency_ms"] = sum(
            _as_int(result["latency_ms"]) for result in recording_runtime.results
        )
        if outline_mode == "replay" and record.get("path_kind") == "LLM":
            record["first_call_classification"] = "NOT_APPLICABLE_MULTI_NODE"
        else:
            record["first_call_classification"] = _first_call_classification(
                record=record,
                path_kind=str(record.get("path_kind", "NOT_APPLICABLE")),
                provider_calls=provider_calls,
                inference_count=len(recording_runtime.results),
            )
        records.append(record)
        print(json.dumps(record, ensure_ascii=True, sort_keys=True), flush=True)

    summary = _summarize_records(
        records=records,
        split=split,
        duration_ms=int((time.perf_counter() - started) * 1000),
        first_call_applicable=outline_mode != "replay",
    )
    result: dict[str, object] = {
        "schema_version": 1,
        "candidate_id": candidate_id,
        "checkpoint_corpus": checkpoint_root.name,
        "model_id": model_id,
        "model_digest": installed_models.get(model_id),
        "sampling_temperature": sampling_temperature,
        "sampling_seed": sampling_seed,
        "outline_mode": outline_mode,
        "summary": summary,
        "cases": records,
    }
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def _evaluate_case(
    *,
    case: CanonicalCaseV8,
    checkpoint_root: Path,
    llm_runtime: _RecordingInferencePort,
    prompt_refs: Mapping[str, Any],
    model_id: str,
    outline_mode: str,
) -> dict[str, object]:
    checkpoint_path = checkpoint_root / case.case_id / "state" / "data" / "google_work_agent.db"
    if not checkpoint_path.is_file():
        return {"case_id": case.case_id, "outcome": "SKIP_CHECKPOINT_MISSING"}
    state = _load_node_state(checkpoint_path)
    if state is None:
        return {"case_id": case.case_id, "outcome": "SKIP_NO_NODE_INPUT"}
    request_intent = state.get("request_intent")
    answer_outline = state.get("answer_outline")
    retrieval_result = state.get("retrieval_result")
    evidence = state.get("evidence_drafts", [])
    if (
        not isinstance(request_intent, Mapping)
        or not isinstance(answer_outline, Mapping)
        or (retrieval_result is not None and not isinstance(retrieval_result, Mapping))
        or not isinstance(evidence, list)
    ):
        return {"case_id": case.case_id, "outcome": "SKIP_NO_NODE_INPUT"}
    work_analysis = state.get("work_analysis_result")
    if work_analysis is not None and not isinstance(work_analysis, Mapping):
        return {"case_id": case.case_id, "outcome": "SKIP_NO_NODE_INPUT"}
    confirmation_response = _confirmation_response(state)
    user_request = cast(str, case.raw["canonical_user_prompt"])
    if outline_mode == "request-scope":
        refs = [
            ref
            for item in evidence
            if isinstance(item, Mapping)
            for ref in (item.get("evidence_ref") or item.get("evidence_id") or item.get("id"),)
            if isinstance(ref, str) and ref
        ]
        answer_outline = {
            "sections": [user_request],
            "evidence_refs": list(dict.fromkeys(refs)),
        }
    elif outline_mode not in {"stored", "replay"}:
        raise ValueError(f"unsupported outline mode: {outline_mode}")

    llm_path_entered = False

    def invoke_outline(
        prompt_id: str, prompt_input: Mapping[str, object]
    ) -> Mapping[str, object]:
        nonlocal llm_path_entered
        llm_path_entered = True
        if prompt_id != "planning.outline_answer":
            raise ValueError(f"unsupported Planning Prompt slot: {prompt_id}")
        allowed_refs = [
            ref
            for item in evidence
            if isinstance(item, Mapping)
            for ref in (item.get("evidence_ref") or item.get("evidence_id") or item.get("id"),)
            if isinstance(ref, str) and ref
        ]
        result = llm_runtime.infer(
            "LOCAL_GPU",
            prompt_refs[prompt_id],
            prompt_input,
            answer_outline_output_schema(
                allowed_refs,
                confirmation_allowed=answer_confirmation_allowed(
                    request_intent,
                    cast(Mapping[str, object] | None, work_analysis),
                ),
            ),
        )
        return cast(Mapping[str, object], result.structured_output)

    def invoke_compose(
        prompt_id: str, prompt_input: Mapping[str, object]
    ) -> Mapping[str, object]:
        nonlocal llm_path_entered
        llm_path_entered = True
        if prompt_id != "planning.compose_answer":
            raise ValueError(f"unsupported Planning Prompt slot: {prompt_id}")
        schema_projection = prompt_input
        base_projection = prompt_input.get("base_projection")
        if isinstance(base_projection, Mapping):
            schema_projection = base_projection
        outline = schema_projection.get("answer_outline")
        if not isinstance(outline, Mapping):
            raise ValueError("compose_answer requires answer_outline")
        refs = outline.get("evidence_refs")
        if not isinstance(refs, list) or not all(isinstance(ref, str) for ref in refs):
            raise ValueError("compose_answer requires outline evidence_refs")
        failure_record = prompt_input.get("failure_record")
        output_schema: OutputSchemaDefinition = answer_draft_output_schema(refs)
        if (
            isinstance(failure_record, Mapping)
            and failure_record.get("failure_reason_code") == "COMPOSE_ANSWER_PROSE_INVALID"
        ):
            output_schema = answer_semantic_repair_output_schema(refs)
        result = llm_runtime.infer(
            "LOCAL_GPU",
            prompt_refs[prompt_id],
            prompt_input,
            output_schema,
        )
        return cast(Mapping[str, object], result.structured_output)

    started = time.perf_counter()
    run_budget = build_default_run_budget(started_at_ms=int(time.time() * 1000))
    try:
        with (
            provider_dispatch_execution_scope(
                run_id=f"node-replay-{case.case_id}-{uuid4()}",
                now_ms=lambda: int(time.time() * 1000),
            ),
            provider_dispatch_budget_scope(run_budget),
        ):
            if outline_mode == "replay":
                generated_outline = outline_answer(
                    user_request=user_request,
                    request_intent=request_intent,
                    work_analysis=cast(Mapping[str, object] | None, work_analysis),
                    evidence=cast(list[Mapping[str, object]], evidence),
                    invoke=invoke_outline,
                    confirmation_response=confirmation_response,
                    retrieval_result=retrieval_result,
                )
                if generated_outline.get("disposition") == "NEEDS_CONFIRMATION":
                    raise ValueError("outline_answer requested confirmation before composition")
                answer_outline = generated_outline
            answer = compose_answer(
                user_request=user_request,
                request_intent=request_intent,
                answer_outline=cast(Any, answer_outline),
                work_analysis=cast(Mapping[str, object] | None, work_analysis),
                evidence=cast(list[Mapping[str, object]], evidence),
                invoke=invoke_compose,
                confirmation_response=confirmation_response,
                retrieval_result=retrieval_result,
            )
        semantic_review = review_semantics(
            required_semantics=cast(str, case.gold["required_semantics"]),
            forbidden_semantics=cast(str, case.gold["forbidden_semantics"]),
            observation={
                "public_status": None,
                "terminal_result_kind": None,
                "assistant_final_message": answer["answer"],
                "actions": [],
                "context_preview": {
                    "items": [dict(item) for item in evidence],
                    "coverage": (
                        retrieval_result.get("coverage")
                        if isinstance(retrieval_result, Mapping)
                        else None
                    ),
                    "missing_information": (
                        retrieval_result.get("missing_information", [])
                        if isinstance(retrieval_result, Mapping)
                        else []
                    ),
                },
                "error": None,
            },
            model=model_id,
        )
        semantic_valid = (
            semantic_review["required_semantics_satisfied"] is True
            and semantic_review["forbidden_semantics_observed"] is False
        )
        return {
            "case_id": case.case_id,
            "outcome": "SEMANTIC_VALID" if semantic_valid else "SEMANTIC_INVALID",
            "path_kind": "LLM" if llm_path_entered else "DETERMINISTIC",
            "semantic_review": semantic_review,
            "answer": answer["answer"],
            "evidence_ref_count": len(answer["evidence_refs"]),
            "duration_ms": int((time.perf_counter() - started) * 1000),
        }
    except Exception as error:
        return {
            "case_id": case.case_id,
            "outcome": "FAILED",
            "path_kind": "LLM" if llm_path_entered else "DETERMINISTIC",
            "error_type": type(error).__name__,
            "error_message": str(error),
            "reason_code": getattr(error, "reason_code", None),
            "affected_field_paths": list(getattr(error, "affected_field_paths", ())),
            "duration_ms": int((time.perf_counter() - started) * 1000),
        }


def _summarize_records(
    *,
    records: list[dict[str, object]],
    split: str,
    duration_ms: int,
    first_call_applicable: bool = True,
) -> dict[str, object]:
    node_inputs = [
        record for record in records if not str(record["outcome"]).startswith("SKIP_")
    ]
    deterministic_records = [
        record for record in node_inputs if record.get("path_kind") == "DETERMINISTIC"
    ]
    llm_records = [record for record in node_inputs if record.get("path_kind") == "LLM"]
    dispatched = [
        record for record in llm_records if _as_int(record["provider_call_count"]) > 0
    ]
    first_call_valid = sum(
        record["first_call_classification"] == "SEMANTIC_VALID"
        for record in llm_records
    )
    final_valid = sum(record["outcome"] == "SEMANTIC_VALID" for record in node_inputs)
    classifications = Counter(
        str(record["first_call_classification"]) for record in llm_records
    )
    repair_attempted = [
        record
        for record in llm_records
        if _as_int(record["provider_call_count"]) > 1
        or _as_int(record["llm_inference_count"]) > 1
    ]
    return {
        "split": split,
        "case_count": len(records),
        "node_input_count": len(node_inputs),
        "deterministic_path_count": len(deterministic_records),
        "deterministic_semantic_valid_count": sum(
            record["outcome"] == "SEMANTIC_VALID"
            for record in deterministic_records
        ),
        "llm_path_target_count": len(llm_records),
        "llm_dispatched_count": len(dispatched),
        "first_call_semantic_valid_count": (
            first_call_valid if first_call_applicable else None
        ),
        "first_call_semantic_valid_rate": (
            first_call_valid / len(llm_records)
            if first_call_applicable and llm_records
            else None
        ),
        "first_call_dispatched_semantic_valid_rate": (
            first_call_valid / len(dispatched)
            if first_call_applicable and dispatched
            else None
        ),
        "first_call_schema_valid_semantic_invalid_count": (
            classifications.get("SCHEMA_VALID_SEMANTIC_INVALID", 0)
            if first_call_applicable
            else None
        ),
        "repair_attempted_count": (
            len(repair_attempted) if first_call_applicable else None
        ),
        "repair_recovered_count": (
            sum(record["outcome"] == "SEMANTIC_VALID" for record in repair_attempted)
            if first_call_applicable
            else None
        ),
        "repair_still_failed_count": (
            sum(record["outcome"] != "SEMANTIC_VALID" for record in repair_attempted)
            if first_call_applicable
            else None
        ),
        "final_semantic_valid_count": final_valid,
        "final_semantic_invalid_count": len(node_inputs) - final_valid,
        "first_call_classifications": dict(sorted(classifications.items())),
        "provider_dispatch_count": sum(
            _as_int(record["provider_call_count"]) for record in records
        ),
        "input_tokens": sum(_as_int(record["input_tokens"]) for record in records),
        "output_tokens": sum(_as_int(record["output_tokens"]) for record in records),
        "provider_latency_ms": sum(
            _as_int(record["provider_latency_ms"]) for record in records
        ),
        "duration_ms": duration_ms,
    }


def _first_call_classification(
    *,
    record: Mapping[str, object],
    path_kind: str,
    provider_calls: int,
    inference_count: int,
) -> str:
    outcome = str(record["outcome"])
    if outcome.startswith("SKIP_"):
        return "NOT_APPLICABLE_SKIPPED"
    if path_kind == "DETERMINISTIC":
        return "NOT_APPLICABLE_DETERMINISTIC"
    if path_kind != "LLM":
        raise ValueError(f"unsupported path kind: {path_kind}")
    if provider_calls == 0:
        return "PRE_DISPATCH_FAILED"
    if outcome == "FAILED":
        return (
            "SCHEMA_INVALID"
            if not inference_count or provider_calls > inference_count
            else "FAILED"
        )
    if outcome == "SEMANTIC_INVALID":
        return "SCHEMA_VALID_SEMANTIC_INVALID"
    if provider_calls > 1 or inference_count > 1:
        return "REPAIR_RECOVERED"
    return "SEMANTIC_VALID"


def _confirmation_response(state: Mapping[str, object]) -> Mapping[str, object] | None:
    prompt_context = state.get("prompt_context")
    if not isinstance(prompt_context, Mapping):
        return None
    value = prompt_context.get("confirmation_response")
    return value if isinstance(value, Mapping) else None


def _load_node_state(database_path: Path) -> dict[str, object] | None:
    connection = sqlite3.connect(
        f"file:{database_path.resolve().as_posix()}?mode=ro",
        uri=True,
    )
    try:
        rows = connection.execute(
            "SELECT type, checkpoint FROM checkpoints ORDER BY checkpoint_id"
        ).fetchall()
    finally:
        connection.close()
    serde = JsonPlusSerializer(
        allowed_json_modules=_CHECKPOINT_VALUE_TYPES,
        allowed_msgpack_modules=_CHECKPOINT_VALUE_TYPES,
        pickle_fallback=False,
    )
    evidence_drafts: list[object] = []
    for row in rows:
        checkpoint = serde.loads_typed((row[0], bytes(row[1])))
        values = checkpoint.get("channel_values")
        if not isinstance(values, dict):
            continue
        if isinstance(values.get("evidence_drafts"), list):
            evidence_drafts = list(values["evidence_drafts"])
        if "branch:to:compose_answer" in values:
            return {**values, "evidence_drafts": evidence_drafts}
    return None


def _as_int(value: object) -> int:
    if isinstance(value, bool | int):
        return int(value)
    raise TypeError(f"expected integer metric, got {type(value).__name__}")


if __name__ == "__main__":
    main()
