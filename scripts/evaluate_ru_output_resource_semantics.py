"""Compare Output ownership with Resource-owned result semantics on recorded RU inputs."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import cast

from evaluation.dataset_v8 import load_cases
from scripts.evaluate_ru_output_input_projection import EXPECTED_OUTPUTS
from scripts.evaluate_ru_source_status_prompt import EXPECTED_MODEL_DIGEST, MODEL_ID

from google_work_agent.adapters.llm.ollama.transport import OllamaHTTPClient
from google_work_agent.application.agents.request_understanding import (
    identify_output_responsibilities as output_ops,
)
from google_work_agent.application.agents.request_understanding.contracts.output_responsibility_decision import (  # noqa: E501
    OutputResponsibilityCandidateV1,
)
from google_work_agent.application.prompt_runtime.assemble_prompt import assemble_prompt
from google_work_agent.application.prompt_runtime.prompt_registry import (
    DEVELOPMENT_SMOKE,
    default_prompt_manifest_path,
    load_prompt_reference,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.runtime_selection import OLLAMA_FIXED_LOOPBACK_ENDPOINT

_RESULT_KIND_BY_RESOURCE = {
    "GMAIL_MESSAGE": "sent_email_message_or_reply",
    "GMAIL_DRAFT": "saved_email_draft_not_sent",
    "TASK": "google_task_todo_item",
    "CALENDAR_EVENT": "calendar_event_or_meeting",
    "GITHUB_ISSUE": "github_issue_or_ticket",
}


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _pairs(value: object) -> list[list[str]]:
    if not isinstance(value, dict):
        return []
    raw = value.get("output_responsibilities")
    if not isinstance(raw, list):
        return []
    return sorted(
        [
            [str(item["resource_type"]), str(item["effect"])]
            for item in raw
            if isinstance(item, dict)
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-result", type=Path, action="append", required=True)
    parser.add_argument("--result-path", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260923)
    args = parser.parse_args()
    if args.result_path.exists():
        raise ValueError("result path already exists; preserve every prior trial")
    client = OllamaHTTPClient()
    model = next(
        (item for item in client.list_installed_models() if item.model_id == MODEL_ID),
        None,
    )
    if model is None or model.digest != EXPECTED_MODEL_DIGEST:
        raise ValueError("local model digest differs from the fixed comparison")
    prompt_ref = load_prompt_reference(
        "request_understanding.identify_output_responsibilities",
        default_prompt_manifest_path(),
        execution_scope=DEVELOPMENT_SMOKE,
    )
    cases = load_cases()
    result: dict[str, object] = {
        "binding": {
            "model_id": MODEL_ID,
            "model_digest": model.digest,
            "temperature": 0.0,
            "seed": args.seed,
            "prompt_hash": prompt_ref.content_hash,
            "candidate": "OUTPUT_RESOURCE_OWNED_RESULT_KIND_V1",
            "provider_reads": 0,
            "provider_writes": 0,
        },
        "cases": [],
    }
    _write(args.result_path, result)
    records = cast(list[dict[str, object]], result["cases"])
    for trial, input_path in enumerate(args.input_result, start=1):
        source = json.loads(input_path.read_text(encoding="utf-8"))
        for case in source["cases"]:
            case_id = str(case["case_id"])
            owner_call = next(
                (
                    item
                    for item in case.get("atomic", [])
                    if item.get("prompt_id")
                    == "request_understanding.identify_output_responsibilities"
                    and item.get("attempt") == "FIRST"
                ),
                None,
            )
            if owner_call is None:
                continue
            projection = deepcopy(owner_call["input"])
            raw_candidates = cast(list[dict[str, object]], projection["output_candidates"])
            candidate_projection = [
                {
                    **candidate,
                    "owned_result_kind": _RESULT_KIND_BY_RESOURCE[str(candidate["resource_type"])],
                }
                for candidate in raw_candidates
            ]
            projection["output_candidates"] = candidate_projection
            work_unit_ids = tuple(
                str(unit["unit_id"])
                for unit in projection["requested_work"]["work_units"]
            )
            schema_candidates = cast(
                list[OutputResponsibilityCandidateV1],
                candidate_projection,
            )
            schema = output_ops.build_output_responsibility_output_schema(
                schema_candidates,
                work_unit_ids=work_unit_ids,
            )
            response = client.invoke_structured(
                endpoint=OLLAMA_FIXED_LOOPBACK_ENDPOINT,
                model_id=MODEL_ID,
                prompt_ref=prompt_ref,
                prompt_input=projection,
                output_schema=schema,
                timeout_seconds=180,
                instruction_text=assemble_prompt(
                    prompt_ref,
                    projection,
                    execution_scope=DEVELOPMENT_SMOKE,
                ),
                sampling_temperature=0.0,
                sampling_seed=args.seed,
            )
            candidate = json.loads(cast(str, response.content))
            errors = validate_output_schema(candidate, schema.json_schema)
            expected = EXPECTED_OUTPUTS.get(case_id, [])
            baseline_pairs = _pairs(owner_call["structured_output"])
            candidate_pairs = _pairs(candidate)
            record = {
                "trial": trial,
                "source_result": str(input_path),
                "case_id": case_id,
                "expected_output_pairs": expected,
                "baseline_output_pairs": baseline_pairs,
                "candidate_output_pairs": candidate_pairs,
                "baseline_semantic_valid": baseline_pairs == sorted(expected),
                "candidate_semantic_valid": not errors and candidate_pairs == sorted(expected),
                "validation_errors": errors,
                "candidate_output": candidate,
                "llm": {
                    "calls": 1,
                    "input_tokens": response.input_tokens,
                    "output_tokens": response.output_tokens,
                    "latency_ms": response.latency_ms,
                },
                "canonical_required_semantics": cases[case_id].gold.get(
                    "required_semantics"
                ),
                "canonical_forbidden_semantics": cases[case_id].gold.get(
                    "forbidden_semantics"
                ),
            }
            records.append(record)
            _write(args.result_path, result)
            print(
                json.dumps(
                    {
                        "trial": trial,
                        "case_id": case_id,
                        "baseline": baseline_pairs,
                        "candidate": candidate_pairs,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )


if __name__ == "__main__":
    main()
