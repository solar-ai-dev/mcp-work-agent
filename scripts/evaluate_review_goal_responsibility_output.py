"""Compare separated Goal finding responsibilities within one structured inference."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

from scripts.evaluate_review_decomposition_node import MODEL_ID, _runtime
from scripts.evaluate_review_edit_provenance import _inputs
from scripts.evaluate_review_reference_time_node import _candidate_manifest

from google_work_agent.adapters.llm.ollama.transport import OllamaHTTPClient
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
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.llm.structured_inference_contracts import OutputSchemaDefinition

PROMPT_ID = "review.inspect_goal_and_evidence"
GROUPS = {
    "request_alignment": ["ISSUE", "ROUTE_ISSUE", "BLOCKER"],
    "external_evidence": ["ISSUE", "EVIDENCE_GAP", "BLOCKER"],
    "user_choice": ["CONFIRMATION"],
}


def _bundle(root: Path) -> Path:
    manifest_path = _candidate_manifest(root, prompt_id=PROMPT_ID)
    source_path = manifest_path.parent / "sources" / f"{PROMPT_ID}.md"
    existing = source_path.read_text(encoding="utf-8")
    prefix, separator, _ = existing.rpartition("# 출력")
    if not separator:
        raise ValueError("Goal Prompt has no output section")
    source_path.write_text(
        prefix
        + "# 출력\n\n"
        + "하나의 JSON 객체에서 request_alignment는 요청과 제안의 불일치, "
        + "external_evidence는 외부 근거의 부재·오용, user_choice는 사용자가 "
        + "아직 결정해야 할 실제 선택만 기록한다. 같은 결함을 여러 배열에 "
        + "반복하지 않는다. 해당 결함이 없으면 그 배열은 비운다. 각 항목은 "
        + "기존 finding 형식이며 supplied schema의 종류만 사용한다. "
        + "description은 자연스러운 한국어다. JSON 객체 하나만 반환한다.\n",
        encoding="utf-8",
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = next(item for item in manifest["slots"] if item["prompt_slot_id"] == PROMPT_ID)
    entry["content_hash"] = hashlib.sha256(source_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return manifest_path


def _schema() -> OutputSchemaDefinition:
    base = review_inspector_output_schema(PROMPT_ID).json_schema
    finding = base["properties"]["findings"]["items"]
    properties = {
        group: {
            "type": "array",
            "items": {
                **deepcopy(finding),
                "properties": {
                    **deepcopy(finding["properties"]),
                    "finding_kind": {"enum": kinds},
                },
            },
        }
        for group, kinds in GROUPS.items()
    }
    return OutputSchemaDefinition(
        schema_version="review-goal-responsibility-result-v2",
        json_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["schema_version", "dimension", *GROUPS],
            "properties": {
                "schema_version": {"const": 2},
                "dimension": {"const": PROMPT_ID},
                **properties,
            },
        },
    )


def _flatten(output: Any) -> dict[str, Any]:
    if not isinstance(output, dict) or set(output) != {"schema_version", "dimension", *GROUPS}:
        raise ValueError("Goal responsibility output keys are invalid")
    findings = [finding for group in GROUPS for finding in output[group]]
    return validate_review_inspector_result(
        {"schema_version": 1, "dimension": output["dimension"], "findings": findings},
        expected_dimension=PROMPT_ID,
    )


def evaluate(cycle_path: Path, baseline_path: Path, output_path: Path) -> None:
    cycle_bytes = cycle_path.read_bytes()
    cycle = json.loads(cycle_bytes)
    baseline_bytes = baseline_path.read_bytes()
    baseline = json.loads(baseline_bytes)
    if len(baseline["trials"]) != 16:
        raise ValueError("frozen baseline changed")
    source_cases = {item["label"]: item for item in cycle["cases"]}
    input_rows = [(label, value) for label, value, _ in _inputs(cycle)]
    for label in ("WRONG_DATE_023", "FORBIDDEN_ATTENDEE_023"):
        source = source_cases[label]
        detail = next(
            item
            for item in source["stages"][0]["inference_details"]
            if item["prompt_id"] == PROMPT_ID
        )
        input_rows.append((label, detail["prompt_input"]))
    if len(input_rows) != 10:
        raise ValueError("predeclared input count changed")
    installed = next(
        (
            model.digest
            for model in OllamaHTTPClient().list_installed_models()
            if model.model_id == MODEL_ID
        ),
        None,
    )
    if installed != cycle["binding"]["model_digest"]:
        raise ValueError("installed model differs from frozen cycle")
    root = Path(tempfile.mkdtemp(prefix="gwa-review-goal-responsibility-"))
    manifest = _bundle(root)
    runtime = _runtime(root / "runtime", manifest)
    reference = load_prompt_reference(PROMPT_ID, manifest, execution_scope=DEVELOPMENT_SMOKE)
    schema = _schema()
    product_reference = load_prompt_reference(
        PROMPT_ID, default_prompt_manifest_path(), execution_scope=DEVELOPMENT_SMOKE
    )
    if product_reference.content_hash != baseline["binding"]["prompt_hash"]:
        raise ValueError("stored baseline Prompt changed")
    baseline_rows = {trial["label"]: trial for trial in baseline["trials"] if trial["arm"] == "A"}
    result: dict[str, Any] = {
        "binding": {
            "baseline_sha": "e3e840c6",
            "cycle_sha256": hashlib.sha256(cycle_bytes).hexdigest(),
            "baseline_sha256": hashlib.sha256(baseline_bytes).hexdigest(),
            "model_digest": installed,
            "prompt_hash": reference.content_hash,
            "output_schema_version": schema.schema_version,
            "temperature": 0.0,
            "seed": 1729,
            "call_limit": 10,
            "provider_read_enabled": False,
            "provider_write_enabled": False,
        },
        "trials": [],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    for label, prompt_input in input_rows:
        input_hash = hashlib.sha256(
            json.dumps(prompt_input, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        if label in baseline_rows and baseline_rows[label]["input_sha256"] != input_hash:
            raise ValueError(f"{label} baseline input changed")
        trial: dict[str, Any] = {
            "label": label,
            "input_sha256": input_hash,
            "prompt_input": prompt_input,
        }
        started = time.perf_counter()
        base_ms = 1786060800000
        try:
            with (
                provider_dispatch_execution_scope(
                    run_id=f"review-goal-responsibility-{label}",
                    now_ms=lambda start=started, base=base_ms: base
                    + int((time.perf_counter() - start) * 1000),
                ),
                provider_dispatch_budget_scope(build_default_run_budget(started_at_ms=base_ms)),
            ):
                inference = runtime.infer("LOCAL_GPU", reference, prompt_input, schema)
            trial.update(
                outcome="COMPLETED",
                structured_output=inference.structured_output,
                flattened=_flatten(inference.structured_output),
                input_tokens=inference.input_tokens,
                output_tokens=inference.output_tokens,
                provider_latency_ms=inference.latency_ms,
                fallback_reason=inference.fallback_reason,
            )
        except Exception as error:
            code = getattr(error, "code", None)
            trial.update(
                outcome="FAILED",
                error_type=type(error).__name__,
                error_code=getattr(code, "value", None),
                message=str(error),
            )
        trial["duration_ms"] = int((time.perf_counter() - started) * 1000)
        cast(list[dict[str, Any]], result["trials"]).append(trial)
        output_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(label, trial["outcome"], flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycle", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evaluate(args.cycle, args.baseline, args.output)


if __name__ == "__main__":
    main()
