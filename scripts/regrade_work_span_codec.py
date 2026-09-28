"""Replay existing Work FIRST outputs; never infer or grade business semantics.

The candidate expands selector admission only. Original artifacts remain untouched,
and exact source slices, uncovered text and structural acceptance stay distinct.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from typing import Any

from scripts import evaluate_production_snapshot_workflow as shared
from scripts.production_work_span_codec_candidate import (
    SELECTOR_WHITESPACE,
    materialize_work_spans,
)
from scripts.ru_observation import object_hash

from google_work_agent.application.agents.request_understanding.contracts.work_unit_binding import (
    validate_requested_work_definition,
)
from google_work_agent.application.agents.request_understanding.identify_requested_work import (
    REQUESTED_WORK_OUTPUT_SCHEMA,
    validate_requested_work_candidate,
)
from google_work_agent.application.prompt_runtime.prompt_registry import PromptRegistry

WORK_SLOT = "request_understanding.identify_requested_work"
DEFAULT_ROOTS = (
    shared.RESULTS_ROOT / "064-connected-core8-t1",
    shared.RESULTS_ROOT / "064-connected-core8-continuation-t1",
    shared.RESULTS_ROOT / "064-work-ref-v34-core5-t1",
)


def current_prompt_ref() -> dict[str, Any]:
    manifest = shared.default_prompt_manifest_path()
    registry = PromptRegistry(manifest, manifest.parent / "prompt_runtime_input_contract_v1.json")
    return asdict(registry.lookup_for_evaluation(WORK_SLOT))


def _sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _without_whitespace(text: str) -> str:
    return "".join(character for character in text if character not in SELECTOR_WHITESPACE)


def _positions(text: str, part: str) -> list[int]:
    if not part:
        return []
    result: list[int] = []
    start = text.find(part)
    while start >= 0:
        result.append(start)
        start = text.find(part, start + 1)
    return result


def span_observations(value: object, request: str) -> list[dict[str, Any]]:
    """Count literal matches only. No fuzzy matching or semantic reconstruction."""
    result: list[dict[str, Any]] = []
    if not isinstance(value, Mapping) or not isinstance(value.get("work_units"), list):
        return result
    for unit_index, unit in enumerate(value["work_units"]):
        if not isinstance(unit, Mapping) or not isinstance(unit.get("request_spans"), list):
            continue
        for span_index, span in enumerate(unit["request_spans"]):
            if not isinstance(span, str):
                continue
            exact = _positions(request, span)
            normalized = _without_whitespace(span)
            matches = _positions(_without_whitespace(request), normalized)
            if len(exact) == 1:
                category = "EXACT_UNIQUE"
            elif len(exact) > 1:
                category = "EXACT_AMBIGUOUS"
            elif len(matches) == 1:
                category = "WHITESPACE_ONLY_UNIQUE"
            elif len(matches) > 1:
                category = "NORMALIZED_AMBIGUOUS"
            else:
                category = "NONWHITESPACE_DIFFERENCE_OR_EMPTY"
            result.append(
                {
                    "unit_index": unit_index,
                    "span_index": span_index,
                    "selector_sha256": _sha_text(span),
                    "selector_characters": len(span),
                    "nonwhitespace_characters": len(normalized),
                    "exact_matches": len(exact),
                    "comparison_view_matches": len(matches),
                    "comparison": category,
                }
            )
    return result


def _validate(
    validator: Callable[..., Any], value: object, request: str
) -> tuple[dict[str, Any], Any]:
    try:
        definition = validator(deepcopy(value), user_request=request)
        validate_requested_work_definition(definition, user_request=request)
    except (TypeError, ValueError) as error:
        return {"structural_status": "REJECTED", "error": str(error)}, None
    covered: set[int] = set()
    provenance = []
    for unit in definition["work_units"]:
        for span in unit["request_provenance"]:
            start, end = span["start_offset"], span["end_offset"]
            covered.update(range(start, end))
            provenance.append(
                {
                    "unit_id": unit["unit_id"],
                    "start_offset": start,
                    "end_offset": end,
                    "source_text_sha256": _sha_text(span["source_text"]),
                    "exact_current_request_slice": request[start:end] == span["source_text"],
                }
            )
    return {
        "structural_status": "ACCEPTED",
        "definition_sha256": object_hash(definition),
        "work_unit_count": len(definition["work_units"]),
        "provenance": provenance,
        "uncovered_nonwhitespace_characters": sum(
            index not in covered and character not in SELECTOR_WHITESPACE
            for index, character in enumerate(request)
        ),
    }, definition


def compare_first(call: Mapping[str, Any]) -> dict[str, Any]:
    request = call["input"]["user_request"]
    content = call.get("content")
    if not isinstance(content, str):
        raise ValueError("FIRST output has no raw content")
    value = json.loads(content)
    baseline, original_definition = _validate(validate_requested_work_candidate, value, request)
    candidate, new_definition = _validate(materialize_work_spans, value, request)
    return {
        "call_index": call["call_index"],
        "input_sha256": object_hash(call["input"]),
        "request_sha256": _sha_text(request),
        "first_content_sha256": _sha_text(content),
        "output_schema_sha256": object_hash(call["output_schema"]),
        "runtime_policy": deepcopy(call.get("runtime_policy")),
        "model": call.get("model"),
        "temperature": call.get("temperature"),
        "seed": call.get("seed"),
        "wire_options": deepcopy(call.get("wire_options")),
        "wire_request_count": call.get("wire_request_count"),
        "spans": span_observations(value, request),
        "baseline": baseline,
        "candidate": candidate,
        "accepted_baseline_preserved": (
            original_definition == new_definition if original_definition is not None else None
        ),
        "semantic_verdict": "UNREVIEWED",
        "downstream_success": "NOT_EVALUATED",
    }


def build_report(
    roots: Sequence[Path], *, expected_prompt_ref: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Read only the registered artifact roots, including interrupted arm FIRSTs."""
    expected = dict(expected_prompt_ref or current_prompt_ref())
    rows: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    seen_paths: set[Path] = set()
    for root in roots:
        if not root.is_dir():
            raise ValueError(f"missing source artifact root: {root}")
        for path in sorted(root.glob("CASE-CORE-*/**/calls.json")):
            resolved = path.resolve()
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            before = path.read_bytes()
            artifact = {
                "path": path.as_posix(),
                "calls_sha256": hashlib.sha256(before).hexdigest(),
                "case_id": path.relative_to(root).parts[0],
                "arm": path.parent.name,
            }
            for call in json.loads(before)["calls"]:
                if call.get("prompt_id") != WORK_SLOT:
                    continue
                reason = None
                if call.get("prompt_ref") != expected:
                    reason = "PROMPT_REF_DIFFERS"
                elif call.get("output_schema") != REQUESTED_WORK_OUTPUT_SCHEMA.json_schema:
                    reason = "OUTPUT_SCHEMA_DIFFERS"
                elif set(call.get("input", {})) != {"user_request"}:
                    reason = "NOT_ORIGINAL_WORK_FIRST"
                elif not isinstance(call["input"]["user_request"], str):
                    reason = "INVALID_REQUEST_TYPE"
                elif call.get("input_sha256") != object_hash(call["input"]):
                    reason = "INPUT_HASH_MISMATCH"
                elif call.get("state") != "RETURNED" or not call.get("wire_request_count"):
                    reason = "NO_RETURNED_ACTUAL_WIRE_OUTPUT"
                if reason:
                    excluded.append(
                        {**artifact, "call_index": call.get("call_index"), "reason": reason}
                    )
                    continue
                try:
                    row = compare_first(call)
                except (KeyError, TypeError, ValueError) as error:
                    excluded.append(
                        {
                            **artifact,
                            "call_index": call.get("call_index"),
                            "reason": "MALFORMED_RAW",
                            "error": str(error),
                        }
                    )
                else:
                    rows.append({**artifact, **row})
            if path.read_bytes() != before:
                raise ValueError(f"artifact changed during replay: {path}")
    return {
        "schema_version": 1,
        "scope": "EXISTING_WORK_FIRST_STRUCTURAL_REPLAY_NOT_SEMANTIC_OR_WORKFLOW_EVALUATION",
        "prompt_ref": expected,
        "comparison_whitespace_codepoints": sorted(ord(item) for item in SELECTOR_WHITESPACE),
        "new_model_calls": 0,
        "provider_calls": 0,
        "original_artifacts_changed": 0,
        "source_roots": [path.as_posix() for path in roots],
        "rows": rows,
        "excluded": excluded,
        "summary": {
            "first_outputs": len(rows),
            "distinct_requests": len({row["request_sha256"] for row in rows}),
            "span_comparison": dict(
                Counter(span["comparison"] for row in rows for span in row["spans"])
            ),
            "baseline_structural": dict(
                Counter(row["baseline"]["structural_status"] for row in rows)
            ),
            "candidate_structural": dict(
                Counter(row["candidate"]["structural_status"] for row in rows)
            ),
            "baseline_acceptance_regressions": sum(
                row["accepted_baseline_preserved"] is False for row in rows
            ),
            "semantic_verdict": "UNREVIEWED",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, action="append")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(shared.RESULTS_ROOT.resolve()) or output.exists():
        raise ValueError("a new report file within evaluation/results is required")
    report = build_report(args.source_root or DEFAULT_ROOTS)
    report["replay_code_sha256"] = {
        "script": shared.file_hash(Path(__file__)),
        "candidate": shared.file_hash(
            shared.PROJECT_ROOT / "scripts/production_work_span_codec_candidate.py"
        ),
        "product_validator": shared.file_hash(
            shared.PROJECT_ROOT / "src/google_work_agent/application/agents/"
            "request_understanding/identify_requested_work.py"
        ),
    }
    shared.write_json(output, report)
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
