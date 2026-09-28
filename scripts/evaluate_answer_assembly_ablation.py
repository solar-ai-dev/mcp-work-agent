"""090: isolated historical-wire probes, not registered Product inference."""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from scripts import evaluate_answer_mode_first as ordered
from scripts import evaluate_registered_answer_choice as registered
from scripts.evaluate_effect_prohibition_sampler import head, write_json
from scripts.ru_observation import metrics, object_hash

from google_work_agent.application.prompt_runtime.assemble_prompt import (
    _PRODUCT_CONTEXT_INSTRUCTION,
)

previous = ordered.previous
recorder, existing = previous.recorder, previous.existing
ROOT, RESULTS = previous.ROOT, previous.RESULTS
HISTORY = RESULTS / "088-registered-answer-choice-t1/raw.json"
HISTORY_HASH = "41e086022a73ae24405e886e466052c0d2a78371258d82aa7b652f31d2788d0c"
CRITERIA = "evaluation/experiments/090-answer-assembly-ablation-criteria.md"
ARMS = ("CONTEXT_REMOVED", "VERSION_METADATA_084")
GROUPS = registered.GROUPS[:3]
WALL_SECONDS = 1200


def build_payload(original: dict[str, Any], *, arm: str, prior_version: str) -> dict[str, Any]:
    """Preserve transport bytes except the declared single diagnostic factor."""
    if arm not in ARMS or not prior_version:
        raise ValueError("closed arm and historical version required")
    payload = deepcopy(original)
    if arm == ARMS[0]:
        system = payload.get("system")
        if not isinstance(system, str) or system.count(_PRODUCT_CONTEXT_INSTRUCTION) != 1:
            raise ValueError("exactly one current Product context block required")
        # Do not strip surrounding newlines or change the following input heading.
        payload["system"] = system.replace(_PRODUCT_CONTEXT_INSTRUCTION, "", 1)
    else:
        body = json.loads(payload["prompt"])
        if json.dumps(body, ensure_ascii=False, sort_keys=True) != payload["prompt"]:
            raise ValueError("canonical original prompt serialization required")
        ref = body.get("prompt_ref")
        if not isinstance(ref, dict) or not isinstance(ref.get("prompt_version"), str):
            raise ValueError("actual prompt_ref version required")
        if ref["prompt_version"] == prior_version:
            raise ValueError("metadata probe must change the historical version")
        ref["prompt_version"] = prior_version
        payload["prompt"] = json.dumps(body, ensure_ascii=False, sort_keys=True)
    return payload


def _read_history() -> tuple[dict[str, Any], dict[str, Any]]:
    if (
        existing.file_hash(HISTORY) != HISTORY_HASH
        or existing.file_hash(registered.HISTORY) != registered.HISTORY_HASH
    ):
        raise ValueError("sealed 088/084 history changed")
    raw, prior = registered._read(HISTORY), registered._read(registered.HISTORY)
    if (
        not raw["completed"]
        or not raw["binding_unchanged"]
        or not raw["model_binding_unchanged"]
        or raw["fake_wire"]
        or not prior["completed"]
        or not prior["binding_unchanged"]
    ):
        raise ValueError("completed real immutable histories required")
    return raw, prior


