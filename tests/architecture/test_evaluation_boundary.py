from __future__ import annotations

import ast
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[2]
EVALUATION = ROOT / "evaluation"
PRODUCT_ROOTS = (ROOT / "src" / "google_work_agent", ROOT / "launcher")
SHADOW_EVALUATION_RESULT_ROOTS = (
    ROOT / ".runtime" / "reports",
    ROOT / ".runtime" / "results",
    ROOT / "runtime" / "reports",
    ROOT / "runtime" / "results",
    ROOT / "evaluation" / "reports",
)

EXPECTED_EVALUATION_CODE = {
    "evaluation/__init__.py",
    "evaluation/check_workspace.py",
    "evaluation/dataset_v8.py",
    "evaluation/export_materials.py",
    "evaluation/grader_v8.py",
    "evaluation/harness/__init__.py",
    "evaluation/harness/case_runtime.py",
    "evaluation/harness/fault_adapters.py",
    "evaluation/harness/fault_profiles.py",
    "evaluation/harness/gmail_query.py",
    "evaluation/harness/stateful_provider.py",
    "evaluation/harness/temporal_bindings.py",
    "evaluation/prompt_candidate.py",
    "evaluation/observation_v8.py",
    "evaluation/public_client_v8.py",
    "evaluation/public_runner_v8.py",
    "evaluation/semantic_judge_v8.py",
    "evaluation/prompt_candidates/mcp-tool-use-2026-v1/materialize_prompt_candidate.py",
    "evaluation/tests/test_canonical_dataset.py",
    "evaluation/tests/test_case_runtime.py",
    "evaluation/tests/test_execute_canonical_v8.py",
    "evaluation/tests/test_fault_adapters.py",
    "evaluation/tests/test_fault_profiles.py",
    "evaluation/tests/test_public_runner_v8.py",
    "evaluation/tests/test_temporal_bindings.py",
    "evaluation/tests/test_workspace_tools.py",
}

RETIRED_EVALUATION_AUTHORITIES = {
    "evaluation/client/__init__.py",
    "evaluation/client/http.py",
    "evaluation/dataset.py",
    "evaluation/grader.py",
    "evaluation/runner.py",
    "evaluation/experiment_plan.py",
    "evaluation/run_experiment.py",
    "evaluation/compare_experiment_results.py",
    "evaluation/scoring-contract-v1.1.json",
    "evaluation/configs/experiments/prompt-baseline-smoke.template.json",
    "evaluation/configs/experiments/prompt-mcp-research-smoke.template.json",
}


def test_single_evaluation_owner__has_no_legacy__framework_or_parallel_root() -> None:
    assert not (ROOT / "experiments").exists()
    assert not (EVALUATION / "compat").exists()
    assert not any(
        (EVALUATION / name).exists()
        for name in (
            "contracts",
            "domain",
            "application",
            "infrastructure",
            "orchestration",
            "targets",
            "fixtures",
            "projections",
            "reporting",
        )
    )
    tracked = _tracked_files()
    assert {
        path for path in tracked if path.startswith("evaluation/") and path.endswith(".py")
    } == (EXPECTED_EVALUATION_CODE)


def test_product_and__evaluation_import_graph__is_bidirectionally_closed() -> None:
    product_violations: list[str] = []
    for root in PRODUCT_ROOTS:
        for path in root.rglob("*.py"):
            for module, line in _imports(path):
                if module == "evaluation" or module.startswith("evaluation."):
                    product_violations.append(f"{path.relative_to(ROOT)}:{line}:{module}")
    assert product_violations == []

    evaluation_violations: list[str] = []
    for path in EVALUATION.rglob("*.py"):
        for module, line in _imports(path):
            if module == "google_work_agent" or module.startswith("google_work_agent."):
                evaluation_violations.append(f"{path.relative_to(ROOT)}:{line}:{module}")
            if module == "importlib" or module.startswith("importlib."):
                evaluation_violations.append(f"dynamic:{path.relative_to(ROOT)}:{line}:{module}")
    assert evaluation_violations == []


def test_evaluation_assets_are__repository_only_and_results__are_local_by_default() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'include = ["google_work_agent*"]' in pyproject
    assert "evaluation*" not in pyproject
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "/evaluation/results/" in gitignore
    tracked = _tracked_files()
    required = {
        "evaluation/README.md",
        "evaluation/check_workspace.py",
        "evaluation/export_materials.py",
        "evaluation/datasets/e2e/canonical_cases_v8.jsonl",
        "evaluation/datasets/e2e/dataset-manifest-v8.json",
        "evaluation/datasets/e2e/fixtures/google_workspace/provider-snapshot-v8.json",
        "evaluation/prompt_candidates/mcp-tool-use-2026-v1/candidate.json",
        "evaluation/prompt_candidates/planning-review-sllm-decomposition-v0.9.2/"
        "prompt-manifest-v0.9.2-candidate.json",
    }
    assert required <= tracked
    assert RETIRED_EVALUATION_AUTHORITIES.isdisjoint(tracked)


def test_evaluation_results__when_scanned__have_no_shadow_output_root() -> None:
    assert not any(path.exists() for path in SHADOW_EVALUATION_RESULT_ROOTS)


def test_evaluation_assets__do_not_reference__retired_json_authorities() -> None:
    retired_names = {
        Path(path).name
        for path in RETIRED_EVALUATION_AUTHORITIES
        if Path(path).name != "__init__.py"
    }
    checked_suffixes = {".json", ".jsonl", ".md", ".py"}
    stale: list[str] = []
    for path in EVALUATION.rglob("*"):
        if path.is_relative_to(EVALUATION / "results"):
            continue
        if not path.is_file() or path.suffix not in checked_suffixes:
            continue
        content = path.read_text(encoding="utf-8")
        for name in retired_names:
            if name in content:
                stale.append(f"{path.relative_to(ROOT)}:{name}")
    assert stale == []


def _tracked_files() -> set[str]:
    output = subprocess.run(
        ["git", "-c", "core.quotepath=false", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout.decode("utf-8")
    return {path for path in output.split("\0") if path and (ROOT / Path(path)).is_file()}


def _imports(path: Path) -> list[tuple[str, int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.extend((alias.name, node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            result.append((node.module or "", node.lineno))
    return result
