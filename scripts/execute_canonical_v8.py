"""Run Canonical v8 Cases against isolated Product processes and grade artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import statistics
import subprocess
import time
import uuid
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

from evaluation.dataset_v8 import (
    DEFAULT_DATASET_PATH,
    CanonicalCaseV8,
    load_cases,
    normalized_sha256,
)
from evaluation.grader_v8 import GradeV8, grade_case_v8
from evaluation.observation_v8 import normalize_public_observation
from evaluation.public_client_v8 import PublicProductClientV8, PublicRunObservationTimeout
from evaluation.public_runner_v8 import execute_public_case
from evaluation.semantic_judge_v8 import JUDGE_VERSION, review_semantics

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIAGNOSTIC_CASES = (
    "CASE-CORE-001",
    "CASE-CORE-033",
    "CASE-STRESS-001",
    "CASE-STRESS-013",
    "CASE-STRESS-014",
)
PROMPT_MANIFEST = ROOT / "src/google_work_agent/application/prompt_runtime/prompt_manifest.json"
PROVIDER_SNAPSHOT = (
    ROOT / "evaluation/datasets/e2e/fixtures/google_workspace/provider-snapshot-v8.json"
)
FAULT_CONFIG = ROOT / "evaluation/harness/canonical_v8_fault_profiles.json"
FAULT_ADAPTER = ROOT / "evaluation/harness/fault_adapters.py"
SIMULATED_PROVIDER = ROOT / "evaluation/harness/stateful_provider.py"
GRADER = ROOT / "evaluation/grader_v8.py"
OBSERVATION = ROOT / "evaluation/observation_v8.py"
PUBLIC_RUNNER = ROOT / "evaluation/public_runner_v8.py"
PRODUCT_LAUNCHER = ROOT / "scripts/serve_canonical_v8_product.py"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Execute Canonical v8 over public Product HTTP")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--case", action="append", dest="cases")
    parser.add_argument("--result-dir", type=Path)
    parser.add_argument("--case-timeout", type=float, default=900.0)
    parser.add_argument("--startup-timeout", type=float, default=90.0)
    arguments = parser.parse_args(argv)
    cases = load_cases()
    selected_ids = (
        list(cases) if arguments.all else arguments.cases or list(DEFAULT_DIAGNOSTIC_CASES)
    )
    unknown = [case_id for case_id in selected_ids if case_id not in cases]
    if unknown:
        raise ValueError(f"unknown Canonical Case: {unknown[0]}")
    if len(selected_ids) != len(set(selected_ids)):
        raise ValueError("each Canonical Case may be attempted once")
    if arguments.all:
        _require_frozen_worktree()
    metadata = _frozen_metadata(
        full_run=arguments.all,
        case_timeout=arguments.case_timeout,
        startup_timeout=arguments.startup_timeout,
    )
    date = datetime.now(UTC).astimezone().strftime("%Y%m%d")
    suffix = "full" if arguments.all else "diagnostic"
    result_dir = (
        arguments.result_dir
        or ROOT
        / "evaluation/results"
        / f"canonical92-{suffix}-{date}-{metadata['product_sha'][:8]}"
    ).resolve()
    if result_dir.exists() and any(result_dir.iterdir()):
        raise RuntimeError("RESULT_DIRECTORY_NOT_EMPTY")
    (result_dir / "cases").mkdir(parents=True, exist_ok=True)
    _write_json(result_dir / "experiment_manifest.json", metadata)
    environment = _evaluation_environment(metadata)
    records: list[dict[str, Any]] = []
    for index, case_id in enumerate(selected_ids, 1):
        print(f"[{index}/{len(selected_ids)}] {case_id}", flush=True)
        result = _execute_one(
            cases[case_id],
            metadata=metadata,
            result_dir=result_dir,
            environment=environment,
            case_timeout=arguments.case_timeout,
            startup_timeout=arguments.startup_timeout,
        )
        records.append(result)
        _write_json(result_dir / "cases" / f"{case_id}.json", result)
    summary = _summary(records, metadata)
    _write_json(result_dir / "summary.json", summary)
    (result_dir / "README.md").write_text(_readme(summary), encoding="utf-8", newline="\n")
    return 0 if all(item["verdict"] == "PASS" for item in records) else 2


def _execute_one(
    case: CanonicalCaseV8,
    *,
    metadata: dict[str, Any],
    result_dir: Path,
    environment: dict[str, str],
    case_timeout: float,
    startup_timeout: float,
) -> dict[str, Any]:
    case_root = ROOT / "runtime/evaluation-v8" / metadata["experiment_id"] / case.case_id
    descriptor = case_root / "launch.json"
    observation_log = case_root / "calls.jsonl"
    case_root.mkdir(parents=True, exist_ok=True)
    descriptor.unlink(missing_ok=True)
    observation_log.unlink(missing_ok=True)
    command = [
        str(ROOT / ".venv/Scripts/python.exe"),
        "-m",
        "scripts.serve_canonical_v8_product",
        "--case-id",
        case.case_id,
        "--runtime-root",
        str(case_root / "state"),
        "--launch-descriptor",
        str(descriptor),
        "--observation-log",
        str(observation_log),
        "--startup-timeout",
        str(startup_timeout),
    ]
    case_env = dict(environment)
    case_env["GWA_LANGSMITH_QUESTION_ID"] = case.case_id
    started = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env=case_env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )
    snapshot: dict[str, Any] | None = None
    run_id: str | None = None
    evaluation_mode = "UNKNOWN"
    failure_kind: str | None = None
    failure_detail: str | None = None
    try:
        launch = _wait_descriptor(descriptor, process, startup_timeout + 20)
        evaluation_mode = str(launch.get("evaluation_mode", "UNKNOWN"))
        bootstrap_url = launch.get("bootstrap_url")
        base_url = launch.get("base_url")
        if not isinstance(bootstrap_url, str) or not isinstance(base_url, str):
            raise RuntimeError("LAUNCH_DESCRIPTOR_INVALID")
        secret = parse_qs(urlparse(bootstrap_url).fragment).get("bootstrap_secret", [""])[0]
        if not secret:
            raise RuntimeError("BOOTSTRAP_SECRET_MISSING")
        client = PublicProductClientV8(base_url)
        client.bootstrap(secret)
        secret = ""
        client.select_local_model(
            model_id=metadata["model_id"],
            command_id=f"eval-model-{case.case_id}-{metadata['experiment_id']}",
        )
        google_scope = case.google_resource_scope()
        client.bind_google_resource_scope(
            calendar_ids=google_scope["calendar_ids"],
            tasklist_ids=google_scope["tasklist_ids"],
            command_id=f"eval-google-scope-{case.case_id}-{metadata['experiment_id']}",
        )
        public_result = execute_public_case(
            client,
            case.execution_input(),
            auto_approve=_requires_simulated_execution(case),
            timeout_seconds=case_timeout,
        )
        snapshot = public_result.snapshot
        run = snapshot.get("run")
        run_id = str(run.get("run_id")) if isinstance(run, dict) and run.get("run_id") else None
        latency_ms = public_result.latency_ms
    except PublicRunObservationTimeout as error:
        latency_ms = max(0, int((time.monotonic() - started) * 1_000))
        snapshot = error.snapshot
        run_id = error.run_id
        failure_detail = _safe_exception(error)
    except Exception as error:
        latency_ms = max(0, int((time.monotonic() - started) * 1_000))
        failure_kind = "INVALID_ENV" if _environment_failure(error) else "INVALID_HARNESS"
        failure_detail = _safe_exception(error)
    finally:
        _stop_process(process)
    call_records = _read_jsonl(observation_log)
    trace_id = _trace_id(run_id, metadata["langsmith_project"], case_env) if run_id else None
    if snapshot is None:
        observation = {
            "schema_version": 1,
            "case_id": case.case_id,
            "run_id": run_id,
            "latency_ms": latency_ms,
            "llm_call_count": sum(item.get("kind") == "LLM" for item in call_records),
            "connector_read_count": sum(
                item.get("kind") == "CONNECTOR_READ" for item in call_records
            ),
            "connector_write_count": sum(
                item.get("kind") == "CONNECTOR_WRITE" for item in call_records
            ),
            "connector_calls": call_records,
        }
        grade = GradeV8(
            verdict=cast_verdict(failure_kind or "INVALID_HARNESS"),
            first_divergence=failure_detail or "PUBLIC_OBSERVATION_MISSING",
            deterministic_checks={},
            semantic_review={},
        )
        judge_calls = 0
    else:
        observation = normalize_public_observation(
            case_id=case.case_id,
            snapshot=snapshot,
            call_records=call_records,
            latency_ms=latency_ms,
        )
        semantic_review: dict[str, Any] | None = None
        judge_calls = 0
        try:
            semantic_review = review_semantics(
                required_semantics=str(case.gold.get("required_semantics", "")),
                forbidden_semantics=str(case.gold.get("forbidden_semantics", "")),
                observation=observation,
            )
            judge_calls = 1
        except Exception as error:
            failure_detail = _safe_exception(error)
        grade = grade_case_v8(
            case=case.raw,
            observation=observation,
            semantic_review=semantic_review,
        )
        if failure_detail and observation.get("public_status") not in {
            "BLOCKED",
            "COMPLETED",
            "CANCELLED",
            "FAILED",
            "WAITING_CONFIRMATION",
            "WAITING_APPROVAL",
            "FAILED_RETRYABLE",
            "REAUTH_REQUIRED",
            "RECOVERY_REQUIRED",
        }:
            grade = GradeV8(
                "PRODUCT_FAIL",
                "PUBLIC_RUN_DID_NOT_REACH_OBSERVABLE_STATE",
                grade.deterministic_checks,
                grade.semantic_review,
            )
        if case.gold.get("fault_profile") and not any(
            item.get("kind") == "FAULT" for item in call_records
        ):
            target_reached = _fault_target_reached(case, call_records)
            grade = GradeV8(
                "INVALID_HARNESS" if target_reached else "PRODUCT_FAIL",
                (
                    "FAULT_ADAPTER_DID_NOT_APPLY_AT_REACHED_BOUNDARY"
                    if target_reached
                    else "PRODUCT_DID_NOT_REACH_CONFIGURED_FAULT_BOUNDARY"
                ),
                grade.deterministic_checks,
                grade.semantic_review,
            )
        if case.gold.get("fault_profile") and evaluation_mode == "COMPONENT_ONLY":
            grade = GradeV8(
                "INVALID_HARNESS",
                "COMPONENT_ONLY_NOT_PROMOTED_TO_PUBLIC_E2E",
                grade.deterministic_checks,
                grade.semantic_review,
            )
    failure = _failure_projection(grade, observation, call_records)
    return {
        "schema_version": 1,
        "case_id": case.case_id,
        "split": case.raw.get("split"),
        "evaluation_sha": metadata["product_sha"],
        "product_sha": metadata["product_sha"],
        "product_src_tree_sha": metadata["product_src_tree_sha"],
        "dataset_sha256": metadata["dataset_sha256"],
        "grader_version": metadata["grader_version"],
        "grader_sha256": metadata["grader_sha256"],
        "model_id": metadata["model_id"],
        "model_digest": metadata["model_digest"],
        "prompt_manifest_sha256": metadata["prompt_manifest_sha256"],
        "execution_mode": evaluation_mode,
        "run_id": run_id,
        "trace_id": trace_id,
        "normalized_observation": observation,
        "verdict": grade.verdict,
        "first_divergence": grade.first_divergence,
        "first_failure_owner": failure["owner"],
        "first_failure_node": failure["node"],
        "first_failure_operation": failure["operation"],
        "deterministic_checks": grade.deterministic_checks,
        "semantic_review": grade.semantic_review,
        "semantic_judge_error": failure_detail,
        "judge_calls": judge_calls,
        "rerun_to_pass": 0,
    }


def _requires_simulated_execution(case: CanonicalCaseV8) -> bool:
    profile_name = case.gold.get("fault_profile")
    if not isinstance(profile_name, str):
        return False
    document = json.loads(FAULT_CONFIG.read_text(encoding="utf-8"))
    profile = next(
        (item for item in document["profiles"] if item.get("name") == profile_name), None
    )
    if not isinstance(profile, dict) or profile.get("evaluation_mode") != "SIMULATED_PROVIDER":
        return False
    return any(
        isinstance(operation, str)
        and any(token in operation for token in ("create", "update", "send"))
        for rule in profile.get("rules", [])
        if isinstance(rule, dict)
        for operation in rule.get("operations", [])
    )


def _fault_target_reached(case: CanonicalCaseV8, call_records: list[dict[str, Any]]) -> bool:
    profile_name = case.gold.get("fault_profile")
    if not isinstance(profile_name, str):
        return False
    document = json.loads(FAULT_CONFIG.read_text(encoding="utf-8"))
    profile = next(
        (item for item in document["profiles"] if item.get("name") == profile_name), None
    )
    if not isinstance(profile, dict):
        return False
    for rule in profile.get("rules", []):
        if not isinstance(rule, dict):
            continue
        operations = {
            operation for operation in rule.get("operations", []) if isinstance(operation, str)
        }
        trigger = rule.get("trigger")
        prerequisite = trigger.get("prerequisite") if isinstance(trigger, dict) else None
        for index, record in enumerate(call_records):
            if (
                record.get("tool_id") not in operations
                and record.get("operation") not in operations
            ):
                continue
            if prerequisite is None or _fault_prerequisite_reached(
                str(prerequisite), call_records[:index]
            ):
                return True
    return False


def _fault_prerequisite_reached(prerequisite: str, call_records: list[dict[str, Any]]) -> bool:
    if prerequisite == "WRITE_RESULT_UNKNOWN":
        return any(
            record.get("kind") == "FAULT"
            and record.get("outcome") in {"LOSE_RESPONSE", "RETURN_UNKNOWN"}
            for record in call_records
        )
    if prerequisite == "TASK_UPDATE_APPLIED":
        return any(
            record.get("kind") == "CONNECTOR_WRITE"
            and record.get("tool_id") == "tasks_update_task"
            and record.get("effect_applied") is True
            for record in call_records
        )
    if prerequisite == "TASK_UPDATE_VERIFIED":
        return _fault_prerequisite_reached("TASK_UPDATE_APPLIED", call_records) and any(
            record.get("kind") == "CONNECTOR_READ"
            and record.get("tool_id") == "tasks_get_task"
            and record.get("outcome") == "SUCCESS"
            for record in call_records
        )
    if prerequisite == "CALENDAR_EVENT_VERIFIED":
        effect_applied = any(
            record.get("kind") == "CONNECTOR_WRITE"
            and record.get("tool_id") == "calendar_create_event"
            and record.get("effect_applied") is True
            for record in call_records
        )
        verification_succeeded = any(
            record.get("kind") == "CONNECTOR_READ"
            and record.get("tool_id") == "calendar_get_event"
            and record.get("outcome") == "SUCCESS"
            for record in call_records
        )
        return effect_applied and verification_succeeded
    return False


def _failure_projection(
    grade: GradeV8,
    observation: dict[str, Any],
    call_records: list[dict[str, Any]],
) -> dict[str, str | None]:
    if grade.verdict == "PASS":
        return {"owner": None, "node": None, "operation": None}
    if grade.verdict == "INVALID_ENV":
        owner, node = "EVALUATION_ENV", "isolated_product_launcher"
    elif grade.verdict in {"INVALID_HARNESS", "INVALID_EXPERIMENT"}:
        owner, node = "EVALUATION_HARNESS", "public_runner_v8"
    elif grade.verdict == "SAFETY_FAIL":
        owner, node = "PRODUCT_WRITE_SAFETY", "write_execution"
    else:
        owner = "PRODUCT"
        status = observation.get("public_status")
        node = (
            "retrieval"
            if status == "RETRIEVING"
            else "write_recovery"
            if status == "RECOVERY_REQUIRED"
            else "approval_projection"
            if status in {"WAITING_APPROVAL", "WAITING_CONFIRMATION"}
            else "terminal_projection"
        )
    last_call = next(
        (
            item
            for item in reversed(call_records)
            if item.get("kind") in {"CONNECTOR_READ", "CONNECTOR_WRITE", "LLM", "FAULT"}
        ),
        {},
    )
    operation = last_call.get("tool_id") or last_call.get("operation")
    return {
        "owner": owner,
        "node": node,
        "operation": str(operation) if isinstance(operation, str) else None,
    }


def _frozen_metadata(
    *, full_run: bool, case_timeout: float, startup_timeout: float
) -> dict[str, Any]:
    sha = _git("rev-parse", "HEAD")
    src_tree = _directory_hash(ROOT / "src/google_work_agent")
    prompt = json.loads(PROMPT_MANIFEST.read_text(encoding="utf-8"))
    model_digest = _ollama_digest("qwen3.5:9b")
    experiment_id = f"canonical92-v8-{sha[:8]}-{uuid.uuid4().hex[:10]}"
    return {
        "schema_version": 1,
        "experiment_id": experiment_id,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "run_kind": "FULL" if full_run else "DIAGNOSTIC",
        "product_sha": sha,
        "product_src_tree_sha": src_tree,
        "dataset_path": str(DEFAULT_DATASET_PATH.relative_to(ROOT)).replace("\\", "/"),
        "dataset_sha256": normalized_sha256(DEFAULT_DATASET_PATH),
        "prompt_manifest_sha256": normalized_sha256(PROMPT_MANIFEST),
        "prompt_bundle_version": prompt.get("prompt_bundle_version"),
        "graph_version": "resume-contract-v2",
        "model_id": "qwen3.5:9b",
        "model_digest": model_digest,
        "temperature": 0.0,
        "seed": 20260914,
        "context_config": "production-default",
        "case_timeout_seconds": case_timeout,
        "startup_timeout_seconds": startup_timeout,
        "provider_snapshot_sha256": normalized_sha256(PROVIDER_SNAPSHOT),
        "fault_config_sha256": normalized_sha256(FAULT_CONFIG),
        "fault_adapter_sha256": normalized_sha256(FAULT_ADAPTER),
        "simulated_provider_sha256": normalized_sha256(SIMULATED_PROVIDER),
        "public_runner_sha256": normalized_sha256(PUBLIC_RUNNER),
        "product_launcher_sha256": normalized_sha256(PRODUCT_LAUNCHER),
        "normalized_observation_sha256": normalized_sha256(OBSERVATION),
        "grader_version": "canonical-v8-grader-1",
        "grader_sha256": normalized_sha256(GRADER),
        "semantic_judge_version": JUDGE_VERSION,
        "langsmith_project": f"google-work-agent-canonical92-{sha[:8]}",
        "rerun_to_pass": 0,
    }


def _evaluation_environment(metadata: dict[str, Any]) -> dict[str, str]:
    result = dict(os.environ)
    for key, value in _read_dotenv(ROOT / ".env.local").items():
        result.setdefault(key, value)
    if not result.get("LANGSMITH_API_KEY", "").strip():
        raise RuntimeError("LANGSMITH_API_KEY_MISSING")
    result.update(
        {
            "GWA_LANGSMITH_ENABLED": "1",
            "LANGSMITH_PROJECT": metadata["langsmith_project"],
            "GWA_LANGSMITH_CODE_SHA": metadata["product_sha"],
            "GWA_LANGSMITH_EXPERIMENT_ID": metadata["experiment_id"],
            "GWA_LANGSMITH_MODEL_DIGEST": metadata["model_digest"],
            "GWA_LANGSMITH_MODEL_ID": metadata["model_id"],
            "GWA_LANGSMITH_PROMPT_CONTENT_HASH": metadata["prompt_manifest_sha256"],
            "GWA_LANGSMITH_PROMPT_ID": "canonical-v8-production-bundle",
            "GWA_LANGSMITH_PROMPT_VERSION": str(metadata["prompt_bundle_version"]),
            "GWA_DEVELOPMENT_LLM_TEMPERATURE": "0",
            "GWA_DEVELOPMENT_LLM_SEED": "20260914",
        }
    )
    return result


def _trace_id(run_id: str, project: str, environment: dict[str, str]) -> str | None:
    try:
        from langsmith import Client

        client = Client(api_key=environment["LANGSMITH_API_KEY"])
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            runs = client.list_runs(
                project_name=project,
                is_root=True,
                start_time=datetime.now(UTC) - timedelta(minutes=30),
                limit=100,
            )
            for run in runs:
                metadata = (run.extra or {}).get("metadata", {})
                if isinstance(metadata, dict) and metadata.get("domain_run_id") == run_id:
                    return str(run.trace_id or run.id)
            time.sleep(1)
    except Exception:
        return None
    return None


def _stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        process.communicate(timeout=5)
        return
    try:
        if os.name == "nt":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            process.send_signal(signal.SIGINT)
        process.wait(timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
    process.communicate(timeout=5)


def _wait_descriptor(
    path: Path, process: subprocess.Popen[str], timeout_seconds: float
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if path.is_file():
            value = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                return value
        if process.poll() is not None:
            stdout, stderr = process.communicate(timeout=5)
            detail = (stderr or stdout)[-1000:].replace("\n", " ")
            raise RuntimeError(f"ISOLATED_PRODUCT_EXITED:{detail}")
        time.sleep(0.1)
    raise RuntimeError("ISOLATED_PRODUCT_STARTUP_TIMEOUT")


def _summary(records: list[dict[str, Any]], metadata: dict[str, Any]) -> dict[str, Any]:
    verdicts = Counter(str(item["verdict"]) for item in records)
    splits = Counter(str(item["split"]) for item in records)
    failure_owners = Counter(
        str(item["first_failure_owner"]) for item in records if item.get("first_failure_owner")
    )
    failure_nodes = Counter(
        str(item["first_failure_node"]) for item in records if item.get("first_failure_node")
    )
    failure_operations = Counter(
        str(item["first_failure_operation"])
        for item in records
        if item.get("first_failure_operation")
    )
    valid = [item for item in records if not str(item["verdict"]).startswith("INVALID_")]
    latencies = [int(item["normalized_observation"].get("latency_ms", 0)) for item in records]
    return {
        "schema_version": 1,
        "experiment_id": metadata["experiment_id"],
        "total": len(records),
        "splits": dict(sorted(splits.items())),
        "verdicts": dict(sorted(verdicts.items())),
        "failure_owners": dict(sorted(failure_owners.items())),
        "failure_nodes": dict(sorted(failure_nodes.items())),
        "failure_operations": dict(sorted(failure_operations.items())),
        "product_denominator": len(valid),
        "product_pass": sum(item["verdict"] == "PASS" for item in valid),
        "llm_calls": sum(
            int(item["normalized_observation"].get("llm_call_count", 0)) for item in records
        ),
        "judge_calls": sum(int(item.get("judge_calls", 0)) for item in records),
        "connector_reads": sum(
            int(item["normalized_observation"].get("connector_read_count", 0)) for item in records
        ),
        "connector_writes": sum(
            int(item["normalized_observation"].get("connector_write_count", 0)) for item in records
        ),
        "provider_effects": sum(
            bool(call.get("effect_applied"))
            for item in records
            for call in item["normalized_observation"].get("connector_calls", [])
            if isinstance(call, dict) and call.get("kind") == "CONNECTOR_WRITE"
        ),
        "rerun_to_pass": 0,
        "latency_mean_ms": round(statistics.mean(latencies), 1) if latencies else None,
        "latency_median_ms": round(statistics.median(latencies), 1) if latencies else None,
        "latency_p95_ms": _percentile(latencies, 0.95),
        "product_sha": metadata["product_sha"],
        "product_src_tree_sha": metadata["product_src_tree_sha"],
    }


def _readme(summary: dict[str, Any]) -> str:
    verdict_rows = "\n".join(f"| {name} | {count} |" for name, count in summary["verdicts"].items())
    owner_rows = "\n".join(
        f"| {name} | {count} |" for name, count in summary["failure_owners"].items()
    )
    return f"""# Canonical v8 평가 결과

