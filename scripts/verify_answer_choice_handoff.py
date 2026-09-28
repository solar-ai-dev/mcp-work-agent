"""Replay six sealed 084 responses through the unchanged 082 Product component.

Only an evaluation-module renderer symbol is injected. No Product callable,
historical checkpoint, model response, or request is patched or regenerated.
"""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from scripts import verify_answer_fact_handoff as existing
from scripts.answer_fact_selection_candidate import bind_fact_selection_schema
from scripts.answer_rendering_choice_candidate import materialize_answer_rendering_choice
from scripts.evaluate_answer_mode_first import transport_hash, verify_wire_seals
from scripts.evaluate_effect_prohibition_sampler import head, write_json
from scripts.evaluate_output_format_ablation import file_hash
from scripts.ru_observation import object_hash

from google_work_agent.ports.llm.output_schema_validation import validate_output_schema

ROOT = existing.ROOT
RESULTS = existing.RESULTS
HISTORY = RESULTS / "084-answer-mode-first-t1/raw.json"
HISTORY_HASH = "3ce662090733ad1d7c8811a566f8f4541514198463212b69615540beca6a8a1b"
CRITERIA = "evaluation/experiments/086-answer-choice-handoff-criteria.md"


def replay_case(
    projection: dict[str, Any],
    selection: dict[str, Any],
    snapshots: dict[str, Any],
    **kwargs: Any,
) -> dict[str, Any]:
    """Reuse actual compiled Planning/store/terminal owners, including their failures."""
    expected_snapshots = deepcopy(snapshots)

    def materialize(value: object, *, prompt_input: Any, source_snapshots: Any) -> Any:
        # Both saved branches were generated from these exact bound Task facts.
        # This is replay provenance, not general PROSE eligibility or a new policy.
        if (
            source_snapshots != expected_snapshots
            or bind_fact_selection_schema(prompt_input, source_snapshots=source_snapshots) is None
        ):
            raise ValueError("saved choice requires its exact current-Run Task snapshots")
        return materialize_answer_rendering_choice(
            value, prompt_input=prompt_input, source_snapshots=source_snapshots
        )

    with patch.object(existing, "materialize_fact_selection", materialize):
        return existing.replay_case(projection, selection, snapshots, **kwargs)


def validate_saved_row(case: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    payload = row["payload"]
    if (
        row["case_id"] != case["case_id"]
        or row["state"] != "RETURNED"
        or row["wire_request_count"] != 1
        or transport_hash(payload) != case["candidate_transport_sha256"]
        or row["wire_bytes_sha256"] != case["candidate_transport_sha256"]
        or object_hash(payload) != case["candidate_wire_sha256"]
        or object_hash(case["prompt_input"]) != case["candidate_input_sha256"]
        or json.loads(payload["prompt"])["input"] != case["prompt_input"]
    ):
        raise ValueError("084 saved response/input/wire binding differs")
    value = json.loads(row["content"])
    if validate_output_schema(value, payload["format"]):
        raise ValueError("saved response fails the sealed 084 mode-first schema")
    if row["answer_admission"]["validation"]["structural_result"] != "VALID":
        raise ValueError("saved response has no admitted Product draft")
    return cast(dict[str, Any], value)


def run_gate(output: Path) -> dict[str, Any]:
    output = output.resolve()
    if not output.is_relative_to(RESULTS.resolve()) or output == RESULTS.resolve():
        raise ValueError("dedicated evaluation/results directory required")
    if file_hash(HISTORY) != HISTORY_HASH:
        raise ValueError("084 history changed")
    history = json.loads(HISTORY.read_text(encoding="utf-8"))
    if not history["completed"] or not history["binding_unchanged"] or len(history["calls"]) != 6:
        raise ValueError("complete bound six-call 084 history required")
    verify_wire_seals(history["binding"])
    dependencies = dict(history["binding"]["source_hashes"])
    if not dependencies or any(file_hash(ROOT / p) != h for p, h in dependencies.items()):
        raise ValueError("084 Product/candidate source changed")
    checkpoint = existing.load_checkpoint()
    supports = {
        path: file_hash(ROOT / path)
        for path in (
            "scripts/verify_answer_fact_handoff.py",
            "scripts/verify_answer_choice_handoff.py",
            "tests/evaluation/test_answer_choice_handoff.py",
            CRITERIA,
        )
    }
    raw: dict[str, Any] = {
        "kind": "086_COMPILED_PLANNING_CHOICE_HANDOFF",
        "head_sha": head(),
        "history_sha256": HISTORY_HASH,
        "database_sha256": existing.DATABASE_HASH,
        "checkpoint_sha256": existing.CHECKPOINT_HASH,
        "source_hashes": dependencies,
        "support_hashes": supports,
        "scope": "FRESH_COMPONENT_WITH_TERMINAL_INTENT_NOT_MAIN_OR_DB_COMMIT",
        "model_calls": 0,
        "provider_calls": 0,
        "semantic_verdict": "NOT_EVALUATED",
        "cases": [],
        "completed": False,
    }
    path = output / "raw.json"
    write_json(path, raw, exclusive=True)
    try:
        for case, row in zip(history["binding"]["cases"], history["calls"], strict=True):
            value = validate_saved_row(case, row)
            result = replay_case(
                case["prompt_input"],
                value,
                case["snapshots"],
                component_state=checkpoint if case["group"] == "CORE005_LOOKUP" else None,
                component_run_id="086-" + case["case_id"],
            )
            result.update(case_id=case["case_id"], mode=value["mode"])
            result["preserves_084_validated_draft"] = (
                result.get("final_result") == row["answer_admission"]["validation"]["normalized"]
            )
            if not result["preserves_084_validated_draft"]:
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
            and file_hash(existing.DATABASE) == existing.DATABASE_HASH
            and all(file_hash(ROOT / p) == h for p, h in (dependencies | supports).items())
        )
        raw["component_verdict"] = (
            "PASS"
            if raw["completed"]
            and raw["binding_unchanged"]
            and len(raw["cases"]) == 6
            and all(row["component_verdict"] == "PASS" for row in raw["cases"])
            else "FAIL"
        )
        write_json(path, raw)
    return raw


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result-dir", type=Path, required=True)
    raw = run_gate(parser.parse_args().result_dir)
    print(json.dumps({key: raw[key] for key in ("component_verdict", "binding_unchanged")}))
    raise SystemExit(0 if raw["component_verdict"] == "PASS" else 1)


if __name__ == "__main__":
    main()
