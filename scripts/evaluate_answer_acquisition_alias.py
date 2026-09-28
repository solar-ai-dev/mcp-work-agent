"""091 exact Source alias omission, reusing historical wire and FIRST recording."""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from scripts import answer_acquisition_alias_candidate as candidate
from scripts import evaluate_answer_assembly_ablation as history
from scripts.evaluate_effect_prohibition_sampler import head, write_json
from scripts.ru_observation import metrics, object_hash

existing, recorder, ordered = history.existing, history.recorder, history.ordered
ROOT, RESULTS = history.ROOT, history.RESULTS
CRITERIA = "evaluation/experiments/091-answer-acquisition-alias-criteria.md"
ARM = "EXACT_ACQUISITION_ALIAS_OMITTED"
WALL_SECONDS = 1200


def verify_wire_seals(plan: dict[str, Any]) -> None:
    expected = [(g, trial) for trial in (1, 2) for g in history.GROUPS]
    if [(c["group"], c["trial"]) for c in plan["cases"]] != expected:
        raise ValueError("fixed three inputs times two FIRSTs required")
    ordered.verify_wire_seals(plan)
    for case in plan["cases"]:
        if case["original_prompt_input"] != json.loads(case["original_payload"]["prompt"])["input"]:
            raise ValueError("admission input differs from the authoritative original wire")
        payload, projection, contract = candidate.build_payload(
            case["original_payload"], source_snapshots=case["snapshots"]
        )
        if (
            ordered.transport_hash(payload) != case["candidate_transport_sha256"]
            or projection != case["prompt_input"]
            or contract != case["evaluation_input_contract"]
            or object_hash(projection) != case["candidate_input_sha256"]
        ):
            raise ValueError("exact omission/contract/wire changed")


def make_plan(model: dict[str, Any]) -> dict[str, Any]:
    # Reuse all immutable history/model/fixture/current-assembler checks, not its arms.
    source = history.make_plan(model)
    cases = []
    for old in source["cases"][:6]:
        payload, projection, contract = candidate.build_payload(
            old["original_payload"], source_snapshots=old["snapshots"]
        )
        case = {
            k: deepcopy(old[k])
            for k in (
                "group",
                "trial",
                "snapshots",
                "upstream",
                "historical_case_id",
                "historical_row_sha256",
                "historical_transport_sha256",
                "original_payload",
            )
        }
        case.update(
            case_id=f"{case['group']}-ALIAS_OMITTED-T{case['trial']}",
            arm=ARM,
            prompt_input=projection,
            original_prompt_input=deepcopy(json.loads(old["original_payload"]["prompt"])["input"]),
            candidate_payload=payload,
            candidate_input_sha256=object_hash(projection),
            candidate_transport_sha256=ordered.transport_hash(payload),
            candidate_property_orders=ordered.property_orders(payload),
            evaluation_input_contract=contract,
        )
        cases.append(case)
    hashes = dict(source["source_hashes"])
    for path in (
        "scripts/answer_acquisition_alias_candidate.py",
        "scripts/evaluate_answer_acquisition_alias.py",
        "tests/evaluation/test_answer_acquisition_alias.py",
        CRITERIA,
        "docs/canonical/15-agent-capability-failure-prompt-contract.md",
    ):
        hashes[path] = existing.file_hash(ROOT / path)
    plan = {
        **source,
        "kind": "091_EXACT_ACQUISITION_ALIAS_OMISSION",
        "head_sha": head(),
        "cases": cases,
        "source_hashes": hashes,
        "scope": "EVALUATION_INPUT_VIEW_DIRECT_WIRE_NOT_REGISTERED_ROUTER_OR_PRODUCT_ACTIVATION",
        "input_contract_version": candidate.INPUT_VERSION,
        "policy": {
            "new_calls": 6,
            "unique_historical_calls": 6,
            "repair": 0,
            "retry": 0,
            "concurrency": 1,
            "timeout_seconds": 180,
            "wall_seconds": WALL_SECONDS,
            "wall_enforcement": "BEFORE_NEXT_DISPATCH",
        },
    }
    verify_wire_seals(plan)
    return plan


def record_admission(row: dict[str, Any], case: dict[str, Any]) -> None:
    # Admission/materialization still consumes the authoritative full original input.
    # The reduced view exists only at the model input boundary, never in Product State.
    full = {**case, "prompt_input": case["original_prompt_input"]}
    ordered.record_admission(row, full)
    row["evaluation_input_contract"] = case["evaluation_input_contract"]


def execute_plan(
    plan: dict[str, Any],
    output: Path,
    *,
    plan_sha256: str,
    reconstruct_plan: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    verify_wire_seals(plan)
    start, post = time.monotonic(), existing.transport._post_json
    dispatched: list[str] = []

    def bounded_post(**kwargs: Any) -> dict[str, Any]:
        if kwargs["path"] == "/api/generate":
            if time.monotonic() - start >= WALL_SECONDS:
                raise TimeoutError("091 next-dispatch wall guard reached")
            dispatched.append(ordered.transport_hash(kwargs["payload"]))
        return cast(dict[str, Any], post(**kwargs))

    def reconstruct() -> dict[str, Any]:
        verify_wire_seals(plan)
        fresh = reconstruct_plan()
        verify_wire_seals(fresh)
        return fresh

    with patch.object(existing.transport, "_post_json", bounded_post):
        raw = recorder.execute_registered_plan(
            plan,
            output,
            plan_sha256=plan_sha256,
            reconstruct_plan=reconstruct,
            claim_directory=".answer-acquisition-alias-trials",
            reference_results=plan["historical_references"],
            reference_metric="088_historical_six_unique_firsts",
            stop_after_response=record_admission,
        )
    for index, row in enumerate(raw["calls"]):
        sent = index < len(dispatched)
        row.update(actual_http_dispatched=sent, wire_request_count=int(sent), arm=ARM)
        if not sent:
            row["state"] = "NOT_DISPATCHED"
    raw["actual_http_calls"] = len(dispatched)
    raw["metrics"]["control_new"] = metrics(
        [r for r in raw["calls"] if r["actual_http_dispatched"]]
    )
    raw.update(transport_dispatch_sha256=dispatched, registered_router_calls=0, scope=plan["scope"])
    write_json(output / "raw.json", raw)
    return raw


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--execute-plan", type=Path)
    parser.add_argument("--result-dir", type=Path, required=True)
    parser.add_argument("--plan-sha256")
    args = parser.parse_args()
    if args.prepare:
        directory = recorder._output_directory(args.result_dir)
        plan = make_plan(existing.inspect_diagnostic_model("presence_zero"))
        path = directory / "preregistered-plan.json"
        write_json(path, plan, exclusive=True)
        print(json.dumps({"plan": str(path), "sha256": object_hash(plan), "generation_calls": 0}))
        return
    if not args.plan_sha256:
        parser.error("--execute-plan requires --plan-sha256")
    raw = execute_plan(
        history.registered._read(args.execute_plan),
        args.result_dir,
        plan_sha256=args.plan_sha256,
        reconstruct_plan=lambda: make_plan(existing.inspect_diagnostic_model("presence_zero")),
    )
    print(json.dumps({k: raw[k] for k in ("diagnostic_status", "actual_http_calls")}))
    raise SystemExit(0 if raw["diagnostic_status"] == "RECORDED" else 1)


if __name__ == "__main__":
    main()