| 항목 | 결과 |
|---|---:|
| 전체 Case | {summary["total"]} |
| Product 분모 | {summary["product_denominator"]} |
| PASS | {summary["product_pass"]} |
| Product LLM 호출 | {summary["llm_calls"]} |
| Semantic Judge 호출 | {summary["judge_calls"]} |
| Connector READ | {summary["connector_reads"]} |
| Connector WRITE | {summary["connector_writes"]} |
| Simulated Provider effect | {summary["provider_effects"]} |
| rerun-to-pass | {summary["rerun_to_pass"]} |

## 판정

| Verdict | Count |
|---|---:|
{verdict_rows}

## 최초 실패 Owner

| Owner | Count |
|---|---:|
{owner_rows or "| 없음 | 0 |"}

세부 결과는 `cases/CASE-*.json`, 고정 입력은 `experiment_manifest.json`,
집계는 `summary.json`에 있다.
"""


def _read_dotenv(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not path.is_file():
        return result
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip().strip("\"'")
    return result


def _ollama_digest(model: str) -> str:
    with urlopen("http://127.0.0.1:11434/api/tags", timeout=10) as response:
        value = json.loads(response.read().decode("utf-8"))
    for item in value.get("models", []):
        if item.get("model") == model and isinstance(item.get("digest"), str):
            return str(item["digest"])
    raise RuntimeError("REQUIRED_MODEL_NOT_INSTALLED")


def _require_frozen_worktree() -> None:
    if _git("status", "--porcelain", "--untracked-files=all"):
        raise RuntimeError("FULL_EVALUATION_REQUIRES_CLEAN_WORKTREE")
    upstream = _git("rev-parse", "@{u}")
    if upstream != _git("rev-parse", "HEAD"):
        raise RuntimeError("FULL_EVALUATION_REQUIRES_PUSHED_HEAD")


def _git(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


def _directory_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [
        value
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and isinstance((value := json.loads(line)), dict)
    ]


def _environment_failure(error: BaseException) -> bool:
    text = str(error)
    return any(
        token in text
        for token in (
            "REAUTH",
            "AUTH_REQUIRED",
            "LOCAL_UNAVAILABLE",
            "REQUIRED_MODEL",
            "LANGSMITH",
            "STARTUP_TIMEOUT",
        )
    )


def _safe_exception(error: BaseException) -> str:
    text = str(error).replace("\r", " ").replace("\n", " ")[:500]
    return f"{type(error).__name__}:{text}"


def cast_verdict(value: str) -> Any:
    allowed = {
        "PASS",
        "PRODUCT_FAIL",
        "SAFETY_FAIL",
        "INVALID_ENV",
        "INVALID_HARNESS",
        "INVALID_EXPERIMENT",
    }
    return value if value in allowed else "INVALID_HARNESS"


def _percentile(values: list[int], fraction: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, int(len(ordered) * fraction + 0.999) - 1))]


if __name__ == "__main__":
    raise SystemExit(main())
