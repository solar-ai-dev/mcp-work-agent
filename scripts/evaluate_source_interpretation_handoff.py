"""Inactive, sealed final-interpretation -> Product Source admission diagnostic."""

from __future__ import annotations

import argparse
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from scripts import evaluate_ru_semantic_capability as control
from scripts.evaluate_effect_prohibition_sampler import write_json
from scripts.ru_observation import metrics, object_hash

from google_work_agent.application.agents.request_understanding.identify_source_dependencies import (  # noqa: E501
    build_source_dependency_candidates,
    build_source_dependency_output_schema,
)
from google_work_agent.application.agents.request_understanding.merge_resource_responsibilities import (  # noqa: E501
    merge_resource_responsibilities,
)
from google_work_agent.application.prompt_runtime.assemble_prompt import assemble_prompt
from google_work_agent.application.prompt_runtime.prompt_registry import EVALUATION, PromptRegistry
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_development_tool_registry,
)

existing, ROOT, RESULTS = control.existing, control.ROOT, control.RESULTS
PROMPT_ID = "request_understanding.identify_source_dependencies"
CANDIDATE_ID = "evaluation.source_interpretation_handoff"
INPUT_CONTRACT = "evaluation-source-optional-interpretation-v1"
INPUT_DECLARATION = (
    "추가 optional 입력 interpretation_candidate는 같은 사용자 요청을 해석한 모델의 "
    "비권위 참고문이다. 사용자 원문이나 기존 입력을 대체하지 않으며, "
    "Source 결정은 기존 책임대로 판단한다."
)
INTERPRETATION_RAW = RESULTS / "072-ru-natural-reasoning-t1/raw.json"
INTERPRETATION_HASH = "af183697e4a0e1b5aa68a5ca5d270dc2f115d7704cd02581cbcd38128a6f7186"
INTERPRETATION_PLAN_HASH = "1cc3c0658d2c9e423024363c3af542db1525fc13b0289b9120281e430185a0ab"
CASE_IDS = ("CASE-CORE-017", "CASE-CORE-049", "CASE-CORE-005")
CRITERIA = "evaluation/experiments/074-source-interpretation-handoff-criteria.md"


