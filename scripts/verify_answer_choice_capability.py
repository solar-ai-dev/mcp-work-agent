"""Check 087 wire equivalence using nine distinct existing responses; no inference."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from scripts import evaluate_answer_choice_adjacent as adjacent
from scripts import evaluate_answer_mode_first as ordered
from scripts.answer_choice_capability_candidate import build_capability_wire
from scripts.evaluate_effect_prohibition_sampler import head, write_json
from scripts.evaluate_output_format_ablation import file_hash
from scripts.ru_observation import object_hash

ROOT, RESULTS = adjacent.ROOT, adjacent.RESULTS
CRITERIA = "evaluation/experiments/087-answer-choice-capability-criteria.md"
HISTORIES = {
    "084-answer-mode-first-t1/raw.json": (
        "3ce662090733ad1d7c8811a566f8f4541514198463212b69615540beca6a8a1b"
    ),
    "085-answer-choice-adjacent-t1/raw.json": (
        "9c4bcb8049adbf684fd4ae94cfffbd1723505c2ec87ac6edd4e0bae851e6e337"
    ),
}


def verify_reused_response(
    case: dict[str, Any], row: dict[str, Any], *, historical_product: bool = False
) -> dict[str, Any]:
    projection, snapshots = case["prompt_input"], case["snapshots"]
    # These are exact, already validated synthetic/historical observations, not
    # new Provider reads or a replacement for Product Run-store authorization.
    if adjacent.resolve_unique_task_calendar_snapshots(projection["evidence"], snapshots) is None:
        raise ValueError("bound observation missing or stale")
    original = adjacent.handoff._wire_projection(projection)["wire_payload"]
    payload = build_capability_wire(original, projection, snapshots)
    if ordered.transport_hash(payload) != ordered.transport_hash(row["payload"]):
        raise ValueError("new wire has no exact historical response")
    if json.loads(payload["prompt"])["input"] != projection:
        raise ValueError("projection changed")
    replay_case = {
        **deepcopy(case),
        "arm": "BASELINE" if historical_product else "MODE_FIRST",
        "candidate_transport_sha256": ordered.transport_hash(payload),
    }
    replay = {"payload": payload, "content": row["content"]}
    ordered.record_admission(replay, replay_case)
    valid = replay["answer_admission"].get("validation", {}).get("structural_result") == "VALID"
    return {
        "case_id": case["case_id"],
        "reused_response_sha256": object_hash(row),
        "reuse_scope": "EXACT_WIRE_REUSE_NOT_NEW_TRIAL",
        "restores_product_wire": historical_product,
        "wire_bytes_sha256": ordered.transport_hash(payload),
        "response": replay,
        "structural_verdict": "PASS" if valid else "FAIL",
        "semantic_verdict": "NOT_REVIEWED",
    }


def run_gate(output: Path) -> dict[str, Any]:
    output = ordered.previous.recorder._output_directory(output)
    histories = {}
    source_hashes: dict[str, str] = {}
    for relative, digest in HISTORIES.items():
        path = RESULTS / relative
        if file_hash(path) != digest:
            raise ValueError("history changed")
        history = json.loads(path.read_text(encoding="utf-8"))
        if not history["completed"] or not history["binding_unchanged"]:
            raise ValueError("incomplete historical result")
        if any(file_hash(ROOT / p) != h for p, h in history["binding"]["source_hashes"].items()):
            raise ValueError("historical Product/helper code changed")
        histories[relative[:3]] = history
        source_hashes.update(history["binding"]["source_hashes"])
    for support_path in (
        "scripts/answer_choice_capability_candidate.py",
        "scripts/verify_answer_choice_capability.py",
        "tests/evaluation/test_answer_choice_capability.py",
        CRITERIA,
    ):
        source_hashes[support_path] = file_hash(ROOT / support_path)
    if any(file_hash(ROOT / p) != digest for p, digest in source_hashes.items()):
        raise ValueError("historical Product/helper code changed")
    raw: dict[str, Any] = {
        "kind": "087_ANSWER_CAPABILITY_EXACT_WIRE_REUSE",
        "head_sha": head(),
        "source_hashes": source_hashes,
        "history_hashes": HISTORIES,
        "cases": [],
        "completed": False,
        "model_calls": 0,
        "provider_calls": 0,
        "graph_calls": 0,
        "semantic_verdict": "NOT_EVALUATED",
        "business_success": "NOT_EVALUATED",
    }
    path = output / "raw.json"
    write_json(path, raw, exclusive=True)
    try:
        for experiment, history in histories.items():
            for case, row in zip(history["binding"]["cases"], history["calls"], strict=True):
                if case["case_id"] != row["case_id"] or row["state"] != "RETURNED":
                    raise ValueError("saved case/response mismatch")
                if experiment == "085" and case["group"] != "SYNTHETIC_TASK_NOTES":
                    continue
                raw["cases"].append(verify_reused_response(case, row))
                write_json(path, raw)
        adjacent_raw = histories["085"]
        calendar = next(
            c
            for c in adjacent_raw["binding"]["cases"]
            if c["group"] == "SYNTHETIC_CALENDAR_LOCATION"
        )
        reference = next(
            c
            for c in adjacent_raw["binding"]["historical_prose"]
            if c["case_id"] == "SYNTHETIC_CALENDAR_LOCATION"
        )
        historical = reference["source_row"]["calls"][0]
        row = {
            "payload": historical["wire_payload"],
            "content": historical["provider_response"]["response"],
        }
        case = {**calendar, "case_id": "SYNTHETIC_CALENDAR_LOCATION-065-HISTORICAL-ONCE"}
        raw["cases"].append(verify_reused_response(case, row, historical_product=True))
        raw["completed"] = True
    except Exception as error:
        raw.update(error_type=type(error).__name__, error=str(error))
    finally:
        raw["binding_unchanged"] = (
            head() == raw["head_sha"]
            and all(file_hash(RESULTS / p) == h for p, h in HISTORIES.items())
            and all(file_hash(ROOT / p) == h for p, h in source_hashes.items())
        )
        raw["wire_gate"] = (
            "PASS"
            if raw["completed"]
            and raw["binding_unchanged"]
            and len(raw["cases"]) == 9
            and all(c["structural_verdict"] == "PASS" for c in raw["cases"])
            else "FAIL"
        )
        write_json(path, raw)
    return raw


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result-dir", required=True, type=Path)
    raw = run_gate(parser.parse_args().result_dir)
    print(json.dumps({key: raw[key] for key in ("wire_gate", "binding_unchanged", "model_calls")}))
    raise SystemExit(0 if raw["wire_gate"] == "PASS" else 1)


if __name__ == "__main__":
    main()
