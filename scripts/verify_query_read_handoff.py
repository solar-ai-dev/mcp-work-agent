"""069 frozen Query -> real READ boundaries with one local snapshot port.

This is a separate deterministic component gate, not a Run resume, model trial,
live Google permission check, or business-success evaluation.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

from evaluation.dataset_v8 import DEFAULT_DATASET_PATH, DEFAULT_PROVIDER_FIXTURE_PATH, load_cases
from scripts import evaluate_query_ref_postfix as previous
from scripts.evaluate_effect_prohibition_sampler import head, write_json
from scripts.evaluate_output_format_ablation import file_hash
from scripts.ru_observation import object_hash
from scripts.serve_canonical_v8_product import _case_resources

from google_work_agent.adapters.langgraph.subgraphs.retrieval.projections import (
    execute_read_projection as read_projection,
)
from google_work_agent.adapters.system.json_settings import _view_from_payload
from google_work_agent.adapters.system.memory.run_retrieval_cache import InMemoryRunRetrievalCache
from google_work_agent.application.agents.retrieval.assess_sufficiency import (
    source_statuses_prompt_projection,
)
from google_work_agent.application.agents.retrieval.bind_exact_resource_refs import (
    bind_exact_resource_refs,
)
from google_work_agent.application.agents.retrieval.build_query import (
    bind_required_container_constraints,
    build_query,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    validate_retrieval_query_plan_v2,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan_schema import (
    normalize_retrieval_query_plan_candidate,
)
from google_work_agent.application.agents.retrieval.execute_read import (
    RetrievalReadBindingError,
    execute_read,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_development_tool_registry,
)
from google_work_agent.application.use_cases.resource.require_resource_selection import (
    RequireResourceSelectionHandler,
    SelectedResourceReadPort,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.connector.connector_read_port import ConnectorReadResultV1
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.system.contracts.workflow_execution import SelectedResourceRef

ROOT = previous.ROOT
RESULTS = ROOT / "evaluation/results"
OUTPUT = RESULTS / "070-query-read-handoff"
SOURCE = RESULTS / "069-query-exact-ref-first-t1"
SOURCE_HASHES = {
    "plan.json": "020e7509e70e24716de6821bfb5ddbad1f3689647ad60c3cd46d6e33188ec346",
    "raw.json": "86335bcc9dac46eb9961dfa5e34e0eb31958ebd40595162a7eee77e22bd52735",
}
CRITERIA = "evaluation/experiments/070-query-read-handoff-criteria.md"
COMPONENT_RUN = "component-070-query-read-handoff"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def load_inputs() -> dict[str, Any]:
    _require(
        {p: file_hash(SOURCE / p) for p in SOURCE_HASHES} == SOURCE_HASHES,
        "closed 069 bytes changed",
    )
    plan, raw = (previous._read(SOURCE / name) for name in ("plan.json", "raw.json"))
    authority = previous.load_authority()
    products = {p: digest for p, digest in plan["bound_files"].items() if p.startswith("src/")}
    _require(
        bool(products) and {p: file_hash(ROOT / p) for p in products} == products,
        "Product/Registry changed since 069",
    )
    old = plan["historical_plan"]
    _require(
        file_hash(DEFAULT_DATASET_PATH) == old["dataset_sha256"]
        and file_hash(DEFAULT_PROVIDER_FIXTURE_PATH) == old["snapshot_sha256"],
        "historical Dataset/snapshot changed",
    )
    _require(
        raw["state"] == "RETURNED"
        and raw["model_calls"] == 1
        and raw["structural_validation"] == "VALID"
        and raw["first"] == plan["first"]
        and raw["plan_sha256"] == SOURCE_HASHES["plan.json"]
        and authority["lineage"] == plan["lineage"]
        and authority["call"] == plan["historical_first"],
        "069 authority mismatch",
    )
    case = load_cases()[old["case_id"]].raw
    _require(object_hash(case) == old["case_sha256"], "historical Case changed")
    selected = authority["lineage"]["selected_resources"]
    _require(len(selected) == 1, "one actual selected Task required")
    tasks = [
        r
        for r in _case_resources(case)
        if r["resource_type"] == "task"
        and r["resource_id"] == selected[0]["resource_id"]
        and r["parent_id"] == selected[0]["parent_resource_id"]
    ]
    _require(
        len(tasks) == 1
        and object_hash(tasks[0]) == old["resource_scope"]["selected_task_snapshot_sha256"],
        "exact bound Task snapshot unavailable",
    )
    files = {
        p: file_hash(ROOT / p)
        for p in (
            "scripts/verify_query_read_handoff.py",
            "tests/evaluation/test_query_read_handoff.py",
            "scripts/evaluate_query_ref_postfix.py",
            "scripts/evaluate_effect_prohibition_sampler.py",
            "scripts/evaluate_output_format_ablation.py",
            "scripts/ru_observation.py",
            "scripts/serve_canonical_v8_product.py",
            "evaluation/dataset_v8.py",
            CRITERIA,
        )
    }
    return {
        "authority": authority,
        "first": raw["first_output"],
        "schema": plan["first"]["schema"],
        "expected_fetches": raw["consumer_result"]["source_fetch_plans"],
        "settings": previous._read(previous.SOURCE / "runtime/settings/app-settings.json")[
            "settings"
        ],
        "snapshot": tasks[0],
        "binding": {
            "head": head(),
            "source_069_hashes": SOURCE_HASHES,
            "source_066_hashes": previous.SOURCE_HASHES,
            "checkpoint": plan["lineage"]["checkpoint_id"],
            "product_hashes": products,
            "gate_file_hashes": files,
            "dataset_sha256": old["dataset_sha256"],
            "snapshot_sha256": old["snapshot_sha256"],
            "selected_snapshot_sha256": object_hash(tasks[0]),
            "input_sha256": plan["first"]["input_sha256"],
        },
    }


class SnapshotReader:
    """Only a fixed local Task result; this class has no network or write client."""

    def __init__(self, snapshot: dict[str, Any]) -> None:
        self.snapshot = deepcopy(snapshot)
        self.calls: list[dict[str, Any]] = []

    def execute_read(self, binding: Any, arguments: Any) -> ConnectorReadResultV1:
        expected = {
            "task_list_id": self.snapshot["parent_id"],
            "task_id": self.snapshot["resource_id"],
        }
        _require(
            binding.effect == "READ"
            and binding.tool_id == "tasks_get_task"
            and arguments == expected,
            "synthetic port received an unregistered dispatch",
        )
        self.calls.append({"binding": asdict(binding), "arguments": deepcopy(arguments)})
        return ConnectorReadResultV1(
            1, binding.tool_id, "070-local-snapshot", {"item": deepcopy(self.snapshot)}, None, 1
        )


def verify_controls(
    inputs: dict[str, Any], record: dict[str, Any], save: Callable[[], None]
) -> None:
    """Actual deterministic owners only; no fabricated Evidence/Sufficiency PASS."""
    context = inputs["authority"]["context"]
    unchanged = object_hash(inputs["first"])
    _require(
        not validate_output_schema(inputs["first"], inputs["schema"]),
        "069 FIRST no longer schema-valid",
    )
    query = bind_required_container_constraints(
        normalize_retrieval_query_plan_candidate(deepcopy(inputs["first"])),
        route_policies=context["route_policies"],
        validated_container_refs=context["validated_container_refs"],
    )
    query = validate_retrieval_query_plan_v2(
        query,
        frozen_routes=context["frozen_routes"],
        supported_constraint_kinds={
            key: value.supported_kinds for key, value in context["route_policies"].items()
        },
        validated_resource_refs=context["validated_resource_refs"],
        validated_container_refs=context["validated_container_refs"],
    )
    fetches = build_query(
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
    _require(
        fetches == inputs["expected_fetches"] and len(fetches) == 1, "069 materialization changed"
    )
    plan = fetches[0]
    route = next(r for r in context["frozen_routes"] if r["route_id"] == plan["route_id"])
    selected = tuple(
        SelectedResourceRef(**item) for item in inputs["authority"]["lineage"]["selected_resources"]
    )
    exact = bind_exact_resource_refs(
        request_intent=context["prompt_input"]["request_intent"],
        frozen_routes=context["frozen_routes"],
        selected_resources=selected,
    )
    detail_ref = plan["detail_candidate_ref"]
    if detail_ref is None:
        raise ValueError("selected detail reference is required")
    _require(
        detail_ref in exact["refs_by_route"].get(plan["route_id"], []),
        "detail reference is not selected for this exact route",
    )
    identity = exact["identities_by_ref"][detail_ref]
    tool, arguments = read_projection.project_connector_call(
        plan, route=route, page_size=20, detail_resource=identity
    )
    registry = load_development_tool_registry()
    binding = registry.bind_required(plan["connector_id"], tool, "READ")
    settings = _view_from_payload(inputs["settings"])
    account = settings.google_resource_account_id
    _require(isinstance(account, str) and bool(account), "historical account scope missing")
    reader, cache = SnapshotReader(inputs["snapshot"]), InMemoryRunRetrievalCache()
    record.update(
        normalized_query=query,
        source_fetch_plans=fetches,
        selected_identity=identity,
        projected_tool=tool,
        projected_arguments=arguments,
        registry_binding=asdict(binding),
        account_context="SYNTHETIC_GETTER_RETURNS_HISTORICAL_SELECTED_ACCOUNT_NOT_LIVE_AUTH",
        synthetic_calls=reader.calls,
        read_attempts=[],
    )
    save()

    def dispatch(
        *,
        target_arguments: Any = arguments,
        target_binding: Any = binding,
        current_account: str = cast(str, account),
        handle: str,
    ) -> Any:
        budget = build_default_run_budget(started_at_ms=1)
        attempt: dict[str, Any] = {"handle": handle, "budget": budget}
        record["read_attempts"].append(attempt)
        save()
        try:
            result = execute_read(
                plan=plan,
                run_id=COMPONENT_RUN,
                binding=target_binding,
                tool_arguments=target_arguments,
                connector_reader=SelectedResourceReadPort(
                    reader,
                    RequireResourceSelectionHandler(lambda: settings, lambda _: current_account),
                ),
                read_result_cache=cache,
                read_result_handle=handle,
                run_budget=budget,
                now_ms=2,
                prior_query_attempts=[],
                request_intent=context["prompt_input"]["request_intent"],
                selected_resources=selected,
            )
        except Exception as error:
            attempt["error"] = {"type": type(error).__name__, "message": str(error)}
            save()
            raise
        attempt["result"] = asdict(result)
        save()
        return result, budget

    success, budget = dispatch(handle="070-success")
    record.update(normal_read=asdict(success), component_budget=budget)
    save()
    _require(
        success.status == "COMPLETE" and success.provider_called and len(reader.calls) == 1,
        "normal local snapshot read did not complete exactly once",
    )
    cached = cache.resolve_read_result(
        success.read_result_handle, COMPONENT_RUN, plan["route_id"], plan["query_identity_hash"]
    )
    if cached.status != "EXHAUSTED" or cached.entry is None:
        raise ValueError("same-Run cache binding lost")
    record["cached_read_result"] = asdict(cached.entry.read_result)
    save()
    acquisition = read_projection.project_acquisition_result(
        [(plan, cached.entry.read_result)], remaining_budget={}
    )
    coverage = source_statuses_prompt_projection(
        tool_route_plan=inputs["authority"]["lineage"]["tool_route_plan"],
        acquisition_result=acquisition,
        known_work_unit_ids=[
            w["unit_id"]
            for w in context["prompt_input"]["request_intent"]["requested_work"]["work_units"]
        ],
    )
    status = next(item for item in coverage if item["route_id"] == route["route_id"])
    _require(
        status["work_unit_ids"] == route["work_unit_ids"] and status["status"] == "COMPLETE",
        "route/Work coverage changed",
    )
    record.update(
        normal_read=asdict(success),
        component_budget=budget,
        budget_scope="NEW_DEFAULT_COMPONENT_BUDGET_NOT_HISTORICAL_RUN_BUDGET",
        acquisition=acquisition,
        source_statuses=coverage,
        synthetic_calls=reader.calls,
    )
    record["controls"] = []
    save()

    def control(name: str, passed: bool, **details: Any) -> None:
        record["controls"].append({"name": name, "passed": passed, **details})
        save()
        _require(passed, f"control did not close: {name}")

    outside = "070-unselected-parent"
    _require(
        outside not in (settings.selected_tasklist_ids or ()),
        "negative parent is not outside scope",
    )
    for name, options in (
        ("OUTSIDE_PARENT", {"target_arguments": {**arguments, "task_list_id": outside}}),
        ("ACCOUNT_MISMATCH", {"current_account": str(account) + "-different"}),
    ):
        denied, _ = dispatch(handle=name, **options)
        control(
            name,
            denied.status == "FAILED"
            and denied.failure_code == "PERMISSION_DENIED"
            and not denied.provider_called
            and len(reader.calls) == 1,
            result=asdict(denied),
        )
    try:
        dispatch(
            handle="WRITE_BINDING",
            target_binding=registry.bind_required(
                "google_workspace", "tasks_update_task", "UPDATE"
            ),
        )
    except RetrievalReadBindingError as error:
        control("WRITE_BINDING", len(reader.calls) == 1, error=str(error))
    else:
        control("WRITE_BINDING", False)
    route_without_tool = deepcopy(route)
    route_without_tool["allowed_read_tool_ids"] = []
    try:
        read_projection.project_connector_call(
            plan,
            route=route_without_tool,
            page_size=20,
            detail_resource=identity,
        )
    except PermissionError as error:
        control("REMOVED_TOOL", len(reader.calls) == 1, error=str(error))
    else:
        control("REMOVED_TOOL", False)
    cross = cache.resolve_read_result(
        success.read_result_handle,
        COMPONENT_RUN + "-other",
        plan["route_id"],
        plan["query_identity_hash"],
    )
    control(
        "CROSS_RUN_CACHE", cross.status == "CROSS_RUN" and cross.entry is None, status=cross.status
    )
    for name, route_id, query_hash in (
        ("WRONG_ROUTE_CACHE", plan["route_id"] + "-other", plan["query_identity_hash"]),
        ("WRONG_QUERY_CACHE", plan["route_id"], plan["query_identity_hash"] + "-other"),
    ):
        mismatch = cache.resolve_read_result(
            success.read_result_handle, COMPONENT_RUN, route_id, query_hash
        )
        control(
            name,
            mismatch.status == "BINDING_MISMATCH" and mismatch.entry is None,
            status=mismatch.status,
        )
    wrong_route = deepcopy(acquisition)
    for summary in wrong_route["source_summaries"]:
        summary["route_id"] = plan["route_id"] + "-other"
    unmatched = source_statuses_prompt_projection(
        tool_route_plan=inputs["authority"]["lineage"]["tool_route_plan"],
        acquisition_result=wrong_route,
        known_work_unit_ids=[
            w["unit_id"]
            for w in context["prompt_input"]["request_intent"]["requested_work"]["work_units"]
        ],
    )
    unmatched_status = next(item for item in unmatched if item["route_id"] == route["route_id"])
    control(
        "WRONG_ROUTE_ACQUISITION",
        unmatched_status["status"] == "NOT_ATTEMPTED"
        and unmatched_status["checked_read_count"] == 0
        and unmatched_status["work_unit_ids"] == route["work_unit_ids"],
        source_statuses=unmatched,
    )
    _require(object_hash(inputs["first"]) == unchanged, "stored FIRST was mutated")
    record.update(component_verdict="PASS", synthetic_dispatches=len(reader.calls))
    save()


def run_gate(output: Path | None = None) -> dict[str, Any]:
    output = (OUTPUT if output is None else output).resolve()
    _require(output == OUTPUT.resolve(), "070 uses only its dedicated registered output directory")
    if output.exists():
        raise FileExistsError("070 component attempt already exists")
    inputs = load_inputs()
    output.mkdir(parents=True, exist_ok=False)
    record: dict[str, Any] = {
        "state": "RUNNING",
        "binding": inputs["binding"],
        "model_calls": 0,
        "external_provider_calls": 0,
        "graph_calls": 0,
        "scope": "DETERMINISTIC_COMPONENT_NOT_069_TRIAL_OR_BUSINESS_SUCCESS",
    }
    path = output / "raw.json"
    write_json(path, record, exclusive=True)

    def save() -> None:
        write_json(path, record)

    try:
        verify_controls(inputs, record, save)
        record["state"] = "RETURNED"
    except Exception as error:
        record.update(
            state="FAILED",
            component_verdict="FAIL",
            failure={"type": type(error).__name__, "message": str(error)},
        )
    finally:
        try:
            record["binding_unchanged"] = load_inputs()["binding"] == inputs["binding"]
        except Exception as error:
            record.update(binding_unchanged=False, end_binding_error=str(error))
        if not record["binding_unchanged"]:
            record.update(state="FAILED", component_verdict="FAIL")
            record.setdefault(
                "failure",
                {
                    "type": "AuthorityDrift",
                    "message": "end binding differs from the starting authority",
                },
            )
        save()
    return record


if __name__ == "__main__":
    result = run_gate()
    print(
        json.dumps(
            {
                key: result.get(key)
                for key in (
                    "state",
                    "component_verdict",
                    "synthetic_dispatches",
                    "binding_unchanged",
                )
            }
        )
    )
    raise SystemExit(
        0 if result["state"] == "RETURNED" and result["component_verdict"] == "PASS" else 1
    )
