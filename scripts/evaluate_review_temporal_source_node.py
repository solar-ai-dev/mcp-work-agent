"""Compare Review inputs after separating Gmail receipt metadata from event content."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

from scripts.evaluate_review_decomposition_node import MODEL_ID, PROMPT_ID, _runtime
from scripts.evaluate_review_reference_time_node import _candidate_manifest

from google_work_agent.adapters.llm.ollama.transport import OllamaHTTPClient
from google_work_agent.application.agents.project_run_reference_time import (
    project_run_reference_time,
)
from google_work_agent.application.agents.review.contracts.review_findings import (
    review_inspector_output_schema,
    validate_review_inspector_result,
)
from google_work_agent.application.prompt_runtime.prompt_registry import (
    DEVELOPMENT_SMOKE,
    load_prompt_reference,
)
from google_work_agent.application.use_cases.run.account_provider_dispatch import (
    provider_dispatch_budget_scope,
    provider_dispatch_execution_scope,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget


def _project_input(
    original: dict[str, object], started_at_ms: int, *, include_reference: bool
) -> dict[str, object]:
    candidate = deepcopy(original)
    intent = cast(dict[str, Any], candidate["request_intent"])
    axes = {
        axis
        for item in intent.get("constraints", [])
        if item.get("field") == "temporal_axis"
        for axis in (
            item["value"] if isinstance(item.get("value"), list) else [item.get("value")]
        )
        if isinstance(axis, str)
    }
    if axes == {"EVENT_TIME"}:
        for evidence in cast(list[dict[str, Any]], candidate["evidence"]):
            handle = evidence.get("resource_handle")
            locator = evidence.get("locator")
            excerpt = evidence.get("excerpt")
            if (
                not isinstance(handle, str)
                or not handle.startswith("gmail_thread:")
                or not isinstance(locator, dict)
                or not isinstance(locator.get("received_at"), str)
                or not isinstance(excerpt, str)
                or not excerpt.startswith("Message:")
                or "Thread messages collected:" not in excerpt
            ):
                continue
            envelope = f"Received: {locator['received_at']}"
            lines = excerpt.splitlines(keepends=True)
            matching = [index for index, line in enumerate(lines) if line.strip() == envelope]
            if len(matching) != 1:
                continue
            evidence["excerpt"] = "".join(
                line for index, line in enumerate(lines) if index != matching[0]
            )
            evidence["locator"] = {
                key: value for key, value in locator.items() if key != "received_at"
            }
    if include_reference:
        reference = project_run_reference_time({"started_at_ms": started_at_ms})
        if reference is None:
            raise ValueError("current-Run reference time is unavailable")
        candidate["run_reference_time"] = reference
    return candidate


def _cases(stage: int, actual: dict[str, object], synthetic: dict[str, object],
           preview: dict[str, object] | None) -> list[tuple[str, str, dict[str, object], int]]:
    rows: list[tuple[str, str, dict[str, object], int]] = []
    if stage == 1:
        for case in cast(list[dict[str, Any]], actual["cases"]):
            captured = [
                detail
                for detail in case["work_analysis"]["downstream"]["inference_details"]
                if detail["prompt_id"] == PROMPT_ID
            ]
            if len(captured) != 1:
                raise ValueError("actual Review input capture count changed")
            original = cast(dict[str, object], captured[0]["prompt_input"])
            started_at_ms = cast(int, case["reference_started_at_ms"])
            for arm, include_reference in (("C1", False), ("C2", True)):
                rows.append(
                    (
                        case["case_id"],
                        arm,
                        _project_input(
                            original, started_at_ms, include_reference=include_reference
                        ),
                        started_at_ms,
                    )
                )
    elif stage == 2:
        by_label = {
            item["label"]: item
            for item in cast(list[dict[str, object]], synthetic["cases"])
        }
        for label in (
            "WRONG_ACTION_DATE",
            "MISSING_EXTERNAL_MAIL",
            "FORBIDDEN_ATTENDEE",
        ):
            item = by_label[label]
            started_at_ms = cast(int, item["started_at_ms"])
            rows.append(
                (
                    label,
                    "C2",
                    _project_input(
                        cast(dict[str, object], item["baseline_input"]),
                        started_at_ms,
                        include_reference=True,
                    ),
                    started_at_ms,
                )
            )
        if preview is None:
            raise ValueError("stage 2 requires the corrected Preview input")
        edit = next(
            item
            for item in cast(list[dict[str, object]], preview["trials"])
            if item["label"] == "USER_PREVIEW_EDIT_CLEAR" and item["arm"] == "A"
        )
        original = deepcopy(
            cast(dict[str, object], by_label["USER_PREVIEW_EDIT"]["baseline_input"])
        )
        edited_input = cast(dict[str, Any], edit["prompt_input"])
        original["planning_result"] = edited_input["planning_result"]
        original["user_action_modifications"] = edited_input["user_action_modifications"]
        started_at_ms = cast(int, by_label["USER_PREVIEW_EDIT"]["started_at_ms"])
        rows.append(
            (
                "USER_PREVIEW_EDIT_CLEAR",
                "C2",
                _project_input(original, started_at_ms, include_reference=True),
                started_at_ms,
            )
        )
    elif stage == 3:
        for case in cast(list[dict[str, Any]], actual["cases"]):
            captured = [
                detail
                for detail in case["work_analysis"]["downstream"]["inference_details"]
                if detail["prompt_id"] == PROMPT_ID
            ]
            if len(captured) != 1:
                raise ValueError("actual Review input capture count changed")
            original = cast(dict[str, object], captured[0]["prompt_input"])
            started_at_ms = cast(int, case["reference_started_at_ms"])
            for trial_index in (1, 2):
                for arm in ("A", "C2"):
                    rows.append(
                        (
                            f"{case['case_id']}:{trial_index}",
                            arm,
                            original
                            if arm == "A"
                            else _project_input(
                                original, started_at_ms, include_reference=True
                            ),
                            started_at_ms,
                        )
                    )
    else:
        raise ValueError("stage must be 1, 2, or 3")
    if len(rows) != (8 if stage == 3 else 4):
        raise ValueError("predeclared stage call count changed")
    return rows


def evaluate(
    actual_path: Path, synthetic_path: Path, preview_path: Path | None,
    output_path: Path, *, stage: int,
) -> dict[str, object]:
    actual = json.loads(actual_path.read_text(encoding="utf-8"))
    synthetic = json.loads(synthetic_path.read_text(encoding="utf-8"))
    preview = (
        json.loads(preview_path.read_text(encoding="utf-8"))
        if preview_path is not None
        else None
    )
    installed = {
        item.model_id: item.digest for item in OllamaHTTPClient().list_installed_models()
    }
    if installed.get(MODEL_ID) != actual["binding"]["model_digest"]:
        raise ValueError("installed model digest differs from saved actual inputs")
    rows = _cases(stage, actual, synthetic, preview)
    root = Path(tempfile.mkdtemp(prefix="gwa-review-temporal-source-"))
    manifest = _candidate_manifest(root, optional_field="run_reference_time")
    runtime = _runtime(root / "runtime", manifest)
    reference = load_prompt_reference(
        PROMPT_ID, manifest, execution_scope=DEVELOPMENT_SMOKE
    )
    schema = review_inspector_output_schema(PROMPT_ID)
    result: dict[str, object] = {
        "binding": {
            "baseline_sha": "2523f699",
            "actual_source_sha256": hashlib.sha256(actual_path.read_bytes()).hexdigest(),
            "synthetic_source_sha256": hashlib.sha256(synthetic_path.read_bytes()).hexdigest(),
            "stage": stage,
            "model_id": MODEL_ID,
            "model_digest": installed[MODEL_ID],
            "sampling_temperature": 0.0,
            "sampling_seed": 1729,
            "prompt_content_hash": reference.content_hash,
            "call_limit": len(rows),
            "provider_read_enabled": False,
            "provider_write_enabled": False,
        },
        "trials": [],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    for label, arm, prompt_input, started_at_ms in rows:
        started = time.perf_counter()
        trial: dict[str, object] = {
            "label": label,
            "arm": arm,
            "input_sha256": hashlib.sha256(
                json.dumps(prompt_input, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest(),
            "prompt_input": prompt_input,
        }
        try:
            with (
                provider_dispatch_execution_scope(
                    run_id=f"review-temporal-source-{stage}-{label}-{arm}",
                    now_ms=lambda started_at_ms=started_at_ms, started=started: (
                        started_at_ms + int((time.perf_counter() - started) * 1_000)
                    ),
                ),
                provider_dispatch_budget_scope(
                    build_default_run_budget(started_at_ms=started_at_ms)
                ),
            ):
                inference = runtime.infer("LOCAL_GPU", reference, prompt_input, schema)
            validated = validate_review_inspector_result(
                inference.structured_output, expected_dimension=PROMPT_ID
            )
            trial.update(
                {
                    "outcome": "COMPLETED",
                    "structured_output": validated,
                    "input_tokens": inference.input_tokens,
                    "output_tokens": inference.output_tokens,
                    "provider_latency_ms": inference.latency_ms,
                }
            )
        except Exception as error:
            code = getattr(error, "code", None)
            trial.update(
                {
                    "outcome": "FAILED",
                    "error_type": type(error).__name__,
                    "error_code": getattr(code, "value", None),
                }
            )
        trial["duration_ms"] = int((time.perf_counter() - started) * 1_000)
        cast(list[dict[str, object]], result["trials"]).append(trial)
        output_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(label, arm, trial["outcome"], trial["duration_ms"], flush=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--actual", type=Path, required=True)
    parser.add_argument("--synthetic", type=Path, required=True)
    parser.add_argument("--preview", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--stage", type=int, choices=(1, 2, 3), required=True)
    args = parser.parse_args()
    evaluate(args.actual, args.synthetic, args.preview, args.output, stage=args.stage)


if __name__ == "__main__":
    main()
