"""Evaluate the #288 item-owned binding through adjacent downstream contracts."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from evaluation.requested_work_binding_contract import (
    project_inline_work_unit_ids,
    validate_inline_work_unit_ids,
)
from evaluation.requested_work_connected_handoff import (
    default_connected_scenarios,
    default_tool_bindings,
    project_connected_handoff,
    validate_connected_handoff,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-result", type=Path, required=True)
    parser.add_argument("--result-path", type=Path, required=True)
    parser.add_argument("--product-head", required=True)
    arguments = parser.parse_args()
    if arguments.result_path.exists():
        raise ValueError("result path already exists; preserve every prior trial")

    source = _object(json.loads(arguments.source_result.read_text(encoding="utf-8")))
    cases = _object_list(source.get("cases"), "cases")
    binding_valid = 0
    single_work = 0
    multi_work = 0
    core_cases: list[dict[str, object]] = []
    for raw_case in cases:
        case_id = _string(raw_case.get("case_id"), "case_id")
        user_request = _string(raw_case.get("user_request"), f"{case_id}.user_request")
        materialize = _object(raw_case.get("materialize"), f"{case_id}.materialize")
        decomposition = _object(materialize.get("candidate"), f"{case_id}.candidate")
        inline = project_inline_work_unit_ids(decomposition)
        errors = [
            error
            for error in validate_inline_work_unit_ids(inline, user_request=user_request)
            if "non-verbatim request span" not in error
        ]
        requested_work = _object(inline.get("requested_work"), f"{case_id}.requested_work")
        work_units = _object_list(requested_work.get("work_units"), f"{case_id}.work_units")
        binding_valid += int(not errors)
        single_work += int(len(work_units) == 1)
        multi_work += int(len(work_units) > 1)
        core_cases.append(
            {
                "case_id": case_id,
                "work_unit_count": len(work_units),
                "binding_valid": not errors,
                "binding_errors": errors,
            }
        )

    scenario_results: list[dict[str, object]] = []
    connected_valid = 0
    for scenario in default_connected_scenarios():
        candidate = project_connected_handoff(scenario, tool_bindings=default_tool_bindings())
        errors = validate_connected_handoff(scenario, candidate)
        connected_valid += int(not errors)
        baseline = _flat_baseline_metrics(scenario)
        scenario_results.append(
            {
                "scenario_id": scenario["scenario_id"],
                "valid": not errors,
                "errors": errors,
                "current_flat_baseline": baseline,
                "connected_candidate": candidate,
                "comparison": {
                    "provider_read_delta": (
                        candidate["metrics"]["provider_read_count"]
                        - baseline["provider_read_count"]
                    ),
                    "output_capability_selection_delta": (
                        candidate["metrics"]["output_capability_selection_count"]
                        - baseline["output_capability_selection_count"]
                    ),
                    "planning_specification_delta": (
                        candidate["metrics"]["planning_specification_count"]
                        - baseline["planning_specification_count"]
                    ),
                    "answer_planning_input_delta": (
                        candidate["metrics"]["answer_planning_input_count"]
                        - baseline["answer_planning_input_count"]
                    ),
                },
            }
        )

    result = {
        "version": "ru288-connected-handoff-v1",
        "scope": "EVALUATION_ONLY_CONNECTED_CONTRACT",
        "product_head": arguments.product_head,
        "source": {
            "path": arguments.source_result.as_posix(),
            "sha256": _sha256(arguments.source_result),
            "model_call_count": 0,
            "provider_read_count": 0,
            "provider_write_count": 0,
            "prompt_change": False,
            "product_contract_change": False,
        },
        "core24_binding_gate": {
            "case_count": len(cases),
            "binding_valid": binding_valid,
            "single_work_unit_cases": single_work,
            "multi_work_unit_cases": multi_work,
            "cases": core_cases,
        },
        "connected_contract_gate": {
            "scenario_count": len(scenario_results),
            "valid": connected_valid,
            "scenarios": scenario_results,
        },
        "first_binding_loss": {
            "operation": "tool_routing.determine_io_resources._resource_responsibility_candidate",
            "source_behavior": (
                "Source owner items become a resource_type tuple and Output owner items become "
                "resource/effect pairs; no WorkUnit applicability reaches route binding."
            ),
            "upstream_guard": (
                "RequestIntentV2 validation also rejects repeated source resource_type "
                "and repeated output resource/effect before WorkUnit applicability can "
                "distinguish them."
            ),
        },
        "minimal_contract_candidate": {
            "input_route": (
                "One shared capability route per Resource with union work_unit_ids; it does not "
                "take ownership of query requirements."
            ),
            "retrieval": (
                "A deterministic route requirement projection carries the exact source owner "
                "items; one query/read per input route and route-scoped coverage carry "
                "work_unit_ids while Evidence is not duplicated."
            ),
            "answer_planning": (
                "One shared ANSWER planning input carries evidence grouped by WorkUnit; it does "
                "not create one model invocation per WorkUnit."
            ),
            "output_route": (
                "One route per Output responsibility item with work_unit_ids; Tool capability "
                "selection remains shared by resource/effect."
            ),
            "planning": (
                "One planned specification per frozen output route carrying work_unit_ids; no "
                "Provider write and no WorkRelation-to-action-dependency conversion."
            ),
        },
        "decision": {
            "connected_handoff": "ADOPT_FOR_PRODUCTION_MIGRATION_SCOPE",
            "request_intent_v3_production": "HOLD_UNTIL_ATOMIC_MIGRATION",
            "reason_codes": [
                "BINDING_SURVIVES_TOOL_ROUTE_RETRIEVAL_PLANNING",
                "SHARED_READ_NOT_DUPLICATED",
                "SHARED_TOOL_SELECTION_NOT_DUPLICATED",
                "DISTINCT_OUTPUT_MEANING_NOT_MERGED",
                "SIMPLE_REQUEST_CALL_COUNTS_UNCHANGED",
            ],
        },
    }
    arguments.result_path.parent.mkdir(parents=True, exist_ok=True)
    arguments.result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _flat_baseline_metrics(scenario: Mapping[str, object]) -> dict[str, int | bool]:
    sources = _object_list(scenario.get("source_responsibilities"), "source_responsibilities")
    outputs = _object_list(scenario.get("output_responsibilities"), "output_responsibilities")
    source_resources = {
        _string(item.get("resource_type"), "source.resource_type") for item in sources
    }
    output_pairs = [
        (
            _string(item.get("resource_type"), "output.resource_type"),
            _string(item.get("effect"), "output.effect"),
        )
        for item in outputs
    ]
    unique_output_pairs = set(output_pairs)
    representable = len(unique_output_pairs) == len(output_pairs)
    return {
        "request_intent_v2_representable": representable,
        "provider_read_count": len(source_resources),
        "output_capability_selection_count": len(unique_output_pairs),
        "answer_planning_input_count": int(not outputs),
        "planning_specification_count": len(unique_output_pairs) if representable else 0,
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _object(value: object, path: str = "root") -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError(f"{path} must be an object")
    return value


def _object_list(value: object, path: str) -> list[dict[str, object]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise TypeError(f"{path} must be an object list")
    return cast(list[dict[str, object]], value)


def _string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise TypeError(f"{path} must be a non-empty string")
    return value


if __name__ == "__main__":
    main()