def build_payload(original: dict[str, Any], interpretation: str) -> dict[str, Any]:
    """Keep original authority and strict output; add an explicitly inactive input."""
    if not isinstance(interpretation, str) or not interpretation.strip():
        raise ValueError("nonempty exact final interpretation required")
    body = json.loads(original["prompt"])
    if not isinstance(body, dict) or set(body) != {"prompt_ref", "input", "output_schema"}:
        raise ValueError("Product FIRST envelope required")
    projection = body["input"]
    if not isinstance(projection, dict) or set(projection) != {
        *control.INPUT_FIELDS,
        "requested_work",
        "goal_candidate",
        "source_candidates",
    }:
        raise ValueError("exact original Source FIRST fields required")
    registry = PromptRegistry()
    ref = registry.lookup_for_evaluation(PROMPT_ID)
    if body["prompt_ref"] != {
        "prompt_id": ref.prompt_id,
        "prompt_version": ref.prompt_version,
        "content_hash": ref.content_hash,
    }:
        raise ValueError("original Source PromptRef differs from Product")
    catalog = list(build_source_dependency_candidates(load_development_tool_registry()))
    if projection["source_candidates"] != catalog:
        raise ValueError("original Source catalog differs from current Registry")
    work_ids = [unit["unit_id"] for unit in projection["requested_work"]["work_units"]]
    schema = build_source_dependency_output_schema(catalog, work_unit_ids=work_ids).json_schema
    if body["output_schema"] != schema or original.get("format") != schema:
        raise ValueError("original Source schema differs from Product")
    instruction = assemble_prompt(ref, projection, registry=registry, execution_scope=EVALUATION)
    if original["system"] != instruction:
        raise ValueError("original Source assembly differs from Product")
    role = registry.source_text(PROMPT_ID).rstrip()
    suffix = (
        json.dumps(projection, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    )
    if not instruction.startswith(role + "\n\n") or not instruction.endswith(suffix):
        raise ValueError("unsupported Product FIRST assembly")
    candidate_role = role + "\n\n" + INPUT_DECLARATION
    result, candidate_body = deepcopy(original), deepcopy(body)
    candidate_body["input"]["interpretation_candidate"] = interpretation
    candidate_body["prompt_ref"] = {
        "prompt_id": CANDIDATE_ID,
        "prompt_version": "v1",
        "content_hash": hashlib.sha256(candidate_role.encode("utf-8")).hexdigest(),
    }
    result["system"] = (
        candidate_role
        + instruction[len(role) : -len(suffix)]
        + json.dumps(
            candidate_body["input"], ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )
        + "\n"
    )
    result["prompt"] = json.dumps(candidate_body, ensure_ascii=False, sort_keys=True)
    return result


def make_plan(model: dict[str, Any]) -> dict[str, Any]:
    if existing.file_hash(INTERPRETATION_RAW) != INTERPRETATION_HASH:
        raise ValueError("frozen interpretation bytes changed")
    raw = control.shared.read_json(INTERPRETATION_RAW)
    frozen = raw["binding"]
    if (
        object_hash(frozen) != INTERPRETATION_PLAN_HASH
        or raw["plan_sha256"] != INTERPRETATION_PLAN_HASH
        or not raw["completed"]
        or not raw["binding_unchanged"]
        or raw["diagnostic_status"] != "RECORDED"
        or raw["actual_http_calls"] != 3
        or frozen["model"] != model
    ):
        raise ValueError("complete frozen interpretation with identical model required")
    current = control.make_plan(model)  # Current Source wire/validator, no generation.
    cases = []
    for case_id in CASE_IDS:
        source = next(c for c in current["cases"] if c["case_id"] == case_id)
        old_cases = [c for c in frozen["cases"] if c["case_id"] == case_id]
        rows = [r for r in raw["calls"] if r["case_id"] == case_id]
        if len(old_cases) != 1 or len(rows) != 1:
            raise ValueError("exactly one frozen interpretation per Core required")
        old, row = old_cases[0], rows[0]
        payload = old["candidate_payload"]
        call = source["source_call"]
        if (
            old["case_binding"] != source["case_binding"]
            or payload != row["payload"]
            or row["wire_sha256"] != object_hash(payload)
            or old["candidate_wire_sha256"] != object_hash(payload)
            or row["input_sha256"] != old["candidate_input_sha256"]
            or row["input_sha256"] != object_hash(json.loads(payload["prompt"]))
            or json.loads(payload["prompt"]) != {k: call["input"][k] for k in control.INPUT_FIELDS}
            or payload != {**source["candidate_payload"], "think": True}
            or row["state"] != "RETURNED"
            or row["wire_request_count"] != 1
            or row["validation"] != "NONEMPTY_TEXT"
            or row["done"] is not True
            or row["model"] != model["model_id"]
        ):
            raise ValueError("interpretation current request/wire/completion mismatch")
        candidate = build_payload(existing.reconstruct_payload(call), row["content"])
        cases.append(
            {
                "case_id": case_id,
                "case_binding": deepcopy(source["case_binding"]),
                "source_call": deepcopy(call),
                "candidate_payload": candidate,
                "candidate_wire_sha256": object_hash(candidate),
                "candidate_input_sha256": object_hash(json.loads(candidate["prompt"])["input"]),
                "interpretation_result": {**deepcopy(row), "new_call": False},
                "interpretation_row_sha256": object_hash(row),
                "historical_source_result": deepcopy(source["historical_source_result"]),
            }
        )
    hashes = dict(current["source_hashes"])
    for path in (
        "scripts/evaluate_source_interpretation_handoff.py",
        "tests/evaluation/test_source_interpretation_handoff.py",
        "docs/canonical/15-agent-capability-failure-prompt-contract.md",
        CRITERIA,
    ):
        hashes[path] = existing.file_hash(ROOT / path)
    return {
        "kind": "INACTIVE_SOURCE_INTERPRETATION_HANDOFF_074",
        "head_sha": current["head_sha"],
        "model": model,
        "cases": cases,
        "input_contract": INPUT_CONTRACT,
        "source_reference_head": current["baseline_head"],
        "source_reference_raw_sha256": current["baseline_raw_sha256"],
        "interpretation_head": frozen["head_sha"],
        "interpretation_raw_sha256": INTERPRETATION_HASH,
        "source_hashes": hashes,
        "historical_file_differences": {
            p: {"historical": digest, "current": hashes.get(p)}
            for p, digest in frozen["source_hashes"].items()
            if digest != hashes.get(p)
        },
        "dataset_sha256": current["dataset_sha256"],
        "fixture_sha256": current["fixture_sha256"],
        "policy": {
            "new_calls": 3,
            "trials": 1,
            "concurrency": 1,
            "timeout_seconds": 180,
            "retry": 0,
            "repair": 0,
            "provider_calls": 0,
            "graph_calls": 0,
        },
        "semantic_verdict": "NOT_REVIEWED",
        "business_success": "NOT_EVALUATED",
    }


def admit_source(content: object, case: dict[str, Any]) -> dict[str, Any]:
    validation = existing.validate_response(content, {**case, "owner": "source"})
    merged = None
    if validation["structural_result"] == "VALIDATED":
        projection = case["source_call"]["input"]
        merged = merge_resource_responsibilities(
            source_decisions=validation["validated_output"],
            output_decisions={"output_responsibilities": []},
            source_candidates=tuple(projection["source_candidates"]),
            output_candidates=(),
            request_text=projection["user_request"],
        )["source_reads"]
    return {
        "validation": validation,
        "merged_source_reads": merged,
        "merge_scope": "SOURCE_ONLY_EMPTY_OUTPUT_NOT_COMPLETE_RU",
        "semantic_verdict": "NOT_REVIEWED",
        "business_success": "NOT_EVALUATED",
    }


def execute_plan(plan: dict[str, Any], output: Path, *, plan_sha256: str) -> dict[str, Any]:
    raw = control.execute_registered_plan(
        plan,
        output,
        plan_sha256=plan_sha256,
        reconstruct_plan=lambda: make_plan(existing.inspect_diagnostic_model("presence_zero")),
        claim_directory=".source-interpretation-trials",
        reference_results=[c["historical_source_result"] for c in plan["cases"]],
        reference_metric="source_historical_reference",
    )
    cases = {c["case_id"]: c for c in plan["cases"]}
    admission = {
        "raw_sha256": existing.file_hash(output / "raw.json"),
        "cases": [
            {"case_id": row["case_id"], **admit_source(row.get("content"), cases[row["case_id"]])}
            for row in raw["calls"]
        ],
        "interpretation_historical_cost": metrics(
            [c["interpretation_result"] for c in plan["cases"]]
        ),
        "combined_interpretation_and_source_cost": metrics(
            [c["interpretation_result"] for c in plan["cases"]] + raw["calls"]
        ),
        "cost_scope": "ALL_REGISTERED_REPLAY_PLUS_ATTEMPTED_SOURCE_NOT_CONNECTED_EXECUTION",
    }
    write_json(output / "source-admission.json", admission, exclusive=True)
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
        output = control._output_directory(args.result_dir)
        plan = make_plan(existing.inspect_diagnostic_model("presence_zero"))
        path = output / "preregistered-plan.json"
        write_json(path, plan, exclusive=True)
        print(json.dumps({"plan": str(path), "sha256": object_hash(plan), "generation_calls": 0}))
    else:
        if not args.plan_sha256:
            parser.error("--execute-plan requires --plan-sha256")
        raw = execute_plan(
            control.shared.read_json(args.execute_plan),
            args.result_dir,
            plan_sha256=args.plan_sha256,
        )
        print(json.dumps({k: raw[k] for k in ("diagnostic_status", "actual_http_calls")}))
        raise SystemExit(0 if raw["diagnostic_status"] == "RECORDED" else 1)


if __name__ == "__main__":
    main()