def _cases(
    raw: dict[str, Any], prior: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cases, references = [], []
    for arm in ARMS:
        for trial in (1, 2):
            for group in GROUPS if arm == ARMS[0] else GROUPS[:1]:
                sources = [
                    c
                    for c in raw["binding"]["cases"]
                    if c["group"] == group and c["trial"] == trial
                ]
                if len(sources) != 1:
                    raise ValueError("unique historical input required")
                source = sources[0]
                rows = [r for r in raw["calls"] if r["case_id"] == source["case_id"]]
                old_cases = [
                    c
                    for c in prior["binding"]["cases"]
                    if c["group"] == group and c["trial"] == trial
                ]
                if len(rows) != 1 or len(old_cases) != 1:
                    raise ValueError("one un-repaired FIRST and prior version per input required")
                row, old = rows[0], old_cases[0]
                payload = row["payload"]
                sealed = source["expected_first"]
                rebuilt = registered.expected_first(source["prompt_input"], source["snapshots"])
                if (
                    row["phase"] != "FIRST"
                    or row["state"] != "RETURNED"
                    or row["wire_request_count"] != 1
                    or row["provider_response_metadata"].get("done") is not True
                    or row["actual_model"] != raw["binding"]["model"]["model_id"]
                    or ordered.transport_hash(payload) != row["transport_sha256"]
                    or ordered.transport_hash(payload) != sealed["transport_sha256"]
                    or ordered.transport_hash(payload) != ordered.transport_hash(rebuilt["payload"])
                    or object_hash(row["input"]) != row["input_sha256"]
                    or row["input"] != source["prompt_input"]
                    or old["prompt_input"] != source["prompt_input"]
                    or old["snapshots"] != source["snapshots"]
                ):
                    raise ValueError("actual historical FIRST/current assembly/input drift")
                old_body = json.loads(old["candidate_payload"]["prompt"])
                body = json.loads(payload["prompt"])
                if old_body["prompt_ref"]["content_hash"] != body["prompt_ref"]["content_hash"]:
                    raise ValueError("historical role changed")
                version = old_body["prompt_ref"]["prompt_version"]
                candidate = build_payload(payload, arm=arm, prior_version=version)
                cases.append(
                    {
                        "case_id": f"{group}-{arm}-T{trial}",
                        "group": group,
                        "arm": arm,
                        "trial": trial,
                        "prompt_input": deepcopy(source["prompt_input"]),
                        "snapshots": deepcopy(source["snapshots"]),
                        "upstream": source["upstream"],
                        "historical_case_id": source["case_id"],
                        "historical_row_sha256": object_hash(row),
                        "historical_transport_sha256": ordered.transport_hash(payload),
                        "original_payload": deepcopy(payload),
                        "prior_version": version,
                        "candidate_payload": candidate,
                        "candidate_input_sha256": object_hash(
                            json.loads(candidate["prompt"])["input"]
                        ),
                        "candidate_transport_sha256": ordered.transport_hash(candidate),
                        "candidate_property_orders": ordered.property_orders(candidate),
                        "metadata_status": "UNREGISTERED_WIRE_PROBE_NOT_PRODUCT_REF_RESOLUTION",
                    }
                )
                if arm == ARMS[0]:
                    references.append(deepcopy(row))
    return cases, references


def verify_wire_seals(plan: dict[str, Any]) -> None:
    expected = [
        (arm, group, trial)
        for arm in ARMS
        for trial in (1, 2)
        for group in (GROUPS if arm == ARMS[0] else GROUPS[:1])
    ]
    if [(c["arm"], c["group"], c["trial"]) for c in plan["cases"]] != expected:
        raise ValueError("fixed A6 then B2 schedule required")
    ordered.verify_wire_seals(plan)
    for case in plan["cases"]:
        transformed = build_payload(
            case["original_payload"], arm=case["arm"], prior_version=case["prior_version"]
        )
        if ordered.transport_hash(transformed) != case["candidate_transport_sha256"]:
            raise ValueError("undeclared wire change")
        if ordered.transport_hash(case["original_payload"]) != case["historical_transport_sha256"]:
            raise ValueError("historical wire seal drift")


def make_plan(model: dict[str, Any]) -> dict[str, Any]:
    raw, prior = _read_history()
    if model != raw["binding"]["model"] or model != prior["binding"]["model"]:
        raise ValueError("model digest/backend/parameters differ from historical comparison")
    canonical = deepcopy(prior["binding"]["canonical_binding"])
    if existing.file_hash(existing.DEFAULT_DATASET_PATH) != canonical["dataset_sha256"]:
        raise ValueError("Canonical dataset drift")
    cases, references = _cases(raw, prior)
    paths = set(raw["binding"]["source_hashes"]) | {
        "scripts/evaluate_answer_assembly_ablation.py",
        "tests/evaluation/test_answer_assembly_ablation.py",
        "scripts/evaluate_ru_semantic_capability.py",
        CRITERIA,
    }
    plan = {
        "kind": "090_ANSWER_ASSEMBLY_TRANSPORT_ABLATION",
        "head_sha": head(),
        "model": model,
        "cases": cases,
        "historical_references": references,
        "historical_head_sha": raw["binding"]["head_sha"],
        "history_hashes": {
            str(HISTORY.relative_to(ROOT)): HISTORY_HASH,
            str(registered.HISTORY.relative_to(ROOT)): registered.HISTORY_HASH,
        },
        "canonical_binding": canonical,
        "provider_fixture_sha256": existing.file_hash(existing.DEFAULT_PROVIDER_FIXTURE_PATH),
        "source_hashes": {p: existing.file_hash(ROOT / p) for p in sorted(paths)},
        "scope": "UNREGISTERED_TRANSPORT_DIAGNOSTIC_NOT_ROUTER_GRAPH_OR_PRODUCT_ACTIVATION",
        "policy": {
            "new_calls": 8,
            "unique_historical_calls": 6,
            "repair": 0,
            "retry": 0,
            "concurrency": 1,
            "timeout_seconds": 180,
            "wall_seconds": WALL_SECONDS,
            "wall_enforcement": "BEFORE_NEXT_DISPATCH",
        },
        "semantic_verdict": "NOT_REVIEWED",
        "business_success": "NOT_EVALUATED",
    }
    verify_wire_seals(plan)
    return plan


def execute_plan(
    plan: dict[str, Any],
    output: Path,
    *,
    plan_sha256: str,
    reconstruct_plan: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    """Reuse the sealed FIRST recorder; add only the pre-dispatch wall guard."""
    verify_wire_seals(plan)
    start = time.monotonic()
    post = existing.transport._post_json
    dispatched: list[str] = []

    def bounded_post(**kwargs: Any) -> dict[str, Any]:
        if kwargs["path"] == "/api/generate":
            if time.monotonic() - start >= WALL_SECONDS:
                raise TimeoutError("090 next-dispatch wall guard reached")
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
            claim_directory=".answer-assembly-ablation-trials",
            reference_results=plan["historical_references"],
            reference_metric="088_historical_six_unique_firsts",
            stop_after_response=ordered.record_admission,
        )
    for index, row in enumerate(raw["calls"]):
        was_sent = index < len(dispatched)
        row["wire_request_count"] = int(was_sent)
        row["actual_http_dispatched"] = was_sent
        row["arm"] = plan["cases"][index]["arm"]
        if not was_sent:
            row["state"] = "NOT_DISPATCHED"
    raw["actual_http_calls"] = len(dispatched)
    raw["metrics"]["control_new"] = metrics(
        [r for r in raw["calls"] if r["actual_http_dispatched"]]
    )
    raw["transport_dispatch_sha256"] = dispatched
    raw["registered_router_calls"] = 0
    raw["scope"] = plan["scope"]
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
        registered._read(args.execute_plan),
        args.result_dir,
        plan_sha256=args.plan_sha256,
        reconstruct_plan=lambda: make_plan(existing.inspect_diagnostic_model("presence_zero")),
    )
    print(json.dumps({k: raw[k] for k in ("diagnostic_status", "actual_http_calls")}))
    raise SystemExit(0 if raw["diagnostic_status"] == "RECORDED" else 1)


if __name__ == "__main__":
    main()
