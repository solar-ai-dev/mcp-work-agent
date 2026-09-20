"""Compare flat RequestIntent with a minimal WorkUnit/WorkRelation projection.

This is an evaluation-only #287 diagnostic.  It deliberately does not run
Tool Routing, Retrieval, Work Analysis, Planning, or any Provider operation.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from argparse import ArgumentParser
from pathlib import Path
from typing import cast

from evaluation.dataset_v8 import load_cases, normalized_sha256

from google_work_agent.adapters.llm.ollama.transport import OllamaHTTPClient
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.runtime_selection import OLLAMA_FIXED_LOOPBACK_ENDPOINT
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)

MODEL_ID = "qwen3.5:9b"
EXPECTED_MODEL_DIGEST = "6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7"
DATASET = Path("evaluation/datasets/e2e/canonical_cases_v8.jsonl")
CANDIDATE_PROMPT = Path(
    "evaluation/prompt_candidates/ru-requested-work-decomposition-v1/sources/"
    "request_understanding.decompose_requested_work.md"
)


CORE24_CASE_IDS = (
    "CASE-CORE-001",
    "CASE-CORE-006",
    "CASE-CORE-009",
    "CASE-CORE-010",
    "CASE-CORE-011",
    "CASE-CORE-012",
    "CASE-CORE-019",
    "CASE-CORE-020",
    "CASE-CORE-021",
    "CASE-CORE-026",
    "CASE-CORE-027",
    "CASE-CORE-028",
    "CASE-CORE-031",
    "CASE-CORE-036",
    "CASE-CORE-037",
    "CASE-CORE-040",
    "CASE-CORE-041",
    "CASE-CORE-046",
    "CASE-CORE-048",
    "CASE-CORE-050",
    "CASE-CORE-051",
    "CASE-CORE-054",
    "CASE-CORE-056",
    "CASE-CORE-059",
)


# Historical v1 candidate contract retained only so the 046~049 raw trials can
# be reproduced.  Its generic relation is not a typed semantic authority for a
# new candidate; the corrected grader treats it as untyped.
DECOMPOSITION_SCHEMA = OutputSchemaDefinition(
    schema_version="requested-work-decomposition-v1-eval",
    json_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["work_units", "work_relations"],
        "properties": {
            "work_units": {
                "type": "array",
                "minItems": 1,
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["unit_id", "objective"],
                    "properties": {
                        "unit_id": {"type": "string", "minLength": 1},
                        "objective": {"type": "string", "minLength": 1},
                    },
                },
            },
            "work_relations": {
                "type": "array",
                "maxItems": 12,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["source_unit_id", "target_unit_id", "kind"],
                    "properties": {
                        "source_unit_id": {"type": "string", "minLength": 1},
                        "target_unit_id": {"type": "string", "minLength": 1},
                        "kind": {"const": "PROVIDES_INPUT_TO"},
                    },
                },
            },
        },
    },
)

COUNTED_DECOMPOSITION_SCHEMA = OutputSchemaDefinition(
    schema_version="requested-work-counted-decomposition-v1-eval",
    json_schema={
        **DECOMPOSITION_SCHEMA.json_schema,
        "required": ["work_count", "work_units", "work_relations"],
        "properties": {
            "work_count": {"type": "integer", "minimum": 1, "maximum": 8},
            **cast(dict[str, object], DECOMPOSITION_SCHEMA.json_schema["properties"]),
        },
    },
)


def main() -> None:
    parser = ArgumentParser()
    parser.add_argument("--result-path", type=Path, required=True)
    parser.add_argument("--case", action="append")
    parser.add_argument("--sampling-seed", type=int, default=20260920)
    parser.add_argument("--candidate-path", type=Path, default=CANDIDATE_PROMPT)
    parser.add_argument("--candidate-id", default="ru-requested-work-decomposition-v1")
    parser.add_argument("--include-work-count", action="store_true")
    arguments = parser.parse_args()
    if arguments.result_path.exists():
        raise ValueError("result path already exists; preserve every prior trial")

    case_ids = arguments.case or list(CORE24_CASE_IDS)
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("duplicate Case ID")
    if any(case_id not in CORE24_CASE_IDS for case_id in case_ids):
        raise ValueError("requested Case is not in the fixed Core comparison set")

    cases = load_cases()
    prompt_bytes = arguments.candidate_path.read_bytes()
    prompt_text = prompt_bytes.decode("utf-8").rstrip()
    prompt_hash = hashlib.sha256(prompt_bytes).hexdigest()
    canonical_authority_hash = _sha256(
        {
            case_id: {
                "canonical_user_prompt": cases[case_id].raw["canonical_user_prompt"],
                "required_semantics": cases[case_id].raw["evaluation_gold"]["required_semantics"],
                "forbidden_semantics": cases[case_id].raw["evaluation_gold"]["forbidden_semantics"],
            }
            for case_id in CORE24_CASE_IDS
        }
    )
    client = OllamaHTTPClient()
    model_digest = next(
        (model.digest for model in client.list_installed_models() if model.model_id == MODEL_ID),
        None,
    )
    if model_digest != EXPECTED_MODEL_DIGEST:
        raise ValueError("local model digest differs from the preregistered comparison")

    prompt_ref = PromptReference(
        prompt_bundle_version="evaluation-only",
        prompt_id="request_understanding.decompose_requested_work",
        prompt_version="requested-work-decomposition-v1-eval",
        content_hash=prompt_hash,
        agent_role="REQUEST_UNDERSTANDING",
        subgraph_name="request_understanding",
        node_name="decompose_requested_work",
        node_state="INITIAL",
        purpose="EVALUATION_ONLY_REQUESTED_WORK_DECOMPOSITION",
        input_schema_version="user-request-only-v1",
        output_schema_version=(
            COUNTED_DECOMPOSITION_SCHEMA.schema_version
            if arguments.include_work_count
            else DECOMPOSITION_SCHEMA.schema_version
        ),
    )
    output_schema = (
        COUNTED_DECOMPOSITION_SCHEMA if arguments.include_work_count else DECOMPOSITION_SCHEMA
    )
    result: dict[str, object] = {
        "binding": {
            "product_sha": _git_head(),
            "dataset_sha256": normalized_sha256(DATASET),
            "canonical_authority_sha256": canonical_authority_hash,
            "prompt_sha256": prompt_hash,
            "candidate_id": arguments.candidate_id,
            "model_id": MODEL_ID,
            "model_digest": model_digest,
            "temperature": 0.0,
            "seed": arguments.sampling_seed,
            "scope": "EVALUATION_ONLY_RU_REQUESTED_WORK_DECOMPOSITION",
            "candidate_calls_per_case": 1,
            "includes_work_count": arguments.include_work_count,
            "provider_read_count": 0,
            "provider_write_count": 0,
        },
        "summary": {
            "case_count": len(case_ids),
            "candidate_count_matches": 0,
            "schema_valid": 0,
        },
        "cases": [],
    }
    _write(arguments.result_path, result)
    records = cast(list[dict[str, object]], result["cases"])
    summary = cast(dict[str, object], result["summary"])

    for case_id in case_ids:
        raw = cases[case_id].raw
        if raw.get("split") != "CORE":
            raise ValueError(f"{case_id}: Holdout/Stress is not allowed for tuning")
        request = str(raw["canonical_user_prompt"])

        started = time.perf_counter()
        response = client.invoke_structured(
            endpoint=OLLAMA_FIXED_LOOPBACK_ENDPOINT,
            model_id=MODEL_ID,
            prompt_ref=prompt_ref,
            prompt_input={"user_request": request},
            output_schema=output_schema,
            timeout_seconds=180,
            instruction_text=prompt_text,
            sampling_temperature=0.0,
            sampling_seed=arguments.sampling_seed,
        )
        candidate = json.loads(cast(str, response.content))
        validation_errors = [
            *validate_output_schema(candidate, output_schema.json_schema),
            *_validate_decomposition(candidate, require_work_count=arguments.include_work_count),
        ]
        units = candidate.get("work_units", []) if isinstance(candidate, dict) else []
        relations = candidate.get("work_relations", []) if isinstance(candidate, dict) else []
        count_matches = not arguments.include_work_count or (
            isinstance(candidate, dict) and candidate.get("work_count") == len(units)
        )
        record = {
            "case_id": case_id,
            "category": raw["category"],
            "user_request": request,
            "canonical_authority": {
                "required_semantics": raw["evaluation_gold"]["required_semantics"],
                "forbidden_semantics": raw["evaluation_gold"]["forbidden_semantics"],
            },
            "candidate": candidate,
            "candidate_schema_errors": validation_errors,
            "candidate_count_matches": count_matches,
            "candidate_input_tokens": response.input_tokens,
            "candidate_output_tokens": response.output_tokens,
            "candidate_latency_ms": response.latency_ms,
            "wall_ms": int((time.perf_counter() - started) * 1_000),
        }
        records.append(record)
        summary["candidate_count_matches"] = cast(int, summary["candidate_count_matches"]) + int(
            count_matches
        )
        summary["schema_valid"] = cast(int, summary["schema_valid"]) + int(not validation_errors)
        _write(arguments.result_path, result)
        print(
            json.dumps(
                {
                    "case_id": case_id,
                    "actual_units": len(units),
                    "actual_relations": len(relations),
                    "schema_valid": not validation_errors,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )


def _validate_decomposition(
    value: object,
    *,
    require_work_count: bool = False,
) -> list[str]:
    if not isinstance(value, dict):
        return ["candidate is not an object"]
    units = value.get("work_units")
    relations = value.get("work_relations")
    if not isinstance(units, list) or not isinstance(relations, list):
        return []
    unit_ids = [
        str(unit.get("unit_id"))
        for unit in units
        if isinstance(unit, dict) and isinstance(unit.get("unit_id"), str)
    ]
    errors: list[str] = []
    if require_work_count and value.get("work_count") != len(units):
        errors.append("work_count must match the number of work_units")
    if len(unit_ids) != len(set(unit_ids)):
        errors.append("work unit ids must be unique")
    known_ids = set(unit_ids)
    edges: set[tuple[str, str]] = set()
    for index, relation in enumerate(relations):
        if not isinstance(relation, dict):
            continue
        source = relation.get("source_unit_id")
        target = relation.get("target_unit_id")
        edge = (str(source), str(target))
        if source not in known_ids or target not in known_ids or source == target:
            errors.append(f"$.work_relations[{index}] has invalid endpoints")
        if edge in edges:
            errors.append(f"$.work_relations[{index}] duplicates an existing relation")
        edges.add(edge)
    if _has_cycle(unit_ids, edges):
        errors.append("work relations must be acyclic")
    return errors


def _has_cycle(unit_ids: list[str], edges: set[tuple[str, str]]) -> bool:
    outgoing: dict[str, set[str]] = {unit_id: set() for unit_id in unit_ids}
    indegree = {unit_id: 0 for unit_id in unit_ids}
    for source, target in edges:
        if source not in outgoing or target not in indegree:
            continue
        if target not in outgoing[source]:
            outgoing[source].add(target)
            indegree[target] += 1
    ready = [unit_id for unit_id, degree in indegree.items() if degree == 0]
    visited = 0
    while ready:
        current = ready.pop()
        visited += 1
        for target in outgoing[current]:
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
    return visited != len(unit_ids)


def _sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


if __name__ == "__main__":
    main()
