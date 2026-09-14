from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATASET_ROOT = ROOT / "evaluation" / "datasets"
E2E_ROOT = DATASET_ROOT / "e2e"
DATASET_PATH = E2E_ROOT / "canonical_cases_v8.jsonl"
MANIFEST_PATH = E2E_ROOT / "dataset-manifest-v8.json"
PROVIDER_PATH = E2E_ROOT / "fixtures" / "google_workspace" / "provider-snapshot-v8.json"


def _json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _cases() -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in DATASET_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _sha256(path: Path) -> str:
    normalized = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def test_canonical_92_ids_and_splits_are_exact() -> None:
    cases = _cases()
    expected_ids = {
        *(f"CASE-CORE-{index:03d}" for index in range(1, 61)),
        *(f"CASE-STRESS-{index:03d}" for index in range(1, 21)),
        *(f"CASE-HOLDOUT-{index:03d}" for index in range(1, 13)),
    }

    assert len(cases) == 92
    assert {case["case_id"] for case in cases} == expected_ids
    assert len({case["case_id"] for case in cases}) == len(cases)
    assert Counter(case["split"] for case in cases) == {
        "CORE": 60,
        "STRESS": 20,
        "HOLDOUT": 12,
    }


def test_manifest_hashes_and_declared_counts_match_files() -> None:
    manifest = _json(MANIFEST_PATH)

    assert manifest["dataset_sha256"] == _sha256(DATASET_PATH)
    assert manifest["provider_snapshot_sha256"] == _sha256(PROVIDER_PATH)
    assert manifest["canonical_counts"] == {
        "CORE": 60,
        "HOLDOUT": 12,
        "STRESS": 20,
        "TOTAL": 92,
    }
    assert manifest["holdout_blind"] is False
    assert manifest["model_runs"] == 0
    assert manifest["smoke_runs"] == 0
    assert manifest["full_pytest_runs"] == 0


def test_every_case_has_provider_binding_gold_and_explicit_readiness() -> None:
    provider = _json(PROVIDER_PATH)
    packs = provider["resource_packs"]
    required_gold = {
        "expected_checkpoint",
        "required_semantics",
        "forbidden_semantics",
        "correction",
        "fault_profile",
        "temporal_values",
        "temporal_binding_required",
    }

    for case in _cases():
        case_packs = case["resource_packs"]
        assert case_packs
        assert set(case_packs) <= set(packs)
        assert case["provider_fixture_ref"] == (
            f"fixtures/google_workspace/provider-snapshot-v8.json#{case_packs[0]}"
        )
        assert set(case["evaluation_gold"]) == required_gold
        readiness = case["readiness"]
        assert readiness["data_ready"] == (not readiness["data_blockers"])
        assert readiness["ready_for_evaluation"] == (
            readiness["data_ready"]
            and readiness["temporal_status"] == "NOT_REQUIRED"
        )


def test_pending_temporal_and_provider_repairs_are_not_hidden() -> None:
    manifest = _json(MANIFEST_PATH)
    cases = _cases()
    pending = {
        case["case_id"]
        for case in cases
        if case["readiness"]["temporal_status"] == "PENDING_TEMPORAL_BINDING"
    }

    assert len(pending) == 46
    assert pending == set(manifest["temporal_pending_case_ids"])
    assert manifest["provider_unresolved_packs"] == [
        "DELTA",
        "JUNIPER",
        "ROOM_CONFLICT",
    ]
    assert manifest["provider_pack_counts"] == {
        "ADD": 0,
        "KEEP": 22,
        "PENDING": 2,
        "REPLACE": 2,
    }

    changes = manifest["provider_changes"]
    assert changes["kestrel_task"]["independent_reread_verified"] is True
    assert changes["delta_message"]["independent_reread_verified"] is True
    assert changes["delta_message"]["all_retired_messages_trash_confirmed"] is True
    assert changes["delta_message"]["standalone_thread_verified"] is False
    assert changes["delta_message"]["active_thread_isolated_verified"] is True


def test_only_canonical_v8_dataset_assets_remain_active() -> None:
    actual = {
        path.relative_to(DATASET_ROOT).as_posix()
        for path in DATASET_ROOT.rglob("*")
        if path.is_file()
    }
    assert actual == {
        "e2e/canonical_cases_v8.jsonl",
        "e2e/dataset-manifest-v8.json",
        "e2e/fixtures/google_workspace/provider-snapshot-v8.json",
    }


def test_only_design_approved_input_changes_are_declared() -> None:
    manifest = _json(MANIFEST_PATH)
    changes = manifest["inputs_changed"]

    assert len(changes) == 17
    assert all(change["field"] == "canonical_user_prompt" for change in changes)
    assert all(
        change["reason"] == "VIRTUAL_TO_ACTUAL_ADDRESS_BINDING"
        for change in changes
    )
