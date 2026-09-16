"""Compare frozen Review inputs with Retrieval's validated availability result."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from scripts.evaluate_review_decomposition_node import MODEL_ID, _runtime

from google_work_agent.adapters.llm.ollama.transport import OllamaHTTPClient
from google_work_agent.application.agents.review.contracts.review_findings import (
    review_inspector_output_schema,
    review_recheck_output_schema,
)
from google_work_agent.application.prompt_runtime.prompt_registry import (
    DEVELOPMENT_SMOKE,
    default_prompt_manifest_path,
    load_prompt_reference,
)
from google_work_agent.application.use_cases.run.account_provider_dispatch import (
    provider_dispatch_budget_scope,
    provider_dispatch_execution_scope,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget

GOAL = "review.inspect_goal_and_evidence"
RECHECK = "review.recheck_affected_dimensions"
PROMPTS = (GOAL, RECHECK)
FIELD = "availability_results"
ORDER = (
    ("NORMAL_023", "A"),
    ("NORMAL_023", "B"),
    ("NORMAL_028", "B"),
    ("NORMAL_028", "A"),
    ("USER_EDIT_023", "A"),
    ("USER_EDIT_023", "B"),
    ("MISSING_MAIL_023", "B"),
    ("MISSING_MAIL_023", "A"),
    ("WRONG_DATE_023", "A"),
    ("WRONG_DATE_023", "B"),
    ("FORBIDDEN_ATTENDEE_023", "B"),
    ("FORBIDDEN_ATTENDEE_023", "A"),
)


def _bundle(root: Path) -> Path:
    source = default_prompt_manifest_path().parent
    target = root / "prompt-candidate"
    target.mkdir()
    shutil.copytree(source / "sources", target / "sources")
    manifest = json.loads((source / "prompt_manifest.json").read_text(encoding="utf-8"))
    contract = json.loads(
        (source / "prompt_runtime_input_contract_v1.json").read_text(encoding="utf-8")
    )
    for prompt_id in PROMPTS:
        entry = next(item for item in manifest["slots"] if item["prompt_slot_id"] == prompt_id)
        input_entry = next(
            item for item in contract["entries"] if item["prompt_slot_id"] == prompt_id
        )
        entry["input_schema_version"] = 2
        input_entry["input_schema_version"] = 2
        if FIELD not in input_entry["optional_root_fields"]:
            input_entry["optional_root_fields"].append(FIELD)
    path = target / "prompt_manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    (target / "prompt_runtime_input_contract_v1.json").write_text(
        json.dumps(contract, ensure_ascii=False), encoding="utf-8"
    )
    return path


def _availability(case: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = [
        input_data["availability_results"]
        for item in case["work_analysis"]["structured_inference_outputs"]
        if isinstance((input_data := item.get("prompt_input")), dict)
        and "availability_results" in input_data
    ]
    if len(candidates) != 1 or not candidates[0]:
        raise ValueError("frozen actual availability result is unavailable")
    return deepcopy(candidates[0])


def _rows(
    cycle: dict[str, Any], connected: dict[str, Any]
) -> list[tuple[str, str, str, dict[str, Any], int, list[dict[str, Any]]]]:
    saved = {item["label"]: item for item in cycle["cases"]}
    upstream = {item["case_id"]: item for item in connected["cases"]}
    rows = []
    for label, arm in ORDER:
        case = saved[label]
        source_case = case["source_case"]
        stage = (
            case["stages"][-1]
            if label in {"WRONG_DATE_023", "FORBIDDEN_ATTENDEE_023"}
            else case["stages"][0]
        )
        prompt_id = RECHECK if stage["stage"] == "review_recheck" else GOAL
        details = next(
            item for item in stage["inference_details"] if item["prompt_id"] == prompt_id
        )
        prompt_input = deepcopy(details["prompt_input"])
        availability = _availability(upstream[source_case])
        if arm == "B":
            prompt_input[FIELD] = availability
        rows.append(
            (
                label,
                arm,
                prompt_id,
                prompt_input,
                upstream[source_case]["reference_started_at_ms"],
                availability,
            )
        )
    return rows


def _fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def evaluate(cycle_path: Path, connected_path: Path, output_path: Path) -> None:
    cycle_bytes = cycle_path.read_bytes()
    connected_bytes = connected_path.read_bytes()
    cycle = json.loads(cycle_bytes)
    connected = json.loads(connected_bytes)
    digest = next(
        (
            item.digest
            for item in OllamaHTTPClient().list_installed_models()
            if item.model_id == MODEL_ID
        ),
        None,
    )
    if digest != cycle["binding"]["model_digest"]:
        raise ValueError("installed model differs from frozen Review cycle")
    rows = _rows(cycle, connected)
    if len(rows) != 12:
        raise ValueError("predeclared comparison size changed")
    root = Path(tempfile.mkdtemp(prefix="gwa-review-availability-"))
    manifest = _bundle(root)
    runtime = _runtime(root / "runtime", manifest)
    refs = {
        prompt_id: load_prompt_reference(prompt_id, manifest, execution_scope=DEVELOPMENT_SMOKE)
        for prompt_id in PROMPTS
    }
    result: dict[str, Any] = {
        "binding": {
            "baseline_sha": "53842ae6",
            "cycle_sha256": hashlib.sha256(cycle_bytes).hexdigest(),
            "connected_sha256": hashlib.sha256(connected_bytes).hexdigest(),
            "model_id": MODEL_ID,
            "model_digest": digest,
            "sampling_temperature": 0.0,
            "sampling_seed": 1729,
            "prompt_hashes": {key: value.content_hash for key, value in refs.items()},
            "call_limit": len(rows),
            "provider_read_enabled": False,
            "provider_write_enabled": False,
        },
        "trials": [],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    for label, arm, prompt_id, prompt_input, started_at_ms, availability in rows:
        started = time.perf_counter()
        schema = (
            review_inspector_output_schema(prompt_id)
            if prompt_id == GOAL
            else review_recheck_output_schema(tuple(prompt_input["affected_dimensions"]))
        )
        trial: dict[str, Any] = {
            "label": label,
            "arm": arm,
            "prompt_id": prompt_id,
            "input_sha256": _fingerprint(prompt_input),
            "availability_sha256": _fingerprint(availability),
            "prompt_input": prompt_input,
        }
        try:
            with (
                provider_dispatch_execution_scope(
                    run_id=f"review-availability-{label}-{arm}",
                    now_ms=lambda base=started_at_ms, start=started: (
                        base + int((time.perf_counter() - start) * 1_000)
                    ),
                ),
                provider_dispatch_budget_scope(
                    build_default_run_budget(started_at_ms=started_at_ms)
                ),
            ):
                inference = runtime.infer("LOCAL_GPU", refs[prompt_id], prompt_input, schema)
            trial.update(
                {
                    "outcome": "COMPLETED",
                    "structured_output": inference.structured_output,
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
                    "message": str(error),
                }
            )
        trial["duration_ms"] = int((time.perf_counter() - started) * 1_000)
        result["trials"].append(trial)
        output_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(label, arm, trial["outcome"], flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycle", type=Path, required=True)
    parser.add_argument("--connected", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evaluate(args.cycle, args.connected, args.output)


if __name__ == "__main__":
    main()
