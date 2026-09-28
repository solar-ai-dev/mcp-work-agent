"""Run a bounded Canonical Core Request Understanding -> Tool Route diagnostic.

Only the two compiled production-owner subgraphs execute. No Connector or
Provider is constructed for the graph, and no Retrieval/Planning node runs.
"""

from __future__ import annotations

import argparse
import hashlib
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
from evaluation.request_semantic_authority_candidate import (
    AtomicSemanticAuthorityCandidate,
    GoalOutputAuthorityCandidate,
    GoalOutputModalityAuthorityCandidate,
    GoalResultModeFirstCandidate,
)
from langgraph.graph import END, START, StateGraph
from scripts.evaluate_ru_output_input_projection import _request
from scripts.evaluate_ru_source_status_prompt import _RecordingInferencePort
from scripts.ru_observation import (
    metrics,
    object_hash,
    observe_local_calls,
    source_chat_envelope,
    source_format_only_envelope,
    source_input_once_envelope,
    thinking_envelope,
)
from scripts.ru_ordered_authority_candidate import OrderedGoalOutputAuthorityCandidate
from scripts.ru_output_source_handoff_candidate import OutputSourceHandoffCandidate
from scripts.ru_request_grounded_goal_candidate import RequestGroundedGoalCandidate
from scripts.ru_scope_authority_candidate import ScopeAuthorityCandidate, scope_authority_candidate
from scripts.ru_source_demand_candidate import (
    JointRoleAuthorityCandidate,
    KeyedSourceCandidate,
    SourceDemandBindingCandidate,
    SourceNeedsThenBindingCandidate,
)
from scripts.ru_source_family_bound_candidate import BoundSourceFamilyCandidate
from scripts.ru_source_family_candidate import SourceFamilyCandidate
from scripts.ru_source_item_repair_candidate import source_item_repair_candidate
from scripts.ru_source_scope_candidate import source_scope_candidate
from scripts.ru_source_scope_handoff_candidate import (
    SourceScopeHandoffCandidate,
    source_scope_handoff_candidate,
)

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
from google_work_agent.adapters.llm.runtime.structured_inference_router import (
    _runtime_policy_for_prompt,
)
from google_work_agent.api.composition import ProductionRuntimeConfig, build_production_runtime
from google_work_agent.application.agents.request_understanding import (
    identify_source_dependencies as source_ops,
)
from google_work_agent.application.agents.request_understanding.contracts import (
    request_goal_candidate_schema as goal_schema_ops,
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
    provider_dispatch_execution_scope,
)
from google_work_agent.application.use_cases.setting.update_settings import UpdateSettingsCommand
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.system.contracts.observability import ObservabilityContext
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
        prompt_ref = args[1]
        inference_input = args[2]
        event = {
            "sequence": len(self.atomic) + 1,
            "prompt_id": prompt_ref.prompt_id,
            "attempt": (
                "REVISION"
                if isinstance(inference_input, Mapping) and "failure_record" in inference_input
                else "FIRST"
            ),
            "input": deepcopy(inference_input),
            "status": "IN_FLIGHT",
        }
        self.atomic.append(event)
        try:
            result = super().infer(*args, **kwargs)
        except Exception as error:
            event.update(status="ERROR", error_type=type(error).__name__, error=str(error)[:500])
            raise
        event.update(status="RETURNED", structured_output=deepcopy(result.structured_output))
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
    parser.add_argument("--source-replay-from", type=Path)
    parser.add_argument("--goal-replay-from", type=Path)
    parser.add_argument("--family-replay-from", type=Path)
    parser.add_argument("--authority-replay-from", type=Path)
    parser.add_argument("--reference-inputs-from", type=Path)
    parser.add_argument("--source-format-only-envelope", action="store_true")
    parser.add_argument("--source-input-once-envelope", action="store_true")
    parser.add_argument("--source-item-repair", action="store_true")
    parser.add_argument("--replay-first-source-payload", action="store_true")
    parser.add_argument("--source-thinking", action="store_true")
    parser.add_argument("--source-chat", action="store_true")
    parser.add_argument("--source-scope-expression", action="store_true")
    parser.add_argument(
        "--semantic-candidate",
        choices=(
            "none",
            "atomic-authority-v2",
            "goal-output-authority-v3",
            "goal-output-modality-authority-v4",
            "result-mode-first-v5",
            "source-demand-binding-v6",
            "source-needs-then-binding-v7",
            "joint-roles-v8",
            "keyed-source-v9",
            "ordered-goal-output-v11",
            "source-family-v15",
            "scope-authority-v16",
            "bound-source-family-v18",
            "output-source-handoff-v20",
            "request-grounded-goal-v21",
            "scope-handoff-v24",
        ),
        default="none",
    )
    args = parser.parse_args()
    if args.source_replay_from and args.goal_replay_from:
        raise ValueError("choose exactly one owner replay boundary")
    if (args.semantic_candidate == "bound-source-family-v18") != bool(args.family_replay_from):
        raise ValueError("bound Source-family candidate requires its frozen family replay")
    if args.family_replay_from and not args.source_replay_from:
        raise ValueError("frozen family refinement must run with Source owner replay")
    if args.authority_replay_from and (
        args.semantic_candidate != "output-source-handoff-v20" or not args.source_replay_from
    ):
        raise ValueError("frozen Output authority requires its Source handoff replay candidate")
    if (
        args.semantic_candidate == "output-source-handoff-v20"
        and args.source_replay_from
        and not args.authority_replay_from
    ):
        raise ValueError("Source handoff replay requires matching frozen Output authority")
    if args.source_thinking and args.source_format_only_envelope:
        raise ValueError("compare one transport axis at a time")
    if args.source_input_once_envelope and (
        args.semantic_candidate != "none"
        or args.source_thinking
        or args.source_chat
        or args.source_format_only_envelope
    ):
        raise ValueError("Source input-once comparison changes only the Product input envelope")
    if args.replay_first_source_payload and (
        not args.source_replay_from or args.semantic_candidate != "none"
    ):
        raise ValueError("first-payload repair replay requires a Product Source owner record")
    if args.source_item_repair and (
        args.semantic_candidate != "none" or args.source_input_once_envelope
        or args.source_thinking or args.source_chat or args.source_format_only_envelope
    ):
        raise ValueError("item repair comparison preserves the Product first-call contract")
    if args.result_path.exists():
        raise ValueError("result path already exists; preserve every prior trial")
    case_ids = _selected_case_ids(all_canonical=args.all_canonical, requested=args.case)
    cases = load_cases()
    reference_records = {}
    if args.reference_inputs_from:
        reference_records = {
            item["case_id"]: item
            for item in json.loads(args.reference_inputs_from.read_text(encoding="utf-8"))["cases"]
        }
    requests = {}
    for case_id in case_ids:
        raw = deepcopy(cases[case_id].raw)
        if reference_records:
            prior = reference_records[case_id]
            goal_input = next(
                item["input"]
                for item in prior["atomic"]
                if item["prompt_id"] == "request_understanding.identify_goal"
            )
            reference = goal_input.get("base_projection", goal_input)["run_reference_time"]
            raw.setdefault("evaluation_context", {})["run_reference_time"] = reference[
                "reference_time"
            ]
        requests[case_id] = _request(case_id, raw)
    replay_path = args.source_replay_from or args.goal_replay_from
    replay_records = (
        {}
        if not replay_path
        else {
            item["case_id"]: item
            for item in json.loads(replay_path.read_text(encoding="utf-8"))["cases"]
        }
    )
    model = next(
        (item for item in OllamaHTTPClient().list_installed_models() if item.model_id == MODEL_ID),
        None,
    )
    if model is None or model.digest is None:
        raise ValueError("selected local model/digest is unavailable")
    with ExitStack() as close_stack:
        if args.semantic_candidate == "scope-authority-v16":
            close_stack.enter_context(scope_authority_candidate())
        elif args.source_scope_expression:
            close_stack.enter_context(source_scope_candidate())
        transport_calls: list[dict[str, Any]] = []
        close_stack.enter_context(observe_local_calls(transport_calls))
        if args.source_input_once_envelope:
            close_stack.enter_context(source_input_once_envelope(transport_calls))
        if args.source_format_only_envelope:
            close_stack.enter_context(source_format_only_envelope(transport_calls))
        if args.source_chat:
            close_stack.enter_context(source_chat_envelope(transport_calls, args.source_thinking))
        elif args.source_thinking:
            close_stack.enter_context(
                thinking_envelope(
                    transport_calls,
                    prompt_ids={"request_understanding.identify_source_dependencies"},
                )
            )
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
        repair_events: list[dict[str, Any]] = []
        if args.source_item_repair:
            close_stack.enter_context(source_item_repair_candidate(runtime, repair_events))
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
        catalog = load_development_tool_registry()
        candidate_class = {
            "atomic-authority-v2": AtomicSemanticAuthorityCandidate,
            "goal-output-authority-v3": GoalOutputAuthorityCandidate,
            "goal-output-modality-authority-v4": (GoalOutputModalityAuthorityCandidate),
            "result-mode-first-v5": GoalResultModeFirstCandidate,
            "source-demand-binding-v6": SourceDemandBindingCandidate,
            "source-needs-then-binding-v7": SourceNeedsThenBindingCandidate,
            "joint-roles-v8": JointRoleAuthorityCandidate,
            "keyed-source-v9": KeyedSourceCandidate,
            "ordered-goal-output-v11": OrderedGoalOutputAuthorityCandidate,
            "source-family-v15": SourceFamilyCandidate,
            "scope-authority-v16": ScopeAuthorityCandidate,
            "bound-source-family-v18": BoundSourceFamilyCandidate,
            "output-source-handoff-v20": OutputSourceHandoffCandidate,
            "request-grounded-goal-v21": RequestGroundedGoalCandidate,
            "scope-handoff-v24": SourceScopeHandoffCandidate,
        }.get(args.semantic_candidate)
        semantic_candidate = (
            candidate_class(
                delegate=runtime,
                tool_catalog=catalog,
                model_id=MODEL_ID,
                sampling_seed=args.seed,
                **(
                    {"family_replay_path": args.family_replay_from}
                    if args.family_replay_from
                    else {}
                ),
                **(
                    {"authority_replay_path": args.authority_replay_from}
                    if args.authority_replay_from
                    else {}
                ),
            )
            if candidate_class is not None
            else None
        )
        recorder = _AtomicRecordingInferencePort(semantic_candidate or runtime)
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
                "product_diff_sha256": hashlib.sha256(
                    subprocess.check_output(["git", "diff", "HEAD", "--", "src"])
                ).hexdigest(),
                "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "dataset_sha256": normalized_sha256(DEFAULT_DATASET_PATH),
                "fixture_sha256": normalized_sha256(DEFAULT_PROVIDER_FIXTURE_PATH),
                "prompt_manifest_sha256": normalized_sha256(manifest),
                "model_id": MODEL_ID,
                "model_digest": model.digest,
                "temperature": 0.0,
                "temperature_scope": (
                    "CONFIGURED_DEFAULT; actual prompt overrides in transport_calls"
                ),
                "seed": args.seed,
                "graph_version": RESUME_CONTRACT_VERSION,
                "trials_per_case": 1,
                "provider_reads": 0,
                "provider_writes": 0,
                "scope": ("GOAL_INPUT_REPLAY" if args.goal_replay_from else "SOURCE_INPUT_REPLAY")
                if replay_records
                else "COMPILED_RU_TO_TOOL_ROUTE_ONLY",
                "source_replay_from": str(args.source_replay_from) if replay_records else None,
                "goal_replay_from": str(args.goal_replay_from) if args.goal_replay_from else None,
                "owner_replay_sha256": (
                    hashlib.sha256(replay_path.read_bytes()).hexdigest() if replay_path else None
                ),
                "reference_inputs_from": str(args.reference_inputs_from)
                if reference_records
                else None,
                "think": False,
                "num_ctx": 16384,
                "source_format_only_envelope": args.source_format_only_envelope,
                "source_input_once_envelope": args.source_input_once_envelope,
                "source_item_repair": args.source_item_repair,
                "source_item_repair_adapter_sha256": (
                    hashlib.sha256(
                        Path(__file__).with_name("ru_source_item_repair_candidate.py").read_bytes()
                    ).hexdigest() if args.source_item_repair else None
                ),
                "replay_first_source_payload": args.replay_first_source_payload,
                "source_thinking": args.source_thinking,
                "source_endpoint": "chat" if args.source_chat else "generate",
                "source_scope_expression": (
                    args.source_scope_expression or args.semantic_candidate == "scope-authority-v16"
                ),
                "semantic_candidate": (
                    None if semantic_candidate is None else semantic_candidate.binding
                ),
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
            transport_calls.clear()
            if semantic_candidate is not None:
                semantic_candidate.reset_case()
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
                "actual_reference_time_ms": reference_ms,
                "fault_profile": cases[case_id].gold.get("fault_profile"),
            }
            repair_events.clear()
            case_stack = ExitStack()
            scope_handoff = None
            try:
                if args.semantic_candidate == "scope-handoff-v24":
                    scope_events: list[dict[str, Any]] = []
                    record["source_scope_handoff_events"] = scope_events
                    scope_handoff = case_stack.enter_context(
                        source_scope_handoff_candidate(
                            user_request=request.request_text,
                            events=scope_events,
                        )
                    )
                if replay_records:
                    replay_prompt_id = (
                        "request_understanding.identify_goal"
                        if args.goal_replay_from
                        else "request_understanding.identify_source_dependencies"
                    )
                    prior_source = next(
                        item
                        for item in replay_records[case_id]["atomic"]
                        if item["prompt_id"] == replay_prompt_id
                    )
                    projection = prior_source["input"]
                    base = projection.get("base_projection", projection)
                    record["owner_input_sha256"] = object_hash(projection)
                    record["actual_owner_reference_time"] = base.get("run_reference_time")
                    work_ids = [item["unit_id"] for item in base["requested_work"]["work_units"]]
                    if scope_handoff is not None:
                        if base["user_request"] != request.request_text:
                            raise ValueError("scope replay request differs from current case")
                        scope_handoff.bind_work_units(work_ids)
                    schema = (
                        goal_schema_ops.identify_goal_output_schema(work_ids)
                        if args.goal_replay_from
                        else source_ops.build_source_dependency_output_schema(
                            source_ops.build_source_dependency_candidates(catalog),
                            work_unit_ids=work_ids,
                        )
                    )
                    prompt_ref = load_prompt_reference(
                        replay_prompt_id, manifest, execution_scope=DEVELOPMENT_SMOKE
                    )
                    if args.replay_first_source_payload:
                        first = next(
                            item for item in replay_records[case_id]["transport_calls"]
                            if item["prompt_id"] == replay_prompt_id
                        )
                        policy = _runtime_policy_for_prompt(runtime.runtime_policy, prompt_ref)
                        if (
                            first["input"] != projection
                            or first["schema_sha256"] != object_hash(schema.json_schema)
                            or first["model"] != MODEL_ID
                            or first["temperature"] != policy.sampling_temperature
                            or first["seed"] != args.seed
                        ):
                            raise ValueError(
                                "frozen first payload has different input/schema/runtime"
                            )
                        approved = runtime.get_approved_model(MODEL_ID)
                        if approved is None or approved.digest != model.digest:
                            raise ValueError(
                                "repair replay requires the current approved model digest"
                            )
                        record["reused_first_dispatch"] = deepcopy(first)
                        record["reused_first_is_new_model_call"] = False
                        structured_output, attempts, _ = runtime._validate_or_repair(
                            provider=runtime.ollama_provider_factory(approved),
                            prompt_ref=prompt_ref,
                            prompt_input=projection,
                            payload=first["content"],
                            output_schema=schema,
                            api_key=None,
                            trace_context=ObservabilityContext(run_id=None),
                            semantic_validate=None,
                            external_transfer_scope=None,
                            runtime_policy=policy,
                        )
                        record["logical_attempts_including_reused_first"] = attempts
                    else:
                        response = recorder.infer("LOCAL_GPU", prompt_ref, projection, schema)
                        structured_output = response.structured_output
                    schema_errors = list(
                        validate_output_schema(structured_output, schema.json_schema)
                    )
                    record.update(
                        status=("GOAL_" if args.goal_replay_from else "SOURCE_")
                        + ("SCHEMA_INVALID" if schema_errors else "RETURNED"),
                        source_output=structured_output,
                        source_schema_errors=schema_errors,
                    )
                    if args.goal_replay_from:
                        record["goal_output"] = record.pop("source_output")
                        record["goal_schema_errors"] = record.pop("source_schema_errors")
                        if scope_handoff is not None and not schema_errors:
                            record["validated_scope_items"] = scope_handoff.raw_scopes(
                                structured_output
                            )
                    record["llm"] = metrics(transport_calls)
                    record["transport_calls"] = deepcopy(transport_calls)
                    record["atomic"] = deepcopy(recorder.atomic)
                    record["source_item_repair_events"] = deepcopy(repair_events)
                    if semantic_candidate is not None:
                        record["semantic_candidate_events"] = deepcopy(semantic_candidate.events)
                    record["wall_latency_ms"] = int((time.perf_counter() - started) * 1000)
                    records.append(record)
                    _write(args.result_path, result)
                    print(
                        json.dumps(
                            {"case_id": case_id, "status": record["status"], "llm": record["llm"]}
                        ),
                        flush=True,
                    )
                    continue
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
                    or state.get("workflow_phase") == "WAITING_CONFIRMATION"
                    else "NO_ROUTE"
                )
            except Exception as error:
                record["status"] = "ERROR"
                record["error_type"] = type(error).__name__
                record["error"] = str(error)[:500]
            finally:
                case_stack.close()
            record["logical_llm"] = {
                "calls": len(recorder.calls)
                - (0 if semantic_candidate is None else semantic_candidate.cached_response_count)
                + (
                    0
                    if semantic_candidate is None
                    else semantic_candidate.additional_provider_call_count
                ),
                "logical_calls": len(recorder.calls),
                "input_tokens": sum(cast(int, call["input_tokens"]) for call in recorder.calls),
                "output_tokens": sum(cast(int, call["output_tokens"]) for call in recorder.calls),
                "reported_latency_ms": sum(
                    cast(int, call["latency_ms"]) for call in recorder.calls
                ),
                "prompts": [call["prompt_id"] for call in recorder.calls],
            }
            record["llm"] = metrics(transport_calls)
            record["transport_calls"] = deepcopy(transport_calls)
            record["source_item_repair_events"] = deepcopy(repair_events)
            if semantic_candidate is not None:
                record["semantic_candidate_events"] = deepcopy(semantic_candidate.events)
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
