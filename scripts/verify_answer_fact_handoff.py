"""Replay sealed 081 selections through compiled Product Planning, without inference.

Historical artifacts are copied into a fresh in-memory component Run. This is
not a resume of the original Run, a new model trial, or Product activation.
The actual Planning graph, projections, snapshot store and compose validator
are used; the injected semantic callable returns a materialized saved selection.
The existing Answer artifact owner and terminal-intent builder are also called.
Supervisor merge, Main/DB terminal commit and delivery remain outside scope.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from scripts.answer_fact_selection_candidate import materialize_fact_selection
from scripts.evaluate_effect_prohibition_sampler import head, write_json
from scripts.evaluate_output_format_ablation import file_hash
from scripts.ru_observation import object_hash

from google_work_agent.adapters.langgraph.main.nodes.response_synthesis_node import (
    build_terminal_commit_intent,
    validate_terminal_commit_intent,
)
from google_work_agent.adapters.langgraph.subgraphs.planning.graph import (
    PlanningRuntimeDependencies,
    PlanningSubgraph,
)
from google_work_agent.adapters.system.memory.retrieval_evidence_store import (
    EvidenceResolutionError,
    RunScopedEvidenceStore,
)
from google_work_agent.adapters.system.sqlite_checkpoint import _CHECKPOINT_VALUE_TYPES
from google_work_agent.application.use_cases.run.build_terminal_message import (
    BuildTerminalMessageHandler,
)

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "evaluation/results"
HISTORY = RESULTS / "081-answer-fact-selection-t1/raw.json"
HISTORY_HASH = "3e3c20e0f8ee4167adaecce95bd1567f21f9cf07b4a94662006fc2759dead390"
DATABASE = RESULTS / "067-query-ref-postfix-connected-t1/runtime/data/google_work_agent.db"
DATABASE_HASH = "5838f3d98b1caedc78a44d195d4cca7fcde693fc483aacf5432955c9a8987f70"
CHECKPOINT_NS = "planning:75e22c70-973f-d965-df2c-8038f025dc72"
CHECKPOINT_ID = "1f1bb599-42f5-6850-8000-d6b5ac6f3e5e"
CHECKPOINT_HASH = "f86e3ad415149615f8f0a79ef1efd172df1dc8db2ee7abf6dece2d08687a0d44"
CRITERIA = "evaluation/experiments/082-answer-fact-handoff-criteria.md"


class _ObservedStore(RunScopedEvidenceStore):
    def __init__(self) -> None:
        super().__init__()
        self.observations: list[dict[str, Any]] = []
        self.resolved: dict[tuple[str, str, str | None], dict[str, object]] = {}

    def resolve_resource_snapshot(
        self, *, run_id: str, resource_handle: str, source_version_ref: str | None = None
    ) -> dict[str, object]:
        row: dict[str, Any] = {
            "run_id": run_id,
            "resource_handle": resource_handle,
            "source_version_ref": source_version_ref,
        }
        self.observations.append(row)
        try:
            value = super().resolve_resource_snapshot(
                run_id=run_id,
                resource_handle=resource_handle,
                source_version_ref=source_version_ref,
            )
        except EvidenceResolutionError:
            row["resolution"] = "DENIED"
            raise
        row.update(resolution="RESOLVED", snapshot_sha256=object_hash(value))
        self.resolved[run_id, resource_handle, source_version_ref] = value
        return value


def load_checkpoint() -> dict[str, Any]:
    """Read one frozen pre-Planning checkpoint, never latest or a writable resume."""
    if file_hash(DATABASE) != DATABASE_HASH:
        raise ValueError("historical database changed")
    connection = sqlite3.connect(DATABASE.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        connection.execute("PRAGMA query_only=ON")
        rows = connection.execute(
            "SELECT type, checkpoint, metadata FROM checkpoints "
            "WHERE checkpoint_ns=? AND checkpoint_id=?",
            (CHECKPOINT_NS, CHECKPOINT_ID),
        ).fetchall()
    finally:
        connection.close()
    if len(rows) != 1 or hashlib.sha256(rows[0][1]).hexdigest() != CHECKPOINT_HASH:
        raise ValueError("exact historical Planning checkpoint required")
    serde = JsonPlusSerializer(
        allowed_json_modules=_CHECKPOINT_VALUE_TYPES,
        allowed_msgpack_modules=_CHECKPOINT_VALUE_TYPES,
        pickle_fallback=False,
    )
    state = serde.loads_typed((rows[0][0], rows[0][1]))["channel_values"]
    metadata = json.loads(rows[0][2])
    if state["run_id"] != metadata["product_run_id"]:
        raise ValueError("historical checkpoint Run differs")
    return {
        "request_intent": state["request_intent"],
        "tool_route_plan": state["tool_route_plan"],
        "retrieval_result": state["retrieval_result"],
        "work_analysis_result": state["work_analysis_result"],
    }


def replay_case(
    projection: dict[str, Any],
    selection: dict[str, Any],
    snapshots: dict[str, Any],
    *,
    component_state: dict[str, Any] | None = None,
    component_run_id: str = "082-component-run",
    stored_run_id: str | None = None,
) -> dict[str, Any]:
    """Use Product graph/store/validator; never synthesize a semantic response."""
    original_hash = object_hash([projection, selection, snapshots, component_state])
    store = _ObservedStore()
    for evidence in projection["evidence"]:
        ref = evidence.get("evidence_ref") or evidence.get("evidence_id") or evidence.get("id")
        if ref in snapshots:
            store.put_resource_snapshot(
                run_id=stored_run_id or component_run_id,
                resource_handle=evidence["resource_handle"],
                source_version_ref=evidence["locator"]["source_version_ref"],
                snapshot=snapshots[ref],
            )
    state = (
        deepcopy(component_state)
        if component_state is not None
        else {
            "request_intent": deepcopy(projection["request_intent"]),
            "tool_route_plan": {"output_plan": {"output_mode": "ANSWER"}},
            "retrieval_result": {
                key: deepcopy(value)
                for key, value in projection.items()
                if key not in {"user_request", "request_intent", "answer_outline", "evidence"}
            },
        }
    )
    state.update(
        run_id=component_run_id,
        user_request=projection["user_request"],
        evidence=deepcopy(projection["evidence"]),
    )
    observed: list[dict[str, Any]] = []

    def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        current = deepcopy(dict(prompt_input))
        observed.append({"prompt_id": prompt_id, "input_sha256": object_hash(current)})
        if prompt_id != "planning.compose_answer" or len(observed) != 1:
            raise ValueError("unexpected semantic boundary; no additional dispatch permitted")
        if current != projection:
            keys = sorted(
                key
                for key in current.keys() | projection.keys()
                if current.get(key) != projection.get(key)
            )
            raise ValueError("compiled compose input differs: " + ", ".join(keys))
        resolved = {}
        for evidence in cast(list[dict[str, Any]], current["evidence"]):
            ref = evidence.get("evidence_ref") or evidence.get("evidence_id") or evidence.get("id")
            key = (
                component_run_id,
                evidence["resource_handle"],
                evidence.get("locator", {}).get("source_version_ref"),
            )
            if key in store.resolved:
                resolved[ref] = store.resolved[key]
        draft = materialize_fact_selection(
            selection, prompt_input=current, source_snapshots=resolved
        )
        if draft is None:
            raise ValueError("saved selection produced no answer; no empty-result inference")
        observed[0]["materialized_draft"] = deepcopy(draft)
        return cast(Mapping[str, object], draft)

    result: dict[str, Any] = {
        "model_calls": 0,
        "provider_calls": 0,
        "semantic_verdict": "NOT_EVALUATED",
        "component_run_id": component_run_id,
        "terminal_composer_calls": 0,
    }

    def reject_terminal_composer(command: object) -> Any:
        result["terminal_composer_calls"] += 1
        raise ValueError("ANSWER_DRAFT must not call terminal prose generation")

    try:
        planning = PlanningSubgraph(
            dependencies=PlanningRuntimeDependencies(invoke=invoke),
            evidence_store=store,
            id_factory=lambda: component_run_id + ":answer",
        )
        graph = planning.build()
        output = graph.invoke(state)
        if len(observed) != 1 or output.get("planning_disposition") != "ANSWER":
            raise ValueError("saved compose selection was not consumed by the ANSWER path")
        answer = planning._materialize_answer(cast(Any, state), output["final_result"])
        terminal = validate_terminal_commit_intent(
            build_terminal_commit_intent(
                {
                    "run_id": component_run_id,
                    "planning_result": answer,
                    "retrieval_result": state.get("retrieval_result"),
                    "run_input": {"user_request": projection["user_request"]},
                },
                facts={
                    "version": 0,
                    "status": "PLANNING",
                    "action_statuses": [],
                    "action_effect_types": [],
                },
                build_terminal_message=BuildTerminalMessageHandler(),
                compose_terminal_response=cast(Any, reject_terminal_composer),
            )
        )
        if (
            terminal["kind"] != "COMPLETE_ANSWER_ONLY"
            or terminal["terminal_message"].content != output["final_result"]["answer"]
        ):
            raise ValueError("terminal ANSWER_DRAFT changed the compiled answer")
        result.update(
            component_verdict="PASS",
            final_result=output["final_result"],
            planning_disposition=output["planning_disposition"],
            materialized_answer=answer,
            terminal_intent={**terminal, "terminal_message": asdict(terminal["terminal_message"])},
        )
    except Exception as error:
        result.update(component_verdict="FAIL", error_type=type(error).__name__, error=str(error))
    result.update(
        semantic_adapter_calls=observed,
        snapshot_resolutions=store.observations,
        inputs_unchanged=original_hash
        == object_hash([projection, selection, snapshots, component_state]),
    )
    if not result["inputs_unchanged"]:
        result["component_verdict"] = "FAIL"
    return result


def run_gate(output: Path) -> dict[str, Any]:
    output = output.resolve()
    if not output.is_relative_to(RESULTS.resolve()) or output == RESULTS.resolve():
        raise ValueError("dedicated evaluation/results directory required")
    if file_hash(HISTORY) != HISTORY_HASH:
        raise ValueError("081 history changed")
    history = json.loads(HISTORY.read_text(encoding="utf-8"))
    if not history["completed"] or not history["binding_unchanged"] or len(history["calls"]) != 4:
        raise ValueError("complete bound four-call history required")
    product = {
        path: digest
        for path, digest in history["binding"]["source_hashes"].items()
        if path.startswith("src/") or path == "scripts/answer_fact_selection_candidate.py"
    }
    if not product or any(file_hash(ROOT / path) != digest for path, digest in product.items()):
        raise ValueError("081 Product/helper source changed")
    checkpoint = load_checkpoint()
    raw: dict[str, Any] = {
        "kind": "082_COMPILED_PLANNING_FACT_HANDOFF",
        "head_sha": head(),
        "history_sha256": HISTORY_HASH,
        "checkpoint_sha256": CHECKPOINT_HASH,
        "database_sha256": DATABASE_HASH,
        "source_hashes": product,
        "support_hashes": {
            p: file_hash(ROOT / p)
            for p in (
                "scripts/verify_answer_fact_handoff.py",
                "tests/evaluation/test_answer_fact_handoff.py",
                CRITERIA,
            )
        },
        "scope": "FRESH_COMPONENT_WITH_TERMINAL_INTENT_NOT_MAIN_OR_DB_COMMIT",
        "model_calls": 0,
        "provider_calls": 0,
        "cases": [],
        "completed": False,
        "semantic_verdict": "NOT_EVALUATED",
    }
    path = output / "raw.json"
    write_json(path, raw, exclusive=True)
    try:
        for case, row in zip(history["binding"]["cases"], history["calls"], strict=True):
            if (
                row["case_id"] != case["case_id"]
                or row["state"] != "RETURNED"
                or row["wire_sha256"] != case["candidate_wire_sha256"]
                or object_hash(row["payload"]) != case["candidate_wire_sha256"]
                or object_hash(case["prompt_input"]) != case["candidate_input_sha256"]
                or json.loads(row["payload"]["prompt"])["input"] != case["prompt_input"]
            ):
                raise ValueError("saved selection/input binding differs")
            actual = case["group"] == "CORE005_LOOKUP"
            result = replay_case(
                case["prompt_input"],
                json.loads(row["content"]),
                case["snapshots"],
                component_state=checkpoint if actual else None,
                component_run_id="082-" + case["case_id"],
            )
            result["case_id"] = case["case_id"]
            expected = row["answer_admission"]["validation"]["normalized"]
            result["preserves_081_validated_draft"] = result.get("final_result") == expected
            if not result["preserves_081_validated_draft"]:
                result["component_verdict"] = "FAIL"
            raw["cases"].append(result)
            write_json(path, raw)
        raw["completed"] = True
    except Exception as error:
        raw.update(error_type=type(error).__name__, error=str(error))
    finally:
        raw["binding_unchanged"] = (
            head() == raw["head_sha"]
            and file_hash(HISTORY) == HISTORY_HASH
            and file_hash(DATABASE) == DATABASE_HASH
            and all(file_hash(ROOT / p) == digest for p, digest in product.items())
            and all(file_hash(ROOT / p) == digest for p, digest in raw["support_hashes"].items())
        )
        raw["component_verdict"] = (
            "PASS"
            if (
                raw["completed"]
                and raw["binding_unchanged"]
                and all(item["component_verdict"] == "PASS" for item in raw["cases"])
            )
            else "FAIL"
        )
        write_json(path, raw)
    return raw


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result-dir", type=Path, required=True)
    args = parser.parse_args()
    raw = run_gate(args.result_dir)
    print(
        json.dumps(
            {
                key: raw[key]
                for key in (
                    "component_verdict",
                    "model_calls",
                    "provider_calls",
                    "binding_unchanged",
                )
            }
        )
    )
    raise SystemExit(0 if raw["component_verdict"] == "PASS" else 1)


if __name__ == "__main__":
    main()
