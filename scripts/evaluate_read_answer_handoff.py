"""Fixed synthetic Planning handoff FIRST diagnostic, not a Graph/92 evaluation.

Prepare performs no generation. Execute calls actual outline/compose functions,
but deliberately uses direct Product assembly/transport, not the structured
router: at most two FIRST calls, without repair, retries, or a model judge.
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Mapping
from contextlib import suppress
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from scripts.evaluate_effect_prohibition_sampler import head, write_json
from scripts.evaluate_output_format_ablation import file_hash, inspect_diagnostic_model
from scripts.ru_observation import object_hash
from tests.support.task_calendar_evidence import bind_task_calendar_snapshots
from tests.unit.application.agents.planning.test_calendar_answer_authority import (
    _input as calendar_input,
)

from google_work_agent.adapters.llm.ollama import transport
from google_work_agent.application.agents.planning.compose_answer import (
    answer_draft_output_schema,
    compose_answer,
)
from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    PlanningSemanticInvoker,
)
from google_work_agent.application.agents.planning.outline_answer import outline_answer
from google_work_agent.application.agents.request_understanding.contracts import (
    request_goal_candidate_schema,
)
from google_work_agent.application.agents.request_understanding.validate_intent import (
    validate_intent,
)
from google_work_agent.application.prompt_runtime.assemble_prompt import assemble_prompt
from google_work_agent.application.prompt_runtime.prompt_registry import EVALUATION, PromptRegistry
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.runtime_selection import OLLAMA_FIXED_LOOPBACK_ENDPOINT

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "evaluation/results"
CRITERIA = "evaluation/experiments/065-read-answer-handoff-model-criteria.md"
PROMPT_ID = "planning.compose_answer"
MODEL_ID = "qwen3.5:9b"
SEED = 20260923
TIMEOUT_SECONDS = 180
CASE_IDS = ("SYNTHETIC_CALENDAR_SCHEDULE", "SYNTHETIC_CALENDAR_LOCATION", "SYNTHETIC_TASK_NOTES")
SUPPORT_FILES = (
    "scripts/evaluate_read_answer_handoff.py",
    "scripts/evaluate_effect_prohibition_sampler.py",
    "scripts/evaluate_output_format_ablation.py",
    "scripts/ru_observation.py",
    "tests/unit/application/agents/planning/test_calendar_answer_authority.py",
    "tests/evaluation/test_read_answer_handoff_diagnostic.py",
    "tests/support/task_calendar_evidence.py",
    "docs/canonical/15-agent-capability-failure-prompt-contract.md",
    CRITERIA,
)


class FirstOnlyBoundReached(RuntimeError):
    """No additional semantic or repair dispatch belongs to this diagnostic."""


class _CapturedFirst(Exception):
    """Stop preparation at the semantic boundary without fabricating a reply."""


def fixtures() -> list[dict[str, Any]]:
    """Explicit minimal typed Planning projections, not generated RU/Gold inputs."""
    cases: list[dict[str, Any]] = []
    for case_id, fields, request, limit in (
        (CASE_IDS[0], ["start", "end"], "선택한 일정 언제야?", 0),
        (CASE_IDS[1], ["start", "end", "location"], "선택한 일정 시간과 장소 알려줘.", 1),
    ):
        intent, evidence, snapshots = calendar_input(fields)
        cases.append(
            {
                "case_id": case_id,
                "dispatch_limit": limit,
                "pipeline_input": {
                    "user_request": request,
                    "request_intent": intent,
                    "evidence": evidence,
                    "source_snapshots": snapshots,
                    "work_analysis": None,
                },
            }
        )
    intent = {
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["TASK"],
        "analysis_requirement": "NONE",
        "resource_responsibilities": {
            "source_reads": [{"resource_type": "TASK", "required_information": ["notes"]}],
            "outputs": [],
        },
    }
    intent["constraints"] = [
        {
            "kind": "RESOURCE",
            "field": "selected_resource_id",
            "value": ["42"],
            "work_unit_ids": ["work-1"],
        }
    ]
    responsibilities = cast(dict[str, Any], intent["resource_responsibilities"])
    responsibilities["source_reads"][0].update(target_scope="SINGULAR", work_unit_ids=["work-1"])
    task_fields = {"title": "장비 수령 확인", "notes": "장비 수령 항목을 확인할 것."}
    evidence = [
        {
            "evidence_id": "e-task",
            "resource_handle": "task:42",
            "excerpt": "\n".join(f"{key}: {value}" for key, value in task_fields.items()),
        }
    ]
    snapshots = bind_task_calendar_snapshots(evidence, {"e-task": task_fields})
    cases.append(
        {
            "case_id": CASE_IDS[2],
            "dispatch_limit": 1,
            "pipeline_input": {
                "user_request": "선택한 작업의 메모를 알려줘.",
                "request_intent": intent,
                "evidence": evidence,
                "source_snapshots": snapshots,
                "work_analysis": None,
            },
        }
    )
    for case in cases:
        value = case["pipeline_input"]
        request, intent = value["user_request"], value["request_intent"]
        intent.update(
            schema_version=3,
            goal=request,
            completion_conditions=["요청한 정보를 근거로 답한다."],
            effect_prohibitions=[],
            ambiguity={"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
            requested_work={
                "work_units": [
                    {
                        "unit_id": "work-1",
                        "request_provenance": [
                            {
                                "source": "USER_REQUEST",
                                "start_offset": 0,
                                "end_offset": len(request),
                                "source_text": request,
                            }
                        ],
                    }
                ],
                "work_relations": [],
            },
            meta={"artifact_id": case["case_id"] + "-intent", "revision": 1, "based_on": []},
        )
        for item in intent["constraints"]:
            item["work_unit_ids"] = ["work-1"]
        for item in intent["resource_responsibilities"]["source_reads"]:
            item.update(target_scope="SINGULAR", work_unit_ids=["work-1"])
        intent["constraints"].extend(
            request_goal_candidate_schema.derive_source_information_constraints(
                intent["resource_responsibilities"]
            )
        )
        value["request_intent"] = validate_intent(
            intent,
            require_meta=True,
            provenance_sources={"USER_REQUEST": request},
        )
    return cases


def _pipeline(
    case: dict[str, Any], invoke: PlanningSemanticInvoker, record: dict[str, Any]
) -> None:
    value = deepcopy(case["pipeline_input"])
    original_hash = object_hash(value)
    try:
        outline = outline_answer(**value, invoke=invoke)
        record["outline"] = deepcopy(outline)
        record["compose_result"] = compose_answer(
            **value,
            answer_outline=cast(Any, outline),
            invoke=invoke,
        )
    finally:
        record["pipeline_input_unchanged"] = object_hash(value) == original_hash
        if not record["pipeline_input_unchanged"]:
            raise ValueError("Planning mutated its frozen input authority")


def _call_arguments(prompt_input: Mapping[str, object]) -> dict[str, Any]:
    registry = PromptRegistry()
    ref = registry.lookup_for_evaluation(PROMPT_ID)
    outline = cast(Mapping[str, object], prompt_input["answer_outline"])
    schema = answer_draft_output_schema(cast(list[str], outline["evidence_refs"]))
    return {
        "endpoint": OLLAMA_FIXED_LOOPBACK_ENDPOINT,
        "model_id": MODEL_ID,
        "prompt_ref": ref,
        "prompt_input": prompt_input,
        "output_schema": schema,
        "timeout_seconds": TIMEOUT_SECONDS,
        "instruction_text": assemble_prompt(
            ref,
            prompt_input,
            registry=registry,
            execution_scope=EVALUATION,
        ),
        "sampling_temperature": None,
        "sampling_seed": SEED,
    }


def _wire_projection(prompt_input: Mapping[str, object]) -> dict[str, Any]:
    arguments = _call_arguments(prompt_input)
    captured: list[dict[str, Any]] = []

    def capture(**kwargs: Any) -> dict[str, str]:
        captured.append(deepcopy(kwargs))
        return {"response": "{}"}

    with patch.object(transport, "_post_json", capture):
        transport.OllamaHTTPClient().invoke_structured(**arguments)
    if len(captured) != 1 or captured[0]["path"] != "/api/generate":
        raise ValueError("Product transport no longer emits one generate request")
    payload = captured[0]["payload"]
    if payload["think"] is not False or payload["options"] != {"num_ctx": 16384, "seed": SEED}:
        raise ValueError("registered Product runtime envelope changed")
    return {
        "prompt_ref": asdict(arguments["prompt_ref"]),
        "input": deepcopy(prompt_input),
        "input_sha256": object_hash(prompt_input),
        "schema": deepcopy(arguments["output_schema"].json_schema),
        "schema_sha256": object_hash(arguments["output_schema"].json_schema),
        "wire_path": captured[0]["path"],
        "wire_payload": payload,
        "wire_sha256": object_hash(payload),
    }


def _bound_files() -> dict[str, str]:
    paths = {
        path
        for path in (ROOT / "src").rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix not in {".pyc", ".pyo"}
    }
    paths.update(ROOT / relative for relative in SUPPORT_FILES)
    return {path.relative_to(ROOT).as_posix(): file_hash(path) for path in sorted(paths)}


def make_plan(model: dict[str, Any]) -> dict[str, Any]:
    """Seal current sources, fixture, Prompt and exact Product wires; generation=0."""
    if model.get("model_id") != MODEL_ID or not model.get("model_digest"):
        raise ValueError("actual fixed installed model digest required")
    version = model.get("ollama_version_response")
    if not isinstance(version, dict) or model.get("ollama_version_sha256") != object_hash(version):
        raise ValueError("hash-bound actual Ollama version required")
    cases = fixtures()
    for case in cases:
        projection: dict[str, Any] = {}

        def capture(
            prompt_id: str,
            prompt_input: Mapping[str, object],
            *,
            projection: dict[str, Any] = projection,
        ) -> Mapping[str, object]:
            if prompt_id != PROMPT_ID or "base_projection" in prompt_input or projection:
                raise ValueError("only the original compose FIRST belongs to preparation")
            projection.update(_wire_projection(prompt_input))
            raise _CapturedFirst

        prepared: dict[str, Any] = {}
        with suppress(_CapturedFirst):
            _pipeline(case, capture, prepared)
        if bool(projection) != bool(case["dispatch_limit"]):
            raise ValueError("registered deterministic/semantic handoff changed")
        case.update(
            pipeline_input_sha256=object_hash(case["pipeline_input"]),
            prepared=prepared,
            first=projection or None,
        )
    return {
        "schema_version": 1,
        "scope": "SYNTHETIC_PLANNING_FIRST_NOT_GRAPH_OR_CANONICAL92",
        "head": head(),
        "bound_files": _bound_files(),
        "model": deepcopy(model),
        "prompt_refs": {
            prompt_id: asdict(PromptRegistry().lookup_for_evaluation(prompt_id))
            for prompt_id in ("planning.outline_answer", PROMPT_ID)
        },
        "fixture_sha256": object_hash(fixtures()),
        "cases": cases,
        "runtime": {
            "temperature": None,
            "seed": SEED,
            "num_ctx": 16384,
            "think": False,
            "timeout_seconds": TIMEOUT_SECONDS,
            "endpoint": OLLAMA_FIXED_LOOPBACK_ENDPOINT,
            "temperature_none_means_model_default_not_zero": True,
        },
        "policy": {
            "case_order": list(CASE_IDS),
            "trials_per_case": 1,
            "max_model_calls": 2,
            "concurrency": 1,
            "repair": 0,
            "retry": 0,
            "model_judge": 0,
            "external_provider_read_write_send": 0,
            "semantic_review": "UNREVIEWED",
            "input_authority": "FIXED_SYNTHETIC_MINIMAL_TYPED_PROJECTION_NOT_RU_OUTPUT",
        },
    }


def _output_directory(path: Path) -> Path:
    resolved = path.resolve()
    if resolved == RESULTS.resolve() or not resolved.is_relative_to(RESULTS.resolve()):
        raise ValueError("a dedicated evaluation/results subdirectory is required")
    return resolved


def _utc() -> str:
    return datetime.now(UTC).isoformat()


def execute_plan(plan_path: Path, plan_sha256: str) -> dict[str, Any]:
    """One exclusive attempt. Failed FIRSTs remain recorded; no reruns or repair."""
    output = _output_directory(plan_path.parent)
    if plan_path.resolve() != output / "plan.json" or file_hash(plan_path) != plan_sha256:
        raise ValueError("exact registered plan.json/hash required")
    if {path.name for path in output.iterdir()} != {"plan.json"}:
        raise FileExistsError("result directory already contains an attempt or other files")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    current = make_plan(inspect_diagnostic_model("presence_zero"))
    if current != plan:
        raise ValueError("HEAD/source/fixture/Prompt/model/runtime drift since prepare")
    write_json(
        output / "attempt.json",
        {
            "plan_sha256": plan_sha256,
            "started_at_utc": _utc(),
            "head": head(),
        },
        exclusive=True,
    )
    raw: dict[str, Any] = {
        "plan_sha256": plan_sha256,
        "scope": plan["scope"],
        "state": "RUNNING",
        "semantic_review": "UNREVIEWED",
        "cases": [],
        "model_calls": 0,
        "external_provider_read_write_send": 0,
    }
    raw_path = output / "raw.json"
    write_json(raw_path, raw, exclusive=True)
    original_post = transport._post_json
    for case in plan["cases"]:
        row: dict[str, Any] = {
            "case_id": case["case_id"],
            "pipeline_input_sha256": case["pipeline_input_sha256"],
            "state": "RUNNING",
            "semantic_review": "UNREVIEWED",
            "calls": [],
        }
        raw["cases"].append(row)
        write_json(raw_path, raw)

        def invoke(
            prompt_id: str,
            prompt_input: Mapping[str, object],
            *,
            row: dict[str, Any] = row,
            case: dict[str, Any] = case,
        ) -> Mapping[str, object]:
            if (
                prompt_id != PROMPT_ID
                or "base_projection" in prompt_input
                or len(row["calls"]) >= case["dispatch_limit"]
                or raw["model_calls"] >= 2
            ):
                row["blocked_followup"] = {
                    "prompt_id": prompt_id,
                    "input": deepcopy(prompt_input),
                    "dispatched": False,
                }
                write_json(raw_path, raw)
                raise FirstOnlyBoundReached("FIRST_ONLY_BOUND_REACHED; repair/retry not dispatched")
            projection = _wire_projection(prompt_input)
            if projection != case["first"]:
                raise ValueError("actual compose projection differs from the registered FIRST")
            call: dict[str, Any] = {**projection, "state": "PREPARED"}
            row["calls"].append(call)
            write_json(raw_path, raw)

            def dispatch(**kwargs: Any) -> dict[str, Any]:
                if (
                    call["state"] != "PREPARED"
                    or kwargs["path"] != projection["wire_path"]
                    or kwargs["payload"] != projection["wire_payload"]
                    or kwargs["endpoint"] != OLLAMA_FIXED_LOOPBACK_ENDPOINT
                    or kwargs["timeout_seconds"] != TIMEOUT_SECONDS
                ):
                    raise ValueError("unexpected or repeated HTTP dispatch")
                call.update(state="DISPATCHING", dispatched_at_utc=_utc())
                raw["model_calls"] += 1
                write_json(raw_path, raw)
                started = time.perf_counter()
                try:
                    response = original_post(**kwargs)
                    # No thinking content is persisted, even if the provider returns it.
                    call["provider_response"] = {
                        key: response.get(key)
                        for key in (
                            "response",
                            "model",
                            "done",
                            "done_reason",
                            "total_duration",
                            "load_duration",
                            "prompt_eval_duration",
                            "eval_duration",
                            "prompt_eval_count",
                            "eval_count",
                        )
                    }
                    call["thinking_present"] = bool(response.get("thinking"))
                    call["thinking_chars"] = len(str(response.get("thinking", "")))
                    call["state"] = "RETURNED"
                    return response
                except Exception as error:
                    call.update(
                        state="FAILED",
                        failure={"type": type(error).__name__, "message": str(error)},
                    )
                    raise
                finally:
                    call["wall_latency_ms"] = round((time.perf_counter() - started) * 1000)
                    write_json(raw_path, raw)

            with patch.object(transport, "_post_json", dispatch):
                response = transport.OllamaHTTPClient().invoke_structured(
                    **_call_arguments(prompt_input)
                )
            call["transport_result"] = asdict(response)
            write_json(raw_path, raw)
            try:
                if not isinstance(response.content, str):
                    raise TypeError("FIRST response must be JSON text")
                value = json.loads(response.content)
            except (json.JSONDecodeError, TypeError):
                call["structural_validation"] = "INVALID_JSON"
                write_json(raw_path, raw)
                raise
            errors = validate_output_schema(value, projection["schema"])
            call.update(
                structural_validation="INVALID_SCHEMA" if errors else "VALID", schema_errors=errors
            )
            write_json(raw_path, raw)
            if errors:
                raise ValueError("original answer schema validation failed")
            return cast(Mapping[str, object], value)

        try:
            _pipeline(case, invoke, row)
            if len(row["calls"]) != case["dispatch_limit"]:
                raise ValueError("registered handoff call count changed")
            row["state"] = "RETURNED"
        except Exception as error:
            row.update(
                state="FAILED",
                failure={
                    "type": type(error).__name__,
                    "message": str(error),
                    "reason_code": getattr(error, "reason_code", None),
                },
            )
        finally:
            write_json(raw_path, raw)
    raw.update(
        state="FINISHED",
        ended_at_utc=_utc(),
        end_head=head(),
        source_binding_unchanged=_bound_files() == plan["bound_files"],
    )
    write_json(raw_path, raw)
    return raw


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", type=Path, metavar="RESULT_DIR")
    mode.add_argument("--execute-plan", type=Path)
    parser.add_argument("--plan-sha256")
    args = parser.parse_args()
    if args.prepare:
        if args.plan_sha256:
            parser.error("--plan-sha256 belongs to --execute-plan")
        output = _output_directory(args.prepare)
        if output.exists():
            raise FileExistsError("prepare requires a new result directory")
        plan = make_plan(inspect_diagnostic_model("presence_zero"))
        output.mkdir(parents=True, exist_ok=False)
        path = output / "plan.json"
        write_json(path, plan, exclusive=True)
        print(json.dumps({"plan": str(path), "plan_sha256": file_hash(path)}, ensure_ascii=False))
    else:
        if not args.plan_sha256:
            parser.error("--execute-plan requires --plan-sha256")
        raw = execute_plan(args.execute_plan, args.plan_sha256)
        print(json.dumps({"state": raw["state"], "model_calls": raw["model_calls"]}))


if __name__ == "__main__":
    main()
