from __future__ import annotations

import json
from pathlib import Path

import pytest
from evaluation.prompt_candidate import (
    PromptCandidateError,
    load_prompt_candidate,
    materialize_prompt_candidate,
)

from google_work_agent.api.composition import ProductionRuntimeConfig
from google_work_agent.application.prompt_runtime.prompt_registry import (
    DEVELOPMENT_SMOKE,
    InactivePromptArtifactError,
    PromptRegistry,
    load_prompt_reference,
)

ROOT = Path(__file__).parents[2]
CANDIDATE = ROOT / "evaluation/prompt_candidates/mcp-tool-use-2026-v1/candidate.json"
ACTIVE_PROMPT_ROOT = ROOT / "src/google_work_agent/application/prompt_runtime"


def test_mcp_candidate_has__current_slot_subset_hashes_and_draft__lifecycle() -> None:
    bundle = load_prompt_candidate(CANDIDATE, repository_root=ROOT)
    active_manifest = json.loads(
        (ACTIVE_PROMPT_ROOT / "prompt_manifest.json").read_text(encoding="utf-8")
    )
    active_slot_ids = {slot["prompt_slot_id"] for slot in active_manifest["slots"]}

    assert bundle.candidate_id == "mcp-tool-use-research-2026-v1"
    assert len(bundle.source_hashes) == bundle.payload["prompt_slot_count"]
    assert set(bundle.source_hashes) < active_slot_ids
    assert active_slot_ids - set(bundle.source_hashes)
    assert bundle.payload["status"] == "DRAFT"
    assert bundle.payload["activation_evidence"] == {
        "node_dev_pass": False,
        "node_holdout_pass": False,
        "safety_gate_pass": False,
        "manifest_approved": False,
    }


def test_materialization__is_deterministic_and_evaluation_loadable__while_product_inactive(
    tmp_path: Path,
) -> None:
    with pytest.raises(PromptCandidateError, match="candidate/Product slot mismatch"):
        materialize_prompt_candidate(
            candidate_path=CANDIDATE,
            repository_root=ROOT,
            output_dir=tmp_path / "default-rejected",
        )
    first = materialize_prompt_candidate(
        candidate_path=CANDIDATE,
        repository_root=ROOT,
        output_dir=tmp_path / "first",
        keep_extra_product_slots=True,
    )
    second = materialize_prompt_candidate(
        candidate_path=CANDIDATE,
        repository_root=ROOT,
        output_dir=tmp_path / "second",
        keep_extra_product_slots=True,
    )
    first_files = {
        path.relative_to(first.output_dir): path.read_bytes()
        for path in first.output_dir.rglob("*")
        if path.is_file()
    }
    second_files = {
        path.relative_to(second.output_dir): path.read_bytes()
        for path in second.output_dir.rglob("*")
        if path.is_file()
    }
    manifest = json.loads(first.prompt_manifest_path.read_text(encoding="utf-8"))
    active_manifest = json.loads(
        (ACTIVE_PROMPT_ROOT / "prompt_manifest.json").read_text(encoding="utf-8")
    )
    active_by_id = {slot["prompt_slot_id"]: slot for slot in active_manifest["slots"]}
    materialized_by_id = {slot["prompt_slot_id"]: slot for slot in manifest["slots"]}
    bundle = load_prompt_candidate(CANDIDATE, repository_root=ROOT)
    registry = PromptRegistry(first.prompt_manifest_path, first.input_contract_path)
    development_config = ProductionRuntimeConfig.development(
        runtime_root=tmp_path / "runtime",
        working_directory=ROOT,
        mcp_manifest_version="test",
        prompt_manifest_path=first.prompt_manifest_path,
    )

    assert first_files == second_files
    assert first.prompt_manifest_hash == second.prompt_manifest_hash
    assert set(materialized_by_id) == set(active_by_id)
    assert len(manifest["slots"]) == len(active_manifest["slots"])
    assert all(slot["activation_status"] == "DRAFT" for slot in manifest["slots"])
    assert all(slot["activation_evidence"] is None for slot in manifest["slots"])
    for slot_id in bundle.source_hashes:
        assert materialized_by_id[slot_id]["prompt_version"] == bundle.candidate_prompt_version
        assert materialized_by_id[slot_id]["content_hash"] == bundle.source_hashes[slot_id]
    extra_slot_ids = set(active_by_id) - set(bundle.source_hashes)
    for extra_slot_id in extra_slot_ids:
        assert materialized_by_id[extra_slot_id] == {
            **active_by_id[extra_slot_id],
            "activation_status": "DRAFT",
            "node_dev_pass": False,
            "node_holdout_pass": False,
            "safety_gate_pass": False,
            "manifest_approved": False,
            "activation_evidence": None,
        }
    assert (
        first.input_contract_path.read_bytes()
        == (ACTIVE_PROMPT_ROOT / "prompt_runtime_input_contract_v1.json").read_bytes()
    )
    for extra_slot_id in extra_slot_ids:
        assert (
            first.output_dir / materialized_by_id[extra_slot_id]["source"]
        ).read_bytes() == (
            ACTIVE_PROMPT_ROOT / active_by_id[extra_slot_id]["source"]
        ).read_bytes()
    for slot in manifest["slots"]:
        registry.lookup_for_evaluation(slot["prompt_slot_id"])
        with pytest.raises(InactivePromptArtifactError):
            registry.lookup_for_product_release(slot["prompt_slot_id"])
    selected = load_prompt_reference(
        "request_understanding.identify_goal",
        manifest_path=development_config.development_prompt_manifest_path,
        execution_scope=DEVELOPMENT_SMOKE,
    )
    assert selected.prompt_bundle_version == bundle.candidate_id
    assert selected.content_hash == bundle.source_hashes[selected.prompt_id]


def test_materializer_refuses__candidate_or_product_source__overwrite(tmp_path: Path) -> None:
    with pytest.raises(PromptCandidateError, match="cannot overlap source artifacts"):
        materialize_prompt_candidate(
            candidate_path=CANDIDATE,
            repository_root=ROOT,
            output_dir=ACTIVE_PROMPT_ROOT,
        )
    with pytest.raises(PromptCandidateError, match="cannot overlap source artifacts"):
        materialize_prompt_candidate(
            candidate_path=CANDIDATE,
            repository_root=ROOT,
            output_dir=CANDIDATE.parent / "generated",
        )


def test_candidate_hash__tampering_is__rejected(tmp_path: Path) -> None:
    candidate_dir = tmp_path / "candidate"
    candidate_dir.mkdir()
    payload = json.loads(CANDIDATE.read_text(encoding="utf-8"))
    payload["base_prompt_manifest"] = str(
        (ACTIVE_PROMPT_ROOT / "prompt_manifest.json").relative_to(ROOT)
    ).replace("\\", "/")
    payload["base_input_contract"] = str(
        (ACTIVE_PROMPT_ROOT / "prompt_runtime_input_contract_v1.json").relative_to(ROOT)
    ).replace("\\", "/")
    payload["candidate_bundle_hash"] = "0" * 64
    (candidate_dir / "candidate.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(PromptCandidateError, match="source hash mismatch|bundle hash mismatch"):
        load_prompt_candidate(candidate_dir / "candidate.json", repository_root=ROOT)
