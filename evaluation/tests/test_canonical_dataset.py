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
FAULT_CONFIG_PATH = ROOT / "evaluation" / "harness" / "canonical_v8_fault_profiles.json"
FAULT_ADAPTER_PATH = ROOT / "evaluation" / "harness" / "fault_adapters.py"
SIMULATED_FIXTURE_PATH = (
    ROOT / "evaluation" / "harness" / "canonical_v8_simulated_fixtures.json"
)


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
            and readiness["temporal_status"]
            in {"NOT_REQUIRED", "BOUND_FIXED_RUN_REFERENCE_TIME"}
        )


def test_temporal_and_provider_readiness_are_complete() -> None:
    manifest = _json(MANIFEST_PATH)
    cases = _cases()
    bound = {
        case["case_id"]
        for case in cases
        if case["readiness"]["temporal_status"]
        == "BOUND_FIXED_RUN_REFERENCE_TIME"
    }

    assert len(bound) == 48
    assert {"CASE-CORE-033", "CASE-CORE-035"} <= bound
    assert manifest["temporal_pending_case_ids"] == []
    assert manifest["temporal_binding"]["bound_case_count"] == 48
    assert manifest["provider_unresolved_packs"] == []
    assert manifest["provider_pack_counts"] == {
        "ADD": 1,
        "KEEP": 23,
        "PENDING": 0,
        "REPLACE": 2,
    }
    assert manifest["status"] == "BENCHMARK_READY"
    assert manifest["benchmark_ready"] == "YES"
    assert manifest["stress_harness_ready"] is True
    assert manifest["stress_harness"] == {
        "adapter": "evaluation/harness/fault_adapters.py",
        "adapter_sha256": _sha256(FAULT_ADAPTER_PATH),
        "configuration": "evaluation/harness/canonical_v8_fault_profiles.json",
        "configuration_sha256": _sha256(FAULT_CONFIG_PATH),
        "evaluation_mode_counts": {
            "COMPONENT_ONLY": 1,
            "LIVE_WITH_FAULT_INJECTION": 6,
            "SIMULATED_PROVIDER": 13,
        },
        "profile_count": 20,
        "ready": True,
        "resolver": "evaluation/harness/fault_profiles.py",
        "runtime": "evaluation/harness/case_runtime.py",
        "simulated_fixture": (
            "evaluation/harness/canonical_v8_simulated_fixtures.json"
        ),
        "simulated_fixture_sha256": _sha256(SIMULATED_FIXTURE_PATH),
        "stateful_provider": "evaluation/harness/stateful_provider.py",
        "validation": "ADAPTER_BOUNDARY_VALIDATED_20_OF_20",
    }

    changes = manifest["provider_changes"]
    assert changes["kestrel_task"]["independent_reread_verified"] is True
    assert changes["delta_message"]["independent_reread_verified"] is True
    assert changes["delta_message"]["standalone_thread_verified"] is True
    assert changes["delta_message"]["retired_thread_trashed_verified"] is True
    assert changes["juniper_review_event"]["overlap_verified"] is True
    assert changes["juniper_review_event"]["distinct_identity_verified"] is True
    assert changes["room_conflict"]["owner_binding_verified"] is True
    assert changes["quartz_attachment"]["attachment_count"] == 1


def test_delta_close_candidate_fixture_is_explicit_and_does_not_replace_live_data() -> None:
    cases = {case["case_id"]: case for case in _cases()}
    stress = cases["CASE-STRESS-010"]
    context = stress["evaluation_context"]
    fixture = _json(SIMULATED_FIXTURE_PATH)["fixtures"]["DELTA_CLOSE_CANDIDATES"]

    assert stress["provider_fixture_ref"] == (
        "fixtures/google_workspace/provider-snapshot-v8.json#DELTA"
    )
    assert context["evaluation_mode"] == "SIMULATED_PROVIDER"
    assert context["simulated_fixture_ref"] == (
        "harness/canonical_v8_simulated_fixtures.json#DELTA_CLOSE_CANDIDATES"
    )
    assert {item["payload"]["project"] for item in fixture["resources"]} == {
        "Delta",
        "Delta Plus",
    }


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
