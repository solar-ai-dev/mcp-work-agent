"""Replay frozen action plans through compiled production Review/Planning/RECHECK."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

from langgraph.graph import END, START, StateGraph
from scripts.evaluate_retrieval_connected_segment import (
    _IdFactory,
    _merge_decision,
    _raise_confirmation_required,
    _RecordingInferencePort,
)
from scripts.evaluate_retrieval_plan_query_node import _load_latest_state
from scripts.evaluate_review_decomposition_node import MODEL_ID, _runtime

from google_work_agent.adapters.langgraph.main.routing.route_after_supervisor import (
    RESUME_CONTRACT_VERSION,
)
from google_work_agent.adapters.langgraph.main.state import (
    GraphState,
    WorkflowPhase,
    initial_graph_state,
)
from google_work_agent.adapters.langgraph.main.supervisor_artifact_revisions import (
    artifact_freshness_violation,
)
from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile
from google_work_agent.adapters.langgraph.registry.node_registry import NodeRegistry
from google_work_agent.adapters.langgraph.registry.resume_target_registry import (
    ResumeTargetRegistry,
)
from google_work_agent.adapters.langgraph.subgraphs.planning.graph import PlanningSubgraph
from google_work_agent.adapters.langgraph.subgraphs.review.graph import ReviewSubgraph
from google_work_agent.adapters.langgraph.subgraphs.review.projections import (
    inspect_goal_and_evidence_projection as goal_projection,
)
from google_work_agent.adapters.llm.ollama.transport import OllamaHTTPClient
from google_work_agent.adapters.system.memory.retrieval_evidence_store import (
    RunScopedEvidenceStore,
)
from google_work_agent.application.prompt_runtime.prompt_registry import (
    DEVELOPMENT_SMOKE,
    default_prompt_manifest_path,
)
from google_work_agent.application.use_cases.run.account_provider_dispatch import (
    provider_dispatch_budget_scope,
    provider_dispatch_execution_scope,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.system.contracts.workflow_execution import WorkflowStartRequest

LABELS = (
    "NORMAL_023",
    "WRONG_DATE_023",
    "FORBIDDEN_ATTENDEE_023",
    "USER_EDIT_023",
    "MISSING_MAIL_023",
    "NORMAL_028",
)
REVISE_LABELS = {"WRONG_DATE_023", "FORBIDDEN_ATTENDEE_023"}


def _saved_input(case: dict[str, Any]) -> dict[str, Any]:
    details = case["work_analysis"]["downstream"]["inference_details"]
    goal = next(
        item["prompt_input"]
        for item in details
        if item["prompt_id"] == "review.inspect_goal_and_evidence"
    )
    route = next(
        item["prompt_input"]
        for item in details
        if item["prompt_id"] == "review.inspect_action_scope_and_route"
    )
    return {
        "request_intent": goal["request_intent"],
        "tool_route_plan": route["tool_route_plan"],
        "work_analysis": goal["work_analysis"],
        "evidence": goal["evidence"],
        "planning_result": goal["planning_result"],
        "started_at_ms": case["reference_started_at_ms"],
    }


def _scenario_inputs(
    connected: dict[str, Any], counterexamples: dict[str, Any]
) -> list[tuple[str, str, dict[str, Any]]]:
    cases = {item["case_id"]: item for item in connected["cases"]}
    if set(cases) != {"CASE-CORE-023", "CASE-CORE-028"}:
        raise ValueError("frozen connected case set changed")
    base_023 = _saved_input(cases["CASE-CORE-023"])
    base_028 = _saved_input(cases["CASE-CORE-028"])
    trials = {item["label"]: item for item in counterexamples["trials"]}
    required = {
        "WRONG_ACTION_DATE",
        "FORBIDDEN_ATTENDEE",
        "USER_PREVIEW_EDIT_CLEAR",
        "MISSING_EXTERNAL_MAIL",
    }
    if not required.issubset(trials):
        raise ValueError("frozen counterexample set changed")
    rows: list[tuple[str, str, dict[str, Any]]] = []
    for label in LABELS:
        source_case = "CASE-CORE-028" if label == "NORMAL_028" else "CASE-CORE-023"
        original = base_028 if label == "NORMAL_028" else base_023
        candidate = json.loads(json.dumps(original, ensure_ascii=False))
        if label == "WRONG_DATE_023":
            candidate["planning_result"] = trials["WRONG_ACTION_DATE"]["prompt_input"][
                "planning_result"
            ]
        elif label == "FORBIDDEN_ATTENDEE_023":
            source = trials["FORBIDDEN_ATTENDEE"]["prompt_input"]
            candidate["planning_result"] = source["planning_result"]
            candidate["request_intent"] = source["request_intent"]
            original_request = next(
                item["excerpt"]
                for item in candidate["evidence"]
                if item.get("origin_type") == "USER_MESSAGE"
            )
            candidate["user_request_text"] = f"{original_request} 참석자는 초대하지 마."
            for item in candidate["evidence"]:
                if item.get("origin_type") == "USER_MESSAGE":
                    item["excerpt"] = candidate["user_request_text"]
            for constraint in candidate["request_intent"]["constraints"]:
                if constraint.get("field") == "original_search_request":
                    constraint["value"] = [candidate["user_request_text"]]
        elif label == "USER_EDIT_023":
            source = trials["USER_PREVIEW_EDIT_CLEAR"]["prompt_input"]
            candidate["planning_result"] = source["planning_result"]
            candidate["user_action_modifications"] = source["user_action_modifications"]
        elif label == "MISSING_MAIL_023":
            source = trials["MISSING_EXTERNAL_MAIL"]["prompt_input"]
            candidate["planning_result"] = source["planning_result"]
            candidate["evidence"] = source["evidence"]
            candidate["work_analysis"] = source["work_analysis"]
        route_ids = {
            item["route_id"]
            for item in candidate["tool_route_plan"]["output_plan"]["output_routes"]
        }
        if any(
            action["route_id"] not in route_ids
            for action in candidate["planning_result"]["actions"]
        ):
            raise ValueError(f"{label} escaped its frozen route")
        rows.append((label, source_case, candidate))
    return rows


def _wrap(graph: Any, name: str) -> Any:
    wrapper = StateGraph(GraphState)
    wrapper.add_node(name, graph)
    wrapper.add_edge(START, name)
    wrapper.add_edge(name, END)
    return wrapper.compile()


def _build_case_state(
    *,
    label: str,
    source_case: str,
    candidate: dict[str, Any],
    checkpoint_root: Path,
) -> tuple[GraphState, RunScopedEvidenceStore, GraphProfile]:
    database = checkpoint_root / source_case / "state" / "data" / "google_work_agent.db"
    persisted = _load_latest_state(database)
    request = persisted.get("__request__")
    if not isinstance(request, WorkflowStartRequest):
        raise ValueError(f"{source_case} has no saved WorkflowStartRequest")
    run_id = f"planning-review-cycle-{label.lower()}"
    budget = build_default_run_budget(started_at_ms=candidate["started_at_ms"])
    replay_request = replace(
        request,
        run_id=run_id,
        workflow_key=run_id,
        requested_mode="LOCAL_GPU",
        request_text=candidate.get("user_request_text", request.request_text),
        run_budget=budget,
    )
    profile = GraphProfile(str(persisted.get("graph_profile", "SIX_ROLE_BASELINE")))
    state = initial_graph_state(
        replay_request,
        graph_profile=profile,
        graph_version="planning-review-cycle-evaluation-v1",
        initial_target="review_entry",
    )
    state["workflow_phase"] = WorkflowPhase.PLAN_REVIEW.value
    state["request_intent"] = candidate["request_intent"]
    state["tool_route_plan"] = candidate["tool_route_plan"]
    state["work_analysis_result"] = candidate["work_analysis"]
    state["planning_result"] = candidate["planning_result"]
    state["__modify_review_changes__"] = candidate.get("user_action_modifications")
    evidence = candidate["evidence"]
    external = [item for item in evidence if item.get("origin_type") != "USER_MESSAGE"]
    user = [item for item in evidence if item.get("origin_type") == "USER_MESSAGE"]
    if len(user) != 1 or user[0]["message_id"] != replay_request.user_message_id:
        raise ValueError(f"{label} user Evidence does not match current Run")
    evidence_store = RunScopedEvidenceStore()
    evidence_store.put(run_id=run_id, evidence_drafts=cast(Any, external))
    retrieval_ref = candidate["work_analysis"]["meta"]["based_on"][-1]
    intent_meta = candidate["request_intent"]["meta"]
    input_plan_meta = candidate["tool_route_plan"]["input_plan"]["meta"]
    retrieval_dependencies = [
        {"artifact_id": meta["artifact_id"], "revision": meta["revision"]}
        for meta in (intent_meta, input_plan_meta)
    ]
    state["retrieval_result"] = {
        "schema_version": 1,
        "meta": {**retrieval_ref, "based_on": retrieval_dependencies},
        "coverage": "PARTIAL" if label == "MISSING_MAIL_023" else "SUFFICIENT",
        "context_bundle_ref": None,
        "evidence_refs": [item["evidence_id"] for item in external],
        "selected_segment_ids": [item["segment_id"] for item in external],
        "excluded_segment_ids": [],
        "source_resource_refs": [item["resource_handle"] for item in external],
        "source_statuses": [],
        "availability_results": [],
        "missing_information": [],
        "retrieval_rounds": 1,
    }
    freshness_reason = artifact_freshness_violation(WorkflowPhase.PLAN_REVIEW, state)
    if freshness_reason is not None:
        raise ValueError(f"{label} reconstructed State is stale: {freshness_reason}")
    return state, evidence_store, profile


def _graph_pair(
    *,
    recorder: _RecordingInferencePort,
    evidence_store: RunScopedEvidenceStore,
    profile: GraphProfile,
    label: str,
    calendar_id: str | None,
) -> tuple[Any, Any, ReviewSubgraph]:
    registry = ResumeTargetRegistry(
        node_registry=NodeRegistry(graph_version=RESUME_CONTRACT_VERSION),
        graph_version=RESUME_CONTRACT_VERSION,
    )
    review_owner = ReviewSubgraph(
        llm_runtime=recorder,
        prompt_manifest_path=None,
        prompt_execution_scope=DEVELOPMENT_SMOKE,
        id_factory=_IdFactory(f"{label}-review"),
        graph_profile=profile,
        merge_decision=cast(Any, _merge_decision),
        evidence_store=evidence_store,
        load_persisted_evidence=lambda _: [],
        confirm_inline=lambda _: (_raise_confirmation_required(), None),
        resume_target_registry=registry,
    )
    planning_owner = PlanningSubgraph(
        llm_runtime=recorder,
        prompt_manifest_path=None,
        prompt_execution_scope=DEVELOPMENT_SMOKE,
        id_factory=_IdFactory(f"{label}-planning"),
        graph_profile=profile,
        merge_decision=cast(Any, _merge_decision),
        evidence_store=evidence_store,
        confirm_inline=lambda _: (_raise_confirmation_required(), None),
        default_calendar_id_provider=lambda: calendar_id,
        default_tasklist_id_provider=lambda: None,
    )
    return (
        _wrap(review_owner.build(), "review"),
        _wrap(planning_owner.build(), "planning"),
        review_owner,
    )


def _stage(
    *,
    graph: Any,
    state: GraphState,
    recorder: _RecordingInferencePort,
    dispatches: Any,
    name: str,
) -> tuple[GraphState, dict[str, object]]:
    calls_before = len(recorder.calls)
    attempts_before = len(recorder.attempts)
    dispatches_before = dispatches()
    started = time.perf_counter()
    output = cast(GraphState, graph.invoke(state, {"recursion_limit": 100}))
    calls = recorder.calls[calls_before:]
    record: dict[str, object] = {
        "stage": name,
        "target": output.get("__target__"),
        "workflow_phase": output.get("workflow_phase"),
        "review_result": output.get("plan_review") if name.startswith("review") else None,
        "planning_result": output.get("planning_result") if name == "planning_revision" else None,
        "llm_calls": len(calls),
        "provider_dispatches": dispatches() - dispatches_before,
        "input_tokens": sum(cast(int, call["input_tokens"]) for call in calls),
        "output_tokens": sum(cast(int, call["output_tokens"]) for call in calls),
        "duration_ms": int((time.perf_counter() - started) * 1_000),
        "inference_attempts": recorder.attempts[attempts_before:],
        "inference_details": [
            {
                "prompt_id": call["prompt_id"],
                "prompt_input": call["prompt_input"],
                "structured_output": call["structured_output"],
                "input_tokens": call["input_tokens"],
                "output_tokens": call["output_tokens"],
            }
            for call in calls
        ],
    }
    return output, record


def evaluate(
    *,
    connected_path: Path,
    counterexamples_path: Path,
    checkpoint_root: Path,
    output_path: Path,
    prepare_only: bool = False,
) -> dict[str, object]:
    connected_bytes = connected_path.read_bytes()
    counterexamples_bytes = counterexamples_path.read_bytes()
    connected = json.loads(connected_bytes)
    counterexamples = json.loads(counterexamples_bytes)
    model_digest = next(
        (
            item.digest
            for item in OllamaHTTPClient().list_installed_models()
            if item.model_id == MODEL_ID
        ),
        None,
    )
    if model_digest != connected["binding"]["model_digest"]:
        raise ValueError("installed model digest differs from frozen source")
    rows = _scenario_inputs(connected, counterexamples)
    runtime = (
        None
        if prepare_only
        else _runtime(
            Path(tempfile.mkdtemp(prefix="gwa-review-cycle-")),
            default_prompt_manifest_path(),
        )
    )
    recorder = None if runtime is None else _RecordingInferencePort(runtime, [])
    if recorder is not None:
        recorder.capture_structured_output = True
    dispatch_count = 0
    if runtime is not None:
        before_dispatch = runtime.before_provider_dispatch

        def count_dispatch() -> None:
            nonlocal dispatch_count
            before_dispatch()
            dispatch_count += 1

        runtime.before_provider_dispatch = count_dispatch
    result: dict[str, object] = {
        "binding": {
            "baseline_sha": "e2e1c458",
            "connected_source_sha256": hashlib.sha256(connected_bytes).hexdigest(),
            "counterexamples_source_sha256": hashlib.sha256(counterexamples_bytes).hexdigest(),
            "model_id": MODEL_ID,
            "model_digest": model_digest,
            "sampling_temperature": 0.0,
            "sampling_seed": 1729,
            "scenario_count": len(rows),
            "provider_read_enabled": False,
            "provider_write_enabled": False,
            "official_domain_run_count": 0,
        },
        "cases": [],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    for label, source_case, candidate in rows:
        state, evidence_store, profile = _build_case_state(
            label=label,
            source_case=source_case,
            candidate=candidate,
            checkpoint_root=checkpoint_root,
        )
        if recorder is None:
            recorder_for_graph = cast(_RecordingInferencePort, object())
        else:
            recorder_for_graph = recorder
        prior_plan = candidate["planning_result"]
        calendar_id = prior_plan["actions"][0]["arguments"].get("calendar_id")
        review_graph, planning_graph, review_owner = _graph_pair(
            recorder=recorder_for_graph,
            evidence_store=evidence_store,
            profile=profile,
            label=label,
            calendar_id=calendar_id if isinstance(calendar_id, str) else None,
        )
        projected = goal_projection.project_inspect_goal_and_evidence_input(
            review_owner._project_runtime_inputs(cast(Any, state))
        )
        case_record: dict[str, object] = {
            "label": label,
            "origin": "SAVED_ACTUAL" if label.startswith("NORMAL") else "SYNTHETIC_COUNTEREXAMPLE",
            "source_case": source_case,
            "review_input_sha256": hashlib.sha256(
                json.dumps(projected, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest(),
            "review_projection": projected if prepare_only else None,
            "plan_before": prior_plan,
            "stages": [],
        }
        if not prepare_only:
            assert recorder is not None
            started = time.perf_counter()
            with (
                provider_dispatch_execution_scope(
                    run_id=state["run_id"],
                    now_ms=lambda started=started, start_ms=candidate["started_at_ms"]: (
                        start_ms + int((time.perf_counter() - started) * 1_000)
                    ),
                ),
                provider_dispatch_budget_scope(cast(Any, state["retry_budget"])),
            ):
                try:
                    reviewed, initial_record = _stage(
                        graph=review_graph,
                        state=state,
                        recorder=recorder,
                        dispatches=lambda: dispatch_count,
                        name="review_initial",
                    )
                    cast(list[dict[str, object]], case_record["stages"]).append(initial_record)
                    status = cast(dict[str, Any], reviewed.get("plan_review") or {}).get("status")
                    target = reviewed.get("__target__")
                    if (
                        label in REVISE_LABELS
                        and status == "REVISE"
                        and target == "PLANNING_REVISE_PLAN"
                    ):
                        revised, planning_record = _stage(
                            graph=planning_graph,
                            state=reviewed,
                            recorder=recorder,
                            dispatches=lambda: dispatch_count,
                            name="planning_revision",
                        )
                        cast(list[dict[str, object]], case_record["stages"]).append(planning_record)
                        case_record["plan_after"] = revised.get("planning_result")
                        if revised.get("__target__") == "PLAN_REVIEW_INSPECT":
                            rechecked, recheck_record = _stage(
                                graph=review_graph,
                                state=revised,
                                recorder=recorder,
                                dispatches=lambda: dispatch_count,
                                name="review_recheck",
                            )
                            cast(list[dict[str, object]], case_record["stages"]).append(
                                recheck_record
                            )
                            case_record["final_target"] = rechecked.get("__target__")
                except Exception as error:
                    code = getattr(error, "code", None)
                    case_record["error"] = {
                        "type": type(error).__name__,
                        "code": getattr(code, "value", None),
                        "message": str(error),
                    }
        cast(list[dict[str, object]], result["cases"]).append(case_record)
        output_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(label, case_record.get("error", "COMPLETED"), flush=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connected", type=Path, required=True)
    parser.add_argument("--counterexamples", type=Path, required=True)
    parser.add_argument("--checkpoint-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    evaluate(
        connected_path=args.connected,
        counterexamples_path=args.counterexamples,
        checkpoint_root=args.checkpoint_root,
        output_path=args.output,
        prepare_only=args.prepare_only,
    )


if __name__ == "__main__":
    main()
