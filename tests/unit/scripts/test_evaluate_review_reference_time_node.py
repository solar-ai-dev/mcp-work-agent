from pathlib import Path

from scripts.evaluate_review_reference_time_node import _candidate_manifest

from google_work_agent.application.prompt_runtime.prompt_registry import (
    DEVELOPMENT_SMOKE,
    default_prompt_manifest_path,
    load_prompt_reference,
)


def test_reference_time_comparison_uses_isolated_prompt_contract(tmp_path: Path) -> None:
    candidate = _candidate_manifest(tmp_path)

    active = load_prompt_reference(
        "review.inspect_goal_and_evidence",
        default_prompt_manifest_path(),
        execution_scope=DEVELOPMENT_SMOKE,
    )
    experimental = load_prompt_reference(
        "review.inspect_goal_and_evidence",
        candidate,
        execution_scope=DEVELOPMENT_SMOKE,
    )

    assert active.input_schema_version == "2"
    assert experimental.input_schema_version == "2"
    assert active.content_hash == experimental.content_hash
