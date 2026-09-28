"""V32 sparse prohibition representation, isolated from Product activation.

Reuses v31's fixed inputs, wire observations and bounded repair loop unchanged.
Only this evaluation module's imported harness symbols are temporarily adapted;
the Product registry, assembler, schemas and consumer implementations are untouched.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from evaluation.dataset_v8 import normalized_sha256
from scripts import evaluate_effect_prohibition_sampler as baseline
from scripts.ru_observation import metrics, object_hash

from google_work_agent.adapters.llm.runtime.prompt_repair_schema_repairer import (
    PromptRepairSchemaRepairer,
)
from google_work_agent.application.agents.request_understanding.contracts.effect_prohibition_decision import (  # noqa: E501
    EffectProhibitionDecisionCandidateV1,
)
from google_work_agent.application.agents.request_understanding.contracts.request_goal_candidate_schema import (  # noqa: E501
    identify_goal_output_schema,
    validate_request_goal_candidate,
)
from google_work_agent.application.agents.request_understanding.contracts.work_unit_binding import (
    work_unit_id_schema,
)
from google_work_agent.application.prompt_runtime.assemble_prompt import assemble_prompt
from google_work_agent.application.prompt_runtime.prompt_registry import EVALUATION, PromptRegistry
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)

CANDIDATE_ID = "sparse-effect-prohibitions-v32"
BASELINE_RAW = baseline.ROOT / "evaluation/results/064-prohibition-sampler-v31-t1/raw.json"
BASELINE_RAW_SHA256 = "97ea14004f5c4d4a37e298f8474d1ccb0f564bd4c80e47944f6e4fd6b7beee39"
SOURCE = """# 역할
현재 요청에서 사용자가 명시적으로 금지한 write effect만 판정한다.
요청된 effect, Resource 역할, Tool, 실행 계획은 판단하지 않는다.

# 입력
user_request가 현재 Run의 원문이다. goal_candidate는 앞선 해석이며 충돌하면 원문이 우선한다.
requested_work.work_units의 업무 경계는 확정되어 있고, 적용되는 현재 unit_id를 보존한다.
effect_candidates는 지원되는 write effect의 닫힌 목록이다.
selected_resource_refs는 선택된 identity이지 금지 근거가 아니다.
confirmation_response는 이번에 확인한 선택만 반영한다.
시간·reconsideration으로 금지를 새로 만들지 않는다.

