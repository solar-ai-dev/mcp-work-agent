"""One frozen Query FIRST through current planner/materializer; no Graph or Provider.

The historical checkpoint is read-only. Preparation captures the actual planner
boundary without a model; execution permits one HTTP generation, never repair.
This is a schema-fix diagnostic, not a new MainGraph trial or business score.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import time
from contextlib import suppress
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from scripts.evaluate_effect_prohibition_sampler import head, write_json
from scripts.evaluate_output_format_ablation import file_hash, inspect_diagnostic_model
from scripts.ru_observation import object_hash

from google_work_agent.adapters.langgraph.subgraphs.retrieval.graph import (
    _runtime_route_constraint_policies,
)
from google_work_agent.adapters.llm.ollama import transport
from google_work_agent.adapters.system.sqlite_checkpoint import _CHECKPOINT_VALUE_TYPES
from google_work_agent.application.agents.retrieval.bind_exact_resource_refs import (
    bind_exact_resource_refs,
)
from google_work_agent.application.agents.retrieval.build_query import (
    bind_required_container_constraints,
    build_query,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan_schema import (
    RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
    normalize_retrieval_query_plan_candidate,
)
from google_work_agent.application.agents.retrieval.plan_query import (
    DEFAULT_RETRIEVAL_BUDGET,
    initial_retrieval_planner_input,
    plan_query,
)
from google_work_agent.application.agents.retrieval.resolve_route_container_scopes import (
    resolve_route_container_scopes,
)
from google_work_agent.application.prompt_runtime.assemble_prompt import assemble_prompt
from google_work_agent.application.prompt_runtime.prompt_registry import EVALUATION, PromptRegistry
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.runtime_selection import OLLAMA_FIXED_LOOPBACK_ENDPOINT
from google_work_agent.ports.llm.structured_inference_contracts import OutputSchemaDefinition
from google_work_agent.ports.llm.structured_inference_port import StructuredInferenceResultV1

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "evaluation/results"
SOURCE = RESULTS / "066-core005-main-graph-t3"
CRITERIA = "evaluation/experiments/069-query-exact-ref-model-criteria.md"
PROMPT_ID = "retrieval.plan_query"
MODEL_ID = "qwen3.5:9b"
TIMEOUT_SECONDS = 180
CHECKPOINT_NS = "context_retriever:fc57e314-22e9-8916-d3cc-613ba658d0ab"
CHECKPOINT_ID = "1f1bb53a-c418-681e-8000-23616bc4bf86"
CHECKPOINT_HASH = "801bf02c22f3fbf39529309bbfc2ae4adf423ceae293d53c496ed421638a9b25"
INPUT_HASH = "38b954e7e9cc504b54a9150b36f91d7fb7acae0edfee5674f89d56377b8baf4e"
SOURCE_HASHES = {
    "calls.json": "b86202441c8ebc80a605025bd70d7e09f2eb2bdb83b26098340fec550033497d",
    "plan.json": "45989a931ff52ba20c4efe59521e751b8c97b8a9e9da13f0131f5fc5a5514f8d",
    "runtime/data/google_work_agent.db": (
        "e9a90afc248ec626aea853164e0746b845b80b4f418767b2ab39c3481c18fb8d"
    ),
    "runtime/settings/app-settings.json": (
        "b64170eeefc417792019afdb5df56440552a00e278641c2e2faa4802f68a0d70"
    ),
}


class FirstOnlyBoundReached(RuntimeError):
    """A consumer requested revision, but no second dispatch is authorized."""


class _CapturedFirst(Exception):
    pass


def _read(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def load_authority() -> dict[str, Any]:
    """Load the exact pre-Query checkpoint, never latest-state or coarse inference."""
    if {name: file_hash(SOURCE / name) for name in SOURCE_HASHES} != SOURCE_HASHES:
        raise ValueError("historical authority bytes changed")
    database = SOURCE / "runtime/data/google_work_agent.db"
    connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        connection.execute("PRAGMA query_only=ON")
        rows = connection.execute(
            "SELECT type, checkpoint, metadata FROM checkpoints "
            "WHERE checkpoint_ns=? AND checkpoint_id=?",
            (CHECKPOINT_NS, CHECKPOINT_ID),
        ).fetchall()
    finally:
        connection.close()
    if len(rows) != 1:
        raise ValueError("one exact historical checkpoint required")
    row = rows[0]
    if hashlib.sha256(row[1]).hexdigest() != CHECKPOINT_HASH:
        raise ValueError("historical checkpoint blob changed")
    serde = JsonPlusSerializer(
        allowed_json_modules=_CHECKPOINT_VALUE_TYPES,
        allowed_msgpack_modules=_CHECKPOINT_VALUE_TYPES,
        pickle_fallback=False,
    )
    state = serde.loads_typed((row[0], row[1]))["channel_values"]
    metadata = json.loads(row[2])
    request = state["__request__"]
    call = next(item for item in _read(SOURCE / "calls.json")["calls"] if item["call_index"] == 8)
    source_plan = _read(SOURCE / "plan.json")
    settings = _read(SOURCE / "runtime/settings/app-settings.json")["settings"]
    if (
        state["run_id"] != request.run_id
        or metadata["product_run_id"] != request.run_id
        or state["request_intent"] != call["input"]["request_intent"]
        or request.request_text != call["input"]["user_request"]
        or object_hash(call["input"]) != INPUT_HASH
        or call["input_sha256"] != INPUT_HASH
        or call["prompt_id"] != PROMPT_ID
        or call["wire_request_count"] != 1
        or call["wire_path"] != "/api/generate"
        or call["state"] != "RETURNED"
        or call["model"] != MODEL_ID
        or call["temperature"] is not None
        or call["seed"] != 20260923
        or call["runtime_policy"]["local_timeout_seconds"] != TIMEOUT_SECONDS
        or state.get("acquisition_result") is not None
        or state.get("retrieval_result") is not None
    ):
        raise ValueError("Run/checkpoint/FIRST authority mismatch")
    routes = state["tool_route_plan"]["input_plan"]["input_routes"]
    refs = bind_exact_resource_refs(
        request_intent=state["request_intent"],
        frozen_routes=routes,
        selected_resources=request.selected_resources,
    )["refs_by_route"]
    containers = resolve_route_container_scopes(
        frozen_routes=routes,
        selected_resources=request.selected_resources,
        authorized_tasklist_ids=settings["selected_tasklist_ids"],
        authorized_calendar_ids=settings["selected_calendar_ids"] or [],
    )
    return {
        "call": call,
        "source_plan": source_plan,
        "lineage": {
            "source_directory": SOURCE.relative_to(ROOT).as_posix(),
            "source_hashes": SOURCE_HASHES,
            "checkpoint_namespace": CHECKPOINT_NS,
            "checkpoint_id": CHECKPOINT_ID,
            "checkpoint_sha256": CHECKPOINT_HASH,
            "checkpoint_metadata": metadata,
            "tool_route_plan": state["tool_route_plan"],
            "selected_resources": [asdict(item) for item in request.selected_resources],
            "historical_scope": source_plan["resource_scope"],
            "run_id": request.run_id,
        },
        "context": {
            "prompt_input": initial_retrieval_planner_input(
                user_request=request.request_text,
                request_intent=state["request_intent"],
                input_routes=routes,
                retrieval_budget=DEFAULT_RETRIEVAL_BUDGET,
                validated_resource_refs=refs,
                validated_container_refs=containers,
            ),
            "requested_mode": request.requested_mode,
            "frozen_routes": routes,
            "route_policies": _runtime_route_constraint_policies(routes),
            "validated_resource_refs": refs,
            "validated_container_refs": containers,
            "retry_budget": deepcopy(state["retry_budget"]),
            "now_ms": state["retry_budget"]["started_at_ms"],
            "timezone": settings["timezone"],
        },
    }


def _pipeline(port: Any, authority: dict[str, Any]) -> dict[str, Any]:
    context = deepcopy(authority["context"])
    ref = PromptRegistry().lookup_for_evaluation(PROMPT_ID)
    query, budget, invoked = plan_query(
        llm_runtime=port,
        prompt_ref=ref,
        revision_prompt_ref=ref,
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        **context,
    )
    plans = build_query(
        query,
        **{
            key: context[key]
            for key in (
                "frozen_routes",
                "route_policies",
                "validated_resource_refs",
                "validated_container_refs",
            )
        },
    )
    return {
        "query_plan": query,
        "source_fetch_plans": plans,
        "llm_invoked": invoked,
        "diagnostic_budget": budget,
    }


def wire_projection(
    call: dict[str, Any], prompt_input: Any, schema: OutputSchemaDefinition
) -> dict[str, Any]:
    registry = PromptRegistry()
    ref = registry.lookup_for_evaluation(PROMPT_ID)
    if asdict(ref) != call["prompt_ref"] or prompt_input != call["input"]:
        raise ValueError("current Query FIRST input/Prompt differs from history")
    captured: list[dict[str, Any]] = []

    def capture(**kwargs: Any) -> dict[str, str]:
        captured.append(deepcopy(kwargs))
        return {"response": "{}"}

    with patch.object(transport, "_post_json", capture):
        transport.OllamaHTTPClient().invoke_structured(
            endpoint=OLLAMA_FIXED_LOOPBACK_ENDPOINT,
            model_id=call["model"],
            prompt_ref=ref,
            prompt_input=prompt_input,
            output_schema=schema,
            timeout_seconds=TIMEOUT_SECONDS,
            instruction_text=assemble_prompt(
                ref, prompt_input, registry=registry, execution_scope=EVALUATION
            ),
            sampling_temperature=call["temperature"],
            sampling_seed=call["seed"],
        )
    if len(captured) != 1 or captured[0]["path"] != "/api/generate":
        raise ValueError("unexpected Product transport shape")
    payload = captured[0]["payload"]
    if payload["options"] != call["wire_options"] or payload["think"] != call["wire_think"]:
        raise ValueError("historical Query sampling envelope changed")
    return {
        "input": deepcopy(prompt_input),
        "input_sha256": object_hash(prompt_input),
        "prompt_ref": asdict(ref),
        "schema": deepcopy(schema.json_schema),
        "schema_version": schema.schema_version,
        "wire_payload": payload,
        "wire_sha256": object_hash(payload),
    }


def check_schema_only_change(old: dict[str, Any], current: Any, refs: dict[str, Any]) -> None:
    """Require exactly the adopted selected-ref enum fix, no other schema drift."""
    expected = deepcopy(old)
    details = [
        item
        for item in expected["properties"]["route_queries"]["items"]["oneOf"]
        if item["properties"]["operation"].get("const") == "DETAIL_FETCH"
    ]
    if len(details) != 1:
        raise ValueError("one historical DETAIL_FETCH branch required")
    fields = details[0]["properties"]
    route_id = fields["route_id"].get("const")
    # The historical binder uses a singleton enum for route identity.
    if route_id is None:
        route_id = fields["route_id"]["enum"][0]
    if fields["detail_candidate_ref"] != {"type": "string", "minLength": 1} or not refs.get(
        route_id
    ):
        raise ValueError("unexpected historical detail authority")
    fields["detail_candidate_ref"] = {"type": "string", "enum": sorted(refs[route_id])}
    if expected != current:
        raise ValueError("current schema differs beyond the adopted exact-ref fix")


def _bound_files() -> dict[str, str]:
    paths = {
        p
        for p in (ROOT / "src").rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix not in {".pyc", ".pyo"}
    }
    paths.update(
        ROOT / p
        for p in (
            "scripts/evaluate_query_ref_postfix.py",
            "tests/evaluation/test_query_ref_postfix.py",
            "scripts/evaluate_effect_prohibition_sampler.py",
            "scripts/evaluate_output_format_ablation.py",
            "scripts/ru_observation.py",
            "docs/canonical/15-agent-capability-failure-prompt-contract.md",
            CRITERIA,
        )
    )
    return {p.relative_to(ROOT).as_posix(): file_hash(p) for p in sorted(paths)}


def make_plan(model: dict[str, Any]) -> dict[str, Any]:
    authority = load_authority()
    source_plan, call = authority["source_plan"], authority["call"]
    if (
        not isinstance(model.get("ollama_version_response"), dict)
        or model["ollama_version_response"].get("version") != "0.34.0"
        or model.get("model_id") != source_plan["model"]["id"]
        or model.get("model_digest") != source_plan["model"]["digest"]
        or model.get("ollama_version_sha256") != object_hash(model.get("ollama_version_response"))
    ):
        raise ValueError("hash-bound actual historical model artifact and server version required")
    first: dict[str, Any] = {}

    class Capture:
        def infer(self, mode: Any, ref: Any, value: Any, schema: Any) -> Any:
            if mode != "LOCAL_GPU" or asdict(ref) != call["prompt_ref"] or first:
                raise ValueError("unexpected preparation boundary")
            check_schema_only_change(
                call["output_schema"],
                schema.json_schema,
                authority["context"]["validated_resource_refs"],
            )
            old = wire_projection(
                call, value, OutputSchemaDefinition(schema.schema_version, call["output_schema"])
            )
            if old["wire_sha256"] != call["wire_sha256"]:
                raise ValueError("original actual Product wire was not reproduced")
            first.update(wire_projection(call, value, schema))
            expected = deepcopy(old["wire_payload"])
            expected["format"] = deepcopy(schema.json_schema)
            body = json.loads(expected["prompt"])
            body["output_schema"] = deepcopy(schema.json_schema)
            expected["prompt"] = json.dumps(body, ensure_ascii=False, sort_keys=True)
            if first["wire_payload"] != expected:
                raise ValueError("current wire changed beyond the bounded output schema")
            raise _CapturedFirst

    with suppress(_CapturedFirst):
        _pipeline(Capture(), authority)
    if not first:
        raise ValueError("expected one semantic Query FIRST, not a deterministic shortcut")
    return {
        "schema_version": 1,
        "kind": "QUERY_EXACT_REF_POSTFIX_FIRST_NOT_MAIN_GRAPH",
        "head": head(),
        "bound_files": _bound_files(),
        "model": deepcopy(model),
        "lineage": authority["lineage"],
        "historical_first": call,
        "historical_plan": source_plan,
        "first": first,
        "policy": {
            "max_model_calls": 1,
            "timeout_seconds": TIMEOUT_SECONDS,
            "concurrency": 1,
            "retry": 0,
            "repair": 0,
            "provider_calls": 0,
            "semantic_review": "UNREVIEWED",
            "historical_score_reused": False,
        },
    }


class FirstOnlyPort:
    def __init__(
        self, plan: dict[str, Any], raw: dict[str, Any], raw_path: Path, authority: dict[str, Any]
    ) -> None:
        self.plan, self.raw, self.raw_path = plan, raw, raw_path
        self.context = authority["context"]

    def infer(self, mode: Any, ref: Any, value: Any, schema: Any) -> StructuredInferenceResultV1:
        if self.raw["model_calls"]:
            self.raw["blocked_followup"] = {
                "input": deepcopy(value),
                "prompt_ref": asdict(ref),
                "schema": deepcopy(schema.json_schema),
                "dispatched": False,
            }
            write_json(self.raw_path, self.raw)
            raise FirstOnlyBoundReached("FIRST_ONLY_BOUND_REACHED; no revision dispatch")
        projection = wire_projection(self.plan["historical_first"], value, schema)
        if (
            mode != "LOCAL_GPU"
            or asdict(ref) != projection["prompt_ref"]
            or projection != self.plan["first"]
        ):
            raise ValueError("actual Query boundary differs from sealed FIRST")
        self.raw.update(model_calls=1, state="DISPATCHING", dispatched_at_utc=_utc())
        write_json(self.raw_path, self.raw)
        started = time.perf_counter()
        try:
            response = transport._post_json(
                endpoint=OLLAMA_FIXED_LOOPBACK_ENDPOINT,
                path="/api/generate",
                payload=projection["wire_payload"],
                timeout_seconds=TIMEOUT_SECONDS,
            )
            self.raw["response"] = {
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
            self.raw.update(
                thinking_present=bool(response.get("thinking")),
                thinking_chars=len(str(response.get("thinking", ""))),
            )
        finally:
            self.raw["wall_latency_ms"] = round((time.perf_counter() - started) * 1000)
            write_json(self.raw_path, self.raw)
        if response.get("model") != MODEL_ID or response.get("done") is not True:
            raise ValueError("response model/completion differs from registered FIRST")
        self.raw["structural_validation"] = "INVALID_JSON"
        write_json(self.raw_path, self.raw)
        content = response.get("response")
        if not isinstance(content, str):
            raise ValueError("FIRST response content must be text")
        result = json.loads(content)
        errors = validate_output_schema(result, schema.json_schema)
        self.raw.update(
            first_output=result,
            schema_errors=errors,
            structural_validation="INVALID_SCHEMA" if errors else "VALID",
        )
        write_json(self.raw_path, self.raw)
        if errors:
            raise ValueError("FIRST schema invalid; repair is not authorized")
        # Observation only: Product still receives the unmodified FIRST below.
        try:
            self.raw["normalized_first"] = bind_required_container_constraints(
                normalize_retrieval_query_plan_candidate(deepcopy(result)),
                route_policies=self.context["route_policies"],
                validated_container_refs=self.context["validated_container_refs"],
            )
        except Exception as error:
            self.raw["normalization_failure"] = {
                "type": type(error).__name__,
                "message": str(error),
            }
            # The actual consumer below owns failure/revision routing; the
            # observation must not replace it or change the original candidate.
        finally:
            write_json(self.raw_path, self.raw)
        input_tokens = response.get("prompt_eval_count")
        output_tokens = response.get("eval_count")
        duration = response.get("total_duration")
        return StructuredInferenceResultV1(
            schema_version=1,
            structured_output=result,
            provider="ollama",
            model=MODEL_ID,
            actual_runtime="LOCAL_GPU",
            input_tokens=input_tokens if type(input_tokens) is int else 0,
            output_tokens=output_tokens if type(output_tokens) is int else 0,
            latency_ms=duration // 1_000_000 if type(duration) is int else 0,
            fallback_reason=None,
        )


def _utc() -> str:
    return datetime.now(UTC).isoformat()


def _output(path: Path) -> Path:
    result = path.resolve()
    if result == RESULTS.resolve() or not result.is_relative_to(RESULTS.resolve()):
        raise ValueError("dedicated evaluation/results directory required")
    return result


def execute_plan(plan_path: Path, plan_sha256: str) -> dict[str, Any]:
    output = _output(plan_path.parent)
    if plan_path.resolve() != output / "plan.json" or file_hash(plan_path) != plan_sha256:
        raise ValueError("exact registered plan file/hash required")
    if {p.name for p in output.iterdir()} != {"plan.json"}:
        raise FileExistsError("diagnostic attempt already exists")
    plan = _read(plan_path)
    if make_plan(inspect_diagnostic_model("presence_zero")) != plan:
        raise ValueError("HEAD/source/checkpoint/input/model drift")
    write_json(
        RESULTS / ".query-ref-postfix-trials" / f"{plan_sha256}.json",
        {"plan_sha256": plan_sha256, "output_directory": str(output)},
        exclusive=True,
    )
    write_json(
        output / "attempt.json",
        {"plan_sha256": plan_sha256, "started_at_utc": _utc()},
        exclusive=True,
    )
    raw: dict[str, Any] = {
        "plan_sha256": plan_sha256,
        "state": "PREPARED",
        "first": plan["first"],
        "model_calls": 0,
        "provider_calls": 0,
        "semantic_review": "UNREVIEWED",
    }
    path = output / "raw.json"
    write_json(path, raw, exclusive=True)
    try:
        authority = load_authority()
        raw["consumer_result"] = _pipeline(FirstOnlyPort(plan, raw, path, authority), authority)
        if raw["model_calls"] != 1:
            raise ValueError("expected exactly one Query FIRST")
        raw["state"] = "RETURNED"
    except Exception as error:
        raw.update(
            state="BOUND_REACHED" if isinstance(error, FirstOnlyBoundReached) else "FAILED",
            failure={
                "type": type(error).__name__,
                "message": str(error),
                "reason_code": getattr(error, "reason_code", None),
                "affected_field_paths": list(getattr(error, "affected_field_paths", ()) or ()),
                "validation_stage": getattr(error, "validation_stage", None),
            },
        )
    finally:
        try:
            raw["end_model"] = inspect_diagnostic_model("presence_zero")
            raw["model_binding_unchanged"] = raw["end_model"] == plan["model"]
        except Exception as error:
            raw.update(
                model_binding_unchanged=False,
                end_model_error={"type": type(error).__name__, "message": str(error)},
            )
        raw.update(
            ended_at_utc=_utc(),
            end_head=head(),
            source_binding_unchanged=_bound_files() == plan["bound_files"],
            historical_authority_unchanged={k: file_hash(SOURCE / k) for k in SOURCE_HASHES}
            == SOURCE_HASHES,
        )
        write_json(path, raw)
    return raw


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--prepare", type=Path)
    modes.add_argument("--execute-plan", type=Path)
    parser.add_argument("--plan-sha256")
    args = parser.parse_args()
    if args.prepare:
        output = _output(args.prepare)
        if output.exists() or args.plan_sha256:
            raise ValueError("prepare requires a new result directory and no execution hash")
        plan = make_plan(inspect_diagnostic_model("presence_zero"))
        output.mkdir(parents=True, exist_ok=False)
        write_json(output / "plan.json", plan, exclusive=True)
        print(
            json.dumps(
                {"plan": str(output / "plan.json"), "plan_sha256": file_hash(output / "plan.json")}
            )
        )
    else:
        if not args.plan_sha256:
            parser.error("--execute-plan requires --plan-sha256")
        result = execute_plan(args.execute_plan, args.plan_sha256)
        print(json.dumps({"state": result["state"], "model_calls": result["model_calls"]}))


if __name__ == "__main__":
    main()
