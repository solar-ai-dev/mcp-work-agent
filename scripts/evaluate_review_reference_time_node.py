"""Replay frozen Review inputs with the current-Run reference-time projection only."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
import time
from dataclasses import fields
from pathlib import Path
from typing import cast
from uuid import uuid4

from google_work_agent.adapters.llm.ollama.transport import OllamaHTTPClient
from google_work_agent.adapters.llm.runtime.llm_credential_router import (
    SessionMemorySecretStore,
)
from google_work_agent.api.composition import (
    ProductionRuntimeConfig,
    build_production_runtime,
)
from google_work_agent.application.agents.project_run_reference_time import (
    project_run_reference_time,
)
from google_work_agent.application.agents.review.contracts.review_findings import (
    review_inspector_output_schema,
    validate_review_inspector_result,
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
from google_work_agent.application.use_cases.run.guard_run_budget import (
    build_default_run_budget,
)
from google_work_agent.application.use_cases.setting.update_settings import (
    UpdateSettingsCommand,
)
from google_work_agent.ports.system.settings_port import SettingsPatchV1

PROMPT_ID = "review.inspect_goal_and_evidence"
MODEL_ID = "qwen3.5:9b"


def _candidate_manifest(
    runtime_root: Path, *, optional_field: str = "run_reference_time"
) -> Path:
    """Keep the rejected optional-input candidate isolated from product artifacts."""
    source = default_prompt_manifest_path().parent
    target = runtime_root / "prompt-candidate"
    target.mkdir()
    shutil.copytree(source / "sources", target / "sources")
    manifest = json.loads((source / "prompt_manifest.json").read_text(encoding="utf-8"))
    contract = json.loads(
        (source / "prompt_runtime_input_contract_v1.json").read_text(encoding="utf-8")
    )
    manifest_entry = next(
        item for item in manifest["slots"] if item["prompt_slot_id"] == PROMPT_ID
    )
    contract_entry = next(
        item for item in contract["entries"] if item["prompt_slot_id"] == PROMPT_ID
    )
    manifest_entry["input_schema_version"] = 2
    contract_entry["input_schema_version"] = 2
    if optional_field not in contract_entry["optional_root_fields"]:
        contract_entry["optional_root_fields"].append(optional_field)
    (target / "prompt_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    (target / "prompt_runtime_input_contract_v1.json").write_text(
        json.dumps(contract, ensure_ascii=False), encoding="utf-8"
    )
    return target / "prompt_manifest.json"


def evaluate(input_path: Path, output_path: Path) -> dict[str, object]:
    source = json.loads(input_path.read_text(encoding="utf-8"))
    if source["binding"]["model_id"] != MODEL_ID:
        raise ValueError("saved input model differs from fixed comparison model")
    installed = {
        model.model_id: model.digest for model in OllamaHTTPClient().list_installed_models()
    }
    if installed.get(MODEL_ID) != source["binding"]["model_digest"]:
        raise ValueError("installed model digest differs from saved baseline")
    runtime_root = Path(tempfile.mkdtemp(prefix="gwa-review-reference-"))
    candidate_manifest = _candidate_manifest(runtime_root)
    config = ProductionRuntimeConfig.development(
        runtime_root=runtime_root,
        working_directory=Path(__file__).resolve().parents[1],
        mcp_manifest_version="2026-08-07.p0",
        keyring_store=SessionMemorySecretStore(),
        prompt_manifest_path=candidate_manifest,
        sampling_temperature=0.0,
        sampling_seed=1729,
    )
    container = build_production_runtime(
        **{field.name: getattr(config, field.name) for field in fields(config)},
        bootstrap_secret=uuid4().hex,
        service_instance_id=f"review-reference-{uuid4()}",
    )
    runtime = container.structured_inference_port
    settings = container.update_settings_handler
    if runtime is None or settings is None:
        raise RuntimeError("local inference runtime is unavailable")
    runtime.run_context_provider = lambda: None
    settings(
        UpdateSettingsCommand(
            str(uuid4()),
            SettingsPatchV1(
                schema_version=1,
                preferred_local_model_id=MODEL_ID,
                preferred_llm_mode="LOCAL_GPU",
                external_llm_consent=False,
            ),
        )
    )
    prompt_ref = load_prompt_reference(
        PROMPT_ID, candidate_manifest, execution_scope=DEVELOPMENT_SMOKE
    )
    schema = review_inspector_output_schema(PROMPT_ID)
    rows: list[dict[str, object]] = []
    for case in source["cases"]:
        case_id = case["case_id"]
        if case_id not in {"CASE-CORE-023", "CASE-CORE-028"}:
            raise ValueError(f"unplanned case: {case_id}")
        captured = [
            detail
            for detail in case["work_analysis"]["downstream"]["inference_details"]
            if detail["prompt_id"] == PROMPT_ID
        ]
        if len(captured) != 1:
            raise ValueError(f"expected one frozen Review input: {case_id}")
        baseline = captured[0]
        original = baseline["prompt_input"]
        if "run_reference_time" in original:
            raise ValueError("baseline already contains the candidate projection")
        started_at_ms = case["reference_started_at_ms"]
        reference = project_run_reference_time({"started_at_ms": started_at_ms})
        if reference is None:
            raise ValueError("current-Run reference time is unavailable")
        candidate = {**original, "run_reference_time": reference}
        input_sha = hashlib.sha256(
            json.dumps(original, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        started = time.perf_counter()
        row: dict[str, object] = {
            "case_id": case_id,
            "baseline_input_sha256": input_sha,
            "baseline_structured_output": baseline["structured_output"],
            "run_reference_time": reference,
        }
        try:
            with (
                provider_dispatch_execution_scope(
                    run_id=f"review-reference-{case_id}",
                    now_ms=lambda started_at_ms=started_at_ms, started=started: (
                        started_at_ms + int((time.perf_counter() - started) * 1_000)
                    ),
                ),
                provider_dispatch_budget_scope(
                    build_default_run_budget(started_at_ms=started_at_ms)
                ),
            ):
                inference = runtime.infer("LOCAL_GPU", prompt_ref, candidate, schema)
            validated = validate_review_inspector_result(
                inference.structured_output, expected_dimension=PROMPT_ID
            )
            row.update(
                {
                    "outcome": "COMPLETED",
                    "candidate_input": candidate,
                    "candidate_structured_output": validated,
                    "input_tokens": inference.input_tokens,
                    "output_tokens": inference.output_tokens,
                    "provider_latency_ms": inference.latency_ms,
                }
            )
        except Exception as error:
            code = getattr(error, "code", None)
            row.update(
                {
                    "outcome": "FAILED",
                    "error_type": type(error).__name__,
                    "error_code": getattr(code, "value", None),
                }
            )
        row["duration_ms"] = int((time.perf_counter() - started) * 1_000)
        rows.append(row)
    result: dict[str, object] = {
        "binding": {
            "input_path": str(input_path),
            "model_id": MODEL_ID,
            "model_digest": installed[MODEL_ID],
            "sampling_temperature": 0.0,
            "sampling_seed": 1729,
            "provider_read_enabled": False,
            "provider_write_enabled": False,
        },
        "cases": rows,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate(args.input, args.output)
    for row in cast(list[dict[str, object]], result["cases"]):
        print(row["case_id"], row["outcome"], row["duration_ms"])


if __name__ == "__main__":
    main()
