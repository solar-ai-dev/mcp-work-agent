"""Run the bounded #287/#288 WorkRelation semantic-owner diagnostic."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from evaluation.dataset_v8 import DEFAULT_DATASET_PATH, load_cases, normalized_sha256
from evaluation.requested_work_relation_candidate import (
    bind_full_request_controls,
    bind_relation_case,
    relation_decision_output_schema,
    relation_decision_pairs,
    relation_diagnostic_cases,
    relation_inference_required,
    relation_output_schema,
    relation_scores,
    semantic_input_sha256,
    validate_relation_candidate,
    validate_relation_decisions,
)

from google_work_agent.adapters.llm.ollama.transport import OllamaHTTPClient
from google_work_agent.ports.llm.runtime_selection import OLLAMA_FIXED_LOOPBACK_ENDPOINT
from google_work_agent.ports.llm.structured_inference_contracts import PromptReference

ROOT = Path(__file__).resolve().parents[1]
OPTIONAL_LIST_PROMPT_PATH = (
    ROOT / "evaluation/prompt_candidates/ru-requested-work-relation-v1/sources/"
    "request_understanding.identify_work_relations.md"
)
EXHAUSTIVE_PAIRS_PROMPT_PATH = (
    ROOT / "evaluation/prompt_candidates/ru-requested-work-relation-decision-v2/sources/"
    "request_understanding.identify_work_relations.md"
)
MODEL_ID = "qwen3.5:9b"
MODEL_DIGEST = "6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result-path", type=Path, required=True)
    parser.add_argument("--product-head", required=True)
    parser.add_argument("--sampling-temperature", type=float, default=0.0)
    parser.add_argument("--sampling-seed", type=int, default=20260921)
    parser.add_argument(
        "--candidate-mode",
        choices=("optional-list", "exhaustive-pairs"),
        default="optional-list",
    )
    arguments = parser.parse_args()
    if arguments.result_path.exists():
        raise ValueError("result path already exists; preserve every prior trial")

    canonical = load_cases()
    definitions = relation_diagnostic_cases()
    if any(canonical[item["case_id"]].raw.get("split") != "CORE" for item in definitions):
        raise ValueError("WorkRelation diagnostic accepts Canonical Core only")
    client = OllamaHTTPClient()
    digest = next(
        (item.digest for item in client.list_installed_models() if item.model_id == MODEL_ID),
        None,
    )
    if digest != MODEL_DIGEST:
        raise ValueError("installed local model digest differs from the fixed binding")

    prompt_path = (
        EXHAUSTIVE_PAIRS_PROMPT_PATH
        if arguments.candidate_mode == "exhaustive-pairs"
        else OPTIONAL_LIST_PROMPT_PATH
    )
    prompt_text = prompt_path.read_text(encoding="utf-8").rstrip()
    prompt_hash = hashlib.sha256(prompt_path.read_bytes()).hexdigest()
    records: list[dict[str, object]] = []
    for definition in definitions:
        case_id = definition["case_id"]
        user_request = str(canonical[case_id].raw["canonical_user_prompt"])
        bound = bind_relation_case(
            bind_full_request_controls(definition, user_request=user_request),
            user_request=user_request,
        )
        before_hash = semantic_input_sha256(bound)
        called = relation_inference_required(bound["work_units"])
        raw_candidate: dict[str, object] = {"schema_version": 1, "work_relations": []}
        input_tokens = 0
        output_tokens = 0
        latency_ms = 0
        validation_error: str | None = None
        relation_pairs: list[dict[str, object]] = []
        started = time.perf_counter()
        if called:
            if arguments.candidate_mode == "exhaustive-pairs":
                relation_pairs = cast(
                    list[dict[str, object]],
                    relation_decision_pairs(
                        bound["work_units"], semantic_items=bound["semantic_items"]
                    ),
                )
                schema = relation_decision_output_schema(relation_pairs)
            else:
                schema = relation_output_schema(bound["work_units"])
            prompt_ref = PromptReference(
                prompt_bundle_version=f"ru-requested-work-relation-{arguments.candidate_mode}-eval",
                prompt_id="request_understanding.identify_work_relations",
                prompt_version=(
                    "2.0.0-candidate"
                    if arguments.candidate_mode == "exhaustive-pairs"
                    else "1.0.0-candidate"
                ),
                content_hash=prompt_hash,
                agent_role="request_understanding",
                subgraph_name="request_understanding",
                node_name="identify_work_relations",
                node_state="BASE",
                purpose="EVALUATION_ONLY_REQUESTED_WORK_RELATION",
                input_schema_version="requested-work-binding-v1-eval",
                output_schema_version=schema.schema_version,
            )
            response = client.invoke_structured(
                endpoint=OLLAMA_FIXED_LOOPBACK_ENDPOINT,
                model_id=MODEL_ID,
                prompt_ref=prompt_ref,
                prompt_input={
                    "user_request": bound["user_request"],
                    "work_units": bound["work_units"],
                    "semantic_items": bound["semantic_items"],
                    **({"candidate_pairs": relation_pairs} if relation_pairs else {}),
                },
                output_schema=schema,
                timeout_seconds=180,
                instruction_text=prompt_text,
                sampling_temperature=arguments.sampling_temperature,
                sampling_seed=arguments.sampling_seed,
            )
            content = response.content
            parsed = json.loads(content) if isinstance(content, str) else content
            if not isinstance(parsed, Mapping):
                raise ValueError(f"{case_id}: relation output is not an object")
            raw_candidate = dict(parsed)
            input_tokens = response.input_tokens
            output_tokens = response.output_tokens
            latency_ms = response.latency_ms
        try:
            if arguments.candidate_mode == "exhaustive-pairs" and called:
                validated = validate_relation_decisions(raw_candidate, pairs=relation_pairs)
            else:
                validated = validate_relation_candidate(
                    raw_candidate,
                    work_units=bound["work_units"],
                    semantic_items=bound["semantic_items"],
                )
        except ValueError as error:
            validation_error = str(error)
            validated = []
        raw_relations = (
            _raw_relations_from_decisions(raw_candidate)
            if arguments.candidate_mode == "exhaustive-pairs" and called
            else _raw_work_relations(raw_candidate, case_id=case_id)
        )
        score = relation_scores(bound["expected_relations"], raw_relations)
        record: dict[str, object] = {
            "case_id": case_id,
            "user_request": user_request,
            "authority_note": bound["authority_note"],
            "allowed_shape": bound.get("allowed_shape"),
            "work_units": bound["work_units"],
            "semantic_items": bound["semantic_items"],
            "expected_relations": bound["expected_relations"],
            "candidate": raw_candidate,
            "scored_relations": raw_relations,
            "validated_relations": validated,
            "validation_error": validation_error,
            "score": score,
            "relation_llm_called": called,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "latency_ms": latency_ms,
            "wall_ms": int((time.perf_counter() - started) * 1_000),
            "semantic_input_sha256": before_hash,
            "semantic_input_unchanged": semantic_input_sha256(bound) == before_hash,
        }
        records.append(record)
        _write_result(
            arguments.result_path,
            records=records,
            product_head=arguments.product_head,
            prompt_hash=prompt_hash,
            model_digest=digest,
            candidate_mode=arguments.candidate_mode,
            prompt_path=prompt_path,
            temperature=arguments.sampling_temperature,
            seed=arguments.sampling_seed,
        )
        print(
            json.dumps(
                {
                    "case_id": case_id,
                    "called": called,
                    "candidate": raw_candidate,
                    "validation_error": validation_error,
                    "score": score,
                    "latency_ms": latency_ms,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            flush=True,
        )


def _write_result(
    path: Path,
    *,
    records: list[dict[str, object]],
    product_head: str,
    prompt_hash: str,
    model_digest: str,
    candidate_mode: str,
    prompt_path: Path,
    temperature: float,
    seed: int,
) -> None:
    aggregate = _aggregate(records)
    result = {
        "version": f"ru287-288-requested-work-relation-{candidate_mode}",
        "binding": {
            "scope": "EVALUATION_ONLY_REQUESTED_WORK_RELATION",
            "product_head": product_head,
            "dataset_sha256": normalized_sha256(DEFAULT_DATASET_PATH),
            "diagnostic_authority_sha256": _diagnostic_hash(),
            "candidate_mode": candidate_mode,
            "prompt_path": prompt_path.relative_to(ROOT).as_posix(),
            "prompt_sha256": prompt_hash,
            "model_id": MODEL_ID,
            "model_digest": model_digest,
            "temperature": temperature,
            "seed": seed,
            "provider_read_count": 0,
            "provider_write_count": 0,
            "holdout_stress_used": False,
            "rerun_to_pass": 0,
        },
        "summary": aggregate,
        "cases": records,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _aggregate(records: list[dict[str, object]]) -> dict[str, object]:
    true_positive = sum(
        _integer(cast(Mapping[str, object], item["score"])["true_positive"]) for item in records
    )
    false_positive = sum(
        _integer(cast(Mapping[str, object], item["score"])["false_positive"]) for item in records
    )
    false_negative = sum(
        _integer(cast(Mapping[str, object], item["score"])["false_negative"]) for item in records
    )
    predicted = true_positive + false_positive
    expected = true_positive + false_negative
    kind_counts: dict[str, Counter[str]] = {
        kind: Counter() for kind in ("CONSUMES_WORK_PRODUCT", "CONSUMES_PLANNED_SPECIFICATION")
    }
    for record in records:
        expected_relations = cast(list[Mapping[str, object]], record["expected_relations"])
        actual_relations = cast(list[Mapping[str, object]], record["scored_relations"])
        expected_by_kind = {
            kind: {
                (_id(item, "source_unit_id"), _id(item, "target_unit_id"))
                for item in expected_relations
                if item.get("kind") == kind
            }
            for kind in kind_counts
        }
        actual_by_kind = {
            kind: {
                (_id(item, "source_unit_id"), _id(item, "target_unit_id"))
                for item in actual_relations
                if item.get("kind") == kind
            }
            for kind in kind_counts
        }
        for kind in kind_counts:
            kind_counts[kind]["true_positive"] += len(expected_by_kind[kind] & actual_by_kind[kind])
            kind_counts[kind]["false_positive"] += len(
                actual_by_kind[kind] - expected_by_kind[kind]
            )
            kind_counts[kind]["false_negative"] += len(
                expected_by_kind[kind] - actual_by_kind[kind]
            )
    return {
        "case_count": len(records),
        "relation_llm_calls": sum(bool(item["relation_llm_called"]) for item in records),
        "single_work_unit_skipped": sum(not bool(item["relation_llm_called"]) for item in records),
        "exact_match_cases": sum(
            bool(cast(Mapping[str, object], item["score"])["exact_match"]) for item in records
        ),
        "validated_cases": sum(item["validation_error"] is None for item in records),
        "semantic_input_unchanged_cases": sum(
            bool(item["semantic_input_unchanged"]) for item in records
        ),
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "precision": 1.0
        if predicted == 0 and expected == 0
        else true_positive / predicted
        if predicted
        else 0.0,
        "recall": true_positive / expected if expected else 1.0,
        "by_kind": {
            kind: {
                **dict(counts),
                "precision": counts["true_positive"]
                / (counts["true_positive"] + counts["false_positive"])
                if counts["true_positive"] + counts["false_positive"]
                else (1.0 if counts["false_negative"] == 0 else 0.0),
                "recall": counts["true_positive"]
                / (counts["true_positive"] + counts["false_negative"])
                if counts["true_positive"] + counts["false_negative"]
                else 1.0,
            }
            for kind, counts in kind_counts.items()
        },
        "input_tokens": sum(_integer(item["input_tokens"]) for item in records),
        "output_tokens": sum(_integer(item["output_tokens"]) for item in records),
        "latency_ms": sum(_integer(item["latency_ms"]) for item in records),
        "wall_ms": sum(_integer(item["wall_ms"]) for item in records),
    }


def _raw_work_relations(
    candidate: Mapping[str, object], *, case_id: str
) -> list[Mapping[str, object]]:
    raw = candidate.get("work_relations", [])
    if not isinstance(raw, list) or not all(isinstance(item, Mapping) for item in raw):
        raise ValueError(f"{case_id}: work_relations is not an object list")
    return cast(list[Mapping[str, object]], raw)


def _raw_relations_from_decisions(
    candidate: Mapping[str, object],
) -> list[Mapping[str, object]]:
    raw = candidate.get("relation_decisions", [])
    if not isinstance(raw, list) or not all(isinstance(item, Mapping) for item in raw):
        raise ValueError("relation_decisions is not an object list")
    return [
        {
            "source_unit_id": item.get("source_unit_id"),
            "target_unit_id": item.get("target_unit_id"),
            "kind": item.get("disposition"),
        }
        for item in cast(list[Mapping[str, object]], raw)
        if item.get("disposition") != "NONE"
    ]


def _diagnostic_hash() -> str:
    return hashlib.sha256(
        json.dumps(relation_diagnostic_cases(), ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _id(item: Mapping[str, object], field: str) -> str:
    value = item.get(field)
    if not isinstance(value, str):
        raise TypeError(f"relation {field} must be a string")
    return value


def _integer(value: object) -> int:
    if not isinstance(value, int):
        raise TypeError("metric must be an integer")
    return value


if __name__ == "__main__":
    main()
