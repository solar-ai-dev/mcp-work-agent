"""Inactive, model-free Source replay gate; never manufacture downstream decisions.

The changed Source lane stops at the first missing exact-input owner response.
Its deterministic route binding is inspected separately from the compiled route
control, which consumes the unchanged, previously finalized v4 intent.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import subprocess
from copy import deepcopy
from datetime import datetime
from itertools import count
from pathlib import Path
from typing import Any, cast

from evaluation.request_semantic_authority_candidate import _goal_output_modality_schema
from scripts.ru_observation import object_hash
from scripts.ru_output_source_handoff_candidate import _projection, _replay_records

from google_work_agent.adapters.langgraph.main.state import initial_graph_state
from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.graph import ToolRoutingSubgraph
from google_work_agent.application.agents.request_understanding import (
    identify_effect_prohibitions as prohibition_ops,
)
from google_work_agent.application.agents.request_understanding import (
    identify_output_responsibilities as output_ops,
)
from google_work_agent.application.agents.request_understanding import (
    identify_source_dependencies as source_ops,
)
from google_work_agent.application.agents.request_understanding.contracts.request_goal_candidate_schema import (  # noqa: E501
    derive_requested_resource_fields,
)
from google_work_agent.application.agents.request_understanding.finalize_intent import (
    finalize_intent,
)
from google_work_agent.application.agents.request_understanding.identify_goal import (
    _validated_candidate,
)
from google_work_agent.application.agents.request_understanding.identify_source_status import (
    identify_source_status,
)
from google_work_agent.application.agents.request_understanding.merge_resource_responsibilities import (  # noqa: E501
    merge_resource_responsibilities,
)
from google_work_agent.application.agents.tool_routing.bind_registry_candidates import (
    bind_registry_candidates,
    business_required_source_routes,
)
from google_work_agent.application.agents.tool_routing.determine_io_resources import (
    _resource_responsibility_candidate,
)
from google_work_agent.application.agents.tool_routing.resolve_policy_preconditions import (
    resolve_policy_preconditions,
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
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_port import StructuredInferenceResultV1
from google_work_agent.ports.system.contracts.workflow_execution import (
    SelectedResourceRef,
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)

CASES = ("CASE-CORE-001", "CASE-CORE-013", "CASE-CORE-023", "CASE-CORE-027")
DEFAULT_SOURCE = Path("evaluation/results/064-output-source-v20-t1/raw.json")
DEFAULT_AUTHORITY = Path(
    "evaluation/results/ru-goal-output-modality-v4-canonical92-trial1-20260924/raw.json"
)
DEFAULT_DATASET = Path("evaluation/datasets/e2e/canonical_cases_v8.jsonl")
DEFAULT_FIXTURE = Path(
    "evaluation/datasets/e2e/fixtures/google_workspace/provider-snapshot-v8.json"
)


class NewSemanticCallRequired(RuntimeError):
    """No model or Provider exists behind the replay boundary."""

    def __init__(self, boundary: dict[str, Any]) -> None:
        super().__init__(str(boundary["prompt_id"]))
        self.boundary = boundary


class ExactRecordedInference:
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self.records = deepcopy(records)
        self.observations: list[dict[str, Any]] = []

    def infer(self, mode: Any, prompt: Any, projection: Any, schema: Any) -> Any:
        observations = {
            "prompt_id": prompt.prompt_id,
            "input_sha256": object_hash(projection),
            "current_schema_sha256": object_hash(schema.json_schema),
            "new_model_calls": 0,
        }
        prior = [item for item in self.records if item["prompt_id"] == prompt.prompt_id]
        matches = [
            item
            for item in prior
            if item["input"] == projection
            and "structured_output" in item
            and not validate_output_schema(item["structured_output"], schema.json_schema)
        ]
        outputs = {object_hash(item["structured_output"]): item for item in matches}
        if len(outputs) != 1:
            observations.update(
                disposition="NEW_SEMANTIC_CALL_REQUIRED",
                prior_input_sha256=[object_hash(item["input"]) for item in prior],
                reason="No unique exact-input recorded response valid under current schema",
            )
            self.observations.append(observations)
            raise NewSemanticCallRequired(observations)
        recorded = next(iter(outputs.values()))
        observations.update(
            disposition="RECORDED_RESPONSE_REPLAYED_NOT_NEW_INFERENCE",
            output_sha256=object_hash(recorded["structured_output"]),
        )
        self.observations.append(observations)
        return StructuredInferenceResultV1(
            schema_version=1,
            structured_output=deepcopy(recorded["structured_output"]),
            provider="RECORDED_RAW_REPLAY",
            model="NO_MODEL_INVOKED",
            actual_runtime="LOCAL_GPU",
            input_tokens=0,
            output_tokens=0,
            latency_ms=0,
            fallback_reason=None,
        )


def _request(case_id: str, case: Any, base: Any) -> WorkflowStartRequest:
    selected = tuple(SelectedResourceRef(**item) for item in base["selected_resource_refs"])
    reference = base["run_reference_time"]["reference_time"]
    return WorkflowStartRequest(
        run_id=f"frozen-gate-{case_id}",
        conversation_id="frozen-source-component-gate",
        workflow_key=f"frozen-gate-{case_id}",
        entry_mode=case["entry_mode"],
        requested_mode="LOCAL_GPU",
        request_text=base["user_request"],
        selected_resource_ids=tuple(item.resource_id for item in selected),
        selected_resources=selected,
        correlation=WorkflowCorrelationContext(case_id, None, "1"),
        run_budget=build_default_run_budget(
            started_at_ms=int(datetime.fromisoformat(reference).timestamp() * 1000)
        ),
    )


def restore_recorded_intent(case: Any, request: WorkflowStartRequest) -> Any:
    """Restore the recorded final projection; derive only redundant typed hints."""
    prior = case["intent"]
    responsibilities = {"source_reads": prior["source_reads"], "outputs": prior["outputs"]}
    effects, resources, _ = derive_requested_resource_fields(responsibilities)
    goal = {
        key: deepcopy(prior[key])
        for key in (
            "goal",
            "completion_conditions",
            "constraints",
            "analysis_requirement",
            "effect_prohibitions",
        )
    }
    goal.update(
        requested_work={
            "work_units": deepcopy(prior["work_units"]),
            "work_relations": deepcopy(prior["relations"]),
        },
        resource_responsibilities=deepcopy(responsibilities),
        requested_effect_hints=effects,
        requested_resource_hints=resources,
    )
    return finalize_intent(
        cast(Any, goal),
        deepcopy(prior["ambiguity"]),
        artifact_id=f"recorded-intent-{case['case_id']}",
        user_request=request.request_text,
    )


def fixture_route_inventory(routes: Any, fixture: Any, pack_names: list[str]) -> list[Any]:
    """Inventory only: no query matching, acquisition status, Evidence, or sufficiency."""
    resources = [
        item for name in pack_names for item in fixture["resource_packs"][name]["resources"]
    ]
    business_ids = {route["route_id"] for route in business_required_source_routes(routes)}
    inventory: list[dict[str, Any]] = []
    for route in routes:
        kind = route["resource_type"].lower()
        if kind == "gmail_message":
            objects = [message for item in resources for message in item.get("messages", [])]
        elif kind == "gmail_attachment":
            objects = [
                attachment
                for item in resources
                for message in item.get("messages", [])
                for attachment in message.get("attachments", [])
            ]
        else:
            objects = [item for item in resources if item["resource_type"] == kind]
        inventory.append(
            {
                "route_id": route["route_id"],
                "resource_type": route["resource_type"],
                "work_unit_ids": list(route["work_unit_ids"]),
                "reason_codes": list(route["reason_codes"]),
                "business_required": route["route_id"] in business_ids,
                "snapshot_object_count": None if kind == "calendar_freebusy" else len(objects),
                "snapshot_objects_sha256": object_hash(objects),
                "inventory_boundary": (
                    "FREEBUSY_REQUIRES_QUERY_RANGE_NOT_A_SNAPSHOT_OBJECT"
                    if kind == "calendar_freebusy"
                    else "CASE_PACK_INVENTORY_NOT_QUERY_RESULT"
                ),
                "empty_required_inventory_risk": (
                    route["route_id"] in business_ids
                    and not objects
                    and kind != "calendar_freebusy"
                ),
            }
        )
    return inventory


def _compiled_control(request: Any, intent: Any, registry: Any, fixture: Any, packs: Any) -> Any:
    sequence = count()
    no_llm = ExactRecordedInference([])

    def no_confirmation(state: Any) -> Any:
        raise NewSemanticCallRequired(
            {"prompt_id": "USER_CONFIRMATION", "user_interrupt": state.get("user_interrupt")}
        )

    graph = ToolRoutingSubgraph(
        llm_runtime=no_llm,
        tool_catalog=registry,
        prompt_manifest_path=None,
        prompt_execution_scope=DEVELOPMENT_SMOKE,
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        merge_decision=lambda state, patch, decision: {
            **state,
            **patch,
            **decision["state_update"],
            "__target__": decision["target"],
        },
        confirm_inline=no_confirmation,
        id_factory=lambda: f"control-{next(sequence)}",
    ).build()
    state = initial_graph_state(
        request,
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        graph_version="frozen-component-only",
        initial_target="tool_routing",
    )
    state["request_intent"] = intent
    try:
        with provider_dispatch_execution_scope():
            result = graph.invoke(state)
    except NewSemanticCallRequired as error:
        return {"disposition": "STOPPED_BEFORE_NEW_SEMANTIC_CALL", "boundary": error.boundary}
    plan = result.get("tool_route_plan")
    return {
        "disposition": "COMPILED_CONTROL_RETURNED" if plan else "COMPILED_CONTROL_NO_PLAN",
        "input_authority": "UNCHANGED_RECORDED_V4_FINAL_INTENT_NOT_V20",
        "plan": plan,
        "fixture_inventory": fixture_route_inventory(
            plan["input_plan"]["input_routes"], fixture, packs
        )
        if plan
        else [],
        "new_model_calls": 0,
    }


def run_case(
    source_case: Any,
    authority_case: Any,
    authority: Any,
    dataset_case: Any,
    fixture: Any,
    registry: Any,
) -> Any:
    base = source_case["atomic"][0]["input"]
    case_id = source_case["case_id"]
    if authority["source_input"] != base or case_id not in authority["origin_case_ids"]:
        raise ValueError("Source replay does not match the recorded same-case authority")
    if base["user_request"] != dataset_case["canonical_user_prompt"]:
        raise ValueError("canonical request differs from frozen raw")
    if base["requested_work"]["work_units"] != authority_case["intent"]["work_units"]:
        raise ValueError("recorded WorkUnit provenance differs")
    work_ids = [item["unit_id"] for item in base["requested_work"]["work_units"]]
    outputs_catalog = output_ops.build_output_responsibility_candidates(registry)
    schema = _goal_output_modality_schema(work_unit_ids=work_ids, output_candidates=outputs_catalog)
    errors = validate_output_schema(authority["goal_output"], schema.json_schema)
    if errors:
        raise ValueError(f"recorded Goal/Output violates current candidate schema: {errors}")
    prohibitions = prohibition_ops.validate_effect_prohibition_candidate(
        authority["prohibitions"],
        effect_candidates=prohibition_ops.build_effect_prohibition_candidates(outputs_catalog),
        work_unit_ids=work_ids,
    )
    outputs = output_ops.validate_output_responsibility_candidate(
        {"output_responsibilities": authority["goal_output"]["requested_outputs"]},
        output_candidates=outputs_catalog,
        effect_prohibitions=prohibitions,
        work_unit_ids=work_ids,
    )
    confirmed = source_case["transport_calls"][0]["input"]["confirmed_output_authority"]
    if confirmed != {
        "requested_result_mode": authority["goal_output"]["requested_result_mode"],
        **outputs,
    }:
        raise ValueError("v20 transport authority differs from recorded Goal/Output")
    source_catalog = source_ops.build_source_dependency_candidates(registry)
    if list(source_catalog) != base["source_candidates"]:
        raise ValueError("current Registry Source catalog differs from frozen input")
    sources = source_ops.validate_source_dependency_candidate(
        source_case["source_output"],
        source_candidates=source_catalog,
        work_unit_ids=work_ids,
    )
    source_ops.validate_source_dependency_semantics(
        sources,
        goal_candidate=base["goal_candidate"],
        has_output_responsibilities=bool(outputs["output_responsibilities"]),
    )
    responsibilities = merge_resource_responsibilities(
        source_decisions=sources,
        output_decisions=outputs,
        source_candidates=source_catalog,
        output_candidates=outputs_catalog,
        request_text=base["user_request"],
    )
    request = _request(case_id, dataset_case, base)
    intent = restore_recorded_intent(authority_case, request)
    replay = ExactRecordedInference(authority_case["atomic"])
    status_ref = load_prompt_reference(
        "request_understanding.identify_source_status",
        default_prompt_manifest_path(),
        execution_scope=DEVELOPMENT_SMOKE,
    )
    continuation: dict[str, Any]
    try:
        statuses = identify_source_status(
            llm_runtime=replay,
            requested_mode="LOCAL_GPU",
            prompt_ref=status_ref,
            prompt_input=base,
            goal_candidate=_projection(authority["goal_output"]),
            responsibilities=responsibilities,
        )
        candidate = _validated_candidate(
            _projection(authority["goal_output"]),
            resource_responsibilities=responsibilities,
            source_statuses=statuses,
            request=request,
            confirmation_response=None,
            effect_prohibitions=prohibitions,
            requested_work=base["requested_work"],
        )
        continuation = {
            "disposition": "STOPPED_BEFORE_UNREPLAYED_RELATION_TEMPORAL_AMBIGUITY",
            "candidate_sha256": object_hash(candidate),
        }
    except NewSemanticCallRequired as error:
        continuation = {"disposition": "NEW_SEMANTIC_CALL_REQUIRED", "boundary": error.boundary}

    # This is not a finalized candidate Intent: only these exact fields are read
    # by the deterministic responsibility projection and scope-policy components.
    partial = {
        "resource_responsibilities": responsibilities,
        "analysis_requirement": authority["goal_output"]["analysis_requirement"],
    }
    semantic = _resource_responsibility_candidate(cast(Any, partial))
    assert semantic is not None
    resolution = resolve_policy_preconditions(request_intent=intent, candidate=semantic)
    sequence = count()
    binding = (
        None
        if resolution.workflow_signal
        else bind_registry_candidates(
            candidate=resolution.candidate,
            tool_catalog=registry,
            id_factory=lambda: f"component-{next(sequence)}",
        )
    )
    return {
        "case_id": case_id,
        "binding": {
            "source_input_sha256": object_hash(base),
            "source_output_sha256": object_hash(sources),
            "joint_goal_output_sha256": object_hash(authority["goal_output"]),
            "prohibitions_sha256": object_hash(prohibitions),
            "requested_work_sha256": object_hash(base["requested_work"]),
            "recorded_final_intent_projection_sha256": object_hash(authority_case["intent"]),
            "reference_time": base["run_reference_time"],
        },
        "validated_source_output_merge": responsibilities,
        "candidate_continuation": continuation,
        "replay_observations": replay.observations,
        "candidate_compiled_tool_route_executed": False,
        "deterministic_components": {
            "authority": "VALIDATED_SOURCE_OUTPUT_PLUS_RECORDED_V4_SCOPE_CONSTRAINTS_ONLY",
            "not_a_finalized_request_intent": True,
            "scope_constraint_authority_sha256": object_hash(intent["constraints"]),
            "workflow_signal": resolution.workflow_signal,
            "input_routes": list(binding.input_routes) if binding else [],
            "fixture_inventory": fixture_route_inventory(
                binding.input_routes, fixture, dataset_case["resource_packs"]
            )
            if binding
            else [],
        },
        "unchanged_v4_compiled_control": _compiled_control(
            request, intent, registry, fixture, dataset_case["resource_packs"]
        ),
        "not_executed": [
            "Query",
            "Connector dispatch",
            "Evidence selection",
            "Sufficiency",
            "Planning",
            "Approval",
            "WRITE",
        ],
        "business_result": "NOT_EVALUATED",
    }


def build_report(
    source_path: Path, authority_path: Path, dataset_path: Path, fixture_path: Path
) -> dict[str, Any]:
    paths = {
        "source_raw": source_path,
        "authority_raw": authority_path,
        "dataset": dataset_path,
        "fixture": fixture_path,
    }
    file_hashes = {
        key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in paths.items()
    }
    source = json.loads(source_path.read_bytes())
    original = json.loads(authority_path.read_bytes())
    for payload in (source, original):
        for key in ("dataset", "fixture"):
            if payload["binding"][f"{key}_sha256"] != file_hashes[key]:
                raise ValueError(f"{key} differs from recorded authority")
    if source["binding"]["owner_replay_sha256"] != file_hashes["authority_raw"]:
        raise ValueError("v20 authority raw hash mismatch")
    dataset = {
        row["case_id"]: row
        for line in dataset_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
        for row in [json.loads(line)]
    }
    fixture = json.loads(fixture_path.read_bytes())
    source_cases = {row["case_id"]: row for row in source["cases"]}
    original_cases = {row["case_id"]: row for row in original["cases"]}
    authorities = _replay_records(original)
    registry = load_development_tool_registry()
    cases = []
    for case_id in CASES:
        row = source_cases[case_id]
        authority = authorities[object_hash(row["atomic"][0]["input"])]
        cases.append(
            run_case(row, original_cases[case_id], authority, dataset[case_id], fixture, registry)
        )
    return {
        "artifact_role": "FROZEN_COMPONENT_DIAGNOSTIC_NOT_MODEL_OR_BUSINESS_SCORE",
        "implementation": {
            "head": subprocess.run(
                ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
            ).stdout.strip(),
            "files": {
                str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(
                    {
                        Path(__file__),
                        default_prompt_manifest_path(),
                        *[
                            Path(cast(str, inspect.getsourcefile(owner)))
                            for owner in (
                                ToolRoutingSubgraph,
                                _validated_candidate,
                                identify_source_status,
                                finalize_intent,
                                _resource_responsibility_candidate,
                                merge_resource_responsibilities,
                                bind_registry_candidates,
                                resolve_policy_preconditions,
                            )
                        ],
                    },
                    key=str,
                )
            },
        },
        "bindings": {
            key: {"path": str(paths[key]), "sha256": value} for key, value in file_hashes.items()
        },
        "registry_contract_version": registry.contract_version,
        "new_model_calls": 0,
        "provider_reads": 0,
        "provider_writes": 0,
        "raw_modified": False,
        "cases": cases,
        "limitations": [
            "Historical ambiguity/status is not copied onto changed Source semantics.",
            "Compiled control is the unchanged recorded v4 intent, not a v20 success.",
            "Fixture inventory is not a query response, acquisition status or selected Evidence.",
            "No sufficient status or final business result is manufactured.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-raw", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--authority-raw", type=Path, default=DEFAULT_AUTHORITY)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("preserve prior diagnostic artifacts; output already exists")
    result = build_report(args.source_raw, args.authority_raw, args.dataset, args.fixture)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as destination:
        json.dump(result, destination, ensure_ascii=False, indent=2)
        destination.write("\n")


if __name__ == "__main__":
    main()