# 출력
effect_prohibitions에는 명시적으로 금지된 effect와 해당 work_unit_ids만 나열한다.
금지가 없으면 빈 목록이다. 목록에 없다는 것은 해당 effect의 요청이나 실행 승인이 아니다.
인용·작성할 본문·예시·가정·조건부 상황을 현재 실행 금지로 바꾸지 않는다.
명시하지 않은 금지를 추측하거나 하나의 금지를 다른 effect까지 확대하지 않는다.
수정 입력에서는 실패한 필드만 고치고 나머지는 보존한다. 지정된 JSON 객체 하나만 반환한다.
"""


def candidate_ref() -> PromptReference:
    return replace(
        PromptRegistry().lookup_for_evaluation(baseline.PROMPT_ID),
        prompt_version="evaluation-sparse-v32",
        content_hash=hashlib.sha256(SOURCE.encode()).hexdigest(),
        output_schema_version="evaluation-sparse-prohibitions-v1",
    )


def sparse_schema(case: dict[str, Any]) -> OutputSchemaDefinition:
    effects = [item["effect"] for item in case["input"]["effect_candidates"]]
    if not effects or len(effects) != len(set(effects)):
        raise ValueError("existing closed effect candidates must be non-empty and unique")
    return OutputSchemaDefinition(
        schema_version="evaluation-sparse-prohibitions-v1",
        json_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["effect_prohibitions"],
            "properties": {
                "effect_prohibitions": {
                    "type": "array",
                    "minItems": 0,
                    "maxItems": len(effects),
                    "uniqueItems": True,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["effect", "work_unit_ids"],
                        "properties": {
                            "effect": {"enum": effects},
                            "work_unit_ids": work_unit_id_schema(case["work_unit_ids"]),
                        },
                    },
                    "allOf": [
                        {
                            "contains": {
                                "type": "object",
                                "properties": {"effect": {"const": effect}},
                                "required": ["effect"],
                            },
                            "minContains": 0,
                            "maxContains": 1,
                        }
                        for effect in effects
                    ],
                }
            },
        },
    )


def validate_sparse(value: object, case: dict[str, Any]) -> dict[str, Any]:
    errors = validate_output_schema(value, sparse_schema(case).json_schema)
    if errors:
        raise ValueError(f"sparse prohibition shape invalid: {'; '.join(errors)}")
    return cast(dict[str, Any], deepcopy(value))


def to_owner_decisions(value: object, case: dict[str, Any]) -> EffectProhibitionDecisionCandidateV1:
    validated = validate_sparse(value, case)
    # The sparse owner contract means each listed item is prohibited. No inferred
    # negative rows, Resource scope, Work union, or semantic correction is added.
    return cast(
        EffectProhibitionDecisionCandidateV1,
        {
            "effect_prohibitions": [
                {**item, "prohibition": "FORBIDDEN"} for item in validated["effect_prohibitions"]
            ]
        },
    )


def normalize_with_product(value: object, case: dict[str, Any]) -> list[dict[str, Any]]:
    """Exercise only the actual Goal normalizer, not a fabricated Source/Output Run."""
    normalized = validate_request_goal_candidate(
        case["input"]["goal_candidate"],
        resource_responsibilities={"source_reads": [], "outputs": []},
        effect_prohibitions=to_owner_decisions(value, case),
        requested_work=case["input"]["requested_work"],
        schema=identify_goal_output_schema(case["work_unit_ids"]),
        work_unit_ids=case["work_unit_ids"],
    )
    return cast(list[dict[str, Any]], normalized["effect_prohibitions"])


def instruction(ref: PromptReference, projection: Mapping[str, object]) -> str:
    if ref != candidate_ref():
        raise ValueError("candidate PromptRef mismatch")
    registry = PromptRegistry()
    base_ref = registry.lookup_for_evaluation(baseline.PROMPT_ID)
    base = assemble_prompt(base_ref, projection, registry=registry, execution_scope=EVALUATION)
    source = registry.source_text(baseline.PROMPT_ID).rstrip()
    if not base.startswith(source + "\n"):
        raise ValueError("Product assembly no longer has a separable owner source")
    return SOURCE.rstrip() + base[len(source) :]


def review_sparse(value: object, case: dict[str, Any]) -> dict[str, Any]:
    if validate_output_schema(value, sparse_schema(case).json_schema):
        return {"result": "STRUCTURALLY_INVALID", "business_success": "NOT_EVALUATED"}
    decisions = to_owner_decisions(value, case)
    observed = {item["effect"] for item in decisions["effect_prohibitions"]}
    expected = set(case["review"]["expected_forbidden_effects"])
    return {
        "missing_prohibitions": sorted(expected - observed),
        "invented_prohibitions": sorted(observed - expected),
        "observed_decisions": deepcopy(decisions["effect_prohibitions"]),
        "expectation": deepcopy(case["review"]),
        "result": "OWNER_EXPECTATION_MET" if observed == expected else "OWNER_EXPECTATION_MISMATCH",
        "business_success": "NOT_EVALUATED",
    }


@contextmanager
def sparse_harness(case: dict[str, Any]) -> Iterator[None]:
    """Scope adaptations to the reused evaluation module, never Product globals."""
    ref = candidate_ref()

    class RegistryView:
        def lookup_for_evaluation(self, prompt_id: str) -> PromptReference:
            if prompt_id != ref.prompt_id:
                raise ValueError("wrong owner requested")
            return ref

    def finalize(value: object, **kwargs: Any) -> dict[str, Any]:
        if kwargs["effect_candidates"] != case["input"]["effect_candidates"]:
            raise ValueError("frozen effect candidates changed")
        if kwargs["work_unit_ids"] != case["work_unit_ids"]:
            raise ValueError("frozen Work binding changed")
        return validate_sparse(value, case)

    def repairer(**kwargs: Any) -> PromptRepairSchemaRepairer:
        return PromptRepairSchemaRepairer(
            execution_scope=kwargs["execution_scope"],
            prompt_loader=lambda *args, **kw: ref,
        )

    with patch.multiple(
        baseline,
        PromptRegistry=RegistryView,
        schema_for=sparse_schema,
        assemble_prompt=lambda current, value, **kw: instruction(current, value),
        validate_effect_prohibition_candidate=finalize,
        review_output=review_sparse,
        PromptRepairSchemaRepairer=repairer,
    ):
        yield


def run_candidate(case: dict[str, Any], client: baseline.OllamaHTTPClient) -> dict[str, Any]:
    with sparse_harness(case):
        row = baseline.run_arm(case, "model_default", client)
    row["candidate_id"] = CANDIDATE_ID
    if row["final"]["structural_result"] == "PASS":
        try:
            row["normalized_prohibitions"] = normalize_with_product(
                row["final"]["validated_output"],
                case,
            )
            row["normalizer_probe"] = "PASS_EMPTY_RESPONSIBILITIES_NOT_CONNECTED_WORKFLOW"
        except ValueError as error:
            row["normalizer_probe"] = {"result": "FAIL", "error": str(error)}
    return row


def baseline_reuse(current: dict[str, Any], path: Path = BASELINE_RAW) -> dict[str, Any]:
    if hashlib.sha256(path.read_bytes()).hexdigest() != BASELINE_RAW_SHA256:
        raise ValueError("frozen baseline raw changed")
    old = json.loads(path.read_text(encoding="utf-8"))
    old_binding = old["binding"]
    for field in (
        "model",
        "prompt_ref",
        "dataset_sha256",
        "fixture_sha256",
        "frozen_inputs_sha256",
        "policy",
    ):
        if current[field] != old_binding[field]:
            raise ValueError(f"baseline {field} mismatch")
    # Other Prompt slots may change their global files; this owner's ref, exact
    # assembled system/input/format and source still have to match below.
    slot_scoped = {
        "src/google_work_agent/application/prompt_runtime/prompt_manifest.json",
        "src/google_work_agent/application/prompt_runtime/prompt_runtime_input_contract_v1.json",
    }
    for path_name, digest in old_binding["source_hashes"].items():
        if path_name not in slot_scoped and current["source_hashes"][path_name] != digest:
            raise ValueError(f"baseline related implementation changed: {path_name}")
    contract_path = (
        "src/google_work_agent/application/prompt_runtime/prompt_runtime_input_contract_v1.json"
    )
    previous_contract = json.loads(
        subprocess.check_output(
            ["git", "show", f"{old_binding['head_sha']}:{contract_path}"],
            cwd=baseline.ROOT,
        )
    )
    current_contract = json.loads((baseline.ROOT / contract_path).read_text(encoding="utf-8"))

    def owner_contract(document: dict[str, Any]) -> dict[str, Any]:
        return {
            **{key: value for key, value in document.items() if key != "entries"},
            "entries": [
                entry
                for entry in document["entries"]
                if entry["prompt_slot_id"] == baseline.PROMPT_ID
            ],
        }

    if owner_contract(previous_contract) != owner_contract(current_contract):
        raise ValueError("baseline owner input contract or global forbidden fields changed")
    rows = [row for row in old["results"] if row["arm"] == "model_default"]
    if len(rows) != 6 or {row["case_id"] for row in rows} != set(baseline.CASE_IDS):
        raise ValueError("baseline lacks the six preregistered cases")
    by_id = {case["case_id"]: case for case in current["cases"]}
    for row in rows:
        case = by_id[row["case_id"]]
        wire = row["wire_calls"][0]
        if (
            row["input_sha256"] != case["input_sha256"]
            or wire["format_sha256"] != case["schema_sha256"]
            or wire["system_sha256"] != case["instruction_sha256"]
            or wire["options"] != {"num_ctx": 16384, "seed": baseline.SEED}
            or wire["think"] is not False
        ):
            raise ValueError("baseline actual wire input/schema/Prompt/runtime mismatch")
    return {
        "raw_path": str(path.relative_to(baseline.ROOT))
        if path.is_relative_to(baseline.ROOT)
        else str(path),
        "raw_sha256": BASELINE_RAW_SHA256,
        "origin_head": old_binding["head_sha"],
        "rows": rows,
        "global_slot_files": {
            name: {
                "before": old_binding["source_hashes"][name],
                "current": current["source_hashes"][name],
            }
            for name in sorted(slot_scoped)
        },
        "contract": "UNCHANGED_OWNER_IMPLEMENTATION_AND_EXACT_WIRE_NO_OLD_SCORE_REGRADING",
        "owner_input_contract_sha256": object_hash(owner_contract(current_contract)),
    }


def make_plan(model: dict[str, Any]) -> dict[str, Any]:
    base = baseline.make_plan(model)
    reuse = baseline_reuse(base)
    cases = baseline.fixed_cases()
    for case in cases:
        case.update(
            sparse_schema=asdict(sparse_schema(case)),
            sparse_schema_sha256=object_hash(sparse_schema(case).json_schema),
            instruction_sha256=hashlib.sha256(
                instruction(candidate_ref(), case["input"]).encode()
            ).hexdigest(),
        )
    return {
        **{key: value for key, value in base.items() if key not in {"cases", "order"}},
        "candidate_id": CANDIDATE_ID,
        "candidate_prompt_ref": asdict(candidate_ref()),
        "candidate_source_sha256": hashlib.sha256(SOURCE.encode()).hexdigest(),
        "candidate_module_sha256": normalized_sha256(Path(__file__)),
        "consumer_source_hashes": {
            name: normalized_sha256(baseline.ROOT / name)
            for name in (
                "src/google_work_agent/application/agents/request_understanding/contracts/request_goal_candidate_schema.py",
                "src/google_work_agent/application/agents/request_understanding/identify_output_responsibilities.py",
            )
        },
        "cases": cases,
        "order": list(baseline.CASE_IDS),
        "baseline_reuse": reuse,
        "arm": "model_default",
        "max_first_calls": 6,
        "max_total_calls": 12,
        "new_baseline_calls": 0,
        "reused_baseline_cases": 6,
        "old_baseline_scores_reused": 6,
        "baseline_reuse_scope": "ONLY_VERIFIED_V31_MODEL_DEFAULT_OWNER_ROWS",
        "pre_v31_baseline_scores_reused": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result-dir", type=Path, required=True)
    parser.add_argument("--execute-plan", type=Path)
    parser.add_argument("--expected-plan-sha256")
    args = parser.parse_args()
    output = args.result_dir.resolve()
    result_root = (baseline.ROOT / "evaluation/results").resolve()
    if not output.is_relative_to(result_root) or output == result_root:
        raise ValueError("dedicated evaluation/results directory required")
    client = baseline.OllamaHTTPClient()
    plan = make_plan(baseline.inspect_model(client))
    if args.execute_plan is None:
        path = output / "preregistered-plan.json"
        baseline.write_json(path, plan, exclusive=True)
        print(json.dumps({"plan": str(path), "sha256": normalized_sha256(path), "model_calls": 0}))
        return
    if normalized_sha256(args.execute_plan) != args.expected_plan_sha256:
        raise ValueError("registered plan hash mismatch")
    if plan != json.loads(args.execute_plan.read_text(encoding="utf-8")):
        raise ValueError("frozen binding changed")
    baseline.write_json(
        result_root / ".sparse-prohibition-trials" / f"{args.expected_plan_sha256}.json",
        {"output": str(output)},
        exclusive=True,
    )
    raw: dict[str, Any] = {"binding": plan, "results": [], "completed": False}
    path = output / "raw.json"
    baseline.write_json(path, raw, exclusive=True)
    for case in plan["cases"]:
        row = run_candidate(case, client)
        raw["results"].append(row)
        baseline.write_json(path, raw)
        print(
            json.dumps({"case_id": case["case_id"], "final": row["final"]}, ensure_ascii=False),
            flush=True,
        )
    raw["metrics"] = metrics([call for row in raw["results"] for call in row["transport_calls"]])
    raw["completed"] = True
    baseline.write_json(path, raw)


if __name__ == "__main__":
    main()
