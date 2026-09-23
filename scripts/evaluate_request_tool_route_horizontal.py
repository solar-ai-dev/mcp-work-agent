"""Run a bounded Canonical Core Request Understanding -> Tool Route diagnostic.

Only the two compiled production-owner subgraphs execute. No Connector or
Provider is constructed for the graph, and no Retrieval/Planning node runs.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from collections.abc import Mapping
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import fields
from pathlib import Path
from typing import Any, Final, Literal, cast
from uuid import uuid4

from evaluation.dataset_v8 import (
    DEFAULT_DATASET_PATH,
    DEFAULT_PROVIDER_FIXTURE_PATH,
    load_cases,
    normalized_sha256,
)
from langgraph.graph import END, START, StateGraph
from scripts.evaluate_ru_output_input_projection import _request
from scripts.evaluate_ru_source_status_prompt import _RecordingInferencePort

from google_work_agent.adapters.langgraph.main.routing.route_after_supervisor import (
    RESUME_CONTRACT_VERSION,
)
from google_work_agent.adapters.langgraph.main.state import GraphState, initial_graph_state
from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.graph import (
    RequestUnderstandingSubgraph,
)
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.graph import ToolRoutingSubgraph
from google_work_agent.adapters.llm.ollama.transport import OllamaHTTPClient
from google_work_agent.adapters.llm.runtime.llm_credential_router import SessionMemorySecretStore
from google_work_agent.api.composition import ProductionRuntimeConfig, build_production_runtime
from google_work_agent.application.prompt_runtime.prompt_registry import (
    DEVELOPMENT_SMOKE,
    default_prompt_manifest_path,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_development_tool_registry,
)
from google_work_agent.application.use_cases.run.account_provider_dispatch import (
    provider_dispatch_execution_scope,
)
from google_work_agent.application.use_cases.setting.update_settings import UpdateSettingsCommand
from google_work_agent.ports.system.settings_port import SettingsPatchV1

MODEL_ID: Final[Literal["qwen3.5:9b"]] = "qwen3.5:9b"
CORE_CASES = (
    "CASE-CORE-001",
    "CASE-CORE-009",
    "CASE-CORE-012",
    "CASE-CORE-019",
    "CASE-CORE-035",
    "CASE-CORE-037",
    "CASE-CORE-049",
    "CASE-CORE-056",
    "CASE-CORE-059",
)


def _selected_case_ids(*, all_canonical: bool, requested: list[str] | None) -> tuple[str, ...]:
    cases = load_cases()
    if all_canonical and requested:
        raise ValueError("--all-canonical and --case cannot be combined")
    case_ids = tuple(cases) if all_canonical else tuple(requested or CORE_CASES)
    if len(case_ids) != len(set(case_ids)) or any(case_id not in cases for case_id in case_ids):
        raise ValueError("cases must be distinct Canonical v8 IDs")
    return case_ids


class _AtomicRecordingInferencePort(_RecordingInferencePort):
    """Keep local-only owner inputs/outputs so first divergence is inspectable."""

    def __init__(self, delegate: Any) -> None:
        super().__init__(delegate)
        self.atomic: list[dict[str, object]] = []

    def infer(self, *args: Any, **kwargs: Any) -> Any:
        result = super().infer(*args, **kwargs)
        prompt_ref = args[1]
        inference_input = args[2]
        self.atomic.append(
            {
                "sequence": len(self.atomic) + 1,
                "prompt_id": prompt_ref.prompt_id,
                "attempt": (
                    "REVISION"
                    if isinstance(inference_input, Mapping) and "failure_record" in inference_input
                    else "FIRST"
                ),
                "input": deepcopy(inference_input),
                "structured_output": deepcopy(result.structured_output),
            }
        )
        return result


def _merge_decision(
    state: Mapping[str, object], update: Mapping[str, object], decision: Mapping[str, object]
) -> dict[str, object]:
    return {
        **state,
        **update,
        **cast(Mapping[str, object], decision["state_update"]),
        "__target__": decision["target"],
    }


def _confirm_early(_state: object) -> tuple[None, dict[str, object]]:
    return None, {"__target__": "end", "__workflow_control__": {"stage": "PAUSED"}}


def _project_result(state: Mapping[str, Any]) -> dict[str, object]:
    intent = state.get("request_intent")
    plan = state.get("tool_route_plan")
    result: dict[str, object] = {
        "workflow_phase": state.get("workflow_phase"),
        "next_target": state.get("__target__"),
        "confirmation_reason": (
            state["user_interrupt"].get("reason_code")
            if isinstance(state.get("user_interrupt"), dict)
            else None
        ),
    }
    if isinstance(intent, dict):
        responsibilities = intent.get("resource_responsibilities") or {}
        work = intent.get("requested_work") or {}
        result["intent"] = {
            "goal": intent.get("goal"),
            "completion_conditions": intent.get("completion_conditions"),
            "analysis_requirement": intent.get("analysis_requirement"),
            "work_units": [
                {
                    "unit_id": unit.get("unit_id"),
                    "request_provenance": unit.get("request_provenance"),
                }
                for unit in work.get("work_units", [])
            ],
            "relations": work.get("work_relations", []),
            "source_reads": [
                {
                    "resource_type": item.get("resource_type"),
                    "required_information": item.get("required_information"),
                    "work_unit_ids": item.get("work_unit_ids"),
                    "target_scope": item.get("target_scope"),
                }
                for item in responsibilities.get("source_reads", [])
            ],
            "outputs": [
                {
                    "resource_type": item.get("resource_type"),
                    "effect": item.get("effect"),
                    "work_unit_ids": item.get("work_unit_ids"),
                }
                for item in responsibilities.get("outputs", [])
            ],
            "constraints": intent.get("constraints"),
            "effect_prohibitions": intent.get("effect_prohibitions"),
            "ambiguity": intent.get("ambiguity"),
        }
    if isinstance(plan, dict):
        result["route"] = {
            "input_routes": [
                {
                    "route_id": item["route_id"],
                    "resource_type": item["resource_type"],
                    "work_unit_ids": item["work_unit_ids"],
                    "allowed_read_tool_ids": item["allowed_read_tool_ids"],
                    "reason_codes": item["reason_codes"],
                }
                for item in plan["input_plan"]["input_routes"]
            ],
            "output_mode": plan["output_plan"]["output_mode"],
            "output_routes": [
                {
                    "route_id": item["route_id"],
                    "resource_type": item["resource_type"],
                    "effect": item["effect"],
                    "selected_tool_id": item["selected_tool_id"],
                    "work_unit_ids": item["work_unit_ids"],
                }
                for item in plan["output_plan"].get("output_routes", [])
            ],
        }
    return result


def _write(path: Path, result: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _close_container(container: Any) -> None:
    for callback in container.shutdown_callbacks:
        callback()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result-path", type=Path, required=True)
    parser.add_argument("--case", action="append")
    parser.add_argument("--all-canonical", action="store_true")
    parser.add_argument("--seed", type=int, default=20260923)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--record-atomic", action="store_true")
    args = parser.parse_args()
    if args.result_path.exists():
        raise ValueError("result path already exists; preserve every prior trial")
    case_ids = _selected_case_ids(all_canonical=args.all_canonical, requested=args.case)
    cases = load_cases()
    requests = {case_id: _request(case_id, cases[case_id].raw) for case_id in case_ids}
    model = next(
        (item for item in OllamaHTTPClient().list_installed_models() if item.model_id == MODEL_ID),
        None,
    )
    if model is None or model.digest is None:
        raise ValueError("selected local model/digest is unavailable")
    with ExitStack() as close_stack:
        manifest = default_prompt_manifest_path()
        config = ProductionRuntimeConfig.development(
            runtime_root=args.result_path.parent / "_runtime",
            working_directory=Path(__file__).resolve().parents[1],
            mcp_manifest_version="2026-08-07.p0",
            keyring_store=SessionMemorySecretStore(),
            prompt_manifest_path=manifest,
            sampling_temperature=0.0,
            sampling_seed=args.seed,
        )
        container = build_production_runtime(
            **{item.name: getattr(config, item.name) for item in fields(config)},
            bootstrap_secret=uuid4().hex,
            service_instance_id=f"ru-route-horizontal-{uuid4()}",
        )
        close_stack.callback(_close_container, container)
        runtime = container.structured_inference_port
        if runtime is None or container.update_settings_handler is None:
            raise RuntimeError("local structured-inference runtime is unavailable")
        runtime.run_context_provider = lambda: None
        container.update_settings_handler(
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
        recorder = _AtomicRecordingInferencePort(runtime)
        catalog = load_development_tool_registry()
        ids = iter(f"ru-route-{index}" for index in range(100000))

        def new_id() -> str:
            return next(ids)

        request_graph = RequestUnderstandingSubgraph(
            llm_runtime=recorder,
            tool_catalog=catalog,
            prompt_manifest_path=manifest,
            prompt_execution_scope=DEVELOPMENT_SMOKE,
            id_factory=new_id,
            graph_profile=GraphProfile.SIX_ROLE_BASELINE,
            merge_decision=cast(Any, _merge_decision),
            confirm_inline=cast(Any, _confirm_early),
            transition_run=lambda _run_id, _transition: None,
        ).build()
        route_graph = ToolRoutingSubgraph(
            llm_runtime=recorder,
            tool_catalog=catalog,
            prompt_manifest_path=manifest,
            prompt_execution_scope=DEVELOPMENT_SMOKE,
            id_factory=new_id,
            graph_profile=GraphProfile.SIX_ROLE_BASELINE,
            merge_decision=cast(Any, _merge_decision),
            confirm_inline=cast(Any, _confirm_early),
        ).build()
        wrapper = StateGraph(GraphState)
        wrapper.add_node("request_understanding", request_graph)
        wrapper.add_node("tool_routing", route_graph)
        wrapper.add_edge(START, "request_understanding")
        wrapper.add_conditional_edges(
            "request_understanding",
            lambda state: (
                "tool_routing"
                if state.get("request_intent") is not None and state.get("user_interrupt") is None
                else "end"
            ),
            {"tool_routing": "tool_routing", "end": END},
        )
        wrapper.add_edge("tool_routing", END)
        graph = wrapper.compile()
        if args.dry_run:
            print(
                json.dumps(
                    {
                        "cases": case_ids,
                        "model_digest": model.digest,
                        "compiled_nodes": list(graph.nodes),
                    }
                )
            )
            return
        result: dict[str, object] = {
            "binding": {
                "product_sha": subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], text=True
                ).strip(),
                "dataset_sha256": normalized_sha256(DEFAULT_DATASET_PATH),
                "fixture_sha256": normalized_sha256(DEFAULT_PROVIDER_FIXTURE_PATH),
                "prompt_manifest_sha256": normalized_sha256(manifest),
                "model_id": MODEL_ID,
                "model_digest": model.digest,
                "temperature": 0.0,
                "seed": args.seed,
                "graph_version": RESUME_CONTRACT_VERSION,
                "trials_per_case": 1,
                "provider_reads": 0,
                "provider_writes": 0,
                "scope": "COMPILED_RU_TO_TOOL_ROUTE_ONLY",
                "case_count": len(case_ids),
                "split_counts": {
                    split: sum(cases[case_id].raw["split"] == split for case_id in case_ids)
                    for split in ("CORE", "HOLDOUT", "STRESS")
                },
            },
            "cases": [],
        }
        _write(args.result_path, result)
        records = cast(list[dict[str, object]], result["cases"])
        for case_id in case_ids:
            request = requests[case_id]
            recorder.calls.clear()
            recorder.atomic.clear()
            started = time.perf_counter()
            reference_ms = request.run_budget["started_at_ms"]

            def current_time_ms(
                reference_ms: int = reference_ms,
                started: float = started,
            ) -> int:
                return reference_ms + int((time.perf_counter() - started) * 1000)

            record: dict[str, object] = {
                "case_id": case_id,
                "split": cases[case_id].raw["split"],
                "category": cases[case_id].raw["category"],
                "entry_mode": request.entry_mode,
                "selected_resource_count": len(request.selected_resources),
                "selected_resources": [
                    {
                        "connector_id": item.connector_id,
                        "resource_type": item.resource_type,
                        "resource_id": item.resource_id,
                        "parent_resource_id": item.parent_resource_id,
                    }
                    for item in request.selected_resources
                ],
                "reference_time": cases[case_id]
                .raw.get("evaluation_context", {})
                .get("run_reference_time"),
                "fault_profile": cases[case_id].gold.get("fault_profile"),
            }
            try:
                with provider_dispatch_execution_scope(
                    run_id=request.run_id,
                    now_ms=current_time_ms,
                ):
                    state = graph.invoke(
                        initial_graph_state(
                            request,
                            graph_profile=GraphProfile.SIX_ROLE_BASELINE,
                            graph_version=RESUME_CONTRACT_VERSION,
                            initial_target="request.identify_goal",
                        ),
                        {"recursion_limit": 100},
                    )
                record.update(_project_result(state))
                route = record.get("route")
                record["status"] = (
                    "NO_TOOL_NEEDED"
                    if isinstance(route, Mapping)
                    and route.get("output_mode") == "ANSWER"
                    and not route.get("input_routes")
                    else "ROUTE_READY"
                    if route is not None
                    else "WAITING_CONFIRMATION"
                    if state.get("user_interrupt") is not None
                    else "NO_ROUTE"
                )
            except Exception as error:
                record["status"] = "ERROR"
                record["error_type"] = type(error).__name__
                record["error"] = str(error)[:500]
            record["llm"] = {
                "calls": len(recorder.calls),
                "input_tokens": sum(cast(int, call["input_tokens"]) for call in recorder.calls),
                "output_tokens": sum(cast(int, call["output_tokens"]) for call in recorder.calls),
                "reported_latency_ms": sum(
                    cast(int, call["latency_ms"]) for call in recorder.calls
                ),
                "prompts": [call["prompt_id"] for call in recorder.calls],
            }
            if args.record_atomic:
                record["atomic"] = deepcopy(recorder.atomic)
            record["wall_latency_ms"] = int((time.perf_counter() - started) * 1000)
            records.append(record)
            _write(args.result_path, result)
            print(
                json.dumps(
                    {"case_id": case_id, "status": record["status"], "llm": record["llm"]},
                    ensure_ascii=False,
                ),
                flush=True,
            )


if __name__ == "__main__":
    main()
