"""One preregistered actual Main Graph trial against local Provider snapshots.

Outputs are local-only observations, not automatic semantic PASS judgements.
Run with ``python -m scripts.evaluate_production_snapshot_workflow --plan ... --output ...``.
The parent enforces the wall bound outside the unchanged Product process budget.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing
import platform
import subprocess
import sys
import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Final
from unittest.mock import patch
from uuid import UUID, uuid4

from scripts.production_snapshot_runtime import (
    DATASET,
    PROJECT_ROOT,
    load_case,
    snapshot_production_runtime,
)
from scripts.ru_observation import metrics, object_hash
from scripts.serve_canonical_v8_product import PROVIDER_SNAPSHOT

from google_work_agent.adapters.llm.ollama import transport as ollama_transport
from google_work_agent.adapters.llm.ollama.transport import OllamaHTTPClient
from google_work_agent.api import composition
from google_work_agent.application.prompt_runtime.prompt_registry import (
    default_prompt_manifest_path,
)
from google_work_agent.application.use_cases.conversation.create_conversation import (
    CreateConversationCommand,
)
from google_work_agent.application.use_cases.resource.issue_selection_handle import (
    IssueSelectionHandleCommand,
)
from google_work_agent.application.use_cases.resource.resolve_selection_handle import (
    ResolveSelectionHandleQuery,
)
from google_work_agent.application.use_cases.run.get_run_snapshot import GetRunSnapshotQuery
from google_work_agent.application.use_cases.run.schedule_run_execution import (
    ScheduleRunExecutionCommand,
)
from google_work_agent.application.use_cases.run.start_run import StartRunCommand
from google_work_agent.ports.llm.structured_inference_contracts import (
    LLMErrorCode,
    LLMInvocationError,
)
from google_work_agent.ports.system.settings_port import SettingsPatchV1

RESULTS_ROOT = PROJECT_ROOT / "evaluation/results"
CASE_ID = "CASE-CORE-005"
MODEL_ID: Final = "qwen3.5:9b"
SEED = 20260923
CALL_CAP = 20
WALL_SECONDS = 600
STOP_STATUSES = frozenset(
    {
        "COMPLETED",
        "FAILED",
        "BLOCKED",
        "CANCELLED",
        "WAITING_CONFIRMATION",
        "WAITING_APPROVAL",
        "REAUTH_REQUIRED",
        "RECOVERY_REQUIRED",
    }
)


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _head() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, text=True
    ).strip()


def _tree_hash(path: Path) -> str:
    files = sorted(
        p
        for p in path.rglob("*")
        if p.is_file()
        and p.suffix in {".py", ".json", ".md", ".sql"}
        and "__pycache__" not in p.parts
    )
    return object_hash({str(p.relative_to(PROJECT_ROOT).as_posix()): file_hash(p) for p in files})


def build_plan(model_digest: str, *, trial_id: str | None = None) -> dict[str, Any]:
    """Read-only preregistration helper: no catalog, Provider, or model call."""
    normalized_digest = model_digest.removeprefix("sha256:")
    if len(normalized_digest) != 64 or any(c not in "0123456789abcdef" for c in normalized_digest):
        raise ValueError("actual model SHA-256 digest required")
    identifier = str(UUID(trial_id)) if trial_id is not None else str(uuid4())
    manifest = default_prompt_manifest_path()
    dependencies = (
        Path(__file__),
        PROJECT_ROOT / "scripts/production_snapshot_runtime.py",
        PROJECT_ROOT / "scripts/ru_observation.py",
        PROJECT_ROOT / "scripts/serve_canonical_v8_product.py",
        PROJECT_ROOT / "evaluation/harness/stateful_provider.py",
        PROJECT_ROOT / "evaluation/harness/gmail_query.py",
        manifest,
        manifest.parent / "prompt_runtime_input_contract_v1.json",
    )
    return {
        "schema_version": 1,
        "kind": "PRODUCTION_SNAPSHOT_SINGLE_TRIAL",
        "trial_id": identifier,
        "case_id": CASE_ID,
        "trials": 1,
        "head_sha": _head(),
        "dataset_sha256": file_hash(DATASET),
        "case_sha256": object_hash(load_case(CASE_ID)),
        "snapshot_sha256": file_hash(PROVIDER_SNAPSHOT),
        "product_tree_sha256": _tree_hash(PROJECT_ROOT / "src"),
        "prompt_tree_sha256": _tree_hash(manifest.parent),
        "tool_registry_sha256": composition.load_development_tool_registry().entries_hash,
        "dependency_sha256": {
            p.resolve().relative_to(PROJECT_ROOT).as_posix(): file_hash(p) for p in dependencies
        },
        "python": {
            "version": platform.python_version(),
            "executable_sha256": file_hash(Path(sys.executable)),
        },
        "model": {"id": MODEL_ID, "digest": model_digest},
        "runtime": {
            "requested_mode": "LOCAL_GPU",
            "seed": SEED,
            "temperature_override": None,
            "reference_time": None,
            "fault_profile": None,
        },
        "bounds": {
            "actual_llm_calls": CALL_CAP,
            "provider_dispatch_attempts": CALL_CAP,
            "wall_seconds": WALL_SECONDS,
        },
        "approval_resumes": 0,
        "provider_writes": 0,
    }


def validate_plan(plan: Mapping[str, Any]) -> None:
    expected = build_plan(plan["model"]["digest"], trial_id=plan["trial_id"])
    if dict(plan) != expected:
        differing = sorted(
            key for key in set(plan) | set(expected) if plan.get(key) != expected.get(key)
        )
        raise ValueError(f"preregistered binding mismatch: {','.join(differing)}")


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    raise TypeError(f"unsupported observation type:{type(value).__name__}")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=_jsonable), encoding="utf-8"
    )
    temporary.replace(path)


class TrialObservation:
    def __init__(self, output: Path) -> None:
        self.output = output
        self.started = time.monotonic()
        self.lock = threading.RLock()
        self.local = threading.local()
        self.calls: list[dict[str, Any]] = []
        self.bound_reason: str | None = None

    def _save(self) -> None:
        write_json(
            self.output / "calls.json",
            {
                "calls": self.calls,
                "metrics": self.metrics(),
                "bound_reason": self.bound_reason,
            },
        )

    def metrics(self) -> dict[str, Any]:
        dispatched = [call for call in self.calls if call.get("wire_request_count", 0)]
        return {
            **metrics(dispatched),
            "provider_dispatch_attempts": len(self.calls),
            "actual_wire_calls": sum(call.get("wire_request_count", 0) for call in self.calls),
        }

    def invoke(self, delegate: Any, operation: str, kwargs: dict[str, Any]) -> Any:
        with self.lock:
            if self.bound_reason is None:
                if time.monotonic() - self.started >= WALL_SECONDS:
                    self.bound_reason = "WALL_TIMEOUT"
                elif len(self.calls) >= CALL_CAP:
                    self.bound_reason = "PROVIDER_DISPATCH_ATTEMPT_CAP"
            if self.bound_reason is not None:
                self._save()
                raise LLMInvocationError(
                    LLMErrorCode.LLM_CALL_BUDGET_EXHAUSTED,
                    f"EXPERIMENT_BOUND_REACHED:{self.bound_reason}",
                )
            if delegate.provider_name != "ollama" or str(delegate.runtime) != "LOCAL_GPU":
                raise RuntimeError("non-local model dispatch forbidden")
            if delegate.model_id != MODEL_ID:
                raise RuntimeError("registered model differs from runtime selection")
            policy = kwargs["runtime_policy"]
            if policy.sampling_seed != SEED:
                raise RuntimeError("registered seed differs from actual runtime policy")
            ref = kwargs["prompt_ref"]
            event: dict[str, Any] = {
                "call_index": len(self.calls) + 1,
                "operation": operation,
                "prompt_id": ref.prompt_id,
                "prompt_ref": asdict(ref),
                "input": deepcopy(kwargs["prompt_input"]),
                "input_sha256": object_hash(kwargs["prompt_input"]),
                "runtime_policy": asdict(policy),
                "temperature": policy.sampling_temperature,
                "seed": policy.sampling_seed,
                "model": delegate.model_id,
                "state": "DISPATCH_STARTED",
                "wire_request_count": 0,
            }
            if "output_schema" in kwargs:
                event["output_schema"] = deepcopy(dict(kwargs["output_schema"].json_schema))
            if "tools" in kwargs:
                event["tools"] = [asdict(tool) for tool in kwargs["tools"]]
            self.calls.append(event)
            self.local.event = event
            self._save()
        started = time.monotonic()
        try:
            result = getattr(delegate, operation)(**kwargs)
            with self.lock:
                event.update(
                    state="RETURNED",
                    content=deepcopy(getattr(result, "content", None)),
                    result=_jsonable(result),
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    latency_ms=result.latency_ms,
                )
            return result
        except Exception as error:
            with self.lock:
                event.update(state="ERROR", error_type=type(error).__name__, error=str(error)[:500])
            raise
        finally:
            with self.lock:
                event["wall_latency_ms"] = int((time.monotonic() - started) * 1000)
                self._save()
            self.local.event = None

    def decorate(self, delegate: Any) -> Any:
        owner = self

        class ObservedProvider:
            provider_name = delegate.provider_name
            runtime = delegate.runtime

            def invoke_structured(self, **kwargs: Any) -> Any:
                return owner.invoke(delegate, "invoke_structured", kwargs)

            def invoke_tool_call(self, **kwargs: Any) -> Any:
                return owner.invoke(delegate, "invoke_tool_call", kwargs)

        return ObservedProvider()

    @contextmanager
    def wire_observer(self) -> Iterator[None]:
        original = ollama_transport._post_json

        def dispatch(**kwargs: Any) -> Any:
            event = getattr(self.local, "event", None)
            if event is not None:
                payload = kwargs["payload"]
                with self.lock:
                    if sum(call["wire_request_count"] for call in self.calls) >= CALL_CAP:
                        self.bound_reason = "ACTUAL_WIRE_CALL_CAP"
                        self._save()
                        raise LLMInvocationError(
                            LLMErrorCode.LLM_CALL_BUDGET_EXHAUSTED,
                            "EXPERIMENT_BOUND_REACHED:ACTUAL_WIRE_CALL_CAP",
                        )
                    event["wire_request_count"] += 1
                    event.update(
                        wire_path=kwargs["path"],
                        wire_options=deepcopy(payload.get("options")),
                        wire_think=payload.get("think"),
                        wire_sha256=object_hash(payload),
                    )
                    self._save()
            return original(**kwargs)

        with patch.object(ollama_transport, "_post_json", dispatch):
            yield


@contextmanager
def drain_before_guard_release(container: Any) -> Iterator[None]:
    """Keep process-global isolation until the actual Product worker is idle.

    Only the external parent deadline may end this wait; it terminates the
    entire isolated child. Product's bounded shutdown alone is insufficient.
    """
    executor = container.schedule_run_execution._workflow_execution
    try:
        yield
    finally:
        executor.begin_shutdown()
        while not executor.await_drained(100):
            pass


def start_case(container: Any, boundary: Any, case: Mapping[str, Any]) -> Any:
    conversation_id, session_digest = str(uuid4()), hashlib.sha256(uuid4().bytes).hexdigest()
    container.create_conversation_handler(
        CreateConversationCommand(
            str(uuid4()),
            object_hash({"conversation_id": conversation_id}),
            conversation_id,
            boundary.account_id,
            "Canonical snapshot evaluation",
            "1",
        )
    )
    selections = []
    for selected in case["selected_resource_bindings"]:
        handle = container.issue_selection_handle(
            IssueSelectionHandleCommand(
                session_digest,
                boundary.account_id,
                "google_workspace",
                selected["resource_type"],
                selected["resource_id"],
                selected["parent_id"],
                None,
            )
        )
        selections.append(
            container.resolve_selection_handle(
                ResolveSelectionHandleQuery(
                    handle,
                    session_digest,
                    boundary.account_id,
                    expected_connector_id="google_workspace",
                    expected_resource_type=selected["resource_type"],
                    expected_resource_id=selected["resource_id"],
                    expected_parent_resource_id=selected["parent_id"],
                    require_parent_match=True,
                )
            )
        )
    command_id = str(uuid4())
    result = container.start_run_handler(
        StartRunCommand(
            command_id,
            object_hash({"command_id": command_id, "request": case["canonical_user_prompt"]}),
            conversation_id,
            case["canonical_user_prompt"],
            case["entry_mode"],
            "LOCAL_GPU",
            "1",
            tuple(selections),
        )
    )
    if not result.applied:
        raise RuntimeError(f"StartRun rejected:{result.result_code}")
    accepted = container.schedule_run_execution(ScheduleRunExecutionCommand(result.handoff_id))
    if not accepted.accepted:
        raise RuntimeError("durable workflow admission rejected")
    return result


def run_trial(plan: dict[str, Any], output: Path) -> None:
    """Child entry; callers must validate/claim the preregistered trial first."""
    observation = TrialObservation(output)
    report: dict[str, Any] = {
        "schema_version": 1,
        "plan": plan,
        "execution_mode": "PRODUCTION_GRAPH_SNAPSHOT_PROVIDER",
        "semantic_verdict": "UNREVIEWED",
        "state": "STARTING",
        "run_id": None,
        "rerun_to_pass": 0,
        "provider_write_count": None,
        "approval_resume_count": 0,
    }
    try:
        validate_plan(plan)
        with (
            observation.wire_observer(),
            snapshot_production_runtime(
                output / "runtime",
                case_id=CASE_ID,
                allow_loopback_model=True,
                sampling_seed=SEED,
                llm_provider_decorator=observation.decorate,
            ) as (container, boundary),
            drain_before_guard_release(container),
        ):
            models = OllamaHTTPClient().list_installed_models()
            observed = [model for model in models if model.model_id == MODEL_ID]
            if len(observed) != 1 or observed[0].digest != plan["model"]["digest"]:
                raise RuntimeError("installed model digest differs from preregistration")
            report["settings_before"] = asdict(container.settings_port.get_settings())
            settings = container.settings_port.update_settings(
                SettingsPatchV1(
                    1,
                    preferred_local_model_id=MODEL_ID,
                    preferred_llm_mode="LOCAL_GPU",
                ),
                operation_ref=plan["trial_id"],
            )
            report["settings"] = asdict(settings)
            result = start_case(container, boundary, load_case(CASE_ID))
            report.update(run_id=result.run_id, start_result=asdict(result), state="RUNNING")
            write_json(output / "raw.json", report)
            while True:
                snapshot = container.get_run_snapshot_handler(GetRunSnapshotQuery(result.run_id))
                if snapshot is not None:
                    report["snapshot"] = asdict(snapshot)
                    report["answer_messages"] = [
                        asdict(message)
                        for message in snapshot.messages
                        if message.role == "ASSISTANT" and message.run_id == result.run_id
                    ]
                report.update(
                    read_results=deepcopy(boundary.read_results),
                    boundary_events=deepcopy(boundary.events),
                    metrics=observation.metrics(),
                    provider_write_count=len(boundary.provider.write_calls),
                    provider_write_attempts=sum(
                        event.get("boundary") == "provider_write_dispatch"
                        for event in boundary.events
                    ),
                )
                write_json(output / "raw.json", report)
                if observation.bound_reason is not None:
                    report.update(
                        state="EXPERIMENT_BOUND_REACHED", bound_reason=observation.bound_reason
                    )
                    break
                if time.monotonic() - observation.started >= WALL_SECONDS:
                    observation.bound_reason = "WALL_TIMEOUT"
                    report.update(state="EXPERIMENT_BOUND_REACHED", bound_reason="WALL_TIMEOUT")
                    break
                if snapshot is not None and snapshot.status in STOP_STATUSES:
                    report["state"] = (
                        "COMPLETED_OBSERVATION"
                        if snapshot.status == "COMPLETED"
                        else "PRODUCT_STOP"
                    )
                    break
                time.sleep(0.1)
            with container.read_unit_of_work_factory() as uow:
                report["evidence"] = [
                    asdict(item) for item in uow.evidence.list_for_run(result.run_id)
                ]
                run = uow.runs.get(result.run_id)
                report["persisted_run"] = None if run is None else asdict(run)
            report.update(
                read_results=deepcopy(boundary.read_results),
                boundary_events=deepcopy(boundary.events),
            )
            write_json(output / "raw.json", report)
    except Exception as error:
        report.update(
            state_before_harness_error=report["state"],
            state="EXPERIMENT_BOUND_REACHED" if observation.bound_reason else "HARNESS_ERROR",
            bound_reason=observation.bound_reason,
            error_type=type(error).__name__,
            error=str(error)[:1000],
        )
    finally:
        report.update(
            metrics=observation.metrics(),
            wall_latency_ms=int((time.monotonic() - observation.started) * 1000),
        )
        write_json(output / "raw.json", report)


def execute_plan(plan_path: Path, output: Path) -> int:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    validate_plan(plan)
    output = output.resolve()
    if not output.is_relative_to(RESULTS_ROOT.resolve()) or output == RESULTS_ROOT.resolve():
        raise ValueError("local results directory required")
    if output.exists() and any(output.iterdir()):
        raise ValueError("result directory must be empty")
    claims = RESULTS_ROOT / ".snapshot-trials"
    claims.mkdir(parents=True, exist_ok=True)
    with (claims / f"{plan['trial_id']}.json").open("x", encoding="utf-8") as stream:
        json.dump({"plan_sha256": object_hash(plan), "output": str(output)}, stream)
    write_json(output / "plan.json", plan)
    context = multiprocessing.get_context("spawn")
    process = context.Process(target=run_trial, args=(plan, output))
    process.start()
    process.join(WALL_SECONDS)
    if process.is_alive():
        process.terminate()
        process.join(10)
        raw_path = output / "raw.json"
        report = (
            json.loads(raw_path.read_text(encoding="utf-8"))
            if raw_path.exists()
            else {"plan": plan}
        )
        report.update(
            state_before_external_timeout=report.get("state"),
            state="EXPERIMENT_BOUND_REACHED",
            bound_reason="EXTERNAL_WALL_TIMEOUT",
            semantic_verdict="UNREVIEWED",
        )
        write_json(raw_path, report)
    elif not (output / "raw.json").exists():
        write_json(
            output / "raw.json",
            {"plan": plan, "state": "HARNESS_ERROR", "exit_code": process.exitcode},
        )
    ending = {"head_sha": _head(), "product_tree_sha256": _tree_hash(PROJECT_ROOT / "src")}
    write_json(
        output / "end_binding.json",
        {**ending, "unchanged": all(plan[key] == value for key, value in ending.items())},
    )
    return 0 if process.exitcode == 0 else 2


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(execute_plan(args.plan, args.output))


if __name__ == "__main__":
    main()
